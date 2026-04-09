import io
import json
import unittest
from unittest.mock import patch

from qdp.web import server


class WebServerApiContractsRound2Tests(unittest.TestCase):
    def _make_handler(self, path):
        handler = server._QDPWebHandler.__new__(server._QDPWebHandler)
        handler.headers = {"Accept": "application/json"}
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()
        handler.path = path
        response = {"status": None, "headers": []}
        handler.send_response = lambda code: response.__setitem__("status", code)
        handler.send_header = lambda key, value: response["headers"].append((key, value))
        handler.end_headers = lambda: None
        handler._trace = server._QDPWebHandler._trace.__get__(handler, server._QDPWebHandler)
        handler.client_address = ("127.0.0.1", 12345)
        return handler, response

    def test_search_invalid_limit_returns_structured_error(self):
        handler, response = self._make_handler("/api/search?q=test&limit=abc")
        with patch("qdp.web.server._get_client"):
            handler._handle_app_api(server.urllib.parse.urlparse(handler.path))
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(response["status"], 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_query")
        self.assertIn("message", payload["error"])

    def test_track_url_success_uses_wrapped_success_payload(self):
        handler, response = self._make_handler("/api/track-url?id=42&fmt=6")
        fake_client = type("Client", (), {"get_track_url": lambda self, tid, fmt: {"url": "https://stream.example.com/file.flac"}})()
        with patch("qdp.web.server._get_client", return_value=fake_client):
            handler._handle_app_api(server.urllib.parse.urlparse(handler.path))
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(response["status"], 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["url"], "/stream?url=https%3A%2F%2Fstream.example.com%2Ffile.flac")
        self.assertIn("download_url", payload["data"])

    def test_stream_missing_url_returns_json_error(self):
        handler, response = self._make_handler("/stream")
        handler._handle_stream_proxy(server.urllib.parse.urlparse(handler.path))
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(response["status"], 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_url")
        self.assertEqual(payload["data"], {})
        self.assertIsNone(payload["error"].get("details"))

    def test_meta_uses_wrapped_success_payload(self):
        handler, response = self._make_handler("/api/meta")
        handler._handle_meta()
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(response["status"], 200)
        self.assertTrue(payload["ok"])
        self.assertIn("data", payload)
        self.assertIsNone(payload["error"])
        self.assertEqual(payload["data"]["version"], server.WEB_PLAYER_VERSION)

    def test_accounts_list_uses_meta_count_and_wrapped_payload(self):
        handler, response = self._make_handler("/api/accounts")
        with patch("qdp.web.server.get_active_account", return_value="main"), patch(
            "qdp.web.server.list_accounts",
            return_value=[("main", {"label": "Primary"}), ("alt", {"label": "Backup"})],
        ):
            handler._handle_app_api(server.urllib.parse.urlparse(handler.path))
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(response["status"], 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["meta"]["count"], 2)
        self.assertEqual(payload["data"]["active_account"], "main")
        self.assertEqual(len(payload["data"]["items"]), 2)
        self.assertIsNone(payload["error"])


if __name__ == "__main__":
    unittest.main()
