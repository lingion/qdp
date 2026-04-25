from __future__ import annotations

import json
import logging
import os
import posixpath
import urllib.parse
from http import HTTPStatus
from json import JSONDecodeError

import requests

from qdp.utils import _should_bypass_proxy, get_active_proxy
from qdp.web._helpers import (
    _CONNECTION_WRITE_ERRORS, _get_user_agent, _guess_content_type,
    _validate_stream_upstream_url, MAX_POST_BODY, MAX_UPSTREAM_RESPONSE,
)
from qdp.web._transforms import _sanitize_download_filename
from qdp.web._state import (
    _asset_cache_path, _ASSET_CACHE_ROOT, _get_runtime_defaults,
    _upstream_play_base, logger,
)


def _is_allowed_cdn_host(host: str) -> bool:
    host = host.lower()
    return (host == "qobuz.com" or host.endswith(".qobuz.com") or
            host == "qobuz-static.com" or host.endswith(".qobuz-static.com"))


class ProxyHandlerMixin:

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

        path = parsed.path
        if '..' in path.split('/'):
            self._send_api_error(400, "invalid_path", "Path traversal not allowed")
            return

        upstream = upstream_base + path
        if query:
            upstream += "?" + query

        headers = {
            "User-Agent": _get_user_agent(defaults),
            "X-App-Id": app_id,
            "Accept": self.headers.get("Accept", "*/*"),
        }
        # Add Qobuz origin headers when going through proxy
        if proxy_host:
            headers["Origin"] = "https://www.qobuz.com"
            headers["Referer"] = "https://www.qobuz.com/"
        ctype = self.headers.get("Content-Type")
        if ctype:
            headers["Content-Type"] = ctype
        if token:
            headers["X-User-Auth-Token"] = token

        data = None
        if method.upper() == "POST":
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except (TypeError, ValueError):
                self._send_api_error(400, "invalid_content_length", "Invalid Content-Length")
                return
            if length > MAX_POST_BODY:
                self._send_api_error(413, "payload_too_large", "Request body too large")
                return
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
        if len(body) > MAX_UPSTREAM_RESPONSE:
            self._send_api_error(502, "upstream_response_too_large", "Upstream response too large")
            return

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
        try:
            self.wfile.write(body)
        except _CONNECTION_WRITE_ERRORS:
            pass

    def _handle_cover_proxy(self, parsed: urllib.parse.ParseResult):
        """Proxy cover images through the proxy pool, falling back to direct."""
        qs = urllib.parse.parse_qs(parsed.query or "")
        raw = (qs.get("url") or [""])[0]
        if not raw:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "missing_url", "Missing url")
            return

        upstream_url = urllib.parse.unquote(raw)

        # Basic validation: only allow image URLs from known CDN domains
        try:
            parsed_url = urllib.parse.urlparse(upstream_url)
            host = (parsed_url.netloc or "").lower()
            if not _is_allowed_cdn_host(host):
                self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_domain", "Only Qobuz CDN URLs allowed")
                return
            if not parsed_url.scheme.startswith("http"):
                self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_scheme", "Only http(s) URLs allowed")
                return
        except ValueError as exc:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_url", str(exc))
            return

        # Determine the fetch URL: proxy pool if available, direct otherwise
        proxy_host = get_active_proxy()
        if proxy_host and not _should_bypass_proxy(upstream_url):
            fetch_url = f"{proxy_host}/proxy?url={urllib.parse.quote(upstream_url, safe='')}"
        else:
            fetch_url = upstream_url

        req_headers = {"User-Agent": _get_user_agent()}

        try:
            r = requests.get(fetch_url, headers=req_headers, timeout=15)
        except requests.exceptions.RequestException as exc:
            # Fallback: try the OPPOSITE path (proxy→direct or direct→proxy)
            fallback_url = None
            if fetch_url != upstream_url:
                # Proxy failed → try direct
                fallback_url = upstream_url
                logger.debug("Cover proxy failed, trying direct: %s", exc)
            elif proxy_host:
                # Direct failed → try proxy
                fallback_url = f"{proxy_host}/proxy?url={urllib.parse.quote(upstream_url, safe='')}"
                logger.debug("Cover direct failed, trying proxy: %s", exc)
            if fallback_url:
                try:
                    r = requests.get(fallback_url, headers=req_headers, timeout=10)
                except requests.exceptions.RequestException as exc2:
                    self._send_api_error(HTTPStatus.BAD_GATEWAY, "cover_fetch_failed", str(exc2)[:200])
                    return
            else:
                self._send_api_error(HTTPStatus.BAD_GATEWAY, "cover_fetch_failed", str(exc)[:200])
                return

        if r.status_code != 200:
            self._send_api_error(r.status_code, "cover_upstream_error", f"Upstream returned {r.status_code}")
            return

        # Determine content type
        content_type = r.headers.get("Content-Type", "")
        if not content_type or "image" not in content_type:
            # Guess from URL extension
            ext = posixpath.splitext(parsed_url.path or "")[1].lower()
            content_type = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".gif": "image/gif",
                ".webp": "image/webp",
            }.get(ext, "image/jpeg")

        body = r.content
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")  # cache covers for 24h
        self.end_headers()
        try:
            self.wfile.write(body)
        except _CONNECTION_WRITE_ERRORS:
            pass

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
            r = requests.get(upstream_url, headers=req_headers, stream=True,
                             timeout=(10, 60), allow_redirects=False)
        except requests.exceptions.RequestException as exc:
            logger.warning("Stream upstream request failed for %s: %s", upstream_url, exc)
            self._send_api_error(HTTPStatus.BAD_GATEWAY, "stream_upstream_failed", f"Stream upstream error: {exc}")
            return

        if r.status_code >= 300 and r.status_code < 400:
            self._send_api_error(HTTPStatus.BAD_GATEWAY, "redirect_not_allowed", "Upstream redirect blocked")
            return

        try:
            self.send_response(r.status_code)
            self._send_cors_headers()

            # Important for audio seeking — do NOT forward Transfer-Encoding;
            # requests already decodes chunked encoding, so forwarding it would
            # cause a protocol violation.
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

            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    self.wfile.write(chunk)
                # Break early on server shutdown
                if getattr(self.server, '_shutdown_event', None) and self.server._shutdown_event.is_set():
                    break
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            logger.debug("Stream client disconnected", exc_info=True)
            return
        finally:
            r.close()

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
                try:
                    self.wfile.write(body)
                except _CONNECTION_WRITE_ERRORS:
                    pass
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
        try:
            self.wfile.write(body)
        except _CONNECTION_WRITE_ERRORS:
            pass
