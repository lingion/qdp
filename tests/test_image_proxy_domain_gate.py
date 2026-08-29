"""Image-proxy URL allow-list must match on parsed hostname suffix, not
substring. "qobuz.com" in target_url lets attacker-crafted URLs like
https://evil.com/?qobuz.com or https://qobuzcdn.evil.com/x.png through —
an SSRF vector when the server runs LAN-reachable.
"""
import logging
import urllib.parse
from unittest import mock

import pytest

from qdp.web import server as web_server

logging.disable(logging.CRITICAL)


def _qs(url: str) -> urllib.parse.ParseResult:
    return urllib.parse.urlparse(f"/api/image-proxy?url={urllib.parse.quote(url, safe='')}")


@pytest.fixture()
def handler():
    h = mock.Mock()
    h.headers = {"User-Agent": "t"}
    h._send_api_error = mock.Mock()
    h._trace = mock.Mock()
    return h


@pytest.mark.parametrize(
    "evil_url",
    [
        "https://evil.com/?u=https://qobuz.com",
        "https://evil.com/qobuz.com/x.png",
        "https://qobuzcdn.evil.com/a.jpg",
        "https://qobuz.com.evil.com/a.jpg",
        "https://static.qobuz.com@evil.com/a.jpg",
    ],
)
def test_substring_lookalikes_rejected(handler, evil_url):
    web_server._QDPWebHandler._handle_image_proxy(handler, _qs(evil_url))
    handler._send_api_error.assert_called_once()
    assert handler._send_api_error.call_args[0][0] == 403


@pytest.mark.parametrize(
    "good_url",
    [
        "https://static.qobuz.com/img/cover/a_og.jpg",
        "https://www.qobuz.com/img/x.jpg",
        "https://cdns-preview-qobuzcdn.example" .replace("example", "qobuz.com") + "/a.jpg",
    ],
)
def test_real_qobuz_domains_pass_gate(handler, good_url, monkeypatch):
    resp = mock.Mock()
    resp.status_code = 200
    resp.content = b"x" * 200
    monkeypatch.setattr(web_server.requests, "get", mock.Mock(return_value=resp))
    web_server._QDPWebHandler._handle_image_proxy(handler, _qs(good_url))
    handler._send_api_error.assert_not_called()
