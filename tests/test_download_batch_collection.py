"""download_batch 集合分发行为测试。

审计发现 P0: 歌单/厂牌批量下载时,download_batch 按"数据形状"(含 tracks_count+artist)
进入主艺人锁定分支,拿歌单名当艺人名做子串匹配,整批专辑被清空。
修复: 只有调用方显式声明 target_artist_id(URL 是 artist 类型)才进入锁定分支。
"""
import tempfile
import unittest
from unittest.mock import patch

from qdp.downloader import Download


def _make_downloader(**kwargs):
    client = type("Client", (), {})()
    defaults = dict(
        client=client,
        item_id="batch-test",
        path=tempfile.mkdtemp(),
        quality=27,
    )
    defaults.update(kwargs)
    return Download(**defaults)


class DownloadBatchCollectionTests(unittest.TestCase):
    def _album_items(self):
        return [
            {
                "id": "10",
                "title": "Greatest Hits",
                "tracks_count": 8,
                "artist": {"id": "42", "name": "Jay Chou"},
            },
            {
                "id": "11",
                "title": "Live Set",
                "tracks_count": 12,
                "artist": {"id": "99", "name": "Wu Bai"},
            },
        ]

    def _flattened_album_ids(self, dloader, items, content_name, target_artist_id):
        """跑 download_batch, 返回真正进入扁平化/下载流程的专辑 id 列表。

        非 artist 批量不进锁定分支, final_list 原样传给 _run_multithreaded_download;
        artist 批量进锁定分支, 经 _flatten_albums_to_tracks, 用 fake fetch 让每张
        专辑产出一首带 album 的 track, 再从下载列表反推专辑 id。
        """
        album_meta = {
            "10": {"id": "10", "title": "Greatest Hits"},
            "11": {"id": "11", "title": "Live Set"},
        }
        track_of = {"10": [{"id": "t10", "album": album_meta["10"]}], "11": [{"id": "t11", "album": album_meta["11"]}]}

        def fake_fetch(album_simple, base_path):
            aid = str(album_simple["id"])
            return {"status": "ready", "tracks": track_of[aid], "report": None}

        with patch.object(dloader, "_fetch_and_prepare_album", side_effect=fake_fetch):
            with patch.object(dloader, "_run_multithreaded_download", return_value={}) as run:
                dloader.download_batch(items, content_name=content_name, target_artist_id=target_artist_id)
        final_list = run.call_args[0][0]
        return sorted(t["album"]["id"] if "album" in t else t["id"] for t in final_list)

    def test_playlist_batch_not_filtered_by_artist_lock(self):
        """歌单名"华语金曲"不该被拿来当艺人名过滤专辑。"""
        dloader = _make_downloader()
        ids = self._flattened_album_ids(dloader, self._album_items(), "华语金曲", None)
        self.assertEqual(ids, ["10", "11"], "歌单批量不应被主艺人锁定分支过滤")

    def test_label_batch_not_filtered_by_artist_lock(self):
        """厂牌批量(无 target_artist_id)同样不能被过滤。"""
        dloader = _make_downloader()
        ids = self._flattened_album_ids(dloader, self._album_items(), "Blue Note", None)
        self.assertEqual(ids, ["10", "11"])

    def test_artist_batch_still_locked_to_target_artist(self):
        """真正的艺人 URL 批量锁定行为保留: target_artist_id 匹配 ID。"""
        dloader = _make_downloader()
        ids = self._flattened_album_ids(dloader, self._album_items(), "Jay Chou", "42")
        self.assertEqual(ids, ["10"])

    def test_artist_batch_spam_keyword_still_filtered(self):
        """艺人批量下 Karaoke/Tribute 黑名单过滤仍然生效。"""
        dloader = _make_downloader()
        items = self._album_items()
        items.append({
            "id": "12",
            "title": "Jay Chou Karaoke Hits",
            "tracks_count": 5,
            "artist": {"id": "42", "name": "Jay Chou"},
        })
        ids = self._flattened_album_ids(dloader, items, "Jay Chou", "42")
        self.assertEqual(ids, ["10"])


if __name__ == "__main__":
    unittest.main()
