from __future__ import annotations

import json
import logging
import os
import random
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from http import HTTPStatus

import requests
from mutagen.flac import FLAC as MutagenFLAC
from mutagen.id3 import APIC
from mutagen.mp3 import MP3 as MutagenMP3

from qdp.accounts import get_active_account, list_accounts, switch_account
from qdp.config import CONFIG_FILE, load_config, save_config
from qdp.downloader import Download
from qdp.web import __version__ as WEB_PLAYER_VERSION
from qdp.web._audio_cache import get_cache_stats, clear_cache, is_cached, parse_range_header, start_background_download
from qdp.web._helpers import _CONNECTION_WRITE_ERRORS, _guess_content_type
from qdp.web._transforms import (
    _download_filename_for_track, _extract_audio_spec, _mask_secret,
    _normalize_track, _parse_qobuz_url, _pick_image, _rewrite_image_url,
    _sanitize_download_filename,
)
from qdp.web._state import (
    _cache_get, _cache_set, _clear_client_cache, _DISCOVER_RANDOM_SEEDS,
    _ENTITY_CACHE, _ENTITY_CACHE_LOCK, _get_client, _get_runtime_defaults,
    logger,
)


def _verify_and_cleanup_covers(directory: str, embed_art: bool) -> dict:
    """Verify embedded cover art and optionally remove standalone cover images.

    Returns dict with keys: verified (int), missing_cover (list), cleaned (bool).

    Behavior:
    - embed_art=False: keep standalone covers untouched.
    - embed_art=True and all audio files in directory tree have embedded covers:
      remove standalone cover files (cover.jpg/.jpeg/.png) to avoid "separated"
      cover artifacts in album folders.
    """
    if not embed_art:
        return {"verified": 0, "missing_cover": [], "cleaned": False}

    audio_files: list[str] = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith((".flac", ".mp3")):
                audio_files.append(os.path.join(root, f))

    if not audio_files:
        return {"verified": 0, "missing_cover": [], "cleaned": False}

    missing: list[str] = []
    verified = 0
    for path in audio_files:
        try:
            if path.lower().endswith(".flac"):
                f = MutagenFLAC(path)
                has_cover = len(f.pictures) > 0
            else:
                f = MutagenMP3(path)
                has_cover = any(isinstance(tag, APIC) for tag in (f.tags or {}).values()) if f.tags else False
            if has_cover:
                verified += 1
            else:
                missing.append(os.path.basename(path))
        except Exception:
            missing.append(os.path.basename(path))

    cleaned = False
    if not missing:
        # All tracks are embedded, safe to remove standalone cover files.
        cover_names = {"cover.jpg", "cover.jpeg", "cover.png"}
        for root, _dirs, files in os.walk(directory):
            for f in files:
                if f.lower() in cover_names:
                    try:
                        os.remove(os.path.join(root, f))
                        cleaned = True
                    except OSError:
                        pass

    return {"verified": verified, "missing_cover": missing, "cleaned": cleaned}





