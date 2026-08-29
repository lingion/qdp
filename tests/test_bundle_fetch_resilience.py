"""Bundle credential bootstrap must survive CN-direct timeouts.

play.qobuz.com is unreachable from CN networks (connect timeout). Both
credential paths (qdp/bundle.py Bundle, qdp/utils.py
fetch_web_player_credentials) must fall back to the configured reverse
proxy (get_bundle_base_url -> proxy /proxy?url= passthrough), and must
read the full 9MB bundle body — iter_content with decode_unicode
truncates on gzip text; a complete read is required for the appId regex.

Also: qdp/utils.get_bundle_base_url must exist and honor proxy config.
"""
import logging
from unittest import mock

import requests

from qdp import utils
from qdp.bundle import Bundle, _get_base_urls

logging.disable(logging.CRITICAL)

_BUNDLE_PATH = "/resources/8.2.0-b034/bundle.js"

_LOGIN_HTML = (
    "<html><script src=\"%s\"></script></html>" % _BUNDLE_PATH
)

# seed must be a 44-char base64 chunk so seed+info+extras concatenation passes
# the >44 guard; info/extras entries use the capitalized city (qobuz-dl format)
_SEED = "c2VlZHNlZWRzZWVkc2VlZHNlZWRzZWVkc2VlZHNlZA=="

_BUNDLE_JS = (
    'production:{api:{appId:"798273057",appSecret:"' + "a" * 32 + '"}}'
    f'x.initialSeed("{_SEED}",window.utimezone.london)'
    'name:"eu/London",info:"aW5mbw==",extras:"ZXh0cmFz",'
)


class _FakeResponse:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.content = text.encode()
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")

    def iter_content(self, chunk_size=1, decode_unicode=False):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size].decode() if decode_unicode else self.content[i:i + chunk_size]


def test_env_override_still_supported(monkeypatch):
    monkeypatch.setenv("QDP_BUNDLE_URL", "https://mirror.example")
    assert _get_base_urls() == ["https://mirror.example"]
    monkeypatch.delenv("QDP_BUNDLE_URL")
    assert "play.qobuz.com" in _get_base_urls()[0]


def test_bundle_falls_back_to_proxy_base(monkeypatch):
    monkeypatch.delenv("QDP_BUNDLE_URL", raising=False)
    monkeypatch.setattr(utils, "get_active_proxy", lambda: "https://q2.example")

    # proxy /proxy?url= passthrough fetch
    calls = []

    def fake_get(self_session, url, **kwargs):
        calls.append(url)
        is_proxy = "q2.example" in url
        # proxy passthrough URLs are percent-encoded (%2Flogin), so match on
        # the decoded form too
        from urllib.parse import unquote

        decoded = unquote(url)
        if "/login" in decoded:
            # direct play.qobuz.com/login: CN-direct times out in real life —
            # emulate by failing the direct path so the proxy fallback fires
            return _FakeResponse(_LOGIN_HTML) if is_proxy else _FakeResponse("", 503)
        if _BUNDLE_PATH in decoded and is_proxy:
            return _FakeResponse(_BUNDLE_JS)
        return _FakeResponse("", 404)

    monkeypatch.setattr(Bundle.__init__.__globals__["Session"], "get", fake_get)
    b = Bundle()
    assert b.get_app_id() == "798273057"
    assert any("q2.example/proxy" in u for u in calls)


def test_fetch_web_player_credentials_uses_proxy_and_full_read(monkeypatch):
    monkeypatch.setattr(utils, "get_active_proxy", lambda: "https://q2.example")
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        from urllib.parse import unquote

        decoded = unquote(url)
        if "/login" in decoded:
            return _FakeResponse(_LOGIN_HTML)
        if _BUNDLE_PATH in decoded:
            return _FakeResponse(_BUNDLE_JS)
        return _FakeResponse("", 404)

    monkeypatch.setattr(utils.requests, "get", fake_get)
    app_id, secrets = utils.fetch_web_player_credentials()
    assert app_id == "798273057"
    assert "/proxy?url=" in seen["url"]
