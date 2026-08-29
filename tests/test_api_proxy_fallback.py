"""API 层代理兜底与 force_proxy 行为测试。

审计发现 P1: qopy.api_call 有代理池时尝试队列只含代理, 直连分支不可达,
README 承诺的"代理全挂直连兜底"在 API 层不存在。反向: force_proxy 只在
downloader 生效, API 层静默直连。
修复: 代理全失败后追加一次直连尝试; force_proxy=True 时禁止直连。
"""
import unittest
from unittest.mock import patch

import requests

from qdp.qopy import Client
from qdp.exceptions import InvalidAppSecretError


def _make_client(force_proxy=False):
    with patch("qdp.qopy.get_proxy_list", return_value=["https://p1.example", "https://p2.example"]):
        with patch("qdp.qopy.get_api_base_url", return_value="https://p1.example/api.json/0.2/"):
            with patch.object(Client, "_pre_fetch_credentials", lambda self, config_file=None: None):
                client = Client.__new__(Client)
                client.secrets = ["s" * 32]
                client.id = "950096963"
                client.proxy_list = ["https://p1.example", "https://p2.example"]
                client.base = "https://p1.example/api.json/0.2/"
                client.sec = "s" * 32
                client.uat = "uat"
                client.force_proxy = force_proxy
                client.session = requests.Session()
    return client


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error")


class ApiProxyFallbackTests(unittest.TestCase):
    def test_all_proxies_fail_then_direct_fallback(self):
        """两个代理全挂 → 必须再试一次直连, 而不是直接抛 ProxyError。"""
        client = _make_client()
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            if url.startswith(("https://p1.example", "https://p2.example")):
                raise requests.exceptions.ProxyError("proxy dead")
            return _FakeResponse(200, {"ok": True})

        with patch.object(client.session, "get", side_effect=fake_get):
            result = client.api_call("track/get", id="123")
        self.assertEqual(result, {"ok": True})
        direct_calls = [u for u in calls if "qobuz.com" in u]
        self.assertEqual(len(direct_calls), 1, "代理全挂后应有一次直连尝试")

    def test_force_proxy_never_goes_direct(self):
        """force_proxy 开启 → 代理全挂也不直连。"""
        client = _make_client(force_proxy=True)
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            raise requests.exceptions.ProxyError("proxy dead")

        with patch.object(client.session, "get", side_effect=fake_get):
            with self.assertRaises(requests.exceptions.ProxyError):
                client.api_call("track/get", id="123")
        self.assertFalse(any("qobuz.com" in u for u in calls), "force_proxy 下不得出现直连请求")

    def test_proxy_success_skips_direct(self):
        """任一代理成功 → 不打直连。"""
        client = _make_client()
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            if url.startswith("https://p2.example"):
                return _FakeResponse(200, {"ok": True})
            raise requests.exceptions.ProxyError("p1 dead")

        with patch.object(client.session, "get", side_effect=fake_get):
            result = client.api_call("track/get", id="123")
        self.assertEqual(result, {"ok": True})
        self.assertFalse(any("qobuz.com" in u for u in calls))


if __name__ == "__main__":
    unittest.main()
