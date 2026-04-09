from __future__ import annotations

import argparse
import contextlib
import io
import ipaddress
import json
import logging
import mimetypes
import os
import posixpath
import random
import re
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import JSONDecodeError
from typing import Dict, Optional, Tuple

_CONNECTION_WRITE_ERRORS = (BrokenPipeError, ConnectionResetError)

import requests

from qdp.qopy import Client

from qdp.accounts import get_active_account, list_accounts, switch_account
from qdp.config import CONFIG_FILE, load_config_defaults
from qdp.web import __version__ as WEB_PLAYER_VERSION
from qdp.utils import get_active_proxy

_ASSET_CACHE_ROOT = os.path.join(os.path.dirname(__file__), "cache-assets")

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 17890
_DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0"

# in-memory request trace (no secrets)
_REQUEST_TRACE = []
_TRACE_LIMIT = 200

_STATIC_ROOT = os.path.join(os.path.dirname(__file__), "static")
_INDEX_FILE = "Discover - Qobuz.html"

_APP_ROOT = os.path.join(os.path.dirname(__file__), "app")
_APP_INDEX_FILE = "index.html"
_APP_CACHE_CONTROL = "no-store, no-cache, must-revalidate, max-age=0"

# module-level singleton
_WEB_SERVER: Optional[ThreadingHTTPServer] = None
_WEB_THREAD: Optional[threading.Thread] = None
_WEB_URL: Optional[str] = None

_CLIENT_CACHE_LOCK = threading.Lock()
_CLIENT_CACHE: Dict[str, Client] = {}
_ENTITY_CACHE_LOCK = threading.Lock()
_ENTITY_CACHE: Dict[tuple, dict] = {}
_ENTITY_CACHE_TTL = 1800
_DISCOVER_RANDOM_SEEDS = ["jazz", "classical", "pop", "new", "electronic", "soundtrack"]

logger = logging.getLogger(__name__)


