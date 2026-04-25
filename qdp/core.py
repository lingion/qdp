import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import requests
from bs4 import BeautifulSoup as bso
from pathvalidate import sanitize_filename
from rich.console import Console
from rich.table import Table

from . import downloader, qopy
from .db import create_db, handle_download_id, iter_download_entries, upsert_download_entry
from .exceptions import AuthenticationError, InvalidAppIdError, InvalidAppSecretError, NonStreamable
from .integrity import discover_library_albums
from .utils import create_and_return_dir, get_url_info, make_m3u, smart_discography_filter

console = Console()
logger = logging.getLogger(__name__)

QUALITIES = {5: "5 - MP3", 6: "6 - 16 bit, 44.1kHz", 7: "7 - 24 bit, <96kHz", 27: "27 - 24 bit, >96kHz"}

C_TEXT = "#9ca3af"
C_TITLE = "#a78bfa"
C_ARTIST = "#a3b18a"
C_INDEX = "#8e9aaf"
C_MAIN = "#778da9"
C_WARN = "#e9c46a"
C_ERR = "#e5989b"
C_DIM = "#6b705c"


ERROR_HINTS = {
    "auth": "登录凭证可能失效。建议先检查 Token / 邮箱密码，必要时运行 qdp -r 重新登录。",
    "app_secret": "App ID / App Secret 可能失效。建议 qdp -r 重置，或切换回推荐的 Android 凭证方案。",
    "proxy": "代理池节点可能不可用。建议先 qdp --doctor 检查代理配置，再尝试 --direct 直连。",
    "copyright": "该资源可能受版权、地区或账号权限限制，当前账号无法串流。",
    "path": "本地下载目录可能无权限、路径过长或被占用。请检查目录权限与剩余空间。",
    "network": "可能是网络波动。可稍后重试，或先切换网络/关闭代理后再试。",
    "generic": "建议先运行 qdp --doctor 检查配置、数据库、目录和代理状态。",
}


