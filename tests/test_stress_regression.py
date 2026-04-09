import os
import tempfile
import unittest
from unittest.mock import patch

from qdp.core import QobuzDL
from qdp.db import create_db, get_download_entry, upsert_download_entry
from qdp.downloader import Download
from tests.test_library_tools import _make_min_flac


class FakeTrackClient:
    def get_album_meta(self, album_id):
        return {
            "id": str(album_id),
            "title": "Album",
            "streamable": True,
            "artist": {"name": "Artist"},
            "release_date_original": "2024-01-01",
            "tracks": {
                "items": [
                    {
                        "id": "t1",
                        "title": "Song A",
                        "track_number": 1,
                        "media_number": 1,
                        "performer": {"name": "Artist"},
                        "maximum_sampling_rate": 44.1,
                        "maximum_bit_depth": 16,
                    },
                    {
                        "id": "t2",
                        "title": "Song B",
                        "track_number": 2,
                        "media_number": 1,
                        "performer": {"name": "Artist"},
                        "maximum_sampling_rate": 44.1,
                        "maximum_bit_depth": 16,
                    },
                ]
            },
        }


class FakeBatchClient:
    def api_call(self, endpoint, **kwargs):
        limit = int(kwargs.get("limit") or 10)
        offset = int(kwargs.get("offset") or 0)
        start = offset + 1
        end = offset + limit + 1
        return {
            kwargs["type"]: {
                "items": [
                    {
                        "id": str(idx),
                        "title": f"Album {idx}",
                        "artist": {"name": "Artist"},
                        "streamable": True,
                        "maximum_bit_depth": 16,
                        "maximum_sampling_rate": 44.1,
                        "release_date_original": "2024-01-01",
                    }
                    for idx in range(start, end)
                ]
            }
        }


class StressRegressionTests(unittest.TestCase):
    def test_verify_and_repair_sequential_updates_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "qdp.db")
            create_db(db_path)
            album_dir = os.path.join(tmp, "Artist - Album (2024)")
            os.makedirs(album_dir)
            _make_min_flac(os.path.join(album_dir, "01. Song A.flac"), title="Song A", artist="Artist", tracknumber="1")
            upsert_download_entry(db_path, "album-1", {"local_path": album_dir, "expected_tracks": 2, "matched_tracks": 2, "integrity_status": "complete"})
            d = Download(FakeTrackClient(), "album-1", tmp, 27, downloads_db=db_path, check_only=True, verify_existing=True)
            report, _, _ = d.inspect_album("album-1", announce=False, repair_db=True)
            self.assertFalse(report.complete)
            self.assertTrue(report.db_repaired)
            entry = get_download_entry(db_path, "album-1")
            self.assertEqual(entry["integrity_status"], "incomplete")

    def test_search_shortcut_stress_and_bulk_artist_selection(self):
        q = QobuzDL(check_only=True)
        q.client = FakeBatchClient()
        captured = []
        with patch.object(q, "download_list_of_urls", side_effect=lambda urls: captured.append(list(urls))):
            # numeric selection now requires execution confirm
            with patch("qdp.ui_search.Console.input", side_effect=["n", "p", "1,2,3,4,5", "y"]):
                q.run_search("artist", "artist", 5)
        self.assertTrue(captured)
        self.assertEqual(len(captured[-1]), 5)

    def test_scan_then_rename_roundtrip_for_multiple_albums(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "qdp.db")
            create_db(db_path)
            for album_name in ["Messy One", "Messy Two"]:
                album_dir = os.path.join(tmp, album_name)
                os.makedirs(album_dir)
                for idx in range(1, 4):
                    _make_min_flac(os.path.join(album_dir, f"{idx}. Song {idx}.flac"), title=f"Song {idx}", artist="Artist", tracknumber=str(idx))
            q = QobuzDL(directory=tmp, downloads_db=db_path, folder_format="{artist} - {album} ({year})", track_format="{tracknumber}. {tracktitle}")
            scan_summary = q.scan_library()
            self.assertEqual(scan_summary["scanned_albums"], 2)
            plan = q.rename_library(dry_run=False)
            self.assertTrue(any(item["kind"] == "album" for item in plan))
            post_summary = q.scan_library()
            self.assertEqual(post_summary["scanned_albums"], 2)


if __name__ == "__main__":
    unittest.main()
