"""Pure data-transform helpers for the QDP web server.

This module contains stateless functions that reshape, normalize, or extract
information from API payloads and user-supplied data.  None of these
functions depend on the web server runtime (no config reads, no network
calls, no global mutable state) — they are safe to import and unit-test
in isolation.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _pick_image(image: object) -> str:
    if not isinstance(image, dict):
        return ""
    for key in ("large", "extralarge", "medium", "small", "thumbnail"):
        val = image.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _rewrite_image_url(url: str) -> str:
    """Rewrite external Qobuz CDN image URLs to go through local /api/cover proxy."""
    if not url or not isinstance(url, str):
        return url or ""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.endswith("qobuz.com") or host.endswith("qobuz-static.com"):
        return "/api/cover?url=" + urllib.parse.quote(url, safe="")
    return url


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
        "image": _rewrite_image_url(_pick_image(album.get("image") if isinstance(album, dict) else {}) or image_fallback),
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
