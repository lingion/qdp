"""QDP web handler base class.

Provides routing, response infrastructure, debug endpoints, CORS,
and static file serving for the QDP local web player.

Mixin classes supply the heavy handler methods (app API, Qobuz API proxy,
stream proxy, cover proxy, cache clear, play assets proxy) at composition time.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Optional

from qdp.web import __version__ as WEB_PLAYER_VERSION
from qdp.web._helpers import (
    _allowed_cors_origin, _APP_CACHE_CONTROL, _APP_ROOT, _APP_INDEX_FILE,
    _APPLE_ROOT, _APPLE_INDEX_FILE,
    _CONNECTION_WRITE_ERRORS, _guess_content_type, _safe_join,
    _STATIC_ROOT, _INDEX_FILE,
)
from qdp.web._state import (
    _inject_monkey_patch, _REQUEST_TRACE, _get_runtime_defaults,
    _clear_client_cache, logger,
)


class QDPHandlerBase(BaseHTTPRequestHandler):
    """Base HTTP handler for QDP web player.

    Contains routing, response helpers, debug endpoints, CORS support,
    and static/app file serving.  Subclass (or compose via mixins) to add
    the concrete handler methods referenced by the GET/POST routers.
    """

    server_version = f"qdp-web/{WEB_PLAYER_VERSION}"

    # ------------------------------------------------------------------
    # Infrastructure
    # ------------------------------------------------------------------

    def log_message(self, fmt: str, *args):
        # keep it quiet; avoid printing secrets.
        return

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")
        if origin and not _allowed_cors_origin(origin):
            self.send_error(HTTPStatus.FORBIDDEN, "Origin not allowed")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        self._trace("POST", path)

        if path == "/api/accounts/switch":
            self._handle_app_api(parsed)
            return

        if path == "/api/cache-clear":
            self._handle_cache_clear_v2()
            return

        if path == "/api/download-settings":
            self._handle_download_settings_post()
            return

        if path == "/api/download-tagged":
            self._handle_app_api(parsed)
            return

        if path.startswith("/api.json/0.2/"):
            self._handle_qobuz_api_proxy(parsed, method="POST")
            return

        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "POST not allowed")

    def _trace(self, method: str, path: str, status: int = 0, note: str = ""):
        try:
            status_code = int(status or 0)
        except (TypeError, ValueError):
            logger.debug("Ignoring non-integer trace status for %s %s: %r", method, path, status)
            status_code = 0
        item = {
            "ts": time.time(),
            "method": method,
            "path": path,
            "status": status_code,
            "note": (note or "")[:200],
        }
        _REQUEST_TRACE.append(item)

    # ------------------------------------------------------------------
    # Main GET router
    # ------------------------------------------------------------------

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        self._trace("GET", path)

        if path == "/__version":
            self._handle_version()
            return

        if path == "/api/meta":
            self._handle_meta()
            return

        if path == "/__trace":
            self._handle_trace()
            return

        if path == "/__shutdown":
            self._handle_shutdown()
            return

        # new local app
        if path in {"/", ""}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/apple/")
            self.end_headers()
            return

        # Apple-style UI — must come before /app check since "/apple".startswith("/app")
        if path.startswith("/apple"):
            self._handle_apple_static(parsed)
            return

        if path.startswith("/app"):
            self._handle_app_static(parsed)
            return

        # Specific API routes must come before the /api/ prefix catch-all
        if path == "/api/cover":
            self._handle_cover_proxy(parsed)
            return

        if path == "/api/cache/clear":
            self._handle_cache_clear()
            return

        if path.startswith("/api/"):
            self._handle_app_api(parsed)
            return

        if path.startswith("/api.json/0.2/"):
            self._handle_qobuz_api_proxy(parsed)
            return

        if path == "/stream":
            self._handle_stream_proxy(parsed)
            return

        # shim: some saved pages reference a non-existing false.js
        if path.endswith("/false.js"):
            self._handle_false_js()
            return

        # play.qobuz.com assets (sprite/icons/service-worker/manifest/legacy/fonts)
        if path.startswith("/assets/") or path.startswith("/legacy/") or path in {
            "/favicon.ico",
            "/favicon.svg",
            "/favicon-96x96.png",
            "/apple-touch-icon.png",
            "/site.webmanifest",
            "/service-worker.js",
            "/robots.txt",
        }:
            self._handle_play_assets_proxy(parsed)
            return

        # serve static
        self._handle_static(parsed)

    # ------------------------------------------------------------------
    # Debug endpoints
    # ------------------------------------------------------------------

    def _handle_version(self):
        self._send_api_success({
            "version": WEB_PLAYER_VERSION,
            "web_player_version": WEB_PLAYER_VERSION,
            "server_version": self.server_version,
        })

    def _handle_meta(self):
        self._send_api_success({
            "version": WEB_PLAYER_VERSION,
            "web_player_version": WEB_PLAYER_VERSION,
            "server_version": self.server_version,
        })

    def _handle_trace(self):
        if not self._debug_endpoint_allowed():
            self._send_api_error(HTTPStatus.FORBIDDEN, "debug_endpoint_forbidden", "Debug endpoint is loopback-only")
            return
        admin_token = os.environ.get("QDP_ADMIN_TOKEN", "")
        if admin_token:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query or "")
            provided = (qs.get("token") or [""])[0]
            if provided != admin_token:
                self._send_api_error(HTTPStatus.FORBIDDEN, "invalid_token", "Invalid admin token")
                return
        # lightweight diagnostics endpoint (no secrets)
        defaults = _get_runtime_defaults()
        payload = {
            "version": WEB_PLAYER_VERSION,
            "web_player_version": WEB_PLAYER_VERSION,
            "has_app_id": bool(str(defaults.get("app_id", "") or "").strip()),
            "has_user_auth_token": bool(str(defaults.get("user_auth_token", "") or "").strip()),
            "use_token": str(defaults.get("use_token", "false")).lower() == "true",
            "proxy_configured": bool(str(defaults.get("proxies", "") or "").strip()),
            "recent_requests": list(_REQUEST_TRACE)[-80:],
        }
        self._send_api_success(payload)

    def _handle_shutdown(self):
        if not self._debug_endpoint_allowed():
            self._send_api_error(HTTPStatus.FORBIDDEN, "debug_endpoint_forbidden", "Debug endpoint is loopback-only")
            return
        admin_token = os.environ.get("QDP_ADMIN_TOKEN", "")
        if admin_token:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query or "")
            provided = (qs.get("token") or [""])[0]
            if provided != admin_token:
                self._send_api_error(HTTPStatus.FORBIDDEN, "invalid_token", "Invalid admin token")
                return
        else:
            logger.warning("Shutdown endpoint called without QDP_ADMIN_TOKEN set; consider setting it for security")
        self._send_api_success({"shutdown": True})
        try:
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        except RuntimeError:
            logger.warning("Failed to start shutdown helper thread", exc_info=True)

    # ------------------------------------------------------------------
    # Response infrastructure
    # ------------------------------------------------------------------

    def _safe_end_headers(self) -> bool:
        try:
            self.end_headers()
            return True
        except _CONNECTION_WRITE_ERRORS:
            logger.info("Client disconnected before headers completed", extra={"path": getattr(self, "path", "")})
            return False
        except OSError:
            logger.info("Client disconnected while finishing headers", extra={"path": getattr(self, "path", "")})
            return False

    def _safe_write_response(self, data: bytes, *, content_type: str, status: int) -> bool:
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if not self._safe_end_headers():
            return False
        try:
            self.wfile.write(data)
            return True
        except _CONNECTION_WRITE_ERRORS:
            logger.info("Client disconnected before response body completed", extra={"path": getattr(self, "path", ""), "status": status})
            return False
        except OSError:
            logger.info("Client disconnected while writing response body", extra={"path": getattr(self, "path", ""), "status": status})
            return False

    def _send_json(self, payload: dict, status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._trace("RESP", self.path, status=status, note="json")
        self._safe_write_response(data, content_type="application/json; charset=utf-8", status=status)

    def _send_api_file_error(self, status: int, code: str, message: str):
        self._send_api_error(status, code, message)

    def _send_plain_json(self, payload: dict, status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._safe_write_response(data, content_type="application/json; charset=utf-8", status=status)

    def _api_envelope(self, ok: bool, *, data: Optional[dict] = None, error: Optional[dict] = None, meta: Optional[dict] = None) -> dict:
        payload = {
            "ok": bool(ok),
            "data": data or {},
            "error": None,
        }
        if error is not None:
            payload["error"] = error
        if meta is not None:
            payload["meta"] = meta
        return payload

    def _send_api_success(self, data: Optional[dict] = None, *, status: int = 200, meta: Optional[dict] = None):
        self._send_json(self._api_envelope(True, data=data, meta=meta), status=status)

    def _send_api_error(self, status: int, code: str, message: str, *, details: Optional[dict] = None):
        error = {
            "code": code,
            "message": message,
        }
        if details:
            error["details"] = details
        self._trace("RESP", self.path, status=status, note=f"error:{code}")
        self._send_json(self._api_envelope(False, error=error), status=status)

    def _parse_int_query(self, qs: dict, name: str, default: int, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
        raw = (qs.get(name) or [str(default)])[0]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"invalid integer for {name}")
        if minimum is not None and value < minimum:
            raise ValueError(f"{name} must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{name} must be <= {maximum}")
        return value

    # ------------------------------------------------------------------
    # Security / CORS
    # ------------------------------------------------------------------

    def _debug_endpoint_allowed(self) -> bool:
        from qdp.web._helpers import _client_is_loopback
        return _client_is_loopback(getattr(self, "client_address", None))

    def _send_cors_headers(self):
        origin = _allowed_cors_origin(self.headers.get("Origin", ""))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type, X-App-Id, X-User-Auth-Token")
        self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges")

    # ------------------------------------------------------------------
    # Static serving
    # ------------------------------------------------------------------

    def _handle_false_js(self):
        # Return a harmless stub script to satisfy broken references in saved HTML snapshots.
        js = "/* qdp webplayer stub */\n".encode("utf-8")
        self._trace("GET", self.path, status=200, note="false_js_stub")
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(js)))
        self._safe_end_headers()
        try:
            self.wfile.write(js)
        except _CONNECTION_WRITE_ERRORS:
            pass

    def _handle_app_static(self, parsed: urllib.parse.ParseResult):
        # /app/ -> serve index.html
        path = parsed.path
        is_app_index = path in {"/app", "/app/"}
        if is_app_index:
            rel = _APP_INDEX_FILE
        else:
            rel = path[len("/app/"):].lstrip("/")
            if not rel:
                rel = _APP_INDEX_FILE
                is_app_index = True
        try:
            full = _safe_join(_APP_ROOT, rel)
        except ValueError as exc:
            logger.warning("Rejected app static path %r: %s", rel, exc)
            self._send_api_file_error(HTTPStatus.BAD_REQUEST, "bad_path", "Bad path")
            return
        if not os.path.isfile(full):
            self._send_api_file_error(HTTPStatus.NOT_FOUND, "not_found", "Not found")
            return
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Read error")
            return

        if is_app_index and rel == _APP_INDEX_FILE:
            body = body.replace(b"__QDP_WEB_VERSION__", WEB_PLAYER_VERSION.encode("utf-8"))

        ctype = _guess_content_type(full)
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", _APP_CACHE_CONTROL)
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self._safe_end_headers()
        try:
            self.wfile.write(body)
        except _CONNECTION_WRITE_ERRORS:
            pass

    def _handle_apple_static(self, parsed: urllib.parse.ParseResult):
        # /apple/ -> serve Apple UI index.html
        path = parsed.path
        is_index = path in {"/apple", "/apple/"}
        if is_index:
            rel = _APPLE_INDEX_FILE
        else:
            rel = path[len("/apple/"):].lstrip("/")
            if not rel:
                rel = _APPLE_INDEX_FILE
                is_index = True
        try:
            full = _safe_join(_APPLE_ROOT, rel)
        except ValueError as exc:
            logger.warning("Rejected apple static path %r: %s", rel, exc)
            self._send_api_file_error(HTTPStatus.BAD_REQUEST, "bad_path", "Bad path")
            return
        if not os.path.isfile(full):
            self._send_api_file_error(HTTPStatus.NOT_FOUND, "not_found", "Not found")
            return
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Read error")
            return

        if is_index and rel == _APPLE_INDEX_FILE:
            body = body.replace(b"__QDP_WEB_VERSION__", WEB_PLAYER_VERSION.encode("utf-8"))

        ctype = _guess_content_type(full)
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", _APP_CACHE_CONTROL)
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self._safe_end_headers()
        try:
            self.wfile.write(body)
        except _CONNECTION_WRITE_ERRORS:
            pass

    def _serve_index_html(self):
        index_path = os.path.join(_STATIC_ROOT, _INDEX_FILE)
        if not os.path.isfile(index_path):
            self._send_api_file_error(HTTPStatus.INTERNAL_SERVER_ERROR, "index_missing", "Index file missing")
            return
        try:
            with open(index_path, "rb") as f:
                data = f.read()
        except OSError:
            self._send_api_file_error(HTTPStatus.INTERNAL_SERVER_ERROR, "read_error", "Read error")
            return
        try:
            text = data.decode("utf-8", errors="ignore")
            text = _inject_monkey_patch(text)
            data = text.encode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            logger.debug("Failed to inject index HTML patch", exc_info=True)
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except _CONNECTION_WRITE_ERRORS:
            pass

    def _handle_static(self, parsed: urllib.parse.ParseResult):
        raw_path = parsed.path
        if raw_path in {"/", ""}:
            raw_path = "/" + _INDEX_FILE

        # decode %20 etc.
        rel_path = urllib.parse.unquote(raw_path)

        try:
            full = _safe_join(_STATIC_ROOT, rel_path)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Bad path")
            return

        if not os.path.isfile(full):
            # SPA fallback: for routes like /login /discover /album/... serve index.html
            accept = (self.headers.get("Accept") or "").lower()
            if "text/html" in accept or raw_path.startswith(("/login", "/discover", "/album", "/artist", "/label", "/playlist", "/user")):
                self._serve_index_html()
                return
            self._send_api_file_error(HTTPStatus.NOT_FOUND, "not_found", "Not found")
            return

        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            self._send_api_file_error(HTTPStatus.INTERNAL_SERVER_ERROR, "read_error", "Read error")
            return

        ctype = _guess_content_type(full)

        # inject only for index html
        if os.path.basename(full) == _INDEX_FILE and ctype.startswith("text/html"):
            try:
                text = data.decode("utf-8", errors="ignore")
                text = _inject_monkey_patch(text)
                data = text.encode("utf-8")
            except (UnicodeDecodeError, ValueError):
                logger.debug("Failed to inject static HTML patch", exc_info=True)

        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except _CONNECTION_WRITE_ERRORS:
            pass