class QobuzDL:
    def __init__(
        self,
        directory="Qobuz Downloads",
        quality=6,
        embed_art=False,
        ignore_singles_eps=False,
        no_m3u_for_playlists=False,
        quality_fallback=True,
        cover_og_quality=False,
        no_cover=False,
        downloads_db=None,
        folder_format="{artist} - {album} ({year})",
        track_format="{tracknumber}. {tracktitle}",
        smart_discography=False,
        no_booklet=False,
        verify_existing=False,
        check_only=False,
        workers=4,
        prefetch_workers=None,
        max_retries=4,
        timeout=30,
        url_rate=8,
        force_proxy=False,
    ):
        self.directory = create_and_return_dir(directory)
        self.quality = quality
        self.embed_art = embed_art
        self.ignore_singles_eps = ignore_singles_eps
        self.no_m3u_for_playlists = no_m3u_for_playlists
        self.quality_fallback = quality_fallback
        self.cover_og_quality = cover_og_quality
        self.no_cover = no_cover
        self.downloads_db = create_db(downloads_db) if downloads_db else None
        self.folder_format = folder_format
        self.track_format = track_format
        self.smart_discography = smart_discography
        self.no_booklet = no_booklet
        self.verify_existing = verify_existing
        self.check_only = check_only
        self.workers = max(1, int(workers or 1))
        self.prefetch_workers = prefetch_workers
        self.max_retries = max_retries
        self.timeout = timeout
        self.url_rate = url_rate
        self.force_proxy = force_proxy
        self._collection_album_cache: Dict[Tuple[str, str], dict] = {}

    def initialize_client(self, email, pwd, app_id, secrets, use_token, user_id, user_auth_token):
        self.client = qopy.Client(email, pwd, app_id, secrets, use_token, user_id, user_auth_token)
        console.print(f"[{C_TEXT}]最高画质: {QUALITIES[int(self.quality)]}[/{C_TEXT}]\n")

    def _build_downloader(self, item_id, base_path=None):
        return downloader.Download(
            self.client,
            item_id,
            base_path or self.directory,
            int(self.quality),
            self.embed_art,
            self.ignore_singles_eps,
            self.quality_fallback,
            self.cover_og_quality,
            self.no_cover,
            self.folder_format,
            self.track_format,
            downloads_db=self.downloads_db,
            no_booklet=self.no_booklet,
            root_folder=self.directory,
            verify_existing=self.verify_existing,
            check_only=self.check_only,
            workers=self.workers,
            prefetch_workers=self.prefetch_workers,
            max_retries=self.max_retries,
            timeout=self.timeout,
            url_rate=self.url_rate,
            force_proxy=self.force_proxy,
        )

    def _print_search_status(self, query, search_type, limit, offset, result_count, action):
        page_num = (offset // limit) + 1
        total_hint = "总结果未知"
        console.print(f"[{C_WARN}]搜索[{search_type}] 关键词:[/{C_WARN}] {query} | 第 {page_num} 页 | 本页 {result_count} 条 | {total_hint} | 操作: {action}")

    def run_search(self, initial_query, search_type, limit):
        query = initial_query
        # New interactive search loop with multi-select + compound operations.
        from qdp.ui_compound import build_plan, confirm_execution, run_plan
        from qdp.ui_search import interactive_search_compound

        while True:
            try:
                result = interactive_search_compound(console, self.client, query, search_type, limit)
                if not result:
                    break
                if result.items:
                    plan = build_plan(result.action, result.items, options=result.options)
                    if confirm_execution(console, plan, console.input):
                        run_plan(console, self, plan)
                # after one execution, exit search.
                break
            except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as exc:
                logger.warning("Search failed for query %s: %s", query, exc, exc_info=logging.getLogger().level <= logging.DEBUG)
                console.print(f"[{C_ERR}]搜索出错: {exc}[/{C_ERR}]")
                break

    def _format_error_message(self, category, exc):
        hint = ERROR_HINTS.get(category, ERROR_HINTS["generic"])
        title_map = {
            "auth": "登录 / Token 异常",
            "app_secret": "App Secret / 配置异常",
            "proxy": "代理池异常",
            "copyright": "版权 / 地区限制",
            "path": "本地路径异常",
            "network": "网络波动",
            "generic": "未知异常",
        }
        title = title_map.get(category, title_map["generic"])
        if logging.getLogger().level <= logging.DEBUG:
            return f"[{C_ERR}]{title}: {exc}\n建议: {hint}[/{C_ERR}]"
        return f"[{C_ERR}]{title}。{hint}[/{C_ERR}]"

    def _categorize_error(self, exc):
        message = str(exc).lower()
        if isinstance(exc, AuthenticationError) or "token" in message or "登录" in message:
            return "auth"
        if isinstance(exc, (InvalidAppIdError, InvalidAppSecretError)) or "app secret" in message or "app id" in message or "签名" in message:
            return "app_secret"
        if isinstance(exc, NonStreamable) or "不可串流" in message or "region" in message or "copyright" in message:
            return "copyright"
        if isinstance(exc, PermissionError) or "permission" in message or "路径" in message or "只读" in message:
            return "path"
        if "proxy" in message or "节点" in message:
            return "proxy"
        if isinstance(exc, requests.exceptions.RequestException) or "timeout" in message or "connection" in message or "重试失败" in message:
            return "network"
        return "generic"

    def download_from_id(self, item_id, album=True, alt_path=None):
        try:
            dloader = self._build_downloader(item_id, alt_path)
            result = dloader.download_id_by_type(not album)
            if self.downloads_db and not album and not self.check_only:
                handle_download_id(self.downloads_db, item_id, add_id=True)
            return result
        except (requests.exceptions.RequestException, OSError, ValueError, sqlite3.Error, NonStreamable, AuthenticationError, InvalidAppIdError, InvalidAppSecretError) as exc:
            category = self._categorize_error(exc)
            logger.warning("Download failed for %s (%s): %s", item_id, category, exc)
            console.print(self._format_error_message(category, exc))
        return None

    def _collect_paginated_items(self, meta_pages, key):
        items = []
        pages = list(meta_pages)
        if not pages:
            return "Unknown", items
        content_name = pages[0].get("name") or pages[0].get("title") or "Unknown"
        for page in pages:
            bucket = page.get(key, {})
            if isinstance(bucket, dict):
                items.extend(bucket.get("items", []))
        return content_name, items

    def _normalize_collection_items(self, items, content_type, target_artist_id=None):
        normalized = list(items or [])
        if content_type == "artist":
            if self.smart_discography:
                normalized = smart_discography_filter(normalized, save_space=True, skip_extras=True)
            if target_artist_id:
                normalized = [item for item in normalized if str(item.get("artist", {}).get("id")) == str(target_artist_id)]
        elif content_type == "playlist":
            album_map = {}
            for track in normalized:
                album = track.get("album") if isinstance(track, dict) else None
                album_id = album.get("id") if isinstance(album, dict) else None
                if album_id:
                    album_map[str(album_id)] = album
                    continue
                direct_id = track.get("id") if isinstance(track, dict) else None
                if direct_id and track.get("tracks_count"):
                    album_map[str(direct_id)] = track
            normalized = list(album_map.values())
        return normalized

    def _check_collection_albums(self, items, content_name, base_path, content_type, target_artist_id=None):
        items = self._normalize_collection_items(items, content_type, target_artist_id=target_artist_id)
        reports = []
        dloader = self._build_downloader("batch-check", base_path)
        for item in items:
            try:
                album_id = str(item["id"])
                report, _, _ = dloader.inspect_album(album_id, base_path=base_path, announce=True, repair_db=False)
                reports.append(report)
            except (requests.exceptions.RequestException, OSError, ValueError, sqlite3.Error, NonStreamable) as exc:
                logger.warning("Check failed for album %s: %s", item.get("id"), exc)
                console.print(f"[{C_ERR}]校验失败:[/{C_ERR}] {item.get('title', item.get('id'))} -> {exc}")
        dloader._print_check_summary(content_name, reports, content_type=content_type)
        return reports

    def scan_library(self):
        if not self.downloads_db:
            console.print(f"[{C_WARN}]当前未启用数据库，scan-library 将只做离线扫描，不会回填 DB。[/]")
        entries = list(iter_download_entries(self.downloads_db)) if self.downloads_db else []
        candidates = discover_library_albums(self.directory, db_entries=entries)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        found_paths = 0
        missing_paths = 0
        incomplete_db_records = 0
        known = 0
        complete = 0
        incomplete = 0
        unknown = 0
        for entry in entries:
            local_path = entry.get("local_path")
            if not local_path:
                missing_paths += 1
                continue
            if os.path.isdir(local_path):
                found_paths += 1
            else:
                missing_paths += 1
            if entry.get("integrity_status") != "complete":
                incomplete_db_records += 1
        for candidate in candidates:
            status = candidate.integrity_status or "unknown"
            if status == "complete":
                complete += 1
                known += 1
            elif status == "incomplete":
                incomplete += 1
                known += 1
            else:
                unknown += 1
            if self.downloads_db:
                target_id = candidate.matched_db_ids[0] if candidate.matched_db_ids else f"offline:{candidate.album_key}"
                upsert_download_entry(
                    self.downloads_db,
                    target_id,
                    {
                        "item_type": "album",
                        "album_id": target_id,
                        "local_path": candidate.album_dir,
                        "expected_tracks": candidate.expected_tracks or candidate.matched_tracks,
                        "matched_tracks": candidate.matched_tracks,
                        "last_checked": now,
                        "integrity_status": status,
                        "folder_format": (candidate.sidecar or {}).get("folder_format"),
                        "track_format": (candidate.sidecar or {}).get("track_format"),
                        "source_quality": json.dumps(((candidate.sidecar or {}).get("quality") or {}).get("source_quality", {}), ensure_ascii=False) if candidate.sidecar else None,
                        "actual_quality": json.dumps(((candidate.sidecar or {}).get("quality") or {}).get("actual_quality", {}), ensure_ascii=False) if candidate.sidecar else None,
                        "bit_depth": (((candidate.sidecar or {}).get("quality") or {}).get("actual_quality") or {}).get("bit_depth") if candidate.sidecar else None,
                        "sampling_rate": (((candidate.sidecar or {}).get("quality") or {}).get("actual_quality") or {}).get("sampling_rate") if candidate.sidecar else None,
                        "sidecar_path": (candidate.sidecar or {}).get("sidecar_path") if candidate.sidecar else None,
                    },
                )
        summary = {
            "db_entries": len(entries),
            "found_paths": found_paths,
            "incomplete": incomplete_db_records,
            "missing_paths": missing_paths,
            "scanned_albums": len(candidates),
            "complete_albums": complete,
            "incomplete_albums": incomplete,
            "unknown_albums": unknown,
            "known_albums": known,
        }
        console.print(
            f"[{C_MAIN}]扫描完成[/] 离线识别专辑: {summary['scanned_albums']} | 完整: {summary['complete_albums']} | 不完整: {summary['incomplete_albums']} | 未知结构: {summary['unknown_albums']}"
        )
        console.print(
            f"[{C_TEXT}]DB 记录: {summary['db_entries']} | 本地目录命中: {summary['found_paths']} | DB 不完整记录: {summary['incomplete']} | 缺少路径: {summary['missing_paths']}[/{C_TEXT}]"
        )
        return summary

    def doctor(self, config_defaults):
        checks = []
        required_keys = ["default_folder", "default_quality", "app_id", "secrets"]
        missing = [key for key in required_keys if not config_defaults.get(key)]
        checks.append(("配置完整性", not missing, "缺少: " + ", ".join(missing) if missing else "OK"))
        db_ok = True
        db_msg = "未启用数据库"
        if self.downloads_db:
            try:
                create_db(self.downloads_db)
                db_msg = "可读写"
            except sqlite3.Error as exc:
                db_ok = False
                db_msg = str(exc)
        checks.append(("数据库", db_ok, db_msg))
        proxy_msg = config_defaults.get("proxies") or "未配置代理池（可正常直连）"
        checks.append(("代理配置", True, proxy_msg))
        dl_dir = self.directory
        writable = os.path.isdir(dl_dir) and os.access(dl_dir, os.W_OK)
        checks.append(("下载目录", writable, dl_dir))
        try:
            dummy = {"artist": "A", "album": "B", "year": "2024", "format": "FLAC", "bit_depth": 16, "sampling_rate": 44.1, "tracknumber": "01", "tracktitle": "Song"}
            folder_preview = self.folder_format.format(**dummy)
            track_preview = self.track_format.format(**dummy)
            fmt_ok = True
            fmt_msg = f"folder={folder_preview} | track={track_preview}"
        except (IndexError, KeyError, ValueError) as exc:
            fmt_ok = False
            fmt_msg = str(exc)
        checks.append(("命名规则", fmt_ok, fmt_msg))
        scan = self.scan_library()
        incomplete_flag = scan.get("incomplete", 0) == 0
        checks.append(("本地库完整性", incomplete_flag, f"不完整记录: {scan.get('incomplete', 0)}"))
        for name, ok, msg in checks:
            color = C_MAIN if ok else C_ERR
            state = "OK" if ok else "FAIL"
            console.print(f"[{color}]{state}[/{color}] {name}: {msg}")
        return checks

    def rename_library(self, dry_run=False, album_keys=None):
        dloader = downloader.Download(None, "rename", self.directory, int(self.quality), folder_format=self.folder_format, track_format=self.track_format, downloads_db=self.downloads_db)
        plan = dloader.plan_library_rename(self.directory, album_keys=album_keys)
        for item in plan:
            action = "预览" if dry_run else "重命名"
            console.print(
                f"[{C_TEXT}]{action}[/] ({item.get('kind', 'unknown')}/{item.get('confidence', 'unknown')}) {item['src']} -> {item['dst']}"
            )
        if not dry_run:
            dloader.apply_rename_plan(plan)
            if self.downloads_db:
                db_entries = list(iter_download_entries(self.downloads_db))
                album_moves = {
                    os.path.normpath(item["src"]): os.path.normpath(item["dst"])
                    for item in plan
                    if item.get("kind") == "album"
                }
                for entry in db_entries:
                    local_path = entry.get("local_path")
                    normalized = os.path.normpath(local_path) if local_path else None
                    if normalized in album_moves:
                        upsert_download_entry(
                            self.downloads_db,
                            entry["id"],
                            {
                                "item_type": entry.get("item_type") or "album",
                                "album_id": entry.get("album_id") or entry["id"],
                                "local_path": album_moves[normalized],
                                "expected_tracks": entry.get("expected_tracks"),
                                "matched_tracks": entry.get("matched_tracks"),
                                "last_checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "integrity_status": entry.get("integrity_status") or "unknown",
                                "folder_format": entry.get("folder_format"),
                                "track_format": entry.get("track_format"),
                                "source_quality": entry.get("source_quality"),
                                "actual_quality": entry.get("actual_quality"),
                                "bit_depth": entry.get("bit_depth"),
                                "sampling_rate": entry.get("sampling_rate"),
                                "sidecar_path": entry.get("sidecar_path"),
                            },
                        )
                for candidate in discover_library_albums(self.directory, db_entries=list(iter_download_entries(self.downloads_db))):
                    target_id = candidate.matched_db_ids[0] if candidate.matched_db_ids else f"offline:{candidate.album_key}"
                    upsert_download_entry(
                        self.downloads_db,
                        target_id,
                        {
                            "item_type": "album",
                            "album_id": target_id,
                            "local_path": candidate.album_dir,
                            "expected_tracks": candidate.expected_tracks or candidate.matched_tracks,
                            "matched_tracks": candidate.matched_tracks,
                            "last_checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "integrity_status": candidate.integrity_status,
                            "folder_format": (candidate.sidecar or {}).get("folder_format"),
                            "track_format": (candidate.sidecar or {}).get("track_format"),
                            "source_quality": json.dumps(((candidate.sidecar or {}).get("quality") or {}).get("source_quality", {}), ensure_ascii=False) if candidate.sidecar else None,
                            "actual_quality": json.dumps(((candidate.sidecar or {}).get("quality") or {}).get("actual_quality", {}), ensure_ascii=False) if candidate.sidecar else None,
                            "bit_depth": (((candidate.sidecar or {}).get("quality") or {}).get("actual_quality") or {}).get("bit_depth") if candidate.sidecar else None,
                            "sampling_rate": (((candidate.sidecar or {}).get("quality") or {}).get("actual_quality") or {}).get("sampling_rate") if candidate.sidecar else None,
                            "sidecar_path": (candidate.sidecar or {}).get("sidecar_path") if candidate.sidecar else None,
                        },
                    )
        return plan

    def handle_url(self, url):
        possibles = {
            "playlist": {"func": self.client.get_plist_meta, "iterable_key": "tracks", "content_type": "playlist"},
            "artist": {"func": self.client.get_artist_meta, "iterable_key": "albums", "content_type": "artist"},
            "label": {"func": self.client.get_label_meta, "iterable_key": "albums", "content_type": "label"},
            "album": {"album": True, "func": None, "content_type": "album"},
            "track": {"album": False, "func": None, "content_type": "track"},
        }
        try:
            url_type, item_id = get_url_info(url)
            type_dict = possibles[url_type]
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping invalid URL %s: %s", url, exc)
            console.print(f"[{C_ERR}]跳过无效链接: {url}[/{C_ERR}]")
            return
        if type_dict.get("func"):
            try:
                pages = list(type_dict["func"](item_id))
                if not pages:
                    return
                content_name, items = self._collect_paginated_items(pages, type_dict["iterable_key"])
                console.print(f"[{C_WARN}]正在获取 {url_type}:[/{C_WARN}] {content_name}")
                target_path = os.path.join(self.directory, sanitize_filename(content_name))
                target_artist_id = item_id if url_type == "artist" else None
                normalized_items = self._normalize_collection_items(items, url_type, target_artist_id=target_artist_id)
                if self.check_only:
                    self._check_collection_albums(normalized_items, content_name, target_path, url_type, target_artist_id=target_artist_id)
                    return
                new_path = create_and_return_dir(target_path)
                console.print(f"[{C_TEXT}]包含 {len(normalized_items)} 个项目，准备下载...[/{C_TEXT}]")
                dloader = self._build_downloader(item_id, new_path)
                dloader.download_batch(normalized_items, content_name=content_name, target_artist_id=target_artist_id)
                if url_type == "playlist" and not self.no_m3u_for_playlists and not self.check_only:
                    make_m3u(new_path)
            except (requests.exceptions.RequestException, OSError, ValueError, NonStreamable, sqlite3.Error) as exc:
                logger.warning("Batch handling failed for %s (%s): %s", url, type(exc).__name__, exc)
                console.print(f"[{C_ERR}]批量处理出错: {exc}[/{C_ERR}]")
        else:
            self.download_from_id(item_id, type_dict["album"])

    def download_list_of_urls(self, raw_args):
        if not raw_args:
            return
        valid_urls = []
        for arg in raw_args:
            arg = arg.strip()
            if "qobuz.com" in arg and "http" in arg:
                valid_urls.append(arg)
            elif os.path.isfile(arg):
                self.download_from_txt_file(arg)
            elif "last.fm" in arg:
                self.download_lastfm_pl(arg)
        if not valid_urls and not any(os.path.isfile(x) or "last.fm" in x for x in raw_args):
            full_text = " ".join(raw_args)
            qobuz_pattern = r"(https?://(?:open|play|www)\.qobuz\.com/[^\s\"']+)"
            valid_urls.extend(re.findall(qobuz_pattern, full_text))
        unique_urls = list(dict.fromkeys(valid_urls))
        if not unique_urls:
            return
        console.print(f"[{C_MAIN}]识别到 {len(unique_urls)} 个链接，开始处理...[/{C_MAIN}]")
        for url in unique_urls:
            self.handle_url(url)

    def download_from_txt_file(self, txt_file):
        with open(txt_file, "r", encoding="utf-8") as txt:
            urls = [line.strip() for line in txt.readlines() if line.strip() and not line.strip().startswith("#")]
        self.download_list_of_urls(urls)

    def download_lastfm_pl(self, playlist_url):
        try:
            response = requests.get(playlist_url, timeout=10)
            response.raise_for_status()
            soup = bso(response.text, "html.parser")
            links = []
            for anchor in soup.find_all("a", href=True):
                href = anchor["href"]
                if "/music/" in href and "/_/'" not in href:
                    links.append(href)
            if not links:
                console.print(f"[{C_WARN}]未从 Last.fm 页面提取到可下载条目。[/{C_WARN}]")
                return
            console.print(f"[{C_MAIN}]从 Last.fm 提取到 {len(links)} 个条目，尝试匹配 Qobuz...[/{C_MAIN}]")
            self.download_list_of_urls(links)
        except requests.exceptions.RequestException as exc:
            logger.warning("Failed to load Last.fm playlist %s: %s", playlist_url, exc)
            console.print(f"[{C_ERR}]Last.fm 列表读取失败: {exc}[/{C_ERR}]")
