import tempfile
import unittest

from qdp.downloader import Download


class FakeClient:
    def __init__(self):
        self.album_meta_calls = []
        self.track_url_calls = []

    def get_album_meta(self, album_id):
        self.album_meta_calls.append(str(album_id))
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
                        "title": "Song",
                        "track_number": 1,
                        "media_number": 1,
                        "performer": {"name": "Artist"},
                        "maximum_sampling_rate": 44.1,
                        "maximum_bit_depth": 16,
                    }
                ]
            },
        }

    def get_track_url(self, track_id, fmt_id=27):
        self.track_url_calls.append((str(track_id), int(fmt_id)))
        if str(track_id) == "t-fallback" and int(fmt_id) == 27:
            raise Exception("source has no requested quality")
        return {"url": f"https://example.com/{track_id}", "sampling_rate": 44.1, "bit_depth": 16}


class DownloaderCacheTests(unittest.TestCase):
    def test_album_meta_is_cached_between_inspections(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            d = Download(client, "album-1", tmp, 27, check_only=True)
            d.inspect_album("album-1", announce=False)
            d.inspect_album("album-1", announce=False)
            self.assertEqual(client.album_meta_calls, ["album-1"])

    def test_prime_track_urls_populates_cache_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            d = Download(client, "album-1", tmp, 27)
            tracks = [
                {"id": "t1", "title": "Song", "track_number": 1, "media_number": 1},
                {"id": "t1", "title": "Song", "track_number": 1, "media_number": 1},
            ]
            d._prime_track_urls(tracks)
            d._prime_track_urls(tracks)
            self.assertEqual(client.track_url_calls, [("t1", 27)])

    def test_quality_fallback_tries_lower_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            d = Download(client, "album-1", tmp, 27)
            resolved = d._resolve_track_url_with_fallback("t-fallback", 27)
            self.assertEqual(resolved["actual_quality"]["quality_code"], 7)
            self.assertEqual(client.track_url_calls, [("t-fallback", 27), ("t-fallback", 7)])

    def test_no_fallback_stops_at_requested_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            d = Download(client, "album-1", tmp, 27, downgrade_quality=False)
            with self.assertRaises(Exception):
                d._resolve_track_url_with_fallback("t-fallback", 27)
            self.assertEqual(client.track_url_calls, [("t-fallback", 27)])


if __name__ == "__main__":
    unittest.main()
