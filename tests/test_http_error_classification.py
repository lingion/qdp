"""HTTP 错误分类与统计分栏测试。

审计发现 P1: _classify_retryable_error 把 HTTP 403/404 误分类为 network,
单轨 5 次 × 外层整批重跑 5 次 = 最多 25 次注定失败的请求; 统计分栏按
消息子串("试听"/"无效")匹配, 网络失败("无效下载链接")被错计入 invalid。
"""
import unittest

import requests

from qdp.downloader import Download, DownloadPipelineError


def _make_downloader():
    client = type("Client", (), {})()
    return Download(client, "album-1", "/tmp/qdp-test-classify", 27)


class HttpErrorClassificationTests(unittest.TestCase):
    def test_403_http_error_not_network(self):
        d = _make_downloader()
        exc = requests.exceptions.HTTPError("403 Client Error: Forbidden")
        category = d._classify_retryable_error(exc)
        self.assertNotEqual(category, "network", "403 是永久性 HTTP 错误, 不该进 network 重试预算")

    def test_404_http_error_not_network(self):
        d = _make_downloader()
        exc = requests.exceptions.HTTPError("404 Client Error: Not Found")
        category = d._classify_retryable_error(exc)
        self.assertNotEqual(category, "network")

    def test_429_still_retryable(self):
        d = _make_downloader()
        exc = requests.exceptions.HTTPError("429 Client Error: Too Many Requests")
        category = d._classify_retryable_error(exc)
        self.assertEqual(category, "network", "429 限流应保持可重试")

    def test_timeout_still_network(self):
        d = _make_downloader()
        exc = requests.exceptions.Timeout("connection timed out")
        self.assertEqual(d._classify_retryable_error(exc), "network")


class StatsSplitTests(unittest.TestCase):
    def test_stats_split_uses_category_not_substring(self):
        """分栏按异常 category, 不按消息子串。

        "无效下载链接" 是 network 失败(category=network), 之前被
        "无效"子串错计为 invalid。
        """
        d = _make_downloader()
        failed_list = [
            {"item": {"id": "1"}, "error": "network 失败: 无效下载链接", "category": "network", "album": "A", "path": "/x", "label": "L1"},
            {"item": {"id": "2"}, "error": "仅提供试听，已跳过", "category": "copyright", "album": "A", "path": "/x", "label": "L2"},
        ]
        stats = {"success": 0, "failed": 0, "skipped": 0, "invalid": 0}
        invalid_count, hard_count = d._split_failed_entries(failed_list)
        stats["invalid"] = invalid_count
        stats["failed"] = hard_count
        self.assertEqual(stats["invalid"], 1, "只有 copyright(试听)进 invalid")
        self.assertEqual(stats["failed"], 1, "network 失败进 failed")


if __name__ == "__main__":
    unittest.main()