def _enrich_local_playlist_tracks(client, raw_tracks: list[dict]) -> list[dict]:
    """Hydrate local playlist tracks with full track + album metadata for tagging.

    Frontend local playlists store simplified track objects, but the download/tag
    pipeline expects full Qobuz track metadata plus album metadata nested on each
    track. This helper resolves that shape while preserving playlist-flat layout.
    """
    if not raw_tracks:
        return []

    track_ids: list[str] = []
    for item in raw_tracks:
        track_id = item.get("id")
        if track_id is None:
            continue
        track_id = str(track_id).strip()
        if track_id:
            track_ids.append(track_id)

    if not track_ids:
        return []

    track_meta_by_id: dict[str, dict] = {}
    max_workers = min(8, max(1, len(track_ids)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(client.get_track_meta, track_id): track_id for track_id in track_ids}
        for future in as_completed(futures):
            track_id = futures[future]
            track_meta_by_id[track_id] = future.result()

    album_ids = {
        str((meta.get("album") or {}).get("id")).strip()
        for meta in track_meta_by_id.values()
        if isinstance(meta, dict) and isinstance(meta.get("album"), dict) and (meta.get("album") or {}).get("id") is not None
    }
    album_meta_by_id: dict[str, dict] = {}
    if album_ids:
        max_workers = min(6, max(1, len(album_ids)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(client.get_album_meta, album_id): album_id for album_id in album_ids}
            for future in as_completed(futures):
                album_id = futures[future]
                album_meta_by_id[album_id] = future.result()

    enriched: list[dict] = []
    for item in raw_tracks:
        track_id = item.get("id")
        if track_id is None:
            continue
        track_id = str(track_id).strip()
        if not track_id:
            continue
        full_track = dict(track_meta_by_id.get(track_id) or {})
        if not full_track:
            continue
        album_ref = full_track.get("album") or {}
        album_id = str(album_ref.get("id")).strip() if album_ref.get("id") is not None else ""
        full_album = album_meta_by_id.get(album_id)
        if full_album:
            full_track["album"] = full_album
        elif isinstance(album_ref, dict):
            full_track["album"] = album_ref
        enriched.append(full_track)
    return enriched




class APIHandlerMixin:

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

        if path == "/api/download-settings":
            self._handle_download_settings_get()
            return

        if path == "/api/browse-dirs":
            self._handle_browse_dirs(qs)
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
                except requests.exceptions.RequestException as exc:
                    self._send_api_error(502, "me_lookup_failed", str(exc)[:200])
                    return
                except ValueError as exc:
                    self._send_api_error(400, "me_lookup_failed", str(exc)[:200])
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
            except requests.exceptions.RequestException as exc:
                self._send_api_error(502, "search_failed", str(exc)[:200])
                return
            except ValueError as exc:
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
                        "image": _rewrite_image_url(_pick_image(it.get("image"))),
                    }
                    album_payload.update(_extract_audio_spec(it))
                    items.append(album_payload)
            elif t == "artists":
                for it in (((raw or {}).get("artists") or {}).get("items") or []):
                    items.append({
                        "id": it.get("id"),
                        "name": it.get("name"),
                        "albums_count": it.get("albums_count"),
                        "image": _rewrite_image_url(_pick_image(it.get("image"))),
                    })
            elif t == "playlists":
                for it in (((raw or {}).get("playlists") or {}).get("items") or []):
                    items.append({
                        "id": it.get("id"),
                        "title": it.get("name") or it.get("title"),
                        "tracks_count": it.get("tracks_count"),
                        "owner": (it.get("owner") or {}).get("name") if isinstance(it.get("owner"), dict) else None,
                        "image": _rewrite_image_url(_pick_image(it.get("image"))),
                    })
            self._send_api_success({"items": items}, meta={"query": q, "type": t, "limit": limit, "offset": offset})
            return

        if path == "/api/discover-random-albums":
            seed = random.choice(_DISCOVER_RANDOM_SEEDS)
            try:
                raw = client.search(seed, "albums", limit=12, offset=random.randint(0, 8))
            except requests.exceptions.RequestException as exc:
                self._send_api_error(502, "discover_failed", str(exc)[:200])
                return
            except ValueError as exc:
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
                    "image": _rewrite_image_url(_pick_image(it.get("image"))),
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
            if not tid.replace('_', '').replace('-', '').isalnum():
                self._send_api_error(400, "invalid_id", "invalid track id")
                return
            try:
                t = client.get_track_meta(tid)
            except requests.exceptions.RequestException as exc:
                self._send_api_error(502, "track_lookup_failed", str(exc)[:200])
                return
            except ValueError as exc:
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
            except requests.exceptions.RequestException as exc:
                self._send_api_error(502, "album_lookup_failed", str(exc)[:200])
                return
            except ValueError as exc:
                self._send_api_error(500, "album_lookup_failed", str(exc)[:200])
                return
            image = _rewrite_image_url(_pick_image((a or {}).get("image")))
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
            except requests.exceptions.RequestException as exc:
                self._send_api_error(502, "playlist_lookup_failed", str(exc)[:200])
                return
            except ValueError as exc:
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
                    image = _rewrite_image_url(_pick_image(page.get("image")))
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
            except requests.exceptions.RequestException as exc:
                self._send_api_error(502, "artist_lookup_failed", str(exc)[:200])
                return
            except ValueError as exc:
                self._send_api_error(400, "artist_lookup_failed", str(exc)[:200])
                return
            albums = []
            artist_name = None
            artist_image = ""
            for page in pages:
                if artist_name is None:
                    artist_name = page.get("name")
                    artist_image = _rewrite_image_url(_pick_image(page.get("image")))
                for it in ((page.get("albums") or {}).get("items") or []):
                    album_payload = {
                        "id": it.get("id"),
                        "title": it.get("title"),
                        "year": it.get("released_at") or it.get("release_date_original"),
                        "image": _rewrite_image_url(_pick_image(it.get("image"))),
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
            if not tid.replace('_', '').replace('-', '').isalnum():
                self._send_api_error(400, "invalid_id", "invalid track id")
                return
            try:
                fmt = self._parse_int_query(qs, "fmt", 5, minimum=5)
            except ValueError as exc:
                self._send_api_error(400, "invalid_query", str(exc))
                return
            try:
                u = client.get_track_url(tid, fmt)
            except requests.exceptions.RequestException as exc:
                self._send_api_error(502, "track_url_failed", str(exc)[:200])
                return
            except ValueError as exc:
                self._send_api_error(400, "track_url_failed", str(exc)[:200])
                return
            raw_url = (u or {}).get("url")
            if not raw_url:
                self._send_api_error(502, "missing_upstream_url", "missing url")
                return
            prox = "/stream?url=" + urllib.parse.quote(raw_url, safe="")
            # Background caching: kick off download if not already cached
            cached_path = is_cached(tid, fmt)
            if not cached_path:
                start_background_download(tid, fmt, raw_url)
            self._send_api_success({
                "url": prox,
                "download_url": f"/api/download?id={urllib.parse.quote(str(tid), safe='')}&fmt={fmt}",
                "cached": cached_path is not None,
            })
            return

        if path == "/api/download-tagged":
            tid = (qs.get("id") or [""])[0]
            if not tid:
                self._send_api_error(400, "missing_id", "missing track id")
                return
            # Allow synthetic local-playlist ID for POST playlist body uploads.
            if tid != "local-playlist" and not tid.replace('_', '').replace('-', '').isalnum():
                self._send_api_error(400, "invalid_id", "invalid track id")
                return
            try:
                fmt = self._parse_int_query(qs, "fmt", 5, minimum=5)
            except ValueError as exc:
                self._send_api_error(400, "invalid_query", str(exc))
                return
            download_dir = (qs.get("path") or [""])[0].strip()
            if not download_dir:
                defaults = _get_runtime_defaults()
                download_dir = defaults.get("default_folder", os.path.join(os.path.expanduser("~"), "Qobuz Downloads"))
            defaults = _get_runtime_defaults()
            try:
                workers = self._parse_int_query(qs, "workers", int(defaults.get("workers", "4") or 4), minimum=1)
            except ValueError as exc:
                self._send_api_error(400, "invalid_query", str(exc))
                return
            embed = (qs.get("embed") or ["1"])[0].strip()
            embed_art = embed == "1"
            dl_type = (qs.get("type") or ["track"])[0].strip().lower()
            album_id = (qs.get("album_id") or [None])[0]
            playlist_id = (qs.get("playlist_id") or [None])[0]

            # Optional POST body used for local playlist bulk download.
            body = {}
            if self.command == "POST":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except (TypeError, ValueError):
                    self._send_api_error(400, "invalid_content_length", "Invalid Content-Length")
                    return
                if length > 1024 * 1024 * 4:
                    self._send_api_error(413, "payload_too_large", "Request body too large")
                    return
                try:
                    body = json.loads(self.rfile.read(length)) if length > 0 else {}
                except (json.JSONDecodeError, ValueError):
                    self._send_api_error(400, "invalid_json", "Invalid JSON body")
                    return

            self._handle_download_tagged(
                client,
                tid,
                fmt,
                download_dir,
                embed_art=embed_art,
                dl_type=dl_type,
                album_id=album_id,
                playlist_id=playlist_id,
                playlist_payload=body,
                workers=workers,
            )
            return

        if path == "/api/cached-track":
            self._handle_cached_track(parsed)
            return

        # Legacy download (302 redirect) — kept for reference
        if path == "/api/download":
            tid = (qs.get("id") or [""])[0]
            if not tid:
                self._send_api_error(400, "missing_id", "missing track id")
                return
            if not tid.replace('_', '').replace('-', '').isalnum():
                self._send_api_error(400, "invalid_id", "invalid track id")
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
            except requests.exceptions.RequestException as exc:
                self._send_api_error(502, "download_prepare_failed", str(exc)[:200])
                return
            except ValueError as exc:
                self._send_api_error(400, "download_prepare_failed", str(exc)[:200])
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

        if path == "/api/cache-stats":
            self._handle_cache_stats()
            return

        self._send_api_error(404, "not_found", "not found")

    def _handle_cache_clear(self):
        """Clear server-side entity cache and return stats."""
        with _ENTITY_CACHE_LOCK:
            count = len(_ENTITY_CACHE)
            _ENTITY_CACHE.clear()
        self._send_api_success({"cleared": count, "message": f"已清除 {count} 条服务端缓存"})
        self._trace("CACHE", "clear", status=200, note=f"cleared {count} entries")

    def _handle_cache_stats(self):
        """Return cache size stats for audio and asset caches."""
        audio = get_cache_stats()
        total_bytes = audio["size_bytes"]
        total_files = audio["file_count"]
        self._send_api_success({
            "audio": audio,
            "total": {"size_bytes": total_bytes, "file_count": total_files},
        })

    def _handle_cache_clear_v2(self):
        """Clear cache by type. Body: {"type": "audio"|"all"}."""
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except (TypeError, ValueError):
            self._send_api_error(400, "invalid_content_length", "Invalid Content-Length")
            return
        if length > 1024 * 64:
            self._send_api_error(413, "payload_too_large", "Request body too large")
            return
        try:
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
        except (json.JSONDecodeError, ValueError):
            self._send_api_error(400, "invalid_json", "Invalid JSON body")
            return
        cache_type = str(body.get("type", "")).strip().lower()
        if cache_type not in ("audio", "all"):
            self._send_api_error(400, "invalid_type", "type must be 'audio' or 'all'")
            return

        freed = 0
        if cache_type in ("audio", "all"):
            freed += clear_cache()
        # Also clear the in-memory entity cache for 'all'
        if cache_type == "all":
            with _ENTITY_CACHE_LOCK:
                _ENTITY_CACHE.clear()
        self._send_api_success({"cleared_bytes": freed})
        self._trace("CACHE", f"clear_v2:{cache_type}", status=200, note=f"freed {freed} bytes")

    def _handle_cached_track(self, parsed: urllib.parse.ParseResult):
        """Serve a cached audio file with full Range-header support for seeking."""
        qs = urllib.parse.parse_qs(parsed.query or "")
        tid = (qs.get("id") or [""])[0]
        if not tid:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "missing_id", "missing track id")
            return
        if not tid.replace('_', '').replace('-', '').isalnum():
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_id", "invalid track id")
            return
        try:
            fmt = self._parse_int_query(qs, "fmt", 5, minimum=5)
        except ValueError as exc:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_query", str(exc))
            return

        cached_path = is_cached(tid, fmt)
        if not cached_path:
            self._send_api_error(HTTPStatus.NOT_FOUND, "not_cached", "track not yet cached")
            return

        try:
            file_size = os.path.getsize(cached_path)
        except OSError:
            self._send_api_error(HTTPStatus.INTERNAL_SERVER_ERROR, "cache_read_error", "failed to stat cached file")
            return

        content_type = _guess_content_type(cached_path)
        range_header = self.headers.get("Range")

        if range_header:
            parsed_range = parse_range_header(range_header, file_size)
            if parsed_range is None:
                # Malformed range – serve full file
                self._send_cached_file_full(cached_path, file_size, content_type)
                return

            start, end = parsed_range
            if start >= file_size:
                # Range Not Satisfiable
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self._send_cors_headers()
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
                return

            end = min(end, file_size - 1)
            length = end - start + 1

            self._trace("GET", parsed.path, status=206, note=f"cached-track range {start}-{end}")
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self._send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "public, max-age=31536000")
            self.end_headers()
            self._stream_file_range(cached_path, start, length)
        else:
            self._trace("GET", parsed.path, status=200, note="cached-track full")
            self._send_cached_file_full(cached_path, file_size, content_type)

    def _send_cached_file_full(self, path: str, file_size: int, content_type: str):
        """Send a complete cached file to the client in chunks."""
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=31536000")
        self.end_headers()
        self._stream_file_range(path, 0, file_size)

    def _handle_download_tagged(self, client, track_id: str, fmt: int, download_dir: str,
                                 embed_art: bool = True, dl_type: str = "track",
                                 album_id: str | None = None, playlist_id: str | None = None,
                                 playlist_payload: dict | None = None, workers: int = 4):
        """Download a track, album, or playlist using the full CLI pipeline (tagging, cover art, etc.)."""
        result = {"success": False, "path": ""}
        error_info = None

        def _run_download():
            nonlocal result, error_info
            try:
                os.makedirs(download_dir, exist_ok=True)

                if dl_type == "playlist":
                    # Playlist download: support both remote Qobuz playlist and local playlist payload.
                    # Semantics: create playlist-named folder first, then keep tracks FLAT inside it.
                    pid = playlist_id or track_id
                    playlist_title = "Playlist"
                    raw_tracks = []

                    if playlist_payload and isinstance(playlist_payload, dict) and isinstance(playlist_payload.get("tracks"), list):
                        playlist_title = str(playlist_payload.get("title") or "Playlist")
                        posted_tracks = [it for it in playlist_payload.get("tracks") or [] if isinstance(it, dict)]
                        if track_id == "local-playlist":
                            raw_tracks = _enrich_local_playlist_tracks(client, posted_tracks)
                        else:
                            raw_tracks = posted_tracks
                    else:
                        pages = list(client.get_plist_meta(pid))
                        for page in pages:
                            if playlist_title == "Playlist":
                                playlist_title = page.get("name") or page.get("title") or "Playlist"
                            for it in ((page.get("tracks") or {}).get("items") or []):
                                raw_tracks.append(it)

                    if not raw_tracks:
                        error_info = "Playlist has no tracks"
                        return

                    safe_name = _sanitize_download_filename(playlist_title, fallback="Playlist")
                    playlist_dir = os.path.join(download_dir, safe_name)
                    os.makedirs(playlist_dir, exist_ok=True)

                    # Keep tracks flat inside playlist folder. This is intentional.
                    dl = Download(
                        client=client,
                        item_id=pid,
                        path=playlist_dir,
                        quality=fmt,
                        embed_art=embed_art,
                        downgrade_quality=True,
                        workers=workers,
                    )
                    batch_stats = dl.download_batch(raw_tracks, content_name=playlist_title)

                    cover_result = _verify_and_cleanup_covers(playlist_dir, embed_art)
                    success_count = (batch_stats or {}).get("success", 0)
                    failed_count = (batch_stats or {}).get("failed", 0)
                    result = {
                        "success": True,
                        "path": os.path.abspath(playlist_dir),
                        "type": "playlist",
                        "playlist_title": playlist_title,
                        "track_count": len(raw_tracks),
                        "success_count": success_count,
                        "failed_count": failed_count,
                        "cover": cover_result,
                    }

                elif dl_type == "album":
                    # Album/release download — download_release creates its own subfolder
                    effective_id = album_id or track_id
                    dl = Download(
                        client=client,
                        item_id=effective_id,
                        path=download_dir,
                        quality=fmt,
                        embed_art=embed_art,
                        downgrade_quality=True,
                    )
                    report = dl.download_release()
                    # The album directory is created by download_release via _album_directory
                    album_dir = report.get("album_dir") or download_dir
                    # If album_dir not in report, find newest subdirectory
                    if not report.get("album_dir"):
                        album_dir = _find_newest_subdir(download_dir)
                    # Verify and cleanup covers
                    cover_result = _verify_and_cleanup_covers(album_dir, embed_art)
                    result = {
                        "success": True,
                        "path": os.path.abspath(album_dir),
                        "type": "album",
                        "cover": cover_result,
                    }
                    if report.get("complete") is not None:
                        result["complete"] = report["complete"]
                        result["matched_count"] = report.get("matched_count", 0)
                        result["expected_count"] = report.get("expected_count", 0)
                else:
                    # Single track download
                    before_files = set()
                    for root, _dirs, files in os.walk(download_dir):
                        for f in files:
                            if f.endswith(('.flac', '.mp3')):
                                before_files.add(os.path.join(root, f))

                    dl = Download(
                        client=client,
                        item_id=track_id,
                        path=download_dir,
                        quality=fmt,
                        embed_art=embed_art,
                        downgrade_quality=True,
                        workers=workers,
                    )
                    dl.download_track()

                    # Find newly created audio files
                    after_files = set()
                    for root, _dirs, files in os.walk(download_dir):
                        for f in files:
                            if f.endswith(('.flac', '.mp3')):
                                after_files.add(os.path.join(root, f))

                    new_files = sorted(after_files - before_files)
                    saved_path = new_files[0] if new_files else download_dir

                    # Verify and cleanup covers for single track
                    parent_dir = os.path.dirname(saved_path) if new_files else download_dir
                    cover_result = _verify_and_cleanup_covers(parent_dir, embed_art)
                    result = {
                        "success": True,
                        "path": os.path.abspath(saved_path),
                        "type": "track",
                        "cover": cover_result,
                    }
            except Exception as exc:
                logger.warning("Tagged download failed for %s %s: %s", dl_type, track_id, exc, exc_info=True)
                error_info = str(exc)[:300]

        # Run download in a separate thread but wait for completion
        # Playlists with many tracks need a longer timeout
        timeout_seconds = 1800 if dl_type == "playlist" else 600
        download_thread = threading.Thread(target=_run_download, daemon=True)
        download_thread.start()
        download_thread.join(timeout=timeout_seconds)

        if download_thread.is_alive():
            self._send_api_error(504, "download_timeout", f"download timed out after {timeout_seconds} seconds")
            return

        if error_info:
            self._send_api_error(500, "download_failed", error_info)
            return

        self._send_api_success(result)

    def _handle_browse_dirs(self, qs: dict):
        """List subdirectories for the file picker UI."""
        raw_path = (qs.get("path") or [""])[0].strip()
        home_dir = os.path.expanduser("~")

        if not raw_path:
            target = home_dir
        else:
            target = os.path.abspath(os.path.expanduser(raw_path))

        # Safety: don't allow paths outside home directory
        try:
            target = os.path.realpath(target)
            home_real = os.path.realpath(home_dir)
            if not target.startswith(home_real):
                target = home_real
        except OSError:
            target = home_dir

        parent = os.path.dirname(target)
        dirs = []
        try:
            for entry in sorted(os.listdir(target)):
                full = os.path.join(target, entry)
                try:
                    if os.path.isdir(full) and not entry.startswith('.'):
                        dirs.append({"name": entry, "path": full})
                except (PermissionError, OSError):
                    continue
        except PermissionError:
            self._send_api_error(403, "permission_denied", f"Cannot read directory: {target}")
            return
        except OSError as exc:
            self._send_api_error(400, "dir_read_error", str(exc)[:200])
            return

        self._send_api_success({
            "path": target,
            "parent": parent if parent != target else None,
            "dirs": dirs,
        })

    def _handle_download_settings_get(self):
        """GET /api/download-settings — return the default download path and preferred workers."""
        defaults = _get_runtime_defaults()
        default_path = defaults.get("default_folder", os.path.join(os.path.expanduser("~"), "Qobuz Downloads"))
        workers = max(1, int(defaults.get("workers", "4") or 4))
        self._send_api_success({"default_path": default_path, "workers": workers})

    def _handle_download_settings_post(self):
        """POST /api/download-settings — save a new default download path and preferred workers."""
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except (TypeError, ValueError):
            self._send_api_error(400, "invalid_content_length", "Invalid Content-Length")
            return
        if length > 1024 * 64:
            self._send_api_error(413, "payload_too_large", "Request body too large")
            return
        try:
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
        except (json.JSONDecodeError, ValueError):
            self._send_api_error(400, "invalid_json", "Invalid JSON body")
            return

        new_path = str(body.get("default_path", "")).strip()
        if not new_path:
            self._send_api_error(400, "missing_path", "default_path is required")
            return
        raw_workers = body.get("workers", 4)
        try:
            new_workers = max(1, int(raw_workers))
        except (TypeError, ValueError):
            self._send_api_error(400, "invalid_workers", "workers must be a positive integer")
            return

        config = load_config(CONFIG_FILE)
        if not config.has_section("DEFAULT"):
            config.add_section("DEFAULT")
        config.set("DEFAULT", "default_folder", new_path)
        config.set("DEFAULT", "workers", str(new_workers))
        save_config(config, CONFIG_FILE)
        from qdp.web._helpers import _CONFIG_CACHE
        _CONFIG_CACHE["data"] = None

        self._send_api_success({"default_path": new_path, "workers": new_workers})

    def _stream_file_range(self, path: str, start: int, length: int):
        """Stream *length* bytes starting at *start* from a local file."""
        chunk_size = 1024 * 64  # 64 KB
        remaining = length
        try:
            with open(path, "rb") as f:
                if start:
                    f.seek(start)
                while remaining > 0:
                    to_read = min(chunk_size, remaining)
                    chunk = f.read(to_read)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            logger.debug("Cached file stream client disconnected", exc_info=True)
