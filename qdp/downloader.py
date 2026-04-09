import hashlib
import json
import logging
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from mutagen import MutagenError
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from pathvalidate import sanitize_filename, sanitize_filepath
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

import qdp.metadata as metadata
from qdp.db import handle_download_id, upsert_download_entry
from qdp.exceptions import NonStreamable
from qdp.integrity import (
    AUDIO_EXTENSIONS,
    build_filename_context,
    discover_library_albums,
    get_title,
    inspect_album_integrity,
    make_track_label,
)
from qdp.sidecar import build_album_sidecar_payload, load_sidecar, summarize_quality_from_tracks, write_sidecar
from qdp.utils import format_proxy_url

DEFAULT_FOLDER = "{artist} - {album} ({year})"
DEFAULT_TRACK = "{artist} - {tracktitle} [{bit_depth}B-{sampling_rate}kHz]"
MAX_WORKERS = 10
DEFAULT_PREPARE_WORKERS = 3
DEFAULT_PREHEAT_WORKERS = 6

DEFAULT_MAX_RETRIES = 4
DEFAULT_TIMEOUT = 30
DEFAULT_PREFETCH_WORKERS = None  # use --workers when None
DEFAULT_URL_RATE = 8  # per second global track/getFileUrl window
MAX_PATH_LENGTH = 240
SAFE_RENAME_METADATA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".txt", ".cue", ".m3u"}

console = Console()
logger = logging.getLogger(__name__)

_SHARED_ALBUM_META_CACHE: Dict[Tuple[int, str], dict] = {}
_SHARED_ALBUM_DIRECTORY_CACHE: Dict[str, str] = {}

BLACKLIST_KEYWORDS = [
    "sped up", "slowed", "reverb", "nightcore",
    "tribute", "cover", "lullaby", "karaoke",
    "instrumental version", "acoustic cover", "piano cover",
    "lofi", "lo-fi", "remix", "hypertechno", "techno mix",
]

C_TEXT = "#abb2bf"
C_MAIN = "#61afef"
C_OK = "#98c379"
C_WARN = "#e5c07b"
C_ERR = "#e06c75"
C_DIM = "#5c6370"
C_BAR_BG = "#3e4451"


@dataclass
class DownloadPipelineError(Exception):
    category: str
    message: str
    hint: str = ""

    def __str__(self) -> str:
        return f"{self.message}。{self.hint}" if self.hint else self.message


class RateLimiter:
    """Simple shared rate limiter (token-bucket-ish using minimum interval)."""

    def __init__(self, rate_per_sec: float):
        self._min_interval = 1.0 / float(rate_per_sec) if rate_per_sec else 0.0
        self._lock = threading.Lock()
        self._next_ts = 0.0

    def acquire(self):
        if self._min_interval <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self._next_ts:
                    self._next_ts = now + self._min_interval
                    return
                sleep_for = self._next_ts - now
            if sleep_for > 0:
                time.sleep(min(0.25, sleep_for))


class ProxyPool:
    """Very small health scoring/circuit breaker for proxy endpoints.

    Proxies here refer to Cloudflare worker base URLs used by qdp.utils.format_proxy_url.

    Note: This is best-effort and deliberately simple.
    """

    def __init__(self, proxies: List[str], cooldown_sec: int = 30, fail_threshold: int = 3):
        self.proxies = [p.rstrip("/") for p in (proxies or []) if p]
        self.cooldown_sec = int(cooldown_sec)
        self.fail_threshold = int(fail_threshold)
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, float]] = {p: {"fails": 0, "cooldown_until": 0.0, "last": 0.0} for p in self.proxies}

    def choose(self) -> Optional[str]:
        with self._lock:
            now = time.monotonic()
            healthy = [p for p in self.proxies if self._state[p]["cooldown_until"] <= now]
            if not healthy:
                return None
            # Prefer lowest fails, then least recently used.
            healthy.sort(key=lambda p: (self._state[p]["fails"], self._state[p]["last"]))
            choice = healthy[0]
            self._state[choice]["last"] = now
            return choice

    def report_success(self, proxy: Optional[str]):
        if not proxy:
            return
        with self._lock:
            if proxy in self._state:
                self._state[proxy]["fails"] = max(0, self._state[proxy]["fails"] - 1)
                self._state[proxy]["cooldown_until"] = 0.0

    def report_failure(self, proxy: Optional[str]):
        if not proxy:
            return
        with self._lock:
            if proxy not in self._state:
                return
            self._state[proxy]["fails"] += 1
            if self._state[proxy]["fails"] >= self.fail_threshold:
                self._state[proxy]["cooldown_until"] = time.monotonic() + self.cooldown_sec


