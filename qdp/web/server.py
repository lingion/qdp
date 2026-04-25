"""
QDP Web Player Server — thin composition entry-point.

The monolithic handler has been split into focused modules:
  _transforms   — pure data functions (no I/O, no shared state)
  _helpers      — config, security, path-safety utilities
  _state        — shared state, caches, Client lifecycle, monkey-patch
  _handler_base — BaseHTTPRequestHandler base (routing + response infra + static)
  _handler_api  — /api/* route handler mixin
  _handler_proxy— proxy/stream handler mixin

This file composes the final handler class and provides the public API
(start_web_player / stop_web_player / main).  Every name that tests
patch via ``qdp.web.server.X`` is re-exported here for backward compat.
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import time
import urllib.parse                                     # noqa: F401  (tests: server.urllib)
from http.server import ThreadingHTTPServer
from typing import Optional

# ── Internal modules ──────────────────────────────────────────────────
from qdp.web import __version__ as WEB_PLAYER_VERSION
from qdp.web._helpers import (
    _DEFAULT_HOST, _DEFAULT_PORT, _runtime_host_port,
    _STATIC_ROOT,
)
from qdp.web._handler_base import QDPHandlerBase
from qdp.web._handler_api import APIHandlerMixin
from qdp.web._handler_proxy import ProxyHandlerMixin
from qdp.web._state import (                           # noqa: F401
    _WEB_SERVER, _WEB_THREAD, _WEB_URL,
    _REQUEST_TRACE, _CONFIG_CACHE,
    _CLIENT_CACHE, _CLIENT_CACHE_LOCK,
    _ENTITY_CACHE, _ENTITY_CACHE_LOCK,
    _get_client, _clear_client_cache, _cache_get, _cache_set,
    _inject_monkey_patch,
    logger,
)

# ── Re-exports for backward compat (tests patch these via qdp.web.server.X) ──
from qdp.web._helpers import (                         # noqa: F401
    _CONNECTION_WRITE_ERRORS, MAX_POST_BODY, MAX_UPSTREAM_RESPONSE,
    _get_runtime_defaults,
    _get_user_agent,
    _validate_stream_upstream_url, _allowed_cors_origin,
    _client_is_loopback, _is_loopback_host, _is_private_host,
    _guess_content_type, _safe_join, _env_value,
    _bool_from_value, _DEFAULT_USER_AGENT, _APP_CACHE_CONTROL,
    _INDEX_FILE, _APP_ROOT, _APP_INDEX_FILE,
    _APPLE_ROOT, _APPLE_INDEX_FILE,
    _ASSET_CACHE_ROOT,
)
from qdp.web._transforms import (                      # noqa: F401
    _pick_image, _rewrite_image_url, _artist_name,
    _extract_first_int, _normalize_sampling_rate_value,
    _extract_sampling_rate, _extract_audio_spec,
    _normalize_track, _sanitize_download_filename,
    _download_extension_for_fmt, _download_filename_for_track,
    _parse_qobuz_url, _mask_secret,
)
# Third-party re-exports that tests patch through server module namespace
import requests                                        # noqa: F401
from qdp.config import load_config_defaults            # noqa: F401
from qdp.accounts import get_active_account, list_accounts  # noqa: F401


# ── Composed handler class ────────────────────────────────────────────
class _QDPWebHandler(APIHandlerMixin, ProxyHandlerMixin, QDPHandlerBase):
    server_version = f"qdp-web/{WEB_PLAYER_VERSION}"


# ── Public API ────────────────────────────────────────────────────────

def _find_free_port(host: str, port: int, max_tries: int = 50) -> int:
    import socket as _socket
    for i in range(max_tries):
        cand = port + i
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, cand))
                return cand
            except OSError:
                continue
    raise OSError("no free port")


def start_web_player(host: Optional[str] = None, port: Optional[int] = None) -> str:
    """Start (or reuse) local web player server. Returns base URL."""
    global _WEB_SERVER, _WEB_THREAD, _WEB_URL

    if _WEB_THREAD and _WEB_THREAD.is_alive() and _WEB_URL:
        return _WEB_URL

    os.makedirs(_STATIC_ROOT, exist_ok=True)

    bind_host, bind_port = _runtime_host_port(host, port)
    free_port = _find_free_port(bind_host, bind_port)
    httpd = ThreadingHTTPServer((bind_host, free_port), _QDPWebHandler)

    t = threading.Thread(target=httpd.serve_forever, name="qdp-web", daemon=True)
    t.start()

    _WEB_SERVER = httpd
    _WEB_THREAD = t
    _WEB_URL = f"http://{bind_host}:{free_port}/"

    # small warmup
    time.sleep(0.1)
    return _WEB_URL


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the qdp local web player")
    parser.add_argument("--host", default=None, help="Bind host (default: env QDP_WEB_HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default: env QDP_WEB_PORT or 17890)")
    args = parser.parse_args([] if argv is None else argv)

    url = start_web_player(host=args.host, port=args.port)
    print(f"QDP web server listening on {url}")
    try:
        while _WEB_THREAD and _WEB_THREAD.is_alive():
            _WEB_THREAD.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_web_player()
    return 0


def stop_web_player():
    global _WEB_SERVER, _WEB_THREAD, _WEB_URL
    if _WEB_SERVER:
        try:
            _WEB_SERVER.shutdown()
        except OSError:
            logger.warning("Web server shutdown raised OSError", exc_info=True)
        try:
            _WEB_SERVER.server_close()
        except OSError:
            logger.warning("Web server close raised OSError", exc_info=True)
    _WEB_SERVER = None
    _WEB_THREAD = None
    _WEB_URL = None


if __name__ == "__main__":
    raise SystemExit(main())
