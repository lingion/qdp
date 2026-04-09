import os
import tempfile
import unittest

from qdp.db import create_db, handle_download_id, get_download_entry
from qdp.integrity import build_expected_tracks, inspect_album_integrity


ALBUM_META = {
    "id": "album-1",
    "title": "Album",
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


class IntegrityTests(unittest.TestCase):
    def test_legacy_naming_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "01. Song A.flac"), "wb").close()
            open(os.path.join(tmp, "02. Song B.flac"), "wb").close()
            report = inspect_album_integrity(
                album_id="album-1",
                album_dir=tmp,
                meta=ALBUM_META,
                current_track_format="{artist} - {tracktitle}",
                downloads_db=None,
            )
            self.assertTrue(report.complete)
            self.assertEqual(report.legacy_naming_hits, 2)
            self.assertEqual(report.expected_naming_hits, 0)

    def test_missing_track_marks_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "01. Song A.flac"), "wb").close()
            report = inspect_album_integrity(
                album_id="album-1",
                album_dir=tmp,
                meta=ALBUM_META,
                current_track_format="{tracknumber}. {tracktitle}",
                downloads_db=None,
            )
            self.assertFalse(report.complete)
            self.assertEqual(report.missing_count, 1)
            self.assertIn("Disc 01 Track 02 - Song B", report.missing_labels)

    def test_db_stale_repair_removes_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "downloads.db")
            create_db(db_path)
            handle_download_id(db_path, "album-1", add_id=True)
            report = inspect_album_integrity(
                album_id="album-1",
                album_dir=tmp,
                meta=ALBUM_META,
                current_track_format="{tracknumber}. {tracktitle}",
                downloads_db=db_path,
                repair_db=True,
            )
            self.assertTrue(report.db_hit)
            self.assertTrue(report.db_stale)
            self.assertTrue(report.db_repaired)
            row = get_download_entry(db_path, "album-1")
            self.assertIsNotNone(row)
            self.assertEqual(row["integrity_status"], "incomplete")

    def test_build_expected_tracks_supports_current_format(self):
        expected = build_expected_tracks(ALBUM_META, "{artist} - {tracktitle}")
        self.assertEqual(expected[0].rel_path, "Artist - Song A")
        self.assertIn("01. Song A", expected[0].legacy_rel_paths)


if __name__ == "__main__":
    unittest.main()
