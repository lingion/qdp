import os
import tempfile
import unittest
from unittest.mock import patch

from qdp.core import QobuzDL


class CoreCheckOnlyTests(unittest.TestCase):
    def test_playlist_check_only_does_not_create_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = QobuzDL(directory=tmp, check_only=True)
            q.client = type("Client", (), {
                "get_plist_meta": lambda self, _id: iter([
                    {
                        "name": "My Playlist",
                        "tracks": {
                            "items": [
                                {"album": {"id": "101", "title": "A1", "artist": {"id": "9", "name": "Artist"}}},
                                {"album": {"id": "101", "title": "A1", "artist": {"id": "9", "name": "Artist"}}},
                            ]
                        },
                    }
                ]),
                "get_artist_meta": lambda self, _id: iter([]),
                "get_label_meta": lambda self, _id: iter([]),
            })()
            with patch.object(q, "_check_collection_albums", return_value=[]) as mocked:
                q.handle_url("https://play.qobuz.com/playlist/abc")
            mocked.assert_called_once()
            called_items = mocked.call_args[0][0]
            self.assertEqual(len(called_items), 1)
            self.assertFalse(os.path.exists(os.path.join(tmp, "My Playlist")))

    def test_artist_check_only_filters_target_artist(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = QobuzDL(directory=tmp, check_only=True)
            items = [
                {"id": "1", "title": "Main", "artist": {"id": "42", "name": "Main Artist"}},
                {"id": "2", "title": "Other", "artist": {"id": "7", "name": "Other"}},
            ]
            normalized = q._normalize_collection_items(items, "artist", target_artist_id="42")
            self.assertEqual([item["id"] for item in normalized], ["1"])


if __name__ == "__main__":
    unittest.main()
