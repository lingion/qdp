import tempfile
import unittest

from qdp.downloader import Download
from qdp.exceptions import InvalidAppSecretError


class FakeClient:
    def __init__(self):
        self.album_meta_calls = []
        self.track_url_calls = []
        self.secret_errors_at = set()

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
            # 模拟生产: 请求不存在的画质档位 → Qobuz 400 → qopy 包成 InvalidAppSecretError
            raise InvalidAppSecretError("API 签名错误 (App Secret 可能已失效)")
        if str(track_id) == "t-secret" and int(fmt_id) in self.secret_errors_at:
            raise InvalidAppSecretError("API 签名错误 (App Secret 可能已失效)")
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

    def test_invalid_secret_error_falls_back_to_lower_tier(self):
        """qopy 把 getFileUrl 400 包成 InvalidAppSecretError 抛出。

        语义双重: 可能 secret 失效, 也可能该画质不存在。fallback 循环必须
        捕获它继续试下一档; 全部档位失败才放弃。
        """
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            client.secret_errors_at = {27}
            d = Download(client, "album-1", tmp, 27)
            resolved = d._resolve_track_url_with_fallback("t-secret", 27)
            self.assertEqual(resolved["actual_quality"]["quality_code"], 7)
            self.assertEqual(client.track_url_calls, [("t-secret", 27), ("t-secret", 7)])

    def test_all_tiers_invalid_secret_raises_auth(self):
        """所有档位都 400 → 真 secret 失效, 最终以 auth 类错误抛出。"""
        from qdp.downloader import DownloadPipelineError

        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            client.secret_errors_at = {27, 7, 6, 5}
            d = Download(client, "album-1", tmp, 27)
            with self.assertRaises(DownloadPipelineError) as ctx:
                d._resolve_track_url_with_fallback("t-secret", 27)
            self.assertIn("quality-fallback", str(ctx.exception))

    def test_no_fallback_stops_at_requested_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            d = Download(client, "album-1", tmp, 27, downgrade_quality=False)
            with self.assertRaises(Exception):
                d._resolve_track_url_with_fallback("t-fallback", 27)
            self.assertEqual(client.track_url_calls, [("t-fallback", 27)])


if __name__ == "__main__":
    unittest.main()
