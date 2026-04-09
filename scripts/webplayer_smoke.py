#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from typing import Any, Dict, List, Optional

import requests

from qdp.web import __version__ as WEB_PLAYER_VERSION
from qdp.web.server import start_web_player, stop_web_player


class SmokeFailure(Exception):
    pass


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _ok(label: str, detail: str = "", json_mode: bool = False, **extra: Any) -> Dict[str, Any]:
    payload = {"label": label, "ok": True, "detail": detail, **extra}
    if not json_mode:
        suffix = f" - {detail}" if detail else ""
        print(f"[PASS] {label}{suffix}")
    return payload


def _fail(label: str, detail: str, json_mode: bool = False, **extra: Any) -> Dict[str, Any]:
    payload = {"label": label, "ok": False, "detail": detail, **extra}
    if not json_mode:
        print(f"[FAIL] {label} - {detail}")
    return payload


def _expect_status(resp: requests.Response, expected: int, label: str) -> None:
    if resp.status_code != expected:
        snippet = resp.text[:300].replace("\n", " ")
        raise SmokeFailure(f"{label}: expected HTTP {expected}, got {resp.status_code}, body={snippet!r}")


def _get_json(resp: requests.Response, label: str, *, allow_api_error: bool = False) -> Dict[str, Any]:
    try:
        payload = resp.json()
    except Exception as exc:
        raise SmokeFailure(f"{label}: response is not valid JSON: {exc}") from exc
    if isinstance(payload, dict) and "ok" in payload and isinstance(payload.get("data"), dict):
        if payload.get("ok") is False:
            error = payload.get("error") or {}
            if allow_api_error:
                return {"_api_error": error}
            raise SmokeFailure(f"{label}: API error {error.get('code') or '-'}: {error.get('message') or 'unknown error'}")
        return payload["data"]
    return payload


def _pick_first_track(search_payload: Dict[str, Any]) -> Dict[str, Any]:
    items = search_payload.get("items") or []
    if not items:
        raise SmokeFailure("/api/search tracks: returned 0 items")
    first = items[0]
    if not first.get("id"):
        raise SmokeFailure(f"/api/search tracks: first item missing id: {first!r}")
    return first


