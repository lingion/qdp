import tempfile
import unittest
from unittest.mock import patch

from qdp.core import QobuzDL


class UrlAndCollectionBehaviourTests(unittest.TestCase):
    def test_playlist_mixed_structure_normalizes_to_unique_albums(self):
        q = QobuzDL(check_only=True)
        items = [
            {"album": {"id": "10", "title": "A"}},
            {"album": {"id": "10", "title": "A"}},
            {"id": "20", "title": "B", "tracks_count": 8},
        ]
        normalized = q._normalize_collection_items(items, "playlist")
        self.assertEqual(sorted(item["id"] for item in normalized), ["10", "20"])

    def test_track_and_album_urls_dispatch_differently(self):
        q = QobuzDL(check_only=True)
        q.client = type("Client", (), {"get_plist_meta": None, "get_artist_meta": None, "get_label_meta": None})()
        calls = []
        with patch.object(q, "download_from_id", side_effect=lambda item_id, album, alt_path=None: calls.append((item_id, album))):
            q.handle_url("https://play.qobuz.com/track/123")
            q.handle_url("https://play.qobuz.com/album/456")
        self.assertEqual(calls, [("123", False), ("456", True)])

    def test_artist_target_filter_keeps_only_target_id(self):
        q = QobuzDL(check_only=True)
        items = [
            {"id": "1", "title": "Main", "artist": {"id": "42", "name": "Main Artist"}},
            {"id": "2", "title": "Guest", "artist": {"id": "99", "name": "Guest Artist"}},
        ]
        normalized = q._normalize_collection_items(items, "artist", target_artist_id="42")
        self.assertEqual([item["id"] for item in normalized], ["1"])


if __name__ == "__main__":
    unittest.main()