def _pick_image(image: object) -> str:
    if not isinstance(image, dict):
        return ""
    for key in ("large", "extralarge", "medium", "small", "thumbnail"):
        val = image.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _artist_name(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("performer", "artist"):
        val = item.get(key)
        if isinstance(val, dict):
            name = val.get("name")
            if name:
                return str(name)
    return str(item.get("artist") or "")


def _extract_first_int(value: object, *keys: str) -> Optional[int]:
    if isinstance(value, dict):
        for key in keys:
            raw = value.get(key)
            if isinstance(raw, bool):
                continue
            if isinstance(raw, (int, float)):
                num = int(raw)
                if num > 0:
                    return num
            if isinstance(raw, str):
                match = re.search(r"(\d+)", raw)
                if match:
                    num = int(match.group(1))
                    if num > 0:
                        return num
    return None


def _normalize_sampling_rate_value(raw: object) -> Optional[int]:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip().lower()
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if not match:
            return None
        val = float(match.group(1))
        if "khz" in text:
            hz = int(round(val * 1000))
        else:
            hz = int(round(val))
    elif isinstance(raw, (int, float)):
        hz = int(round(float(raw)))
    else:
        return None
    if hz <= 0:
        return None
    if hz < 1000:
        hz *= 1000
    return hz


def _extract_sampling_rate(value: object, *keys: str) -> Optional[int]:
    if isinstance(value, dict):
        for key in keys:
            hz = _normalize_sampling_rate_value(value.get(key))
            if hz:
                return hz
    return None


def _extract_audio_spec(item: object, album: Optional[dict] = None) -> dict:
    candidates = []
    if isinstance(item, dict):
        candidates.extend([
            item,
            item.get("audio_info") if isinstance(item.get("audio_info"), dict) else None,
            item.get("audio_quality") if isinstance(item.get("audio_quality"), dict) else None,
            item.get("maximum_format") if isinstance(item.get("maximum_format"), dict) else None,
            item.get("format") if isinstance(item.get("format"), dict) else None,
        ])
        nested_album = item.get("album") if isinstance(item.get("album"), dict) else None
        if nested_album:
            candidates.extend([
                nested_album,
                nested_album.get("audio_info") if isinstance(nested_album.get("audio_info"), dict) else None,
                nested_album.get("audio_quality") if isinstance(nested_album.get("audio_quality"), dict) else None,
                nested_album.get("maximum_format") if isinstance(nested_album.get("maximum_format"), dict) else None,
                nested_album.get("format") if isinstance(nested_album.get("format"), dict) else None,
            ])
    if isinstance(album, dict):
        candidates.extend([
            album,
            album.get("audio_info") if isinstance(album.get("audio_info"), dict) else None,
            album.get("audio_quality") if isinstance(album.get("audio_quality"), dict) else None,
            album.get("maximum_format") if isinstance(album.get("maximum_format"), dict) else None,
            album.get("format") if isinstance(album.get("format"), dict) else None,
        ])

    bit_depth = None
    sampling_rate = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if bit_depth is None:
            bit_depth = _extract_first_int(
                candidate,
                "bit_depth",
                "bitDepth",
                "maximum_bit_depth",
                "max_bit_depth",
                "maximumBitDepth",
                "sample_bit_depth",
            )
        if sampling_rate is None:
            sampling_rate = _extract_sampling_rate(
                candidate,
                "sampling_rate",
                "samplingRate",
                "maximum_sampling_rate",
                "max_sampling_rate",
                "maximumSamplingRate",
                "sample_rate",
                "sampleRate",
            )
        if bit_depth is not None and sampling_rate is not None:
            break

    payload = {}
    if bit_depth is not None:
        payload["bit_depth"] = bit_depth
    if sampling_rate is not None:
        payload["sampling_rate"] = sampling_rate
    return payload


def _normalize_track(item: dict, image_fallback: str = "") -> dict:
    item = item or {}
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    audio_spec = _extract_audio_spec(item, album)
    payload = {
        "id": item.get("id"),
        "title": item.get("title") or item.get("name"),
        "artist": _artist_name(item),
        "image": _pick_image(album.get("image") if isinstance(album, dict) else {}) or image_fallback,
        "albumId": album.get("id") if isinstance(album, dict) else None,
        "albumTitle": album.get("title") if isinstance(album, dict) else None,
    }
    payload.update(audio_spec)
    return payload


def _sanitize_download_filename(name: str, fallback: str = "track") -> str:
    raw = str(name or "").strip()
    cleaned = re.sub(r"[\\/:*?\"<>|]+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or fallback


def _download_extension_for_fmt(fmt: int) -> str:
    if int(fmt) == 5:
        return ".mp3"
    return ".flac"


def _download_filename_for_track(track_meta: dict, fmt: int) -> str:
    title = _sanitize_download_filename((track_meta or {}).get("title") or (track_meta or {}).get("name") or "track")
    ext = _download_extension_for_fmt(fmt)
    if title.lower().endswith(ext):
        return title
    return f"{title}{ext}"


def _parse_qobuz_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as exc:
        logger.warning("Failed to parse Qobuz URL %r: %s", url, exc)
        return None, None
    host = (parsed.netloc or "").lower()
    if not host.endswith("qobuz.com"):
        return None, None
    parts = [p for p in (parsed.path or "").split("/") if p]
    supported = {"track", "album", "artist", "playlist"}
    for idx, part in enumerate(parts):
        lower = part.lower()
        if lower in supported and idx + 1 < len(parts):
            return lower, parts[idx + 1]
    # fallback for odd paths
    m = re.search(r"/(track|album|artist|playlist)/([^/?#]+)", parsed.path or "", re.I)
    if m:
        return m.group(1).lower(), m.group(2)
    return None, None


def _mask_secret(val: str) -> str:
    val = (val or "").strip()
    if not val:
        return ""
    if len(val) <= 6:
        return "*" * len(val)
    return val[:2] + "***" + val[-2:]


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


def _inject_monkey_patch(html: str) -> str:
    """Inject fetch/XHR rewrite + getFileUrl stream rewrite."""

    script = r"""
<script>
(function(){
  const API_PREFIXES = [
    'https://www.qobuz.com/api.json/0.2/',
    'https://www.qobuz.com/api.json/0.2',
    'https://play.qobuz.com/api.json/0.2/',
    'https://play.qobuz.com/api.json/0.2',
    '//www.qobuz.com/api.json/0.2/',
    '//www.qobuz.com/api.json/0.2',
    '//play.qobuz.com/api.json/0.2/',
    '//play.qobuz.com/api.json/0.2',
    '/api.json/0.2/',
    'api.json/0.2/'
  ];

  function rewriteUrl(u){
    try {
      if(!u) return u;
      const s = String(u);
      for (const p of API_PREFIXES){
        if (s.startsWith(p)){
          const rest = s.substring(p.length);
          return '/api.json/0.2/' + rest;
        }
      }
      return s;
    } catch(e){ return u; }
  }

  // route guard: never stay on /login for local player
  function forceDiscover(){
    try {
      if (location && location.pathname === '/login') {
        history.replaceState(null, '', '/discover');
      }
    } catch(e) {}
  }

  const _pushState = history.pushState;
  history.pushState = function(state, title, url){
    try {
      if (typeof url === 'string' && url.startsWith('/login')) url = '/discover';
      const args = Array.prototype.slice.call(arguments);
      args[2] = url;
      const ret = _pushState.apply(this, args);
      forceDiscover();
      return ret;
    } catch(e) {
      return _pushState.apply(this, arguments);
    }
  };

  const _replaceState = history.replaceState;
  history.replaceState = function(state, title, url){
    try {
      if (typeof url === 'string' && url.startsWith('/login')) url = '/discover';
      const args = Array.prototype.slice.call(arguments);
      args[2] = url;
      const ret = _replaceState.apply(this, args);
      forceDiscover();
      return ret;
    } catch(e) {
      return _replaceState.apply(this, arguments);
    }
  };

  // Some routers set pathname after async checks: keep policing for a while
  forceDiscover();
  let __qdp_guard_ticks = 0;
  const __qdp_guard = setInterval(function(){
    __qdp_guard_ticks++;
    forceDiscover();
    if (__qdp_guard_ticks > 200) clearInterval(__qdp_guard); // ~20s
  }, 100);
  window.addEventListener('popstate', forceDiscover);

  // disable analytics/trackers that can break offline/local mode
  try {
    const blocked = ['googletagmanager', 'gtm.js', 'mixpanel', 'clarity', 'braze', 'pixel', 'privacy-center', 'didomi', 'algolia', 'search-insights'];
    const nodes = Array.from(document.querySelectorAll('script[src]'));
    for (const n of nodes) {
      const src = String(n.getAttribute('src')||'');
      if (blocked.some(k => src.includes(k))) {
        n.parentNode && n.parentNode.removeChild(n);
      }
    }
  } catch(e) {}

  // patch fetch
  const _fetch = window.fetch;
  window.fetch = function(input, init){
    try {
      if (typeof input === 'string') {
        input = rewriteUrl(input);
      } else if (input && input.url) {
        const nu = rewriteUrl(input.url);
        if (nu !== input.url) {
          input = new Request(nu, input);
        }
      }
    } catch(e) {}

    return _fetch.call(this, input, init).then(async (resp) => {
      try {
        const url = (resp && resp.url) ? String(resp.url) : '';
        if (url.includes('/api.json/0.2/track/getFileUrl')) {
          const clone = resp.clone();
          const data = await clone.json();
          if (data && data.url && typeof data.url === 'string') {
            const proxied = '/stream?url=' + encodeURIComponent(data.url);
            data.url = proxied;
            return new Response(JSON.stringify(data), {
              status: resp.status,
              statusText: resp.statusText,
              headers: resp.headers
            });
          }
        }
      } catch(e) {}
      return resp;
    });
  };

  // patch XHR open
  const _open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url){
    try { url = rewriteUrl(url); } catch(e) {}
    return _open.apply(this, arguments);
  };
})();
</script>
"""

    # inject ASAP: right after <head> so it runs before any external async scripts
    lower = html.lower()
    head_idx = lower.find("<head")
    if head_idx != -1:
        gt = lower.find(">", head_idx)
        if gt != -1:
            return html[: gt + 1] + script + html[gt + 1 :]

    # fallback: before </head> or </body>
    idx = lower.rfind("</head>")
    if idx != -1:
        return html[:idx] + script + html[idx:]
    idx = lower.rfind("</body>")
    if idx != -1:
        return html[:idx] + script + html[idx:]
    return html + script


def _upstream_play_base() -> str:
    # assets should always come from play.qobuz.com
    return "https://play.qobuz.com"


def _asset_cache_path(path: str) -> str:
    # path like /assets/.. or /legacy/..
    rel = path.lstrip("/")
    return _safe_join(_ASSET_CACHE_ROOT, rel)


def _client_cache_key(defaults: Optional[dict] = None) -> str:
    defaults = defaults or _get_runtime_defaults()
    active_account = get_active_account(CONFIG_FILE) or "default"
    cache_parts = [
        active_account,
        defaults.get("use_token", ""),
        defaults.get("email", ""),
        defaults.get("password", ""),
        defaults.get("user_id", ""),
        defaults.get("app_id", ""),
        defaults.get("user_auth_token", ""),
        defaults.get("secrets", ""),
    ]
    return "|".join(str(part) for part in cache_parts)


def _clear_client_cache() -> None:
    with _CLIENT_CACHE_LOCK:
        _CLIENT_CACHE.clear()
    with _ENTITY_CACHE_LOCK:
        _ENTITY_CACHE.clear()


def _cache_get(bucket: str, entity_id: str):
    now = time.time()
    key = (bucket, str(entity_id))
    with _ENTITY_CACHE_LOCK:
        item = _ENTITY_CACHE.get(key)
        if not item:
            return None
        if now - float(item.get("ts", 0)) > _ENTITY_CACHE_TTL:
            _ENTITY_CACHE.pop(key, None)
            return None
        return item.get("value")


def _cache_set(bucket: str, entity_id: str, value: dict):
    key = (bucket, str(entity_id))
    with _ENTITY_CACHE_LOCK:
        _ENTITY_CACHE[key] = {"ts": time.time(), "value": value}
    return value


def _get_client() -> Client:
    defaults = _get_runtime_defaults()
    key = _client_cache_key(defaults)
    with _CLIENT_CACHE_LOCK:
        client = _CLIENT_CACHE.get(key)
        if client is not None:
            return client
    client = _build_client_from_config()
    setattr(client, "active_account", get_active_account(CONFIG_FILE) or "")
    with _CLIENT_CACHE_LOCK:
        _CLIENT_CACHE.clear()
        _CLIENT_CACHE[key] = client
    return client

def _build_client_from_config() -> Client:
    defaults = _get_runtime_defaults()
    secrets = [s for s in (defaults.get("secrets") or "").split(",") if s]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return Client(
            defaults.get("email", ""),
            defaults.get("password", ""),
            defaults.get("app_id", ""),
            secrets,
            defaults.get("use_token", "false"),
            defaults.get("user_id", ""),
            defaults.get("user_auth_token", ""),
        )


class _QDPWebHandler(BaseHTTPRequestHandler):
    server_version = f"qdp-web/{WEB_PLAYER_VERSION}"

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
        if len(_REQUEST_TRACE) > _TRACE_LIMIT:
            del _REQUEST_TRACE[: max(0, len(_REQUEST_TRACE) - _TRACE_LIMIT)]

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
            self.send_header("Location", "/app/")
            self.end_headers()
            return

        if path.startswith("/app"):
            self._handle_app_static(parsed)
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
        # lightweight diagnostics endpoint (no secrets)
        defaults = _get_runtime_defaults()
        payload = {
            "version": WEB_PLAYER_VERSION,
            "web_player_version": WEB_PLAYER_VERSION,
            "has_app_id": bool(str(defaults.get("app_id", "") or "").strip()),
            "has_user_auth_token": bool(str(defaults.get("user_auth_token", "") or "").strip()),
            "use_token": str(defaults.get("use_token", "false")).lower() == "true",
            "proxy_configured": bool(str(defaults.get("proxies", "") or "").strip()),
            "recent_requests": _REQUEST_TRACE[-80:],
        }
        self._send_api_success(payload)

    def _handle_shutdown(self):
        if not self._debug_endpoint_allowed():
            self._send_api_error(HTTPStatus.FORBIDDEN, "debug_endpoint_forbidden", "Debug endpoint is loopback-only")
            return
        # allow stopping old stuck servers
        self._send_api_success({"shutdown": True})
        try:
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        except RuntimeError:
            logger.warning("Failed to start shutdown helper thread", exc_info=True)

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

    def _handle_false_js(self):
        # Return a harmless stub script to satisfy broken references in saved HTML snapshots.
        js = "/* qdp webplayer stub */\n".encode("utf-8")
        self._trace("GET", self.path, status=200, note="false_js_stub")
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(js)))
        self.end_headers()
        self.wfile.write(js)

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
        self.end_headers()
        self.wfile.write(body)

    def _handle_app_api(self, parsed: urllib.parse.ParseResult):
        qs = urllib.parse.parse_qs(parsed.query or "")
        path = parsed.path

        if path == "/api/accounts":
            active_name = get_active_account(CONFIG_FILE)
            accounts = []
            for name, data in list_accounts(CONFIG_FILE):
                accounts.append({
                    "name": name,
                    "active": name == active_name,
                    "label": data.get("label") or "",
                    "region": data.get("region") or "",
                    "status": data.get("status") or "",
                    "remark": data.get("remark") or "",
                    "email_masked": data.get("email_masked") or _mask_secret(data.get("email", "")),
                    "user_id_masked": data.get("user_id_masked") or _mask_secret(data.get("user_id", "")),
                    "account_type": data.get("account_type") or ("token" if data.get("use_token") == "true" else "account"),
                    "last_used": data.get("last_used") or "",
                })
            payload = {"active_account": active_name, "items": accounts}
            self._send_api_success(payload, meta={"count": len(accounts)})
            return

        if path == "/api/accounts/switch":
            name = (qs.get("name") or [""])[0]
            if not name:
                self._send_api_error(400, "missing_account_name", "missing account name")
                return
            try:
                active_name = switch_account(name, CONFIG_FILE)
                _clear_client_cache()
            except (FileNotFoundError, KeyError, ValueError) as exc:
                self._send_api_error(400, "account_switch_failed", str(exc)[:200])
                return
            payload = {"active_account": active_name}
            self._send_api_success(payload)
            return

        try:
            client = _get_client()
        except (FileNotFoundError, ValueError, requests.exceptions.RequestException) as exc:
            logger.warning("Failed to initialize web client: %s", exc)
            self._send_api_error(500, "client_init_failed", str(exc)[:200])
            return

        if path == "/api/me":
            try:
                me = client.api_call("user/login", use_token="true", user_id=client.session.headers.get("X-User-Auth-Token") and "" or "", user_auth_token="")
            except (ValueError, requests.exceptions.RequestException) as primary_exc:
                logger.warning("Primary /api/me call failed, falling back to direct login probe: %s", primary_exc)
                try:
                    defaults = _get_runtime_defaults()
                    params = {
                        "user_id": defaults.get("user_id", ""),
                        "user_auth_token": defaults.get("user_auth_token", ""),
                    }
                    r = requests.get(
                        "https://www.qobuz.com/api.json/0.2/user/login",
                        params=params,
                        headers={"X-App-Id": str(defaults.get("app_id", ""))},
                        timeout=20,
                    )
                    r.raise_for_status()
                    me = r.json()
                except (requests.exceptions.RequestException, ValueError) as exc:
                    self._send_api_error(500, "me_lookup_failed", str(exc)[:200])
                    return
            user = (me or {}).get("user", {})
            out = {
                "user": {
                    "id": user.get("id"),
                    "display_name": user.get("display_name"),
                    "login": user.get("login"),
                    "country_code": user.get("country_code"),
                },
                "label": getattr(client, "label", ""),
                "subscription": (user.get("subscription") or {}),
                "active_account": get_active_account(CONFIG_FILE) or getattr(client, "active_account", ""),
            }
            self._send_api_success(out)
            return

        if path == "/api/search":
            q = (qs.get("q") or [""])[0]
            t = (qs.get("type") or ["tracks"])[0]
            try:
                limit = self._parse_int_query(qs, "limit", 24, minimum=1, maximum=200)
                offset = self._parse_int_query(qs, "offset", 0, minimum=0)
            except ValueError as exc:
                self._send_api_error(400, "invalid_query", str(exc))
                return
            try:
                raw = client.search(q, t, limit=limit, offset=offset)
            except (ValueError, requests.exceptions.RequestException) as exc:
                self._send_api_error(500, "search_failed", str(exc)[:200])
                return
            items = []
            if t == "tracks":
                for it in (((raw or {}).get("tracks") or {}).get("items") or []):
                    items.append(_normalize_track(it))
            elif t == "albums":
                for it in (((raw or {}).get("albums") or {}).get("items") or []):
                    album_payload = {
                        "id": it.get("id"),
                        "title": it.get("title"),
                        "artist": (it.get("artist") or {}).get("name") if isinstance(it.get("artist"), dict) else None,
                        "year": it.get("released_at") or it.get("release_date_original"),
                        "image": _pick_image(it.get("image")),
                    }
                    album_payload.update(_extract_audio_spec(it))
                    items.append(album_payload)
            elif t == "artists":
                for it in (((raw or {}).get("artists") or {}).get("items") or []):
                    items.append({
                        "id": it.get("id"),
                        "name": it.get("name"),
                        "albums_count": it.get("albums_count"),
                        "image": _pick_image(it.get("image")),
                    })
            elif t == "playlists":
                for it in (((raw or {}).get("playlists") or {}).get("items") or []):
                    items.append({
                        "id": it.get("id"),
                        "title": it.get("name") or it.get("title"),
                        "tracks_count": it.get("tracks_count"),
                        "owner": (it.get("owner") or {}).get("name") if isinstance(it.get("owner"), dict) else None,
                        "image": _pick_image(it.get("image")),
                    })
            self._send_api_success({"items": items}, meta={"query": q, "type": t, "limit": limit, "offset": offset})
            return

        if path == "/api/discover-random-albums":
            seed = random.choice(_DISCOVER_RANDOM_SEEDS)
            try:
                raw = client.search(seed, "albums", limit=12, offset=random.randint(0, 8))
            except (ValueError, requests.exceptions.RequestException) as exc:
                self._send_api_error(500, "discover_failed", str(exc)[:200])
                return
            items = []
            for it in (((raw or {}).get("albums") or {}).get("items") or []):
                if not it.get("id"):
                    continue
                album_payload = {
                    "id": it.get("id"),
                    "title": it.get("title"),
                    "artist": (it.get("artist") or {}).get("name") if isinstance(it.get("artist"), dict) else None,
                    "year": it.get("released_at") or it.get("release_date_original"),
                    "image": _pick_image(it.get("image")),
                }
                album_payload.update(_extract_audio_spec(it))
                items.append(album_payload)
            random.shuffle(items)
            self._send_api_success({"seed": seed, "items": items[:8]})
            return

        if path == "/api/track":
            tid = (qs.get("id") or [""])[0]
            if not tid:
                self._send_api_error(400, "missing_id", "missing track id")
                return
            try:
                t = client.get_track_meta(tid)
            except (ValueError, requests.exceptions.RequestException) as exc:
                self._send_api_error(500, "track_lookup_failed", str(exc)[:200])
                return
            self._send_api_success(_normalize_track(t))
            return

        if path == "/api/album":
            aid = (qs.get("id") or [""])[0]
            if not aid:
                self._send_api_error(400, "missing_id", "missing album id")
                return
            cached = _cache_get("album", aid)
            if cached is not None:
                cached_out = dict(cached)
                cached_out["cache"] = {"hit": True}
                self._trace("CACHE", f"album:{aid}", status=200, note="hit")
                self._send_api_success(cached_out)
                return
            try:
                a = client.get_album_meta(aid)
            except (ValueError, requests.exceptions.RequestException) as exc:
                self._send_api_error(500, "album_lookup_failed", str(exc)[:200])
                return
            image = _pick_image((a or {}).get("image"))
            tracks = []
            for it in (((a or {}).get("tracks") or {}).get("items") or []):
                tracks.append(_normalize_track(it, image_fallback=image))
            payload = {
                "id": a.get("id"),
                "title": a.get("title"),
                "artist": (a.get("artist") or {}).get("name") if isinstance(a.get("artist"), dict) else None,
                "image": image,
                "tracks": tracks,
                "cache": {"hit": False},
            }
            payload.update(_extract_audio_spec(a))
            _cache_set("album", aid, payload)
            self._send_api_success(payload)
            return

        if path == "/api/playlist":
            pid = (qs.get("id") or [""])[0]
            if not pid:
                self._send_api_error(400, "missing_id", "missing playlist id")
                return
            try:
                p = client.get_plist_meta(pid)
            except (ValueError, requests.exceptions.RequestException) as exc:
                self._send_api_error(500, "playlist_lookup_failed", str(exc)[:200])
                return
            items = []
            title = None
            owner = None
            image = ""
            for page in p:
                if title is None:
                    title = page.get("name") or page.get("title")
                    owner = (page.get("owner") or {}).get("name") if isinstance(page.get("owner"), dict) else None
                    image = _pick_image(page.get("image"))
                for it in ((page.get("tracks") or {}).get("items") or []):
                    items.append(_normalize_track(it, image_fallback=image))
            playlist_payload = {"id": pid, "title": title, "owner": owner, "image": image, "tracks": items}
            playlist_payload.update(_extract_audio_spec({"tracks": {"items": items}}))
            self._send_api_success(playlist_payload)
            return

        if path == "/api/artist":
            aid = (qs.get("id") or [""])[0]
            if not aid:
                self._send_api_error(400, "missing_id", "missing artist id")
                return
            cached = _cache_get("artist", aid)
            if cached is not None:
                cached_out = dict(cached)
                cached_out["cache"] = {"hit": True}
                self._trace("CACHE", f"artist:{aid}", status=200, note="hit")
                self._send_api_success(cached_out)
                return
            try:
                pages = list(client.get_artist_meta(aid))
            except (ValueError, requests.exceptions.RequestException) as exc:
                self._send_api_error(500, "artist_lookup_failed", str(exc)[:200])
                return
            albums = []
            artist_name = None
            artist_image = ""
            for page in pages:
                if artist_name is None:
                    artist_name = page.get("name")
                    artist_image = _pick_image(page.get("image"))
                for it in ((page.get("albums") or {}).get("items") or []):
                    album_payload = {
                        "id": it.get("id"),
                        "title": it.get("title"),
                        "year": it.get("released_at") or it.get("release_date_original"),
                        "image": _pick_image(it.get("image")),
                    }
                    album_payload.update(_extract_audio_spec(it))
                    albums.append(album_payload)
            payload = {"id": aid, "name": artist_name, "image": artist_image, "albums": albums, "cache": {"hit": False}}
            _cache_set("artist", aid, payload)
            self._send_api_success(payload)
            return

        if path == "/api/track-url":
            tid = (qs.get("id") or [""])[0]
            if not tid:
                self._send_api_error(400, "missing_id", "missing track id")
                return
            try:
                fmt = self._parse_int_query(qs, "fmt", 5, minimum=5)
            except ValueError as exc:
                self._send_api_error(400, "invalid_query", str(exc))
                return
            try:
                u = client.get_track_url(tid, fmt)
            except (ValueError, requests.exceptions.RequestException) as exc:
                self._send_api_error(500, "track_url_failed", str(exc)[:200])
                return
            raw_url = (u or {}).get("url")
            if not raw_url:
                self._send_api_error(502, "missing_upstream_url", "missing url")
                return
            prox = "/stream?url=" + urllib.parse.quote(raw_url, safe="")
            self._send_api_success({"url": prox, "download_url": f"/api/download?id={urllib.parse.quote(str(tid), safe='')}&fmt={fmt}"})
            return

        if path == "/api/download":
            tid = (qs.get("id") or [""])[0]
            if not tid:
                self._send_api_error(400, "missing_id", "missing track id")
                return
            try:
                fmt = self._parse_int_query(qs, "fmt", 5, minimum=5)
            except ValueError as exc:
                self._send_api_error(400, "invalid_query", str(exc))
                return
            filename = "track"
            try:
                u = client.get_track_url(tid, fmt)
                track_meta = client.get_track_meta(tid)
                filename = _download_filename_for_track(track_meta, fmt)
            except (ValueError, requests.exceptions.RequestException) as exc:
                self._send_api_error(500, "download_prepare_failed", str(exc)[:200])
                return
            raw_url = (u or {}).get("url")
            if not raw_url:
                self._send_api_error(502, "missing_upstream_url", "missing url")
                return
            location = "/stream?url=" + urllib.parse.quote(raw_url, safe="") + "&filename=" + urllib.parse.quote(filename, safe="")
            self.send_response(HTTPStatus.FOUND)
            self._send_cors_headers()
            self.send_header("Location", location)
            self.end_headers()
            return

        if path == "/api/resolve-url":
            raw_url = (qs.get("url") or [""])[0]
            kind, entity_id = _parse_qobuz_url(raw_url)
            if not kind or not entity_id:
                self._send_api_error(400, "unsupported_url", "unsupported url")
                return
            self._send_api_success({"type": kind, "id": entity_id})
            return

        self._send_api_error(404, "not_found", "not found")

    def _debug_endpoint_allowed(self) -> bool:
        return _client_is_loopback(getattr(self, "client_address", None))

    def _send_cors_headers(self):
        origin = _allowed_cors_origin(self.headers.get("Origin", ""))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type, X-App-Id, X-User-Auth-Token")
        self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges")

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
        self.wfile.write(data)

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
        self.wfile.write(data)

    def _handle_qobuz_api_proxy(self, parsed: urllib.parse.ParseResult, method: str = "GET"):
        defaults = _get_runtime_defaults()
        app_id = str(defaults.get("app_id", "") or "")
        token = str(defaults.get("user_auth_token", "") or "")

        # deterministic local smoke endpoint for verifying the proxy contract
        # without relying on external Qobuz route availability.
        if parsed.path.rstrip("/") == "/api.json/0.2/test":
            proxy_host = get_active_proxy()
            upstream_base = (proxy_host.rstrip("/") if proxy_host else "https://www.qobuz.com").rstrip("/")
            payload = {
                "path": parsed.path,
                "method": method.upper(),
                "query": urllib.parse.parse_qs(parsed.query or ""),
                "upstream_base": upstream_base,
                "auth": {
                    "has_app_id": bool(app_id),
                    "has_user_auth_token": bool(token),
                    "user_agent": _get_user_agent(defaults),
                },
            }
            self._trace(method.upper(), parsed.path, status=200, note="proxy_smoke")
            self._send_api_success(payload)
            return

        # upstream base: prefer proxy pool
        proxy_host = get_active_proxy()
        upstream_base = (proxy_host.rstrip("/") if proxy_host else "https://www.qobuz.com").rstrip("/")

        # auto-bootstrap login: if front-end calls user/login without params, inject token-mode params
        query = parsed.query or ""
        if parsed.path.endswith("/user/login"):
            use_token = str(defaults.get("use_token", "false")).lower() == "true"
            if use_token:
                qs = urllib.parse.parse_qs(query)
                if not qs.get("user_id") and defaults.get("user_id") and defaults.get("user_auth_token"):
                    qs["user_id"] = [str(defaults.get("user_id"))]
                if not qs.get("user_auth_token") and defaults.get("user_auth_token"):
                    qs["user_auth_token"] = [str(defaults.get("user_auth_token"))]
                query = urllib.parse.urlencode({k: v[0] if isinstance(v, list) and v else v for k, v in qs.items()})

        upstream = upstream_base + parsed.path
        if query:
            upstream += "?" + query

        headers = {
            "User-Agent": _get_user_agent(defaults),
            "X-App-Id": app_id,
            "Accept": self.headers.get("Accept", "*/*"),
        }
        ctype = self.headers.get("Content-Type")
        if ctype:
            headers["Content-Type"] = ctype
        if token:
            headers["X-User-Auth-Token"] = token

        data = None
        if method.upper() == "POST":
            length = int(self.headers.get("Content-Length") or "0")
            if length > 0:
                data = self.rfile.read(length)

        try:
            if method.upper() == "POST":
                resp = requests.post(upstream, headers=headers, data=data, timeout=30)
            else:
                resp = requests.get(upstream, headers=headers, timeout=20)
        except requests.exceptions.RequestException as exc:
            logger.warning("Qobuz API upstream request failed for %s: %s", parsed.path, exc)
            self._send_api_error(HTTPStatus.BAD_GATEWAY, "upstream_request_failed", f"Upstream error: {exc}")
            return

        body = resp.content

        # rewrite getFileUrl payload to /stream
        try:
            if parsed.path.endswith("/track/getFileUrl") and resp.headers.get("Content-Type", "").startswith("application/json"):
                j = resp.json()
                if isinstance(j, dict) and isinstance(j.get("url"), str) and j.get("url"):
                    j["url"] = "/stream?url=" + urllib.parse.quote(j["url"], safe="")
                    body = json.dumps(j).encode("utf-8")
        except (JSONDecodeError, ValueError, TypeError):
            logger.debug("Failed to rewrite track/getFileUrl payload", exc_info=True)

        self._trace(method.upper(), parsed.path, status=resp.status_code)
        self.send_response(resp.status_code)
        self._send_cors_headers()

        # copy some headers
        passthrough = {
            "Content-Type",
            "Cache-Control",
            "Expires",
            "Pragma",
        }
        for k, v in resp.headers.items():
            if k in passthrough:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_stream_proxy(self, parsed: urllib.parse.ParseResult):
        qs = urllib.parse.parse_qs(parsed.query or "")
        raw = (qs.get("url") or [""])[0]
        if not raw:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "missing_url", "Missing url")
            return

        upstream_url = urllib.parse.unquote(raw)
        requested_filename = (qs.get("filename") or [""])[0]
        requested_filename = _sanitize_download_filename(urllib.parse.unquote(requested_filename), fallback="track")
        try:
            upstream_url = _validate_stream_upstream_url(upstream_url)
        except ValueError as exc:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_stream_url", str(exc))
            return

        req_headers = {
            "User-Agent": _get_user_agent(),
        }
        rng = self.headers.get("Range")
        if rng:
            req_headers["Range"] = rng

        try:
            r = requests.get(upstream_url, headers=req_headers, stream=True, timeout=60)
        except requests.exceptions.RequestException as exc:
            logger.warning("Stream upstream request failed for %s: %s", upstream_url, exc)
            self._send_api_error(HTTPStatus.BAD_GATEWAY, "stream_upstream_failed", f"Stream upstream error: {exc}")
            return

        self.send_response(r.status_code)
        self._send_cors_headers()

        # Important for audio seeking
        for hk in [
            "Content-Type",
            "Content-Length",
            "Accept-Ranges",
            "Content-Range",
            "ETag",
            "Last-Modified",
        ]:
            hv = r.headers.get(hk)
            if hv:
                self.send_header(hk, hv)

        content_disposition = r.headers.get("Content-Disposition")
        if requested_filename:
            ext = posixpath.splitext(urllib.parse.urlparse(upstream_url).path or '')[1]
            filename = requested_filename if posixpath.splitext(requested_filename)[1] else f"{requested_filename}{ext or ''}"
            quoted_filename = urllib.parse.quote(filename)
            content_disposition = f"attachment; filename*=UTF-8''{quoted_filename}"
        elif content_disposition:
            self.send_header("Content-Disposition", content_disposition)

        if requested_filename and content_disposition:
            self.send_header("Content-Disposition", content_disposition)

        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        try:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            logger.debug("Stream client disconnected", exc_info=True)
            return

    def _handle_play_assets_proxy(self, parsed: urllib.parse.ParseResult):
        """Serve play.qobuz.com assets with local disk cache.

        This makes the webapp behave like a 'pure local' play.qobuz.com (UI assets local),
        while API/stream still go through our local proxy.
        """
        os.makedirs(_ASSET_CACHE_ROOT, exist_ok=True)

        cache_path = None
        try:
            cache_path = _asset_cache_path(parsed.path)
        except ValueError:
            cache_path = None

        # If cached on disk, serve it directly
        if cache_path and os.path.isfile(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    body = f.read()
                ctype = _guess_content_type(cache_path)
                self._trace("GET", parsed.path, status=200, note="asset_cache_hit")
                self.send_response(HTTPStatus.OK)
                self._send_cors_headers()
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=31536000")
                self.end_headers()
                self.wfile.write(body)
                return
            except OSError:
                logger.debug("Failed to serve cached asset", exc_info=True)

        # Not cached yet -> fetch from upstream
        upstream = _upstream_play_base() + parsed.path
        if parsed.query:
            upstream += "?" + parsed.query

        headers = {
            "User-Agent": _get_user_agent(),
            "Referer": "https://play.qobuz.com/",
        }

        try:
            resp = requests.get(upstream, headers=headers, timeout=60)
        except requests.exceptions.RequestException as exc:
            logger.warning("Asset upstream request failed for %s: %s", parsed.path, exc)
            self._trace("GET", parsed.path, status=502, note=f"asset_err:{str(exc)[:80]}")
            self._send_api_error(HTTPStatus.BAD_GATEWAY, "asset_upstream_failed", f"Asset upstream error: {exc}")
            return

        body = resp.content

        # Save to cache for next time (only 200)
        if cache_path and resp.status_code == 200:
            try:
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with open(cache_path, "wb") as f:
                    f.write(body)
            except OSError:
                logger.debug("Failed to persist asset cache", exc_info=True)

        self._trace("GET", parsed.path, status=resp.status_code, note="asset_fetch")
        self.send_response(resp.status_code)
        self._send_cors_headers()

        ctype = resp.headers.get("Content-Type")
        if not ctype:
            ctype = _guess_content_type(parsed.path)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if resp.status_code == 200:
            self.send_header("Cache-Control", "public, max-age=31536000")
        self.end_headers()
        self.wfile.write(body)


def _find_free_port(host: str, port: int, max_tries: int = 50) -> int:
    import socket

    for i in range(max_tries):
        cand = port + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