def _check_dom_contract(index_html: str, js_sources: Dict[str, str], app_css: str) -> Dict[str, Any]:
    html_ids = [
        "app",
        "appVersion",
        "qualitySelect",
        "volume",
        "mute",
        "volumeValue",
        "downloadMenu",
        "downloadMenuCard",
        "queue",
        "myPlaylists",
        "mobileSidebarToggle",
        "mobileSidebarOverlay",
        "mobileTabQueue",
        "mobileTabPlaylists",
        "sidebar",
        "player",
        "audio",
        "nowSourcePill",
        "queueSourceBadge",
    ]
    required_scripts = [
        "/app/core.js",
        "/app/accounts.js",
        "/app/queue.js",
        "/app/playlists.js",
        "/app/api.js",
        "/app/discover.js",
        "/app/player.js",
        "/app/app.js",
    ]
    bundle = "\n".join(js_sources.values())
    js_tokens = [
        "DOWNLOAD_FORMAT_OPTIONS",
        "openDownloadMenu",
        "closeDownloadMenu",
        "swapCurrentTrackQuality",
        "queueContextSourceLabel",
        "getUiFlags",
        "reorderQueueItems",
        "commitQueueReorder",
        "syncPlaylistContextAfterQueueReorder",
        "onMobileDrawerTouchStart",
        "loadMeta",
        "setVolume",
        "toggleMute",
        "loadDiscoverRandom",
        "__qdpTestHooks",
    ]
    css_tokens = [
        ".downloadMenuCard",
        ".downloadMenuOption",
        ".mobileSidebarOverlay",
        ".sourceBadge",
        ".sourcePill",
        ".queueHint",
        ".volumePopover",
        ".discoverSection",
    ]
    missing_html = [token for token in html_ids if f'id="{token}"' not in index_html]
    missing_scripts = [script for script in required_scripts if script not in index_html or script not in js_sources]
    missing_js = [token for token in js_tokens if token not in bundle]
    missing_css = [token for token in css_tokens if token not in app_css]
    data_panels = re.findall(r'data-side-panel="([^"]+)"', index_html)
    card_contract_ok = all(token in bundle for token in ['cardBody', 'cardMain', 'metaBadgeHiRes'])
    hi_res_contract_ok = 'samplingRate > 48000' in bundle and '.metaBadgeHiRes' in app_css
    volume_contract_ok = all(token in bundle for token in ['toggleVolumePopover', 'volumePopoverOpen']) and 'volumeSliderVertical' in app_css
    sidebar_contract_ok = all(token in bundle for token in ['setSidebarSection', 'toggleSidebarSection']) and '.sectionBody.collapsed' in app_css
    overflow_contract_ok = all(token in app_css for token in ['overflow-x:hidden', 'text-overflow:ellipsis', 'minmax(0,1fr)'])
    download_coverage_ok = all(token in bundle for token in ['makeTrackDownloadLink', 'makeAlbumDownloadLink', 'triggerBulkDownload'])
    return {
        "html_ids_checked": html_ids,
        "required_scripts_checked": required_scripts,
        "js_tokens_checked": js_tokens,
        "css_tokens_checked": css_tokens,
        "missing_html_ids": missing_html,
        "missing_script_assets": missing_scripts,
        "missing_js_tokens": missing_js,
        "missing_css_tokens": missing_css,
        "mobile_side_panels": data_panels,
        "card_contract_ok": card_contract_ok,
        "hi_res_contract_ok": hi_res_contract_ok,
        "volume_contract_ok": volume_contract_ok,
        "sidebar_contract_ok": sidebar_contract_ok,
        "overflow_contract_ok": overflow_contract_ok,
        "download_coverage_ok": download_coverage_ok,
        "ok": not (missing_html or missing_scripts or missing_js or missing_css) and card_contract_ok and hi_res_contract_ok and volume_contract_ok and sidebar_contract_ok and overflow_contract_ok and download_coverage_ok,
    }