class Download:
    def __init__(
        self,
        client,
        item_id,
        path,
        quality,
        embed_art=False,
        albums_only=False,
        downgrade_quality=True,
        cover_og_quality=False,
        no_cover=False,
        folder_format=None,
        track_format=None,
        downloads_db=None,
        no_booklet=False,
        root_folder=None,
        verify_existing=False,
        check_only=False,
        workers=4,
        prefetch_workers=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
        url_rate: int = DEFAULT_URL_RATE,
        force_proxy: bool = False,
    ):
        self.client = client
        self.item_id = item_id
        self.path = path
        self.quality = quality
        self.albums_only = albums_only
        self.embed_art = embed_art
        self.downgrade_quality = downgrade_quality
        self.cover_og_quality = cover_og_quality
        self.no_cover = no_cover
        self.folder_format = folder_format or DEFAULT_FOLDER
        self.track_format = track_format or DEFAULT_TRACK
        self.downloads_db = downloads_db
        self.no_booklet = no_booklet
        self.verify_existing = verify_existing
        self.root_folder = root_folder if root_folder else path
        self.check_only = check_only
        self.workers = max(1, min(MAX_WORKERS, int(workers or 1)))
        self.prepare_workers = max(1, min(self.workers, DEFAULT_PREPARE_WORKERS))
        effective_prefetch = self.workers if prefetch_workers is None else int(prefetch_workers or 1)
        self.preheat_workers = max(1, min(MAX_WORKERS, effective_prefetch))
        self.download_workers = self.workers
        self.max_retries = max(0, int(max_retries or 0))
        self.timeout = max(1, int(timeout or DEFAULT_TIMEOUT))
        self.force_proxy = bool(force_proxy)

        # Global limiter for track/getFileUrl.
        self.url_limiter = RateLimiter(rate_per_sec=max(0.1, float(url_rate or DEFAULT_URL_RATE)))

        # Proxy health pool (download stage only).
        try:
            from qdp.utils import get_proxy_list
            self.proxy_pool = ProxyPool(get_proxy_list())
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            logger.warning("Proxy pool bootstrap failed; falling back to direct-only mode: %s", exc)
            self.proxy_pool = ProxyPool([])

        self.fmt_album = self.track_format
        self.fmt_single = self.track_format
        self._track_url_cache: Dict[str, dict] = {}
        self._album_meta_cache = _SHARED_ALBUM_META_CACHE
        self._album_directory_cache = _SHARED_ALBUM_DIRECTORY_CACHE

    def download_id_by_type(self, track=True):
        if not track:
            self.download_release()
        else:
            self.download_track()

    def _get_album_meta_cached(self, album_id: str):
        album_id = str(album_id)
        cache_key = (id(self.client), album_id)
        if cache_key not in self._album_meta_cache:
            self._album_meta_cache[cache_key] = self.client.get_album_meta(album_id)
        return self._album_meta_cache[cache_key]

    def _cache_album_artifacts(self, album_id: str, base_path: str, meta: dict):
        cache_key = f"{album_id}:{base_path}"
        if cache_key not in self._album_directory_cache:
            self._album_directory_cache[cache_key] = self._album_directory(meta, base_path)
        return self._album_directory_cache[cache_key]

    def inspect_album(self, album_id: str, base_path: Optional[str] = None, announce=True, repair_db=False):
        base_dir = base_path or self.path
        meta = self._get_album_meta_cached(album_id)
        if not meta.get("streamable"):
            raise NonStreamable("不可串流")
        album_dir = self._cache_album_artifacts(str(album_id), base_dir, meta)
        report = inspect_album_integrity(
            album_id=str(album_id),
            album_dir=album_dir,
            meta=meta,
            current_track_format=self.track_format,
            downloads_db=self.downloads_db,
            repair_db=repair_db,
        )
        if announce:
            self.print_integrity_report(report)
        return report, meta, album_dir

    def print_integrity_report(self, report):
        status = "完整" if report.complete else "不完整"
        color = C_OK if report.complete else C_WARN
        console.print(
            f"[{color}]• {report.album_title}[/{color}] | {status} | 已命中 {report.matched_count}/{report.expected_count} | 缺少 {report.missing_count}"
        )
        console.print(
            f"[{C_DIM}]目录: {report.album_dir} | 旧命名命中: {report.legacy_naming_hits} | 标签识别命中: {report.tag_match_hits} | DB: {'陈旧' if report.db_stale else ('已命中' if report.db_hit else '未命中')}[/{C_DIM}]"
        )
        if report.missing_labels:
            preview = ", ".join(report.missing_labels[:5])
            suffix = " ..." if len(report.missing_labels) > 5 else ""
            console.print(f"[{C_DIM}]缺失曲目: {preview}{suffix}[/{C_DIM}]")

    def _album_directory(self, meta, base_path):
        album_title = get_title(meta)
        file_format, _, bit_depth, sampling_rate = self._get_format(meta)
        album_attr = self._get_album_attr(meta, album_title, file_format, bit_depth, sampling_rate)
        sanitized_title = sanitize_filepath(self.folder_format.format(**album_attr))
        return os.path.join(base_path, sanitized_title)

    def _fetch_track_url(self, track_id, quality=None):
        quality = int(quality or self.quality)
        cache_key = f"{track_id}:{quality}"
        if cache_key not in self._track_url_cache:
            # Rate limit track/getFileUrl.
            self.url_limiter.acquire()
            self._track_url_cache[cache_key] = self.client.get_track_url(track_id, fmt_id=quality)
        return self._track_url_cache[cache_key]

    def _prime_track_urls(self, tracks: List[dict], quality=None):
        """Stage-2 pipeline: resolve track/getFileUrl for each track.

        This stage is rate-limited globally by self.url_limiter.
        """
        quality = int(quality or self.quality)
        unique_track_ids = []
        seen = set()
        for track in tracks or []:
            track_id = str(track.get("id")) if track.get("id") is not None else None
            if not track_id or track_id in seen:
                continue
            seen.add(track_id)
            unique_track_ids.append(track_id)
        if not unique_track_ids:
            return
        max_workers = min(self.preheat_workers, len(unique_track_ids))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self._resolve_track_url_with_fallback, track_id, quality) for track_id in unique_track_ids]
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result and result.get("track_id"):
                        logger.debug("Preheated track %s at quality %s", result.get("track_id"), (result.get("actual_quality") or {}).get("quality_code"))
                except (DownloadPipelineError, requests.exceptions.RequestException, ValueError) as exc:
                    logger.warning("Track URL priming failed: %s", exc)

    def _get_max_quality_url(self, url):
        if not url:
            return None
        if self.cover_og_quality:
            return url.replace("_600.", "_org.").replace("_small.", "_org.").replace("_medium.", "_org.")
        return url

    def _quality_candidates(self, requested_quality: int) -> List[int]:
        requested_quality = int(requested_quality)
        ordered = [requested_quality]
        if not self.downgrade_quality:
            return ordered
        fallback_map = {
            27: [7, 6, 5],
            7: [6, 5],
            6: [5],
            5: [],
        }
        for candidate in fallback_map.get(requested_quality, []):
            if candidate not in ordered:
                ordered.append(candidate)
        return ordered

    def _source_quality_from_track(self, track: dict) -> Dict[str, object]:
        return {
            "quality_code": int(self.quality),
            "bit_depth": track.get("maximum_bit_depth"),
            "sampling_rate": track.get("maximum_sampling_rate"),
            "source_available_quality": {
                "maximum_bit_depth": track.get("maximum_bit_depth"),
                "maximum_sampling_rate": track.get("maximum_sampling_rate"),
            },
        }

    def _classify_retryable_error(self, exc: Exception) -> str:
        if isinstance(exc, DownloadPipelineError):
            return exc.category
        message = str(exc).lower()
        if isinstance(exc, NonStreamable) or "试听" in message or "sample" in message or "不可串流" in message:
            return "copyright"
        if isinstance(exc, (requests.exceptions.ProxyError, requests.exceptions.SSLError)) or "proxy" in message or "ssl" in message:
            return "proxy"
        if isinstance(exc, PermissionError) or "permission" in message or "read-only" in message:
            return "io"
        if isinstance(exc, requests.exceptions.RequestException) or "timeout" in message or "connection" in message:
            return "network"
        if "token" in message or "auth" in message or "401" in message or "app secret" in message or "app id" in message:
            return "auth"
        return "generic"

    def _resolve_track_url_with_fallback(self, track_id, requested_quality=None):
        requested_quality = int(requested_quality or self.quality)
        resolved_cache_key = f"resolved:{track_id}:{requested_quality}"
        if resolved_cache_key in self._track_url_cache:
            return self._track_url_cache[resolved_cache_key]
        attempts = []
        for candidate_quality in self._quality_candidates(requested_quality):
            try:
                payload = self._fetch_track_url(track_id, candidate_quality)
                if not payload or "url" not in payload:
                    if payload and "sample" in payload:
                        raise NonStreamable("仅提供试听")
                    raise DownloadPipelineError("network", "无效下载链接")
                actual_quality = {
                    "quality_code": candidate_quality,
                    "bit_depth": payload.get("bit_depth"),
                    "sampling_rate": payload.get("sampling_rate"),
                }
                result = {
                    "track_id": str(track_id),
                    "requested_quality": requested_quality,
                    "actual_quality": actual_quality,
                    "source_quality": {},
                    "payload": payload,
                    "reason": None if candidate_quality == requested_quality else "fallback_quality",
                    "attempts": attempts,
                }
                self._track_url_cache[resolved_cache_key] = result
                return result
            except (DownloadPipelineError, NonStreamable, requests.exceptions.RequestException, ValueError, TypeError, KeyError) as exc:
                category = self._classify_retryable_error(exc)
                attempts.append({"quality": candidate_quality, "category": category, "error": str(exc)})
                log_level = logging.WARNING if category in {"auth", "copyright"} else logging.INFO
                logger.log(
                    log_level,
                    "Track URL resolution failed for %s at quality %s (%s): %s",
                    track_id,
                    candidate_quality,
                    category,
                    exc,
                )
                # Auth/copyright are not worth retrying other qualities.
                if category in {"auth", "copyright"}:
                    if category == "auth":
                        break
                    if candidate_quality == requested_quality or not self.downgrade_quality:
                        raise
                # transient failures: continue to next quality tier.
                continue
        if attempts:
            last = attempts[-1]
            raise DownloadPipelineError(last["category"], f"URL 预热失败[{last['category']}]: {last['error']}")
        raise DownloadPipelineError("generic", "URL 预热失败")

    def _download_booklet(self, meta, save_dir):
        if self.check_only or self.no_booklet or "goodies" not in meta:
            return
        try:
            count = 1
            for goodie in meta["goodies"]:
                if goodie.get("file_format_id") != 21:
                    continue
                fname = "Digital Booklet.pdf" if count == 1 else f"Digital Booklet {count}.pdf"
                url = format_proxy_url(goodie["url"])
                _get_extra_proxy(url, save_dir, fname)
                count += 1
        except Exception as exc:
            logger.warning("Booklet download failed for %s: %s", save_dir, exc)

    def _download_cover_art(self, meta, save_dir, filename="cover.jpg"):
        if self.check_only or self.no_cover:
            return
        try:
            img_url = meta.get("image", {}).get("large")
            if not img_url:
                return
            url = format_proxy_url(self._get_max_quality_url(img_url))
            _get_extra_proxy(url, save_dir, filename)
        except Exception as exc:
            logger.warning("Cover art download failed for %s: %s", save_dir, exc)

    def _fetch_and_prepare_album(self, album_simple, base_path):
        album_id = str(album_simple["id"])
        try:
            report, meta, album_dir = self.inspect_album(
                album_id,
                base_path=base_path,
                announce=self.check_only,
                repair_db=self.verify_existing and not self.check_only,
            )
            if report.complete:
                return {"status": "complete", "report": report, "album_id": album_id, "album_title": report.album_title}
            if self.check_only:
                return {"status": "checked", "report": report, "album_id": album_id, "album_title": report.album_title}

            os.makedirs(album_dir, exist_ok=True)
            self._download_cover_art(meta, album_dir, "cover.jpg")
            self._download_booklet(meta, album_dir)

            tracks = meta.get("tracks", {}).get("items", [])
            is_multiple = len({t.get("media_number", 1) for t in tracks}) > 1
            self._prime_track_urls(tracks)
            for track in tracks:
                track["_manual_dir"] = album_dir
                track["_is_multiple"] = is_multiple
                track["album"] = meta
                resolution = self._track_url_cache.get(f"resolved:{track.get('id')}:{int(self.quality)}")
                if resolution:
                    track["_cached_track_resolution"] = resolution
                context = build_filename_context(track, (resolution or {}).get("payload"))
                expected_name = self.track_format.format(**context)
                rel_path = expected_name
                if is_multiple:
                    rel_path = os.path.join(f"Disc {int(track.get('media_number', 1) or 1)}", expected_name)
                ext = ".mp3" if int((resolution or {}).get("actual_quality", {}).get("quality_code") or self.quality) == 5 else ".flac"
                track["_expected_filename"] = expected_name + ext
                track["_expected_rel_path"] = rel_path + ext
                track.setdefault("_requested_quality", self.quality)
                track.setdefault("_source_quality", self._source_quality_from_track(track))
                track.setdefault("_actual_quality", (resolution or {}).get("actual_quality") or {})
            return {"status": "ready", "tracks": tracks, "report": report, "album_id": album_id, "album_title": report.album_title, "meta": meta, "album_dir": album_dir}
        except Exception as exc:
            logger.warning("Failed to prepare album %s: %s", album_id, exc)
            return {"status": "invalid", "reason": str(exc), "album_id": album_id}

    def _process_single_track(self, item, count, total_items, meta, dirn, is_multiple, progress, overall_task_id, failed_list, ind_cover, track_fmt):
        if not item:
            progress.update(overall_task_id, advance=1)
            return
        title = item.get("title", "Unknown")
        display_title = title if len(title) <= 25 else title[:24] + "…"
        display_name = f"[{C_DIM}]({count:02d}/{total_items:02d})[/{C_DIM}] [{C_WARN}]{display_title}[/{C_WARN}]"
        task_id = progress.add_task("", filename=display_name, start=False, visible=True)
        progress.update(task_id, description=f"[{C_DIM}]等待...[/{C_DIM}] {display_name}")
        try:
            if "_manual_dir" in item:
                self._process_real_track(item, count, total_items, item.get("album"), item["_manual_dir"], item.get("_is_multiple"), progress, task_id, False, self.fmt_album)
            else:
                self._process_real_track(item, count, total_items, meta, dirn, is_multiple, progress, task_id, ind_cover, track_fmt)
        except Exception as exc:
            album_name = item.get("album", {}).get("title") or (meta or {}).get("title") or "Unknown Album"
            failed_list.append({"item": item, "error": str(exc), "album": album_name, "path": item.get("_manual_dir", dirn), "label": make_track_label(item)})
            logger.warning("Track failed: %s (%s)", display_title, exc)
            progress.console.print(f"[{C_ERR}]失败 {display_name}: {exc}[/{C_ERR}]")
        finally:
            progress.update(overall_task_id, advance=1)
            progress.remove_task(task_id)

    def _flatten_albums_to_tracks(self, album_list, base_path):
        console.print(f"[{C_MAIN}]预解析 {len(album_list)} 张专辑元数据...[/{C_MAIN}]")
        flat_tracks = []
        stats = {"complete": 0, "invalid": 0, "checked": 0, "reports": []}
        with Progress(
            SpinnerColumn(style=C_MAIN),
            TextColumn(f"[{C_TEXT}]解析中...[/{C_TEXT}]"),
            BarColumn(bar_width=20, style=C_BAR_BG, complete_style=C_MAIN),
            TextColumn(f"[{C_DIM}]{{task.completed}}/{{task.total}}[/{C_DIM}]"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Parsing", total=len(album_list))
            with ThreadPoolExecutor(max_workers=min(self.prepare_workers, max(1, len(album_list)))) as executor:
                futures = {executor.submit(self._fetch_and_prepare_album, album, base_path): album for album in album_list}
                for future in as_completed(futures):
                    result = future.result()
                    progress.advance(task)
                    if not result:
                        stats["invalid"] += 1
                        continue
                    if result.get("report"):
                        stats["reports"].append(result["report"])
                    status = result["status"]
                    if status == "ready":
                        flat_tracks.extend(result["tracks"])
                    elif status == "complete":
                        stats["complete"] += 1
                    elif status == "checked":
                        stats["checked"] += 1
                    else:
                        stats["invalid"] += 1
        return flat_tracks, stats

    def download_batch(self, track_list, content_name="歌单", target_artist_id=None):
        final_list = track_list
        batch_ind_cover = True
        if track_list and "tracks_count" in track_list[0] and "artist" in track_list[0]:
            target_artist = content_name
            console.print(f"[{C_WARN}]主艺人锁定: {target_artist} (ID: {target_artist_id or 'Auto'})[/{C_WARN}]")
            filtered_items = []
            skipped_spam = 0
            for item in track_list:
                item_artist_name = item.get("artist", {}).get("name", "")
                item_artist_id = str(item.get("artist", {}).get("id"))
                item_title = item.get("title", "")
                if any(keyword in item_title.lower() for keyword in BLACKLIST_KEYWORDS):
                    skipped_spam += 1
                    continue
                is_relevant = item_artist_id == str(target_artist_id) if target_artist_id else target_artist.lower() in item_artist_name.lower()
                if is_relevant:
                    filtered_items.append(item)
            console.print(f"[{C_OK}]净化结果: {len(track_list)} -> {len(filtered_items)} 专辑[/{C_OK}]")
            if skipped_spam:
                console.print(f"[{C_DIM}]已过滤 {skipped_spam} 个疑似无关/污染条目[/{C_DIM}]")
            final_list, prep_stats = self._flatten_albums_to_tracks(filtered_items, self.path)
            batch_ind_cover = False
            if self.check_only:
                self._print_check_summary(content_name, prep_stats.get("reports", []), content_type="artist")
                return prep_stats
            logger.info("Batch preparation stats: %s", prep_stats)

        if self.check_only:
            console.print(f"[{C_WARN}]check-only 模式下没有需要下载的单曲条目，已跳过落盘。[/]")
            return {"checked": 0, "downloaded": 0}

        stats = self._run_multithreaded_download(final_list, self.path, None, False, ind_cover=batch_ind_cover, track_fmt=self.fmt_single)
        console.print(f"[{C_OK}]✔ {content_name} 任务结束[/{C_OK}]")
        console.print(f"[{C_MAIN}]📂 保存于: {os.path.abspath(self.path)}[/{C_MAIN}]")
        return stats

    def _process_real_track(self, item, count, total_items, meta, dirn, is_multiple, progress, task_id, ind_cover, track_fmt):
        title = item.get("title", "Unknown")
        display_desc = f"({count}/{total_items}) {title[:20]}"
        progress.update(task_id, description=display_desc)
        resolved = item.get("_cached_track_resolution") or self._resolve_track_url_with_fallback(item["id"], self.quality)
        parse = resolved.get("payload") if resolved else None
        if not parse or "url" not in parse:
            if parse and "sample" in parse:
                raise NonStreamable("仅提供试听，已跳过")
            raise DownloadPipelineError("network", "无效下载链接")
        if not parse.get("sampling_rate") and "sample" in parse:
            raise NonStreamable("仅提供试听，已跳过")
        item["_requested_quality"] = resolved.get("requested_quality") if resolved else self.quality
        item["_source_quality"] = resolved.get("source_quality") if resolved else {}
        item["_actual_quality"] = resolved.get("actual_quality") if resolved else {}
        item["_fallback_reason"] = resolved.get("reason") if resolved else None
        is_mp3 = int((resolved.get("actual_quality") or {}).get("quality_code") or self.quality) == 5
        self._download_and_tag(dirn, count, parse, item, meta or item.get("album") or item, False, is_mp3, item.get("media_number") if is_multiple else None, progress, task_id, ind_cover=ind_cover, track_fmt=track_fmt)

    def download_release(self):
        """Download a single album using a 3-stage pipeline.

        Stage 1: album meta (inspect_album)
        Stage 2: track URL prefetch (track/getFileUrl) with rate-limiting
        Stage 3: file download & tagging
        """
        report, meta, dirn = self.inspect_album(self.item_id, announce=True, repair_db=self.verify_existing and not self.check_only)
        if report.complete or self.check_only:
            return report.to_dict()

        os.makedirs(dirn, exist_ok=True)
        self._download_cover_art(meta, dirn, "cover.jpg")
        self._download_booklet(meta, dirn)

        tracks = meta.get("tracks", {}).get("items", [])
        is_multiple = len({t.get("media_number", 1) for t in tracks}) > 1

        # Stage 2.
        self._prime_track_urls(tracks)
        for track in tracks:
            resolution = self._track_url_cache.get(f"resolved:{track.get('id')}:{int(self.quality)}")
            if resolution:
                track["_cached_track_resolution"] = resolution

        # Stage 3.
        stats = self._run_multithreaded_download(tracks, dirn, meta, is_multiple, ind_cover=False, track_fmt=self.track_format)

        quality_summary = summarize_quality_from_tracks(tracks)
        sidecar_payload = build_album_sidecar_payload(meta, dirn, self.folder_format, self.track_format, tracks=tracks, quality_summary=quality_summary)
        sidecar_path = write_sidecar(dirn, sidecar_payload)

        final_report, _, _ = self.inspect_album(self.item_id, base_path=self.path, announce=True, repair_db=False)
        if self.downloads_db:
            upsert_download_entry(
                self.downloads_db,
                self.item_id,
                {
                    "item_type": "album",
                    "album_id": str(self.item_id),
                    "local_path": dirn,
                    "expected_tracks": final_report.expected_count,
                    "matched_tracks": final_report.matched_count,
                    "integrity_status": "complete" if final_report.complete else "incomplete",
                    "folder_format": self.folder_format,
                    "track_format": self.track_format,
                    "source_quality": json.dumps(quality_summary.get("source_quality", {}), ensure_ascii=False),
                    "actual_quality": json.dumps(quality_summary.get("actual_quality", {}), ensure_ascii=False),
                    "bit_depth": quality_summary.get("actual_quality", {}).get("bit_depth"),
                    "sampling_rate": quality_summary.get("actual_quality", {}).get("sampling_rate"),
                    "sidecar_path": sidecar_path,
                },
            )
        console.print(f"[{C_MAIN}]📂 保存于: {os.path.abspath(dirn)}[/{C_MAIN}]")
        logger.info("Album download summary: %s", stats)
        return final_report.to_dict()

    def _build_folder_context_from_candidate(self, candidate):
        sample_rate = 44.1
        bit_depth = 16
        if candidate.audio_files:
            sample_path = os.path.join(candidate.album_dir, candidate.audio_files[0].rel_path)
            try:
                if sample_path.lower().endswith(".flac"):
                    parsed = FLAC(sample_path)
                    sample_rate = round((parsed.info.sample_rate or 44100) / 1000, 1)
                    bit_depth = parsed.info.bits_per_sample or 16
                else:
                    parsed = MP3(sample_path)
                    sample_rate = round((parsed.info.sample_rate or 44100) / 1000, 1)
                    bit_depth = 16
            except (MutagenError, OSError, ValueError, TypeError) as exc:
                logger.debug("Folder context fallback for %s: %s", sample_path, exc)
        return {
            "artist": candidate.guessed_artist or "Unknown",
            "album": candidate.guessed_album or os.path.basename(candidate.album_dir),
            "year": candidate.guessed_year or "0000",
            "format": "FLAC",
            "bit_depth": bit_depth,
            "sampling_rate": f"{sample_rate:g}",
        }

    def _build_track_context_from_path(self, file_path, fallback_index=0):
        context = {
            "artist": "Unknown",
            "tracktitle": os.path.splitext(os.path.basename(file_path))[0],
            "tracknumber": f"{fallback_index + 1:02d}",
            "bit_depth": 16,
            "sampling_rate": "44.1",
        }
        try:
            if file_path.lower().endswith(".flac"):
                audio = FLAC(file_path)
                context["tracktitle"] = (audio.get("TITLE") or [context["tracktitle"]])[0]
                context["artist"] = (audio.get("ARTIST") or [context["artist"]])[0]
                track_no = (audio.get("TRACKNUMBER") or [context["tracknumber"]])[0]
                context["tracknumber"] = f"{int(str(track_no).split('/')[0]):02d}"
                context["bit_depth"] = audio.info.bits_per_sample or 16
                context["sampling_rate"] = f"{((audio.info.sample_rate or 44100) / 1000):g}"
            else:
                audio = MP3(file_path)
                tags = getattr(audio, "tags", {}) or {}
                title = tags.get("TIT2")
                artist = tags.get("TPE1")
                track_no = tags.get("TRCK")
                if title and getattr(title, "text", None):
                    context["tracktitle"] = title.text[0]
                if artist and getattr(artist, "text", None):
                    context["artist"] = artist.text[0]
                if track_no and getattr(track_no, "text", None):
                    context["tracknumber"] = f"{int(str(track_no.text[0]).split('/')[0]):02d}"
                context["sampling_rate"] = f"{((audio.info.sample_rate or 44100) / 1000):g}"
        except Exception as exc:
            logger.debug("Track context fallback for %s: %s", file_path, exc)
        return context

    def plan_library_rename(self, base_dir, album_keys=None):
        plan = []
        candidates = discover_library_albums(base_dir)
        if album_keys:
            wanted = {str(k) for k in album_keys if k}
            candidates = [cand for cand in candidates if str(cand.album_key) in wanted]
        for candidate in candidates:
            sidecar = candidate.sidecar or load_sidecar(candidate.album_dir)
            folder_context = self._build_folder_context_from_candidate(candidate)
            if sidecar:
                q = (sidecar.get("quality") or {}).get("actual_quality") or {}
                folder_context.update({
                    "artist": sidecar.get("artist") or folder_context.get("artist"),
                    "album": sidecar.get("album_title") or folder_context.get("album"),
                    "year": str(sidecar.get("year") or folder_context.get("year") or "0000"),
                    "bit_depth": q.get("bit_depth") or folder_context.get("bit_depth"),
                    "sampling_rate": q.get("sampling_rate") or folder_context.get("sampling_rate"),
                })
            desired_album_name = sanitize_filepath(self.folder_format.format(**folder_context))
            desired_album_dir = os.path.join(os.path.dirname(candidate.album_dir), desired_album_name)
            if os.path.normpath(candidate.album_dir) != os.path.normpath(desired_album_dir):
                plan.append({
                    "src": candidate.album_dir,
                    "dst": desired_album_dir,
                    "kind": "album",
                    "confidence": candidate.confidence,
                    "reason": "folder_format",
                    "album_key": candidate.album_key,
                })
            audio_files = sorted(candidate.audio_files, key=lambda item: item.rel_path)
            sidecar_track_map = {}
            if sidecar:
                for track in sidecar.get("tracks") or []:
                    sidecar_track_map[(int(track.get("disc", 1) or 1), int(track.get("track_number", 0) or 0))] = track
            for index, file_info in enumerate(audio_files):
                src = os.path.join(candidate.album_dir, file_info.rel_path)
                disc_name = os.path.dirname(file_info.rel_path)
                context = self._build_track_context_from_path(src, fallback_index=index)
                sidecar_track = sidecar_track_map.get(file_info.key) if file_info.key else None
                if sidecar_track:
                    q = sidecar_track.get("actual_quality") or (sidecar.get("quality") or {}).get("actual_quality") or {}
                    context.update({
                        "artist": sidecar_track.get("artist") or context.get("artist"),
                        "tracktitle": sidecar_track.get("title") or context.get("tracktitle"),
                        "tracknumber": f"{int(sidecar_track.get('track_number', index + 1) or index + 1):02d}",
                        "bit_depth": q.get("bit_depth") or context.get("bit_depth"),
                        "sampling_rate": q.get("sampling_rate") or context.get("sampling_rate"),
                    })
                desired_file_name = sanitize_filename(self.track_format.format(**context)).strip() or os.path.basename(src)
                relative_parent = ""
                if disc_name and disc_name not in (".", os.curdir):
                    relative_parent = disc_name
                dst_root = desired_album_dir if os.path.normpath(candidate.album_dir) != os.path.normpath(desired_album_dir) else candidate.album_dir
                dst = os.path.join(dst_root, relative_parent, desired_file_name + file_info.extension)
                if os.path.normpath(src) != os.path.normpath(dst):
                    plan.append({
                        "src": src,
                        "dst": dst,
                        "kind": "track",
                        "confidence": "high" if file_info.key or any(file_info.tag_identity) else candidate.confidence,
                        "reason": "track_format",
                        "album_key": candidate.album_key,
                    })
            if os.path.normpath(candidate.album_dir) != os.path.normpath(desired_album_dir):
                for root, _, names in os.walk(candidate.album_dir):
                    rel_root = os.path.relpath(root, candidate.album_dir)
                    for name in names:
                        ext = os.path.splitext(name)[1].lower()
                        if ext not in SAFE_RENAME_METADATA_EXTENSIONS:
                            continue
                        src = os.path.join(root, name)
                        dst_root = desired_album_dir if rel_root in (".", os.curdir) else os.path.join(desired_album_dir, rel_root)
                        dst = os.path.join(dst_root, name)
                        if os.path.normpath(src) != os.path.normpath(dst):
                            plan.append({
                                "src": src,
                                "dst": dst,
                                "kind": "asset",
                                "confidence": candidate.confidence,
                                "reason": "album_move",
                                "album_key": candidate.album_key,
                            })
        unique_plan = []
        seen = set()
        for item in plan:
            key = (os.path.normpath(item["src"]), os.path.normpath(item["dst"]), item["kind"])
            if key in seen:
                continue
            seen.add(key)
            unique_plan.append(item)
        return unique_plan

    def apply_rename_plan(self, plan):
        normalized_plan = []
        destinations = {}
        sources = {os.path.normpath(item["src"]): item for item in plan}
        for item in plan:
            src = os.path.normpath(item["src"])
            dst = os.path.normpath(item["dst"])
            if src == dst:
                continue
            if dst in destinations and destinations[dst] != src:
                raise FileExistsError(f"重命名冲突：多个源指向同一目标 {dst}")
            if item.get("kind") != "album" and os.path.exists(dst) and dst not in sources:
                raise FileExistsError(f"目标已存在，停止避免覆盖: {dst}")
            destinations[dst] = src
            normalized_plan.append({**item, "src": src, "dst": dst})
        move_items = [entry for entry in normalized_plan if entry["kind"] in {"track", "asset"}]
        album_items = [entry for entry in normalized_plan if entry["kind"] == "album"]
        for item in sorted(move_items, key=lambda entry: len(entry["src"]), reverse=True):
            src = item["src"]
            dst = item["dst"]
            if not os.path.exists(src):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
        for item in sorted(album_items, key=lambda entry: len(entry["src"]), reverse=True):
            src = item["src"]
            if os.path.isdir(src):
                for root, dirs, _ in os.walk(src, topdown=False):
                    for dir_name in dirs:
                        full_dir = os.path.join(root, dir_name)
                        try:
                            os.rmdir(full_dir)
                        except OSError:
                            logger.debug("Album child directory not empty after move: %s", full_dir)
                try:
                    os.rmdir(src)
                except OSError:
                    logger.debug("Album source directory not empty after move: %s", src)

    def _run_multithreaded_download(self, tracks, dirn, meta, is_multiple, ind_cover, track_fmt):
        queue_items = list(tracks or [])
        max_attempts = max(1, self.max_retries + 1)
        failed_list = []
        stats = {"success": 0, "failed": 0, "skipped": 0, "invalid": 0}
        succeeded_ids = set()
        for attempt in range(max_attempts):
            failed_list = []
            total_items = len(queue_items)
            if total_items == 0:
                break
            progress = Progress(
                TextColumn("{task.description}", justify="left"),
                BarColumn(bar_width=15, style=C_BAR_BG, complete_style=C_MAIN, finished_style=C_OK),
                TextColumn(f"[{C_WARN}]{{task.percentage:>3.0f}}%[/{C_WARN}]"),
                DownloadColumn(binary_units=True),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=True,
            )
            with progress:
                overall_task_id = progress.add_task(f"[{C_MAIN}]总进度 ({total_items})[/{C_MAIN}]", filename="Batch", total=total_items)
                with ThreadPoolExecutor(max_workers=min(self.download_workers, max(1, total_items))) as executor:
                    futures = [executor.submit(self._process_single_track, item, idx + 1, total_items, meta, dirn, is_multiple, progress, overall_task_id, failed_list, ind_cover, track_fmt) for idx, item in enumerate(queue_items)]
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except (DownloadPipelineError, NonStreamable, requests.exceptions.RequestException, OSError, ValueError, TypeError, KeyError, MutagenError) as exc:
                            logger.warning("Unexpected worker failure during batch download: %s", exc, exc_info=True)
            current_ids = {str(item.get("id")) for item in queue_items if item.get("id") is not None}
            failed_ids = {str(entry["item"].get("id")) for entry in failed_list if entry["item"].get("id") is not None}
            succeeded_ids.update(current_ids - failed_ids)
            stats["failed"] = len(failed_ids)
            queue_items = [entry["item"] for entry in failed_list]
            if not failed_list:
                break
            if attempt < max_attempts - 1:
                time.sleep(2)
        stats["success"] = len(succeeded_ids)
        invalid_errors = [entry for entry in failed_list if "试听" in entry["error"] or "无效" in entry["error"]]
        hard_failures = [entry for entry in failed_list if entry not in invalid_errors]
        stats["invalid"] = len(invalid_errors)
        stats["failed"] = len(hard_failures)
        console.print(f"[{C_DIM}]结果统计: 成功 {stats['success']} / 失败 {stats['failed']} / 跳过 {stats['skipped']} / 无效 {stats['invalid']}[/{C_DIM}]")
        return stats

    def download_track(self):
        if self.check_only:
            console.print(f"[{C_WARN}]单曲目前无法做完整性校验，已跳过下载。[/]")
            return {"checked": False, "reason": "single_track_not_supported"}
        meta = self.client.get_track_meta(self.item_id)
        resolved = self._resolve_track_url_with_fallback(self.item_id, self.quality)
        parse = resolved["payload"]
        progress = Progress(
            TextColumn("{task.description}", justify="left"),
            BarColumn(bar_width=15, style=C_BAR_BG, complete_style=C_MAIN),
            TextColumn(f"[{C_WARN}]{{task.percentage:>3.0f}}%[/{C_WARN}]"),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        )
        with progress:
            track_num = meta.get("track_number", 0)
            disp_name = f"{track_num:02d}. {meta.get('title', 'Unknown')}"[:30]
            task_id = progress.add_task(description=f"[{C_MAIN}]{disp_name}[/{C_MAIN}]", filename=disp_name, start=False)
            meta["_requested_quality"] = resolved.get("requested_quality")
            meta["_source_quality"] = self._source_quality_from_track(meta)
            meta["_actual_quality"] = resolved.get("actual_quality") or {}
            is_mp3 = int((resolved.get("actual_quality") or {}).get("quality_code") or self.quality) == 5
            self._download_and_tag(self.path, 1, parse, meta, meta, True, is_mp3, None, progress, task_id, ind_cover=True, track_fmt=self.track_format)
        console.print(f"\n[{C_MAIN}]📂 保存于: {os.path.abspath(self.path)}[/{C_MAIN}]")
        return {"checked": False, "downloaded": True}

    def _build_final_track_path(self, root_dir: str, formatted_name: str, extension: str, uniqueness_key: str) -> str:
        sanitized_name = sanitize_filename(formatted_name).strip() or "untitled"
        candidate = os.path.join(root_dir, sanitized_name + extension)
        if len(candidate) <= MAX_PATH_LENGTH:
            return candidate
        digest = hashlib.sha1(uniqueness_key.encode("utf-8")).hexdigest()[:10]
        stem_budget = max(32, MAX_PATH_LENGTH - len(root_dir) - len(extension) - len(digest) - 3)
        shortened_stem = sanitized_name[:stem_budget].rstrip(" ._") or sanitized_name[:stem_budget] or "track"
        return os.path.join(root_dir, f"{shortened_stem}-{digest}{extension}")

    def _download_and_tag(self, root_dir, tmp_count, track_url_dict, track_metadata, album_or_track_metadata, is_track, is_mp3, multiple, progress, task_id, ind_cover, track_fmt):
        extension = ".mp3" if is_mp3 else ".flac"
        # Prefer proxy for download stage, but allow direct fallback.
        url = track_url_dict["url"]
        if multiple:
            root_dir = os.path.join(root_dir, f"Disc {multiple}")
        os.makedirs(root_dir, exist_ok=True)
        temp_file = os.path.join(root_dir, f".{tmp_count:02}.tmp")
        context = build_filename_context(track_metadata, track_url_dict)
        formatted_name = track_fmt.format(**context)
        uniqueness_key = f"{track_metadata.get('id', '')}:{formatted_name}:{extension}"
        final_file = self._build_final_track_path(root_dir, formatted_name, extension, uniqueness_key)
        track_metadata["_expected_filename"] = os.path.basename(final_file)
        base_album_dir = track_metadata.get("_manual_dir") or root_dir
        if multiple and track_metadata.get("_manual_dir"):
            base_album_dir = track_metadata.get("_manual_dir")
        track_metadata["_expected_rel_path"] = os.path.relpath(final_file, base_album_dir)
        if os.path.isfile(final_file):
            if os.path.getsize(final_file) >= 1024:
                try:
                    MP3(final_file) if is_mp3 else FLAC(final_file)
                    track_metadata["_download_status"] = "skipped"
                    progress.update(task_id, visible=False)
                    return
                except (MutagenError, OSError) as exc:
                    logger.warning("Existing file validation failed for %s, re-downloading: %s", final_file, exc)
                    os.remove(final_file)
            else:
                os.remove(final_file)
        retry_budget = {
            "network": max(1, self.max_retries),
            "proxy": max(1, min(3, self.max_retries)),
            "io": 1,
            "auth": 0,
            "copyright": 0,
            "generic": max(1, min(2, self.max_retries)),
        }
        attempts = {key: 0 for key in retry_budget}
        last_error = None

        def _backoff(n: int, base: float = 0.8, cap: float = 12.0) -> float:
            # Exponential backoff with jitter.
            return min(cap, base * (2 ** max(0, n - 1)) + random.random() * 0.5)

        # Download URL can be proxied; we support (proxy pool -> direct) fallback.
        direct_url = track_url_dict["url"]

        while True:
            proxy_host = self.proxy_pool.choose() if self.proxy_pool.proxies else None
            use_proxy = bool(proxy_host)
            if self.force_proxy and not proxy_host:
                # Force proxy but none healthy -> treat as failure.
                raise DownloadPipelineError("proxy", "代理池无健康节点（force-proxy 已开启）")
            if self.force_proxy:
                use_proxy = True
            attempt_url = f"{proxy_host}/proxy?url={requests.utils.quote(direct_url, safe='')}" if use_proxy and proxy_host else (direct_url if not use_proxy else format_proxy_url(direct_url))
            try:
                response = requests.get(attempt_url, stream=True, timeout=self.timeout)
                response.raise_for_status()
                total_length = int(response.headers.get("content-length", 0))
                progress.update(task_id, completed=0, total=total_length)
                progress.start_task(task_id)
                with open(temp_file, "wb") as file_obj:
                    for chunk in response.iter_content(chunk_size=32768):
                        if chunk:
                            file_obj.write(chunk)
                            progress.advance(task_id, len(chunk))
                if total_length and os.path.getsize(temp_file) != total_length:
                    raise DownloadPipelineError("network", f"文件大小不匹配: expected={total_length}, actual={os.path.getsize(temp_file)}")
                if use_proxy:
                    self.proxy_pool.report_success(proxy_host)
                break
            except Exception as exc:
                category = self._classify_retryable_error(exc)
                last_error = exc
                attempts[category] = attempts.get(category, 0) + 1
                if use_proxy:
                    self.proxy_pool.report_failure(proxy_host)
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                progress.update(task_id, completed=0)

                # If proxies keep failing, automatically try direct (unless force_proxy).
                if category == "proxy" and not self.force_proxy:
                    # One extra direct attempt beyond proxy budget.
                    if attempts[category] > retry_budget.get(category, 0):
                        try:
                            response = requests.get(direct_url, stream=True, timeout=self.timeout)
                            response.raise_for_status()
                            total_length = int(response.headers.get("content-length", 0))
                            progress.update(task_id, completed=0, total=total_length)
                            progress.start_task(task_id)
                            with open(temp_file, "wb") as file_obj:
                                for chunk in response.iter_content(chunk_size=32768):
                                    if chunk:
                                        file_obj.write(chunk)
                                        progress.advance(task_id, len(chunk))
                            if total_length and os.path.getsize(temp_file) != total_length:
                                raise DownloadPipelineError("network", f"文件大小不匹配: expected={total_length}, actual={os.path.getsize(temp_file)}")
                            break
                        except (DownloadPipelineError, requests.exceptions.RequestException, OSError) as direct_exc:
                            last_error = direct_exc
                            category = self._classify_retryable_error(direct_exc)
                            attempts[category] = attempts.get(category, 0) + 1
                            logger.warning("Direct download fallback failed for %s: %s", track_metadata.get("id"), direct_exc)

                if attempts[category] > retry_budget.get(category, 0):
                    hint = {
                        "network": "网络波动，建议稍后重试。",
                        "proxy": "代理异常：建议尝试 --direct 或调整代理池；现在会自动直连兜底。",
                        "auth": "认证/secret 失效，建议 qdp -r 或检查 token。",
                        "copyright": "资源受版权/地区限制，当前账号不可串流。",
                        "io": "本地 IO/权限异常，请检查目录权限与空间。",
                        "generic": "未知错误，请用 --debug 查看细节。",
                    }.get(category, "下载失败")
                    track_metadata["_download_status"] = "failed"
                    logger.warning(
                        "Track download exhausted retries for %s via %s (%s): %s",
                        track_metadata.get("id"),
                        attempt_url,
                        category,
                        last_error,
                    )
                    raise DownloadPipelineError(category, f"{category} 失败: {last_error}", hint=hint)

                time.sleep(_backoff(attempts[category]))
        try:
            if is_mp3:
                metadata.tag_mp3(temp_file, root_dir, final_file, track_metadata, album_or_track_metadata, is_track, em_image=False)
            else:
                metadata.tag_flac(temp_file, root_dir, final_file, track_metadata, album_or_track_metadata, is_track, em_image=False)
        except (MutagenError, OSError, ValueError) as exc:
            logger.warning("Tagging failed for %s: %s", final_file, exc)
        if os.path.exists(temp_file):
            os.replace(temp_file, final_file)
        track_metadata["_download_status"] = "downloaded"
        track_metadata["_final_path"] = final_file
        if ind_cover and not self.no_cover:
            try:
                img_url = album_or_track_metadata.get("image", {}).get("large") or track_metadata.get("album", {}).get("image", {}).get("large")
                if img_url:
                    track_img_path = final_file.rsplit(".", 1)[0] + ".jpg"
                    if not os.path.exists(track_img_path):
                        _get_extra_proxy(format_proxy_url(self._get_max_quality_url(img_url)), root_dir, os.path.basename(track_img_path))
            except (AttributeError, OSError, requests.exceptions.RequestException) as exc:
                logger.debug("Track cover download skipped for %s: %s", final_file, exc)

    def _print_check_summary(self, content_name, reports, content_type="collection"):
        total = len(reports)
        complete = sum(1 for report in reports if report.complete)
        incomplete = total - complete
        missing_tracks = sum(report.missing_count for report in reports)
        legacy_hits = sum(report.legacy_naming_hits for report in reports)
        stale_db = sum(1 for report in reports if report.db_stale)
        console.rule(f"[{C_MAIN}]校验摘要: {content_name} ({content_type})[/{C_MAIN}]")
        console.print(f"[{C_TEXT}]总专辑: {total} | 完整: {complete} | 不完整: {incomplete} | 缺失曲目: {missing_tracks} | 旧命名命中: {legacy_hits} | DB 陈旧: {stale_db}[/{C_TEXT}]")

    @staticmethod
    def _get_album_attr(meta, album_title, file_format, bit_depth, sampling_rate):
        return {
            "artist": meta["artist"]["name"],
            "album": album_title,
            "year": meta["release_date_original"].split("-")[0],
            "format": file_format,
            "bit_depth": bit_depth,
            "sampling_rate": sampling_rate,
        }

    def _get_format(self, item_dict, is_track_id=False, track_url_dict=None):
        quality_met = True
        if int(self.quality) == 5:
            return ("MP3", quality_met, None, None)
        track_dict = item_dict if is_track_id else item_dict["tracks"]["items"][0]
        try:
            resolved = track_url_dict or self._resolve_track_url_with_fallback(track_dict["id"], self.quality)
            new_track_dict = resolved.get("payload") if isinstance(resolved, dict) and resolved.get("payload") else resolved
            if int(self.quality) > 6 and new_track_dict.get("bit_depth") == 16:
                quality_met = False
            return ("FLAC", quality_met, new_track_dict.get("bit_depth"), new_track_dict.get("sampling_rate"))
        except (DownloadPipelineError, NonStreamable, requests.exceptions.RequestException, ValueError, TypeError, KeyError) as exc:
            logger.warning("Unable to resolve format for %s: %s", item_dict.get('id'), exc)
            return ("Unknown", quality_met, None, None)


def _get_extra_proxy(proxy_url, dirn, filename):
    extra_file = os.path.join(dirn, filename)
    if os.path.isfile(extra_file):
        return
    try:
        response = requests.get(proxy_url, timeout=10)
        response.raise_for_status()
        with open(extra_file, "wb") as file_obj:
            file_obj.write(response.content)
    except (requests.exceptions.RequestException, OSError) as exc:
        logger.warning("Extra asset download failed for %s: %s", extra_file, exc)
