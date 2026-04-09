import tempfile
import unittest

from qdp.downloader import Download, DownloadPipelineError


class FakeClientRate:
    def __init__(self):
        self.calls = []

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
                        "id": f"t{idx}",
                        "title": f"Song {idx}",
                        "track_number": idx,
                        "media_number": 1,
                        "performer": {"name": "Artist"},
                        "maximum_sampling_rate": 44.1,
                        "maximum_bit_depth": 16,
                    }
                    for idx in range(1, 6)
                ]
            },
        }

    def get_track_url(self, track_id, fmt_id):
        self.calls.append((str(track_id), int(fmt_id)))
        return {"url": f"https://example.com/{track_id}", "sampling_rate": 44.1, "bit_depth": 16}


class DownloaderPipelineTests(unittest.TestCase):
    def test_prime_track_urls_respects_rate_limiter_calls(self):
        # We can't reliably assert timing in CI, but we can assert that
        # get_track_url is called once per track, and results are cached.
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClientRate()
            d = Download(client, "album-1", tmp, 27, workers=4, prefetch_workers=3, url_rate=1000)
            meta = client.get_album_meta("album-1")
            tracks = meta["tracks"]["items"]
            d._prime_track_urls(tracks)
            d._prime_track_urls(tracks)
            # Only 5 unique tracks, requested quality is 27.
            self.assertEqual(len(client.calls), 5)
            self.assertTrue(all(call[1] == 27 for call in client.calls))

    def test_resolve_track_url_raises_structured_pipeline_error_after_attempts(self):
        class FailingClient:
            def get_track_url(self, track_id, fmt_id):
                raise ValueError("broken upstream payload")

        with tempfile.TemporaryDirectory() as tmp:
            d = Download(FailingClient(), "album-1", tmp, 27, workers=1, prefetch_workers=1, url_rate=1000)
            with self.assertRaises(DownloadPipelineError) as ctx:
                d._resolve_track_url_with_fallback("track-1", 27)
        self.assertEqual(ctx.exception.category, "generic")
        self.assertIn("URL 预热失败", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