def run(base_url: Optional[str] = None, no_start: bool = False, json_mode: bool = False) -> int:
    started_here = False
    results: List[Dict[str, Any]] = []
    structured: Dict[str, Any] = {"api": {}, "dom": {}, "assets": {}}
    base = ""
    suppressed_stdout = io.StringIO()

    def _execute() -> None:
        nonlocal started_here, base

        if base_url:
            base = base_url.rstrip("/")
        else:
            if no_start:
                raise SmokeFailure("--no-start requires --base-url")
            base = start_web_player().rstrip("/")
            started_here = True

        if not json_mode:
            print(f"[INFO] Base URL: {base}/")
            print(f"[INFO] Expected version source: qdp.web.__version__ = {WEB_PLAYER_VERSION}")

        resp = requests.get(f"{base}/app/", timeout=20)
        _expect_status(resp, 200, "/app/")
        index_html = resp.text
        results.append(_ok("/app/", "HTTP 200", json_mode, bytes=len(resp.content)))
        structured["assets"]["/app/"] = {"bytes": len(resp.content)}

        resp = requests.get(f"{base}/__version", timeout=20)
        _expect_status(resp, 200, "/__version")
        version_payload = _get_json(resp, "/__version")
        version = str(version_payload.get("version") or version_payload.get("web_player_version") or "").strip()
        if not version:
            raise SmokeFailure("/__version: version is empty")
        if version != WEB_PLAYER_VERSION:
            raise SmokeFailure(f"/__version: version mismatch endpoint={version!r}, module={WEB_PLAYER_VERSION!r}")
        results.append(_ok("/__version", f"version={version}", json_mode, version=version))
        structured["api"]["__version"] = version_payload

        resp = requests.get(f"{base}/api/meta", timeout=20)
        _expect_status(resp, 200, "/api/meta")
        meta_payload = _get_json(resp, "/api/meta")
        meta_version = str(meta_payload.get("version") or meta_payload.get("web_player_version") or "").strip()
        if meta_version != WEB_PLAYER_VERSION:
            raise SmokeFailure(f"/api/meta: version mismatch api/meta={meta_version!r}, module={WEB_PLAYER_VERSION!r}")
        results.append(_ok("/api/meta", f"version={meta_version}", json_mode, version=meta_version))
        structured["api"]["meta"] = meta_payload

        resp = requests.get(f"{base}/api/discover-random-albums", timeout=30)
        if resp.status_code == 200:
            discover_payload = _get_json(resp, "/api/discover-random-albums")
            discover_items = discover_payload.get("items") or []
            if not isinstance(discover_items, list):
                raise SmokeFailure("/api/discover-random-albums: items is not a list")
            results.append(_ok("/api/discover-random-albums", f"seed={discover_payload.get('seed') or '-'}, items={len(discover_items)}", json_mode, seed=discover_payload.get('seed') or '', items=len(discover_items)))
            structured["api"]["discover_random_albums"] = {"seed": discover_payload.get("seed") or "", "items": len(discover_items), "available": True}
        else:
            discover_error = _get_json(resp, "/api/discover-random-albums", allow_api_error=True).get("_api_error") or {}
            detail = discover_error.get("message") or f"HTTP {resp.status_code}"
            results.append(_ok("/api/discover-random-albums", f"skipped: {detail}", json_mode, skipped=True, error_code=discover_error.get("code") or "http_error"))
            structured["api"]["discover_random_albums"] = {"available": False, "error": discover_error}

        resp = requests.get(f"{base}/api/me", timeout=30)
        if resp.status_code == 200:
            me_payload = _get_json(resp, "/api/me")
            results.append(_ok("/api/me", f"active_account={me_payload.get('active_account') or '-'}", json_mode))
            structured["api"]["me"] = {"active_account": me_payload.get("active_account") or "", "available": True}
        else:
            me_error = _get_json(resp, "/api/me", allow_api_error=True).get("_api_error") or {}
            detail = me_error.get("message") or f"HTTP {resp.status_code}"
            results.append(_ok("/api/me", f"skipped: {detail}", json_mode, skipped=True, error_code=me_error.get("code") or "http_error"))
            structured["api"]["me"] = {"available": False, "error": me_error}

        resp = requests.get(
            f"{base}/api/search",
            params={"type": "tracks", "q": "daft punk", "limit": 5},
            timeout=30,
        )
        track_id = None
        if resp.status_code == 200:
            search_payload = _get_json(resp, "/api/search tracks")
            first_track = _pick_first_track(search_payload)
            track_id = first_track["id"]
            results.append(
                _ok(
                    "/api/search tracks",
                    f"items={len(search_payload.get('items') or [])}, first_track_id={track_id}",
                    json_mode,
                    items=len(search_payload.get("items") or []),
                    first_track_id=track_id,
                )
            )
            structured["api"]["search_tracks"] = {
                "items": len(search_payload.get("items") or []),
                "first_track_id": track_id,
                "available": True,
            }
        else:
            search_error = _get_json(resp, "/api/search tracks", allow_api_error=True).get("_api_error") or {}
            detail = search_error.get("message") or f"HTTP {resp.status_code}"
            results.append(_ok("/api/search tracks", f"skipped: {detail}", json_mode, skipped=True, error_code=search_error.get("code") or "http_error"))
            structured["api"]["search_tracks"] = {"available": False, "error": search_error}

        if track_id:
            resp = requests.get(f"{base}/api/track-url", params={"id": track_id, "fmt": 5}, timeout=30)
            _expect_status(resp, 200, "/api/track-url")
            track_url_payload = _get_json(resp, "/api/track-url")
            stream_path = str(track_url_payload.get("url") or "").strip()
            if not stream_path.startswith("/stream?url="):
                raise SmokeFailure(f"/api/track-url: unexpected proxied stream url: {stream_path!r}")
            results.append(_ok("/api/track-url", "returned local /stream proxy URL", json_mode, url=stream_path))
            structured["api"]["track_url"] = {"url": stream_path, "available": True}

            stream_url = f"{base}{stream_path}"
            resp = requests.get(stream_url, headers={"Range": "bytes=0-1"}, stream=True, timeout=60)
            if resp.status_code != 206:
                snippet = ""
                try:
                    snippet = resp.text[:200].replace("\n", " ")
                except Exception:
                    pass
                raise SmokeFailure(f"/stream Range: expected HTTP 206, got {resp.status_code}, body={snippet!r}")
            content_range = resp.headers.get("Content-Range", "")
            accept_ranges = resp.headers.get("Accept-Ranges", "")
            results.append(
                _ok(
                    "/stream Range",
                    f"HTTP 206, Content-Range={content_range or '-'}, Accept-Ranges={accept_ranges or '-'}",
                    json_mode,
                    content_range=content_range,
                    accept_ranges=accept_ranges,
                )
            )
            structured["api"]["stream_range"] = {
                "status": 206,
                "content_range": content_range,
                "accept_ranges": accept_ranges,
                "available": True,
            }
            resp.close()
        else:
            results.append(_ok("/api/track-url", "skipped: search unavailable", json_mode, skipped=True))
            results.append(_ok("/stream Range", "skipped: track url unavailable", json_mode, skipped=True))
            structured["api"]["track_url"] = {"available": False}
            structured["api"]["stream_range"] = {"available": False}

        assets = {}
        js_sources: Dict[str, str] = {}
        app_css = ""
        for path in (
            "/app/app.css",
            "/app/core.js",
            "/app/accounts.js",
            "/app/queue.js",
            "/app/playlists.js",
            "/app/api.js",
            "/app/discover.js",
            "/app/player.js",
            "/app/app.js",
        ):
            resp = requests.get(f"{base}{path}", timeout=20)
            _expect_status(resp, 200, path)
            assets[path] = {"bytes": len(resp.content)}
            if path.endswith(".js"):
                js_sources[path] = resp.text
            elif path.endswith("app.css"):
                app_css = resp.text
            results.append(_ok(path, f"bytes={len(resp.content)}", json_mode, bytes=len(resp.content)))
        structured["assets"].update(assets)

        dom_contract = _check_dom_contract(index_html, js_sources, app_css)
        if not dom_contract["ok"]:
            raise SmokeFailure(
                f"frontend DOM contract failed: html={dom_contract['missing_html_ids']}, scripts={dom_contract.get('missing_script_assets', [])}, js={dom_contract['missing_js_tokens']}, css={dom_contract['missing_css_tokens']}"
            )
        results.append(
            _ok(
                "frontend-dom-contract",
                f"checked_ids={len(dom_contract['html_ids_checked'])}, panels={','.join(dom_contract['mobile_side_panels'])}",
                json_mode,
                contract=dom_contract,
            )
        )
        structured["dom"] = dom_contract

    try:
        if json_mode:
            with contextlib.redirect_stdout(suppressed_stdout):
                _execute()
        else:
            _execute()

        payload = {
            "ok": True,
            "base_url": base,
            "expected_version": WEB_PLAYER_VERSION,
            "results": results,
            "structured": structured,
        }
        if json_mode:
            _print_json(payload)
        else:
            print("[PASS] Web Player smoke test completed")
        return 0

    except SmokeFailure as exc:
        payload = {
            "ok": False,
            "base_url": base,
            "error": str(exc),
            "expected_version": WEB_PLAYER_VERSION,
            "results": results,
            "structured": structured,
        }
        if json_mode:
            _print_json(payload)
        else:
            print(f"[FAIL] {exc}")
        return 1
    except Exception as exc:
        payload = {
            "ok": False,
            "base_url": base,
            "error": f"unexpected: {exc}",
            "expected_version": WEB_PLAYER_VERSION,
            "results": results,
            "structured": structured,
        }
        if json_mode:
            _print_json(payload)
        else:
            print(f"[FAIL] unexpected error - {exc}")
        return 1
    finally:
        if started_here:
            try:
                stop_web_player()
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test local qdp web player")
    parser.add_argument(
        "--base-url",
        default="",
        help="Reuse an already running web player URL, e.g. http://127.0.0.1:17890",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Do not auto-start local server; requires --base-url",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    args = parser.parse_args()
    return run(base_url=args.base_url or None, no_start=args.no_start, json_mode=args.json)


if __name__ == "__main__":
    sys.exit(main())
