import os
import tempfile
import unittest

from mutagen.flac import FLAC

from qdp.core import QobuzDL
from qdp.sidecar import build_album_sidecar_payload, write_sidecar, load_sidecar
from qdp.db import create_db, get_download_entry, upsert_download_entry
from qdp.downloader import Download


def _make_min_flac(path, title="Song", artist="Artist", tracknumber="1", discnumber="1"):
    sample_rate = 44100
    channels = 1
    bits_per_sample = 16
    data = b"\x00\x00" * sample_rate
    total_samples = len(data) // 2
    streaminfo = bytearray()
    streaminfo += (4096).to_bytes(2, "big")
    streaminfo += (4096).to_bytes(2, "big")
    streaminfo += (0).to_bytes(3, "big")
    streaminfo += (len(data)).to_bytes(3, "big")
    upper = (sample_rate << 12) | (channels - 1) << 9 | (bits_per_sample - 1) << 4 | ((total_samples >> 32) & 0x0F)
    lower = total_samples & 0xFFFFFFFF
    streaminfo += upper.to_bytes(4, "big")
    streaminfo += lower.to_bytes(4, "big")
    streaminfo += b"\x00" * 16
    vendor = b"qdp-tests"
    comments = [
        f"TITLE={title}".encode(),
        f"ARTIST={artist}".encode(),
        f"TRACKNUMBER={tracknumber}".encode(),
        f"DISCNUMBER={discnumber}".encode(),
    ]
    vorbis = bytearray()
    vorbis += len(vendor).to_bytes(4, "little")
    vorbis += vendor
    vorbis += len(comments).to_bytes(4, "little")
    for comment in comments:
        vorbis += len(comment).to_bytes(4, "little")
        vorbis += comment
    with open(path, "wb") as handle:
        handle.write(b"fLaC")
        handle.write(bytes([0x00]))
        handle.write(len(streaminfo).to_bytes(3, "big"))
        handle.write(streaminfo)
        handle.write(bytes([0x84]))
        handle.write(len(vorbis).to_bytes(3, "big"))
        handle.write(vorbis)
        handle.write(bytes([0xFF, 0xF8, 0x69, 0x08, 0x00, 0x00]))
        handle.write(data)
    parsed = FLAC(path)
    parsed["TITLE"] = title
    parsed["ARTIST"] = artist
    parsed["TRACKNUMBER"] = tracknumber
    parsed["DISCNUMBER"] = discnumber
    parsed.save()


def _album_meta(album_id="1", title="Album", artist="Artist"):
    return {
        "id": album_id,
        "title": title,
        "artist": {"name": artist},
        "release_date_original": "2024-01-01",
        "tracks": {
            "items": [
                {
                    "id": "t1",
                    "title": "Song",
                    "track_number": 1,
                    "media_number": 1,
                    "performer": {"name": artist},
                    "maximum_sampling_rate": 44.1,
                    "maximum_bit_depth": 16,
                }
            ]
        },
    }


