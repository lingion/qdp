import io
import json
import socket
import tempfile
import threading
import time
import unittest
from contextlib import closing
from unittest.mock import patch

import requests

from qdp.web import server


class _FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None, json_data=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._json_data = json_data

    def json(self):
        if self._json_data is not None:
            return self._json_data
        if self.content:
            return json.loads(self.content.decode("utf-8"))
        return {}

    def iter_content(self, chunk_size=65536):
        data = self.content or b""
        for idx in range(0, len(data), chunk_size):
            yield data[idx : idx + chunk_size]


class WebServerRuntimeTests(unittest.TestCase):
    def tearDown(self):
        server.stop_web_player()

    def test_runtime_defaults_apply_environment_overrides(self):
        with patch.dict(
            "os.environ",
            {
                "QDP_WEB_HOST": "127.0.0.2",
                "QDP_WEB_PORT": "18901",
                "QOBUZ_APP_ID": "env-app-id",
                "QOBUZ_USER_AUTH_TOKEN": "env-auth-token",
                "QOBUZ_USER_AGENT": "env-agent/1.0",
            },
            clear=False,
        ), patch("qdp.web.server.load_config_defaults", return_value={"app_id": "cfg-app", "user_auth_token": "cfg-token"}):
            defaults = server._get_runtime_defaults()
            host, port = server._runtime_host_port()

        self.assertEqual(defaults["app_id"], "env-app-id")
        self.assertEqual(defaults["user_auth_token"], "env-auth-token")
        self.assertEqual(defaults["user_agent"], "env-agent/1.0")
        self.assertEqual(defaults["use_token"], "true")
        self.assertEqual(host, "127.0.0.2")
        self.assertEqual(port, 18901)

    def test_validate_stream_upstream_url_rejects_private_or_invalid_hosts(self):
        self.assertEqual(
            server._validate_stream_upstream_url("https://stream.example.com/audio.flac"),
            "https://stream.example.com/audio.flac",
        )
        for invalid in [
            "",
            "ftp://stream.example.com/file.flac",
            "https://127.0.0.1/file.flac",
            "https://localhost/file.flac",
            "https://192.168.1.20/file.flac",
            "/relative/path.flac",
        ]:
            with self.assertRaises(ValueError, msg=invalid):
                server._validate_stream_upstream_url(invalid)

    def test_qobuz_api_proxy_uses_env_auth_and_masks_trace(self):
        payload = {"url": "https://audio.example.com/file.flac", "user_auth_token": "upstream-visible-only"}
        fake_response = _FakeResponse(
            status_code=200,
            content=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            json_data=payload,
        )
        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["url"] = url
            captured["headers"] = dict(headers or {})
            return fake_response

        with patch.dict(
            "os.environ",
            {
                "QOBUZ_APP_ID": "app-from-env",
                "QOBUZ_USER_AUTH_TOKEN": "secret-token-123456",
                "QOBUZ_USER_AGENT": "qdp-test-agent/1.0",
            },
            clear=False,
        ), patch("qdp.web.server.load_config_defaults", return_value={}), patch("qdp.web.server.requests.get", side_effect=fake_get):
            handler = server._QDPWebHandler.__new__(server._QDPWebHandler)
            handler.headers = {"Accept": "application/json"}
            handler.rfile = io.BytesIO()
            handler.wfile = io.BytesIO()
            response = {"status": None, "headers": []}
            handler.send_response = lambda code: response.__setitem__("status", code)
            handler.send_header = lambda key, value: response["headers"].append((key, value))
            handler.end_headers = lambda: None
            handler._trace = server._QDPWebHandler._trace.__get__(handler, server._QDPWebHandler)
            parsed = server.urllib.parse.urlparse("/api.json/0.2/track/getFileUrl?track_id=42")

            server._REQUEST_TRACE.clear()
            handler._handle_qobuz_api_proxy(parsed)

        self.assertEqual(response["status"], 200)
        self.assertIn(("Content-Type", "application/json"), response["headers"])
        self.assertEqual(captured["headers"]["X-App-Id"], "app-from-env")
        self.assertEqual(captured["headers"]["X-User-Auth-Token"], "secret-token-123456")
        self.assertEqual(captured["headers"]["User-Agent"], "qdp-test-agent/1.0")
        body = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(body["url"], "/stream?url=https%3A%2F%2Faudio.example.com%2Ffile.flac")
        trace_dump = json.dumps(server._REQUEST_TRACE)
        self.assertNotIn("secret-token-123456", trace_dump)
        self.assertNotIn("upstream-visible-only", trace_dump)

    def test_main_serves_http_routes_and_invalid_stream_request(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ",
            {
                "QDP_WEB_HOST": "127.0.0.1",
                "QDP_WEB_PORT": "18911",
                "QDP_APP_ID": "smoke-app-id",
                "QDP_AUTH_TOKEN": "smoke-auth-token",
                "QDP_USER_AGENT": "smoke-agent/1.0",
            },
            clear=False,
        ), patch.object(server, "_APP_ROOT", tmpdir):
            with open(f"{tmpdir}/index.html", "w", encoding="utf-8") as fp:
                fp.write("<!doctype html><title>runtime ok</title><div>runtime ok</div>")

            thread = threading.Thread(target=server.main, daemon=True)
            thread.start()
            base_url = self._wait_for_server("127.0.0.1", 18911)

            root_resp = requests.get(base_url + "/", allow_redirects=False, timeout=5)
            app_resp = requests.get(base_url + "/app/", timeout=5, headers={"Origin": "http://127.0.0.1:3000"})
            version_resp = requests.get(base_url + "/__version", timeout=5)
            meta_resp = requests.get(base_url + "/api/meta", timeout=5)
            missing_resp = requests.get(base_url + "/missing-route", timeout=5)
            bad_stream_resp = requests.get(base_url + "/stream", timeout=5)
            proxy_resp = requests.get(base_url + "/api.json/0.2/test?x=1", timeout=5)

            self.assertEqual(root_resp.status_code, 302)
            self.assertEqual(root_resp.headers.get("Location"), "/app/")
            self.assertEqual(app_resp.status_code, 200)
            self.assertIn("runtime ok", app_resp.text)
            self.assertEqual(app_resp.headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:3000")
            self.assertEqual(version_resp.status_code, 200)
            version_payload = version_resp.json()
            self.assertTrue(version_payload["ok"])
            self.assertEqual(version_payload["data"]["version"], server.WEB_PLAYER_VERSION)
            self.assertEqual(meta_resp.status_code, 200)
            meta_payload = meta_resp.json()
            self.assertTrue(meta_payload["ok"])
            self.assertEqual(meta_payload["data"]["version"], server.WEB_PLAYER_VERSION)
            self.assertIsNone(meta_payload["error"])
            self.assertEqual(missing_resp.status_code, 404)
            self.assertEqual(bad_stream_resp.status_code, 400)
            bad_stream_payload = bad_stream_resp.json()
            self.assertFalse(bad_stream_payload["ok"])
            self.assertEqual(bad_stream_payload["error"]["code"], "missing_url")
            self.assertEqual(proxy_resp.status_code, 200)
            proxy_payload = proxy_resp.json()
            self.assertTrue(proxy_payload["ok"])
            self.assertEqual(proxy_payload["data"]["query"], {"x": ["1"]})
            self.assertTrue(proxy_payload["data"]["auth"]["has_app_id"])
            self.assertTrue(proxy_payload["data"]["auth"]["has_user_auth_token"])

            requests.get(base_url + "/__shutdown", timeout=5)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_proxy_smoke_route_documents_runtime_contract(self):
        with patch.dict(
            "os.environ",
            {
                "QDP_APP_ID": "smoke-app-id",
                "QDP_AUTH_TOKEN": "smoke-auth-token",
                "QDP_USER_AGENT": "smoke-agent/1.0",
            },
            clear=False,
        ), patch("qdp.web.server.load_config_defaults", return_value={}):
            handler = server._QDPWebHandler.__new__(server._QDPWebHandler)
            handler.headers = {"Accept": "application/json"}
            handler.rfile = io.BytesIO()
            handler.wfile = io.BytesIO()
            response = {"status": None, "headers": []}
            handler.path = "/api.json/0.2/test?x=1"
            handler.send_response = lambda code: response.__setitem__("status", code)
            handler.send_header = lambda key, value: response["headers"].append((key, value))
            handler.end_headers = lambda: None
            handler._trace = server._QDPWebHandler._trace.__get__(handler, server._QDPWebHandler)

            server._REQUEST_TRACE.clear()
            handler._handle_qobuz_api_proxy(server.urllib.parse.urlparse(handler.path))

        self.assertEqual(response["status"], 200)
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["path"], "/api.json/0.2/test")
        self.assertEqual(payload["data"]["query"], {"x": ["1"]})
        self.assertEqual(payload["data"]["auth"]["user_agent"], "smoke-agent/1.0")
        self.assertIsNone(payload["error"])
        trace_dump = json.dumps(server._REQUEST_TRACE)
        self.assertNotIn("smoke-auth-token", trace_dump)

    def test_send_json_ignores_client_disconnect_during_body_write(self):
        handler = server._QDPWebHandler.__new__(server._QDPWebHandler)
        handler.path = "/api/meta"
        handler.headers = {}
        handler.rfile = io.BytesIO()
        response = {"status": None, "headers": []}
        handler.send_response = lambda code: response.__setitem__("status", code)
        handler.send_header = lambda key, value: response["headers"].append((key, value))
        handler.end_headers = lambda: None
        handler._trace = server._QDPWebHandler._trace.__get__(handler, server._QDPWebHandler)

        class _BrokenWriter:
            def write(self, _data):
                raise BrokenPipeError("client closed")

        handler.wfile = _BrokenWriter()

        handler._send_json({"ok": True}, status=200)

        self.assertEqual(response["status"], 200)
        self.assertIn(("Content-Type", "application/json; charset=utf-8"), response["headers"])

    @staticmethod
    def _wait_for_server(host, port, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex((host, port)) == 0:
                    return f"http://{host}:{port}"
            time.sleep(0.05)
        raise AssertionError(f"server did not start on {host}:{port}")


if __name__ == "__main__":
    unittest.main()
