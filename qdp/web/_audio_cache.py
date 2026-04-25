"""Background audio cache for seamless stream-while-caching fallback.

When the frontend requests a stream URL via ``/api/track-url``, the backend
starts a background thread to download the full track to disk.  If the
proxied stream drops mid-playback, the frontend can switch to
``/api/cached-track?id=…&fmt=…`` which serves the locally-cached file
with full Range-header support for seeking.

Cache layout::

    ~/.cache/qdp/audio/<track_id>_<fmt>.<ext>

Thread-safety is ensured via per-key locks and status tracking dicts.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Dict, Optional, Tuple

import requests

from qdp.web._helpers import _get_user_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_id(track_id: str) -> str:
    """Remove path traversal characters from track IDs."""
    return re.sub(r'[/\\.]', '_', str(track_id))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_AUDIO_CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache", "qdp", "audio")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

# key = "track_id:fmt" → {"status": "downloading"|"complete"|"failed", "path": str}
_CACHE_STATUS_LOCK = threading.Lock()
_CACHE_STATUS: Dict[str, dict] = {}

# key = "track_id:fmt" → active download thread
_ACTIVE_DOWNLOADS_LOCK = threading.Lock()
_ACTIVE_DOWNLOADS: Dict[str, threading.Thread] = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extension_from_content_type(content_type: str) -> str:
    ct = (content_type or "").lower().split(";")[0].strip()
    mapping = {
        "audio/flac": ".flac",
        "audio/x-flac": ".flac",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/aac": ".aac",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/ogg": ".ogg",
    }
    return mapping.get(ct, "")


def _extension_from_fmt(fmt: int) -> str:
    """Guess file extension from Qobuz format ID."""
    if int(fmt) == 5:
        return ".mp3"
    return ".flac"


def _cache_key(track_id: str, fmt: int) -> str:
    return f"{track_id}:{fmt}"


def _cache_path(track_id: str, fmt: int, ext: str) -> str:
    safe_id = _sanitize_id(track_id)
    filename = f"{safe_id}_{fmt}{ext}"
    return os.path.join(_AUDIO_CACHE_ROOT, filename)


def _temp_path(track_id: str, fmt: int, ext: str) -> str:
    safe_id = _sanitize_id(track_id)
    filename = f".{safe_id}_{fmt}{ext}.tmp"
    return os.path.join(_AUDIO_CACHE_ROOT, filename)


def _ensure_cache_dir() -> None:
    os.makedirs(_AUDIO_CACHE_ROOT, exist_ok=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_cached(track_id: str, fmt: int) -> Optional[str]:
    """Return the cached file path if the track is on disk, else *None*."""
    _ensure_cache_dir()
    for ext in (".flac", ".mp3", ".m4a", ".wav", ".ogg"):
        path = _cache_path(track_id, fmt, ext)
        if os.path.isfile(path):
            key = _cache_key(track_id, fmt)
            with _CACHE_STATUS_LOCK:
                _CACHE_STATUS[key] = {"status": "complete", "path": path}
            return path
    return None


def is_downloading(track_id: str, fmt: int) -> bool:
    key = _cache_key(track_id, fmt)
    with _CACHE_STATUS_LOCK:
        return _CACHE_STATUS.get(key, {}).get("status") == "downloading"


def start_background_download(track_id: str, fmt: int, cdn_url: str) -> None:
    """Kick off a background download if not already cached or downloading."""
    if is_cached(track_id, fmt):
        return

    key = _cache_key(track_id, fmt)

    with _CACHE_STATUS_LOCK:
        if _CACHE_STATUS.get(key, {}).get("status") == "downloading":
            return

    with _ACTIVE_DOWNLOADS_LOCK:
        if key in _ACTIVE_DOWNLOADS and _ACTIVE_DOWNLOADS[key].is_alive():
            return

    ext = _extension_from_fmt(fmt)
    _ensure_cache_dir()

    final_path = _cache_path(track_id, fmt, ext)
    tmp_path = _temp_path(track_id, fmt, ext)

    with _CACHE_STATUS_LOCK:
        _CACHE_STATUS[key] = {"status": "downloading", "path": final_path}

    thread = threading.Thread(
        target=_download_worker,
        args=(track_id, fmt, cdn_url, tmp_path, final_path, ext),
        daemon=True,
        name=f"audio-cache-{track_id}-{fmt}",
    )

    with _ACTIVE_DOWNLOADS_LOCK:
        _ACTIVE_DOWNLOADS[key] = thread

    try:
        thread.start()
    except RuntimeError:
        with _CACHE_STATUS_LOCK:
            _CACHE_STATUS.pop(key, None)
        with _ACTIVE_DOWNLOADS_LOCK:
            _ACTIVE_DOWNLOADS.pop(key, None)
        logger.warning("Failed to start download thread for %s", key)


def parse_range_header(range_header: str, file_size: int) -> Optional[Tuple[int, int]]:
    """Parse an HTTP ``Range`` header, returning ``(start, end)`` inclusive.

    Returns *None* if the header is malformed.
    """
    m = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not m:
        return None
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    if start > end:
        return None
    if start >= file_size:
        return None
    return start, end


def cleanup_stale_temp_files(max_age_seconds: int = 86400) -> int:
    """Remove orphaned ``.tmp`` files from the cache directory.

    Files whose *mtime* is older than *max_age_seconds* (default 24 h) are
    removed.  Returns the number of files removed.
    """
    _ensure_cache_dir()
    cutoff = time.time() - max_age_seconds
    removed = 0
    try:
        for entry in os.listdir(_AUDIO_CACHE_ROOT):
            if not entry.endswith(".tmp"):
                continue
            full = os.path.join(_AUDIO_CACHE_ROOT, entry)
            try:
                if os.path.isfile(full) and os.path.getmtime(full) < cutoff:
                    os.remove(full)
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed


# ---------------------------------------------------------------------------
# Cache stats & clearing
# ---------------------------------------------------------------------------


def get_cache_stats() -> dict:
    """Return audio cache directory size and file count."""
    size_bytes = 0
    file_count = 0
    if os.path.isdir(_AUDIO_CACHE_ROOT):
        try:
            for entry in os.listdir(_AUDIO_CACHE_ROOT):
                full = os.path.join(_AUDIO_CACHE_ROOT, entry)
                try:
                    if os.path.isfile(full):
                        size_bytes += os.path.getsize(full)
                        file_count += 1
                except OSError:
                    pass
        except OSError:
            pass
    return {"size_bytes": size_bytes, "file_count": file_count}


def clear_cache() -> int:
    """Delete all files in the audio cache directory and reset status.

    Returns total bytes freed.
    """
    freed = 0
    if os.path.isdir(_AUDIO_CACHE_ROOT):
        try:
            for entry in os.listdir(_AUDIO_CACHE_ROOT):
                full = os.path.join(_AUDIO_CACHE_ROOT, entry)
                try:
                    if os.path.isfile(full):
                        freed += os.path.getsize(full)
                        os.remove(full)
                except OSError:
                    pass
        except OSError:
            pass
    with _CACHE_STATUS_LOCK:
        _CACHE_STATUS.clear()
    return freed


# ---------------------------------------------------------------------------
# Download worker (runs in a daemon thread)
# ---------------------------------------------------------------------------


def _download_worker(
    track_id: str,
    fmt: int,
    cdn_url: str,
    tmp_path: str,
    final_path: str,
    ext: str,
) -> None:
    key = _cache_key(track_id, fmt)
    try:
        headers = {"User-Agent": _get_user_agent()}
        resp = requests.get(cdn_url, headers=headers, timeout=(10, 300), stream=True)
        resp.raise_for_status()

        # Detect actual content type and adjust extension if needed
        actual_ext = _extension_from_content_type(resp.headers.get("Content-Type", ""))
        if actual_ext and actual_ext != ext:
            final_path = _cache_path(track_id, fmt, actual_ext)
            tmp_path = _temp_path(track_id, fmt, actual_ext)

        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)

        # Atomic rename: temp → final
        os.replace(tmp_path, final_path)

        with _CACHE_STATUS_LOCK:
            _CACHE_STATUS[key] = {"status": "complete", "path": final_path}

        logger.info("Background cache complete: %s fmt=%s → %s", track_id, fmt, final_path)

    except Exception:
        logger.warning("Background cache failed for %s fmt=%s", track_id, fmt, exc_info=True)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass

        with _CACHE_STATUS_LOCK:
            _CACHE_STATUS[key] = {"status": "failed", "path": ""}

    finally:
        with _ACTIVE_DOWNLOADS_LOCK:
            _ACTIVE_DOWNLOADS.pop(key, None)


# ---------------------------------------------------------------------------
# Module-load cleanup
# ---------------------------------------------------------------------------

# Clean up stale temp files left over from interrupted downloads.
cleanup_stale_temp_files()
