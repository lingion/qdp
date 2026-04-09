import json
import os
import tempfile
import unittest

from qdp.sidecar import get_sidecar_path, load_sidecar


class SidecarLegacyCompatTests(unittest.TestCase):
    def test_load_sidecar_falls_back_to_legacy_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            album_dir = os.path.join(tmp, "Album")
            os.makedirs(album_dir)
            legacy_path = os.path.join(album_dir, "qdp_album.json")
            with open(legacy_path, "w", encoding="utf-8") as handle:
                json.dump({"album_id": "1", "tracks": [{"track_id": "t1", "expected_filename": "01. A.flac"}]}, handle)

            # Preferred path doesn't exist
            self.assertFalse(os.path.exists(get_sidecar_path(album_dir)))
            loaded = load_sidecar(album_dir)
            self.assertEqual(loaded["album_id"], "1")
            # sidecar_path should point to legacy file.
            self.assertEqual(os.path.normpath(loaded["sidecar_path"]), os.path.normpath(legacy_path))
            # upgraded field
            self.assertEqual(loaded["tracks"][0]["expected_stem"], "01. A")


if __name__ == "__main__":
    unittest.main()