class LibraryToolsTests(unittest.TestCase):
    def test_scan_library_summarizes_db_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "qdp.db")
            create_db(db_path)
            album_dir = os.path.join(tmp, "Artist - Album A (2024)")
            os.makedirs(album_dir)
            _make_min_flac(os.path.join(album_dir, "01. Song.flac"), title="Song", artist="Artist", tracknumber="1")
            upsert_download_entry(db_path, "1", {"local_path": album_dir, "integrity_status": "incomplete", "expected_tracks": 2})
            upsert_download_entry(db_path, "2", {"local_path": os.path.join(tmp, "Missing")})
            q = QobuzDL(directory=tmp, downloads_db=db_path)
            summary = q.scan_library()
            self.assertEqual(summary["db_entries"], 2)
            self.assertEqual(summary["found_paths"], 1)
            self.assertEqual(summary["incomplete"], 2)
            self.assertEqual(summary["scanned_albums"], 1)
            self.assertEqual(summary["incomplete_albums"], 1)

    def test_doctor_reports_format_and_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "qdp.db")
            q = QobuzDL(directory=tmp, downloads_db=db_path)
            checks = q.doctor({"default_folder": tmp, "default_quality": "27", "app_id": "1", "secrets": "x", "proxies": ""})
            names = [name for name, _, _ in checks]
            self.assertIn("命名规则", names)
            self.assertIn("下载目录", names)

    def test_rename_library_dry_run_returns_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            album_dir = os.path.join(tmp, "Album")
            os.makedirs(album_dir)
            old_path = os.path.join(album_dir, "1. Song.flac")
            _make_min_flac(old_path, title="Song", artist="Artist", tracknumber="1")
            q = QobuzDL(directory=tmp, folder_format="{artist} - {album} ({year})", track_format="{tracknumber}. {tracktitle}")
            plan = q.rename_library(dry_run=True)
            self.assertGreaterEqual(len(plan), 2)
            track_moves = [item for item in plan if item["kind"] == "track"]
            album_moves = [item for item in plan if item["kind"] == "album"]
            self.assertEqual(track_moves[0]["src"], old_path)
            self.assertTrue(track_moves[0]["dst"].endswith("01. Song.flac"))
            self.assertTrue(album_moves[0]["dst"].endswith("Artist - Album (0000)"))

    def test_rename_library_apply_avoids_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Download(client=None, item_id="x", path=tmp, quality=27)
            src = os.path.join(tmp, "a.flac")
            dst = os.path.join(tmp, "b.flac")
            open(src, "wb").close()
            open(dst, "wb").close()
            with self.assertRaises(FileExistsError):
                d.apply_rename_plan([{"src": src, "dst": dst, "kind": "track"}])

    def test_db_upsert_persists_integrity_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "qdp.db")
            create_db(db_path)
            upsert_download_entry(db_path, "album-1", {"local_path": "/tmp/a", "expected_tracks": 10, "matched_tracks": 8, "integrity_status": "incomplete"})
            entry = get_download_entry(db_path, "album-1")
            self.assertEqual(entry["expected_tracks"], 10)
            self.assertEqual(entry["matched_tracks"], 8)
            self.assertEqual(entry["integrity_status"], "incomplete")

    def test_rename_library_apply_updates_album_and_disc_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "qdp.db")
            create_db(db_path)
            album_dir = os.path.join(tmp, "Old Album")
            disc_dir = os.path.join(album_dir, "Disc 2")
            os.makedirs(disc_dir)
            track1 = os.path.join(album_dir, "1. Intro.flac")
            track2 = os.path.join(disc_dir, "2. Finale.flac")
            _make_min_flac(track1, title="Intro", artist="Artist", tracknumber="1", discnumber="1")
            _make_min_flac(track2, title="Finale", artist="Artist", tracknumber="2", discnumber="2")
            meta = _album_meta(album_id="album-42", title="Old Album", artist="Artist")
            payload = build_album_sidecar_payload(meta, album_dir, "{artist} - {album} ({year})", "{tracknumber}. {tracktitle}", tracks=[
                {"id": "x1", "title": "Intro", "track_number": 1, "media_number": 1, "performer": {"name": "Artist"}, "_expected_filename": "01. Intro.flac", "_expected_rel_path": "01. Intro.flac", "_actual_quality": {"quality_code": 6, "bit_depth": 16, "sampling_rate": 44.1}},
                {"id": "x2", "title": "Finale", "track_number": 2, "media_number": 2, "performer": {"name": "Artist"}, "_expected_filename": "02. Finale.flac", "_expected_rel_path": os.path.join("Disc 2", "02. Finale.flac"), "_actual_quality": {"quality_code": 6, "bit_depth": 16, "sampling_rate": 44.1}},
            ], quality_summary={"actual_quality": {"quality_code": 6, "bit_depth": 16, "sampling_rate": 44.1}, "source_quality": {"quality_code": 27}})
            write_sidecar(album_dir, payload)
            upsert_download_entry(db_path, "album-42", {"local_path": album_dir, "expected_tracks": 2, "matched_tracks": 2, "integrity_status": "complete"})
            q = QobuzDL(directory=tmp, downloads_db=db_path, folder_format="{artist} - {album} ({year})", track_format="{tracknumber}. {tracktitle}")
            plan = q.rename_library(dry_run=False)
            self.assertTrue(any(item["kind"] == "album" for item in plan))
            new_album_dir = os.path.join(tmp, "Artist - Old Album (2024)")
            self.assertTrue(os.path.isdir(new_album_dir))
            self.assertTrue(os.path.exists(os.path.join(new_album_dir, "01. Intro.flac")))
            self.assertTrue(os.path.exists(os.path.join(new_album_dir, "Disc 2", "02. Finale.flac")))
            entry = get_download_entry(db_path, "album-42")
            self.assertEqual(entry["local_path"], new_album_dir)

    def test_scan_library_handles_mixed_large_structure_and_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "qdp.db")
            create_db(db_path)
            album_a = os.path.join(tmp, "Artist A - Album A (2024)")
            album_b = os.path.join(tmp, "Loose Files")
            disc_b = os.path.join(album_b, "Disc 2")
            os.makedirs(album_a)
            os.makedirs(disc_b)
            for idx in range(1, 6):
                _make_min_flac(os.path.join(album_a, f"{idx:02d}. Song {idx}.flac"), title=f"Song {idx}", artist="Artist A", tracknumber=str(idx))
            for idx in range(1, 4):
                _make_min_flac(os.path.join(album_b, f"{idx}. Track {idx}.flac"), title=f"Track {idx}", artist="Artist B", tracknumber=str(idx))
            _make_min_flac(os.path.join(disc_b, "4. Track 4.flac"), title="Track 4", artist="Artist B", tracknumber="4", discnumber="2")
            upsert_download_entry(db_path, "album-a", {"local_path": album_a, "expected_tracks": 5, "integrity_status": "complete"})
            q = QobuzDL(directory=tmp, downloads_db=db_path)
            summary = q.scan_library()
            self.assertEqual(summary["scanned_albums"], 2)
            self.assertEqual(summary["complete_albums"], 1)
            self.assertGreaterEqual(summary["unknown_albums"], 1)

    def test_sidecar_write_read_and_scan_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "qdp.db")
            create_db(db_path)
            album_dir = os.path.join(tmp, "Legacy Folder")
            os.makedirs(album_dir)
            _make_min_flac(os.path.join(album_dir, "01. Song.flac"), title="Song", artist="Artist", tracknumber="1")
            meta = _album_meta(album_id="album-1", title="Album", artist="Artist")
            payload = build_album_sidecar_payload(meta, album_dir, "{artist} - {album} ({year})", "{tracknumber}. {tracktitle}", tracks=[
                {"id": "t1", "title": "Song", "track_number": 1, "media_number": 1, "performer": {"name": "Artist"}, "_expected_filename": "01. Song.flac", "_expected_rel_path": "01. Song.flac", "_source_quality": {"quality_code": 27}, "_actual_quality": {"quality_code": 6, "bit_depth": 16, "sampling_rate": 44.1}},
            ], quality_summary={"source_quality": {"quality_code": 27}, "actual_quality": {"quality_code": 6, "bit_depth": 16, "sampling_rate": 44.1}})
            sidecar_path = write_sidecar(album_dir, payload)
            loaded = load_sidecar(album_dir)
            self.assertEqual(loaded["album_id"], "album-1")
            self.assertEqual(sidecar_path, loaded["sidecar_path"])
            q = QobuzDL(directory=tmp, downloads_db=db_path)
            summary = q.scan_library()
            self.assertEqual(summary["scanned_albums"], 1)
            entry = get_download_entry(db_path, "album-1")
            self.assertEqual(entry["sidecar_path"], sidecar_path)
            self.assertEqual(entry["bit_depth"], 16)


if __name__ == "__main__":
    unittest.main()
