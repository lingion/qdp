import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

# Sidecar file name:
# - new (preferred): <album_dir>/.qdp/album.json
# - legacy: <album_dir>/qdp_album.json
SIDECAR_FILENAME = "qdp_album.json"
SIDECAR_ALT_DIR = ".qdp"
SIDECAR_ALT_FILENAME = "album.json"

SIDECAR_VERSION = 2

logger = logging.getLogger(__name__)


def get_sidecar_path(album_dir: str, filename: str = SIDECAR_FILENAME, prefer_alt: bool = True) -> str:
    """Return preferred sidecar path.

    If prefer_alt=True, returns <album_dir>/.qdp/album.json.
    Otherwise returns legacy <album_dir>/qdp_album.json (or given filename).
    """
    if prefer_alt:
        return os.path.join(album_dir, SIDECAR_ALT_DIR, SIDECAR_ALT_FILENAME)
    return os.path.join(album_dir, filename)


def _candidate_sidecar_paths(album_dir: str, filename: str = SIDECAR_FILENAME) -> List[str]:
    return [
        get_sidecar_path(album_dir, filename=filename, prefer_alt=True),
        get_sidecar_path(album_dir, filename=filename, prefer_alt=False),
    ]


def load_sidecar(album_dir: str, filename: str = SIDECAR_FILENAME) -> Optional[Dict]:
    """Load sidecar json.

    Search order: new .qdp/album.json -> legacy qdp_album.json.
    """
    sidecar_path = None
    for candidate in _candidate_sidecar_paths(album_dir, filename=filename):
        if os.path.isfile(candidate):
            sidecar_path = candidate
            break
    if not sidecar_path:
        return None
    try:
        with open(sidecar_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data = upgrade_legacy_sidecar_payload(data)
            data.setdefault("sidecar_path", sidecar_path)
            return data
    except Exception as exc:
        logger.debug("Failed to load sidecar %s: %s", sidecar_path, exc)
    return None


def write_sidecar(album_dir: str, payload: Dict, filename: str = SIDECAR_FILENAME, prefer_alt: bool = True) -> str:
    """Write sidecar.

    prefer_alt=True writes to <album_dir>/.qdp/album.json.
    """
    os.makedirs(album_dir, exist_ok=True)
    sidecar_path = get_sidecar_path(album_dir, filename=filename, prefer_alt=prefer_alt)
    os.makedirs(os.path.dirname(sidecar_path), exist_ok=True)
    enriched = dict(payload or {})
    enriched.setdefault("schema", "qdp_album_sidecar")
    enriched.setdefault("sidecar_version", SIDECAR_VERSION)
    enriched.setdefault("updated_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    with open(sidecar_path, "w", encoding="utf-8") as handle:
        json.dump(enriched, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return sidecar_path


def _normalize_sampling_rate(sr):
    try:
        value = float(sr)
    except Exception:
        return None
    if value > 1000:
        value = value / 1000
    return value


def upgrade_legacy_sidecar_payload(payload: Dict) -> Dict:
    """Upgrade older sidecar payloads to the latest schema shape.

    This function is best-effort and avoids raising.
    """
    if not isinstance(payload, dict):
        return payload
    upgraded = dict(payload)
    upgraded.setdefault("schema", "qdp_album_sidecar")
    version = upgraded.get("sidecar_version")
    if version is None:
        upgraded["sidecar_version"] = 1
    # Ensure track fields.
    tracks = list(upgraded.get("tracks") or [])
    normalized_tracks = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        t = dict(track)
        # rename expected_filename->expected_stem for v2 target field name.
        expected_stem = t.get("expected_stem")
        if not expected_stem:
            expected_name = t.get("expected_filename") or t.get("expected_rel_path") or ""
            expected_stem = os.path.splitext(os.path.basename(expected_name))[0] if expected_name else ""
        t.setdefault("expected_stem", expected_stem)
        # maintain legacy fields
        t.setdefault("expected_filename", t.get("expected_filename") or "")
        t.setdefault("expected_rel_path", t.get("expected_rel_path") or "")
        t.setdefault("actual_file", t.get("actual_file") or t.get("_final_path") or "")
        # normalize quality info
        aq = dict(t.get("actual_quality") or {})
        if "sampling_rate" in aq:
            aq["sampling_rate"] = _normalize_sampling_rate(aq.get("sampling_rate"))
        t["actual_quality"] = aq
        normalized_tracks.append(t)
    upgraded["tracks"] = normalized_tracks
    # normalize summary quality
    quality = dict(upgraded.get("quality") or {})
    for key in ("source_quality", "actual_quality"):
        q = dict(quality.get(key) or {})
        if "sampling_rate" in q:
            q["sampling_rate"] = _normalize_sampling_rate(q.get("sampling_rate"))
        quality[key] = q
    upgraded["quality"] = quality
    return upgraded


def build_album_sidecar_payload(
    meta: Dict,
    album_dir: str,
    folder_format: str,
    track_format: str,
    tracks: Optional[Iterable[Dict]] = None,
    quality_summary: Optional[Dict] = None,
) -> Dict:
    """Build sidecar payload.

    Sidecar fields are intended for accurate offline library operations:
    - scan-library / verify: expected tracks list
    - rename-library: deterministic mapping disc/track -> title/artist/expected_stem

    Note: we keep some legacy keys (expected_filename/expected_rel_path) for backwards compatibility.
    """
    tracks = list(tracks or meta.get("tracks", {}).get("items", []))
    payload_tracks: List[Dict] = []
    for track in tracks:
        expected_rel_path = track.get("_expected_rel_path") or ""
        expected_filename = track.get("_expected_filename") or ""
        expected_name = expected_rel_path or expected_filename
        expected_stem = os.path.splitext(os.path.basename(expected_name))[0] if expected_name else ""
        aq = dict(track.get("_actual_quality") or {})
        if "sampling_rate" in aq:
            aq["sampling_rate"] = _normalize_sampling_rate(aq.get("sampling_rate"))
        payload_tracks.append(
            {
                "track_id": str(track.get("id")) if track.get("id") is not None else "",
                "disc": int(track.get("media_number", 1) or 1),
                "track_number": int(track.get("track_number", 0) or 0),
                "title": track.get("title") or "Unknown",
                "artist": (track.get("performer") or {}).get("name")
                or (track.get("artist") or {}).get("name")
                or (meta.get("artist") or {}).get("name")
                or "",
                "expected_stem": expected_stem,
                "expected_filename": expected_filename,
                "expected_rel_path": expected_rel_path,
                "actual_file": track.get("_final_path") or "",
                "bit_depth": aq.get("bit_depth"),
                "sampling_rate": aq.get("sampling_rate"),
                "source_quality": track.get("_source_quality") or {},
                "actual_quality": aq,
            }
        )
    qs = dict(quality_summary or {})
    if "actual_quality" in qs and isinstance(qs.get("actual_quality"), dict):
        aq = dict(qs.get("actual_quality") or {})
        if "sampling_rate" in aq:
            aq["sampling_rate"] = _normalize_sampling_rate(aq.get("sampling_rate"))
        qs["actual_quality"] = aq
    if "source_quality" in qs and isinstance(qs.get("source_quality"), dict):
        sq = dict(qs.get("source_quality") or {})
        if "sampling_rate" in sq:
            sq["sampling_rate"] = _normalize_sampling_rate(sq.get("sampling_rate"))
        qs["source_quality"] = sq

    return {
        "album_id": str(meta.get("id", "")),
        "album_title": meta.get("title") or "Unknown",
        "artist": (meta.get("artist") or {}).get("name") or "Unknown",
        "year": (meta.get("release_date_original") or "0000").split("-")[0],
        "quality": qs,
        "folder_format": folder_format,
        "track_format": track_format,
        "folder_format_version": 1,
        "track_format_version": 1,
        "album_dir": album_dir,
        "tracks": payload_tracks,
    }


def summarize_quality_from_tracks(tracks: Iterable[Dict]) -> Dict:
    tracks = list(tracks or [])
    if not tracks:
        return {}
    actual = [track.get("_actual_quality") or {} for track in tracks if track.get("_actual_quality")]
    source = [track.get("_source_quality") or {} for track in tracks if track.get("_source_quality")]
    requested = [track.get("_requested_quality") for track in tracks if track.get("_requested_quality") is not None]
    summary = {
        "requested_quality": max(requested) if requested else None,
        "source_quality": source[0] if source else {},
        "actual_quality": actual[0] if actual else {},
        "downloaded_tracks": sum(1 for track in tracks if track.get("_download_status") == "downloaded"),
        "skipped_tracks": sum(1 for track in tracks if track.get("_download_status") == "skipped"),
        "failed_tracks": sum(1 for track in tracks if track.get("_download_status") == "failed"),
    }
    summary["fallback_used"] = any((track.get("_requested_quality") is not None and (track.get("_actual_quality") or {}).get("quality_code") not in (None, track.get("_requested_quality"))) for track in tracks)
    return summary
