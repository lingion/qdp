"""Configuration, security, and path-safety helpers for the QDP web server.

This module groups constants and utility functions that deal with runtime
configuration, host validation, CORS security, content-type guessing, and
safe filesystem path joining.  The helpers are used by the request handler
and the server start/stop machinery but have *no* dependency on the HTTP
framework itself (no ``http.server`` imports), making them straightforward
to test in isolation.
"""

from __future__ import annotations

import ipaddress
import logging
import mimetypes
import os
import urllib.parse
from typing import Dict, Optional, Tuple

from qdp.config import CONFIG_FILE, load_config_defaults

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONNECTION_WRITE_ERRORS = (BrokenPipeError, ConnectionResetError)

MAX_POST_BODY = 1_048_576  # 1 MB
MAX_UPSTREAM_RESPONSE = 10_485_760  # 10 MB

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 17890
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0"
)

_APP_CACHE_CONTROL = "no-store, no-cache, must-revalidate, max-age=0"

_STATIC_ROOT = os.path.join(os.path.dirname(__file__), "static")
_INDEX_FILE = "Discover - Qobuz.html"

_APP_ROOT = os.path.join(os.path.dirname(__file__), "app")
_APP_INDEX_FILE = "index.html"

_APPLE_ROOT = os.path.join(os.path.dirname(__file__), "apple")
_APPLE_INDEX_FILE = "index.html"

_ASSET_CACHE_ROOT = os.path.join(os.path.dirname(__file__), "cache-assets")

# ---------------------------------------------------------------------------
# Config cache (TTL-based)
# ---------------------------------------------------------------------------

_CONFIG_CACHE: dict = {"ts": 0, "data": None}
_CONFIG_CACHE_TTL = 5.0  # seconds

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return str(value).strip()
    return ""


def _bool_from_value(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _get_runtime_defaults() -> Dict[str, str]:
    import time

    now = time.time()
    if _CONFIG_CACHE["data"] is not None and (now - _CONFIG_CACHE["ts"]) < _CONFIG_CACHE_TTL:
        return _CONFIG_CACHE["data"]
    defaults = load_config_defaults(CONFIG_FILE)
    merged = dict(defaults)

    app_id = _env_value("QDP_APP_ID", "QOBUZ_APP_ID")
    if app_id:
        merged["app_id"] = app_id

    user_agent = _env_value("QDP_USER_AGENT", "QOBUZ_USER_AGENT")
    if user_agent:
        merged["user_agent"] = user_agent

    use_token_env = _env_value("QDP_USE_TOKEN", "QOBUZ_USE_TOKEN")
    if use_token_env:
        merged["use_token"] = "true" if _bool_from_value(use_token_env) else "false"

    auth_token = _env_value("QDP_AUTH_TOKEN", "QOBUZ_AUTH_TOKEN", "QOBUZ_USER_AUTH_TOKEN")
    if auth_token:
        merged["user_auth_token"] = auth_token
        merged["use_token"] = "true"

    _CONFIG_CACHE["ts"] = now
    _CONFIG_CACHE["data"] = merged
    return merged


def _runtime_host_port(host: Optional[str] = None, port: Optional[int] = None) -> Tuple[str, int]:
    env_host = _env_value("QDP_WEB_HOST")
    env_port = _env_value("QDP_WEB_PORT")

    final_host = str(host or env_host or _DEFAULT_HOST).strip() or _DEFAULT_HOST

    raw_port = port if port is not None else (env_port or _DEFAULT_PORT)
    try:
        final_port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid port: {raw_port!r}") from exc
    if not (1 <= final_port <= 65535):
        raise ValueError(f"Port out of range: {final_port}")
    return final_host, final_port


def _get_user_agent(defaults: Optional[Dict[str, str]] = None) -> str:
    defaults = defaults or _get_runtime_defaults()
    return str(defaults.get("user_agent") or _DEFAULT_USER_AGENT)


def _is_private_host(host: str) -> bool:
    parsed = urllib.parse.urlparse(host if "://" in host else f"http://{host}")
    hostname = (parsed.hostname or host or "").strip().strip("[]")
    lowered = hostname.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        addr = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return bool(addr.is_loopback or addr.is_private or addr.is_link_local)


def _is_loopback_host(host: str) -> bool:
    parsed = urllib.parse.urlparse(host if "://" in host else f"http://{host}")
    hostname = (parsed.hostname or host or "").strip().strip("[]")
    lowered = hostname.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def _origin_is_loopback(origin: str) -> bool:
    if not origin:
        return False
    try:
        parsed = urllib.parse.urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return _is_loopback_host(parsed.hostname or "")


def _client_is_loopback(client_address: object) -> bool:
    if not client_address:
        return False
    host = client_address[0] if isinstance(client_address, tuple) and client_address else client_address
    return _is_loopback_host(str(host or ""))


def _allowed_cors_origin(origin: str) -> str:
    if _origin_is_loopback(origin):
        return origin
    return ""


def _validate_stream_upstream_url(raw_url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(raw_url)
    except ValueError as exc:
        raise ValueError("invalid stream url") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise ValueError("stream url must use http or https")
    if not parsed.netloc:
        raise ValueError("stream url missing host")
    if _is_private_host(parsed.hostname or ""):
        raise ValueError("stream url host is not allowed")
    return parsed.geturl()


def _guess_content_type(path: str) -> str:
    ctype, _ = mimetypes.guess_type(path)
    return ctype or "application/octet-stream"


def _safe_join(root: str, rel: str) -> str:
    # Prevent path traversal
    rel = rel.lstrip("/")
    rel = rel.replace("\\", "/")
    full = os.path.abspath(os.path.join(root, rel))
    root_abs = os.path.abspath(root)
    if not full.startswith(root_abs + os.sep) and full != root_abs:
        raise ValueError("invalid path")
    return full
