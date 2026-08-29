"""web player 安全加固测试。

审计发现(P2, 威胁模型=单用户本地工具):
- SSRF: _is_private_host 只看字面量, 十进制 IP("2130706433")/短格式("127.1")
  绕过; 域名从不做 DNS 校验; /stream 跟随重定向。
- CSRF: POST 不校验 Origin; CORS 放行本机任意端口 Origin。
- LAN: --host 非 loopback 时零认证暴露全盘枚举/任意目录写盘。
"""
import http
import io
import json
import unittest
from unittest.mock import patch

from qdp.web import server


def _make_handler(path, headers=None):
    handler = server._QDPWebHandler.__new__(server._QDPWebHandler)
    handler.headers = headers or {"Accept": "application/json"}
    handler.rfile = io.BytesIO()
    handler.wfile = io.BytesIO()
    handler.path = path
    response = {"status": None, "headers": []}
    handler.send_response = lambda code: response.__setitem__("status", code)
    handler.send_header = lambda key, value: response["headers"].append((key, value))
    handler.end_headers = lambda: None
    handler._trace = lambda *a, **k: None
    handler.client_address = ("127.0.0.1", 12345)
    return handler, response


class SsrfTests(unittest.TestCase):
    def test_decimal_ip_host_rejected(self):
        # 2130706433 = 127.0.0.1 的十进制形式
        self.assertTrue(server._is_private_host("2130706433"))

    def test_short_ip_form_rejected(self):
        self.assertTrue(server._is_private_host("127.1"))

    def test_domain_resolving_to_loopback_rejected(self):
        with patch.object(server.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 0))]):
            self.assertTrue(server._is_private_host("attacker.example"))

    def test_normal_public_domain_allowed(self):
        with patch.object(server.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            self.assertFalse(server._is_private_host("example.com"))

    def test_unresolvable_domain_rejected(self):
        with patch.object(server.socket, "getaddrinfo", side_effect=server.socket.gaierror("nx")):
            self.assertTrue(server._is_private_host("nonexistent.invalid"))

    def test_stream_upstream_rejects_decimal_ip(self):
        with self.assertRaises(ValueError):
            server._validate_stream_upstream_url("http://2130706433/file.flac")

    def test_stream_upstream_rejects_private_domain(self):
        with patch.object(server.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 0))]):
            with self.assertRaises(ValueError):
                server._validate_stream_upstream_url("http://internal.example/file.flac")


class OriginTests(unittest.TestCase):
    def setUp(self):
        self._old_server = server._WEB_SERVER
        self._old_token = server._WEB_ACCESS_TOKEN
        server._WEB_ACCESS_TOKEN = None

    def tearDown(self):
        server._WEB_SERVER = self._old_server
        server._WEB_ACCESS_TOKEN = self._old_token

    def _fake_httpd(self, port):
        httpd = type("FakeHTTPD", (), {})
        httpd.server_address = ("127.0.0.1", port)
        return httpd

    def test_post_with_foreign_origin_rejected(self):
        server._WEB_SERVER = self._fake_httpd(17890)
        handler, response = _make_handler(
            "/api/cache-clear",
            headers={"Origin": "http://127.0.0.1:9999", "Content-Length": "2"},
        )
        handler.rfile.write(b"{}")
        handler.do_POST()
        self.assertEqual(response["status"], 403, "跨端口 Origin 的 POST 应被拒")

    def test_post_with_same_port_origin_allowed(self):
        server._WEB_SERVER = self._fake_httpd(17890)
        handler, response = _make_handler(
            "/api/cache-clear",
            headers={"Origin": "http://127.0.0.1:17890", "Content-Length": "2"},
        )
        handler.rfile.write(b"{}")
        with patch.object(server._QDPWebHandler, "_handle_app_api", lambda self, parsed: None):
            handler.do_POST()
        self.assertNotEqual(response["status"], 403)

    def test_cors_allows_only_server_port(self):
        server._WEB_SERVER = self._fake_httpd(17890)
        self.assertEqual(server._allowed_cors_origin("http://127.0.0.1:17890"), "http://127.0.0.1:17890")
        self.assertEqual(server._allowed_cors_origin("http://127.0.0.1:9999"), "")


class LanTokenTests(unittest.TestCase):
    def setUp(self):
        self._old_token = server._WEB_ACCESS_TOKEN
        self._old_server = server._WEB_SERVER

    def tearDown(self):
        server._WEB_ACCESS_TOKEN = self._old_token
        server._WEB_SERVER = self._old_server

    def test_loopback_mode_no_token_required(self):
        server._WEB_ACCESS_TOKEN = None
        handler, response = _make_handler("/__version")
        self.assertTrue(handler._access_token_ok())

    def test_lan_mode_requires_token(self):
        server._WEB_ACCESS_TOKEN = "tok123"
        handler, response = _make_handler("/__version")
        ok = handler._access_token_ok()
        self.assertFalse(ok, "LAN 模式无 token 应拒绝")

    def test_lan_mode_header_token_accepted(self):
        server._WEB_ACCESS_TOKEN = "tok123"
        handler, _ = _make_handler("/__version", headers={"X-QDP-Token": "tok123"})
        self.assertTrue(handler._access_token_ok())

    def test_lan_mode_query_token_accepted(self):
        server._WEB_ACCESS_TOKEN = "tok123"
        handler, _ = _make_handler("/?token=tok123")
        self.assertTrue(handler._access_token_ok())

    def test_start_web_player_generates_token_for_lan(self):
        # 0.0.0.0 绑定必须生成 token
        created = {}

        def fake_httpd(addr, handler):
            created["addr"] = addr
            t = type("FakeHTTPD", (), {})
            t.server_address = (addr[0], addr[1])
            t.serve_forever = lambda: None
            t.shutdown = lambda: None
            t.server_close = lambda: None
            return t

        with patch.object(server, "ThreadingHTTPServer", side_effect=fake_httpd):
            with patch.object(server, "_find_free_port", return_value=17891):
                with patch.object(server.threading.Thread, "start", lambda self: None):
                    url = server.start_web_player(host="0.0.0.0", port=17891)
        self.assertIsNotNone(server._WEB_ACCESS_TOKEN, "LAN 绑定必须生成 access token")
        # 收尾
        if server._WEB_SERVER is not None:
            server._WEB_SERVER = None
        server._WEB_ACCESS_TOKEN = self._old_token


if __name__ == "__main__":
    unittest.main()
