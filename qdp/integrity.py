import fnmatch
import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from mutagen.flac import FLAC
from mutagen.id3 import ID3NoHeaderError
from mutagen.mp3 import EasyMP3
from pathvalidate import sanitize_filename

from qdp.db import handle_download_id, remove_download_id, upsert_download_entry
from qdp.sidecar import load_sidecar

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = (".mp3", ".flac")
LEGACY_TRACK_FORMATS = (
    "{tracknumber}. {tracktitle}",
    "{artist} - {tracktitle}",
    "{tracknumber}. {artist} - {tracktitle}",
    "{artist} - {tracktitle} [{bit_depth}B-{sampling_rate}kHz]",
    "{tracknumber}. {artist} - {tracktitle} [{bit_depth}B-{sampling_rate}kHz]",
)


@dataclass
class ExpectedTrack:
    key: Tuple[int, int]
    label: str
    rel_path: str
    legacy_rel_paths: List[str] = field(default_factory=list)
    tag_identity: Tuple[str, str] = ("", "")


@dataclass
class AudioFileInfo:
    rel_path: str
    stem: str
    extension: str
    key: Optional[Tuple[int, int]] = None
    tag_identity: Tuple[str, str] = ("", "")


@dataclass
class LibraryAlbumCandidate:
    album_key: str
    album_dir: str
    audio_files: List[AudioFileInfo] = field(default_factory=list)
    root_audio_files: List[AudioFileInfo] = field(default_factory=list)
    cover_files: List[str] = field(default_factory=list)
    matched_db_ids: List[str] = field(default_factory=list)
    guessed_artist: str = ""
    guessed_album: str = ""
    guessed_year: str = ""
    disc_count: int = 1
    matched_tracks: int = 0
    expected_tracks: int = 0
    integrity_status: str = "unknown"
    confidence: str = "unknown"
    sidecar: Optional[Dict] = None

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["audio_files"] = [file_info.rel_path for file_info in self.audio_files]
        data["root_audio_files"] = [file_info.rel_path for file_info in self.root_audio_files]
        return data


@dataclass
class IntegrityReport:
    album_id: str
    album_title: str
    album_dir: str
    expected_count: int
    matched_count: int
    missing_count: int
    complete: bool
    db_hit: bool
    db_stale: bool
    db_repaired: bool
    expected_naming_hits: int
    legacy_naming_hits: int
    tag_match_hits: int
    missing_labels: List[str] = field(default_factory=list)
    missing_entries: List[Dict] = field(default_factory=list)
    matched_entries: List[Dict] = field(default_factory=list)
    has_cover: bool = False
    has_booklet: bool = False
    cover_issues: List[str] = field(default_factory=list)
    booklet_issues: List[str] = field(default_factory=list)
    cover_valid: bool = False
    cover_path: Optional[str] = None
    booklets: List[Dict] = field(default_factory=list)
    all_extras_valid: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BatchCheckReport:
    content_name: str
    content_type: str
    total: int
    complete: int
    incomplete: int
    missing_tracks: int
    legacy_hits: int
    stale_db: int
    missing_covers: int = 0
    missing_booklets: int = 0
    reports: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


def get_title(item_dict: dict) -> str:
    album_title = item_dict.get("title", "Unknown")
    version = item_dict.get("version")
    if version and version.lower() not in album_title.lower():
        album_title = f"{album_title} ({version})"
    return album_title


def make_track_key(track: dict) -> Tuple[int, int]:
    return (int(track.get("media_number", 1) or 1), int(track.get("track_number", 0) or 0))


def make_track_label(track: dict) -> str:
    disc, track_no = make_track_key(track)
    return f"Disc {disc:02d} Track {track_no:02d} - {track.get('title', 'Unknown')}"


def _normalize_text(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _safe_get(d: dict, *keys, default=None):
    curr = d
    for key in keys:
        try:
            curr = curr[key]
        except (KeyError, TypeError, IndexError):
            return default
    return curr


def build_filename_context(track: dict, track_url_dict: Optional[dict] = None) -> Dict[str, str]:
    sr = track.get("maximum_sampling_rate", 44.1)
    if track_url_dict and track_url_dict.get("sampling_rate"):
        sr = track_url_dict["sampling_rate"]
    if sr and sr > 1000:
        sr = sr / 1000
    sr_str = f"{sr:g}" if sr else "44.1"
    bd = track.get("maximum_bit_depth", 16)
    if track_url_dict and track_url_dict.get("bit_depth"):
        bd = track_url_dict["bit_depth"]
    artist = _safe_get(track, "performer", "name") or _safe_get(track, "artist", "name") or "Unknown"
    title = track.get("title", "Unknown")
    return {
        "artist": artist,
        "bit_depth": bd or 16,
        "sampling_rate": sr_str,
        "tracktitle": title,
        "tracknumber": f"{track.get('track_number', 0):02}",
    }


def _candidate_rel_paths(track: dict, current_track_format: str, is_multiple: bool, legacy_formats: Sequence[str]) -> Tuple[str, List[str]]:
    context = build_filename_context(track)

    def build_rel_path(template: str) -> str:
        stem = sanitize_filename(template.format(**context)).strip() or "untitled"
        if is_multiple:
            return os.path.join(f"Disc {int(track.get('media_number', 1) or 1)}", stem)
        return stem

    primary = build_rel_path(current_track_format)
    legacy_paths = []
    for template in legacy_formats:
        try:
            candidate = build_rel_path(template)
        except Exception:
            continue
        if candidate != primary and candidate not in legacy_paths:
            legacy_paths.append(candidate)
    return primary, legacy_paths


def build_expected_tracks(meta: dict, current_track_format: str, legacy_formats: Sequence[str] = LEGACY_TRACK_FORMATS, sidecar: Optional[Dict] = None) -> List[ExpectedTrack]:
    sidecar_tracks = list((sidecar or {}).get("tracks") or [])
    if sidecar_tracks:
        expected = []
        for track in sidecar_tracks:
            disc = int(track.get("disc", 1) or 1)
            track_no = int(track.get("track_number", 0) or 0)
            artist = track.get("artist") or _safe_get(meta, "artist", "name") or ""
            rel_path = track.get("expected_rel_path") or track.get("expected_filename") or ""
            rel_path = os.path.splitext(rel_path)[0] if rel_path else rel_path
            expected.append(
                ExpectedTrack(
                    key=(disc, track_no),
                    label=f"Disc {disc:02d} Track {track_no:02d} - {track.get('title', 'Unknown')}",
                    rel_path=rel_path,
                    legacy_rel_paths=[],
                    tag_identity=(_normalize_text(track.get("title")), _normalize_text(artist)),
                )
            )
        return expected
    tracks = meta.get("tracks", {}).get("items", [])
    is_multiple = len({int(t.get("media_number", 1) or 1) for t in tracks}) > 1
    expected = []
    for track in tracks:
        rel_path, legacy_rel_paths = _candidate_rel_paths(track, current_track_format, is_multiple, legacy_formats)
        artist = _safe_get(track, "performer", "name") or _safe_get(track, "artist", "name") or _safe_get(meta, "artist", "name") or ""
        expected.append(
            ExpectedTrack(
                key=make_track_key(track),
                label=make_track_label(track),
                rel_path=rel_path,
                legacy_rel_paths=legacy_rel_paths,
                tag_identity=(_normalize_text(track.get("title")), _normalize_text(artist)),
            )
        )
    return expected


def _read_audio_tags(file_path: str) -> Tuple[Optional[Tuple[int, int]], Tuple[str, str]]:
    try:
        if file_path.lower().endswith(".flac"):
            audio = FLAC(file_path)
            track_no = (audio.get("TRACKNUMBER") or [None])[0]
            disc_no = (audio.get("DISCNUMBER") or [1])[0]
            title = (audio.get("TITLE") or [""])[0]
            artist = (audio.get("ARTIST") or [""])[0]
        else:
            try:
                audio = EasyMP3(file_path)
            except ID3NoHeaderError:
                return None, ("", "")
            track_raw = (audio.get("tracknumber") or [None])[0]
            disc_raw = (audio.get("discnumber") or [1])[0]
            title = (audio.get("title") or [""])[0]
            artist = (audio.get("artist") or [""])[0]
            track_no = str(track_raw).split("/")[0] if track_raw else None
            disc_no = str(disc_raw).split("/")[0] if disc_raw else 1
        if track_no is None:
            key = None
        else:
            key = (int(disc_no or 1), int(str(track_no).split("/")[0]))
        return key, (_normalize_text(title), _normalize_text(artist))
    except Exception as exc:
        logger.debug("Unable to read tags from %s: %s", file_path, exc)
        return None, ("", "")


def scan_audio_files(base_dir: str) -> List[AudioFileInfo]:
    files: List[AudioFileInfo] = []
    if not os.path.isdir(base_dir):
        return files
    for root, _, names in os.walk(base_dir):
        for name in names:
            if not name.lower().endswith(AUDIO_EXTENSIONS):
                continue
            full_path = os.path.join(root, name)
            rel_file = os.path.relpath(full_path, base_dir)
            rel_stem = os.path.splitext(rel_file)[0]
            key, tag_identity = _read_audio_tags(full_path)
            files.append(
                AudioFileInfo(
                    rel_path=rel_file,
                    stem=rel_stem,
                    extension=os.path.splitext(name)[1].lower(),
                    key=key,
                    tag_identity=tag_identity,
                )
            )
    return files


# ── Cover art and booklet constants ──

COVER_FILENAMES = (
    "cover.jpg", "cover.jpeg", "cover.png",
    "folder.jpg", "folder.png",
    "artwork.jpg", "artwork.png",
    "front.jpg", "front.png",
)

BOOKLET_PATTERNS = ("Digital Booklet*.pdf", "booklet*.pdf")

MIN_FILE_SIZE = 1024


# ── Internal format helpers ──

def _validate_file_magic(file_path: str, expected_format: str) -> Optional[str]:
    """Validate file magic bytes. Returns an issue string or None if valid."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(8)
    except OSError as exc:
        return f"Cannot read file: {exc}"
    if len(header) < 4:
        return "File too short to read magic bytes"
    if expected_format == "jpeg":
        if not header[:3] == b"\xff\xd8\xff":
            return f"Invalid JPEG magic bytes: {header[:3]!r}"
    elif expected_format == "png":
        if not header[:4] == b"\x89PNG":
            return f"Invalid PNG magic bytes: {header[:4]!r}"
    elif expected_format == "pdf":
        if not header[:4] == b"%PDF":
            return f"Invalid PDF magic bytes: {header[:4]!r}"
    return None


def _validate_cover(album_dir: str) -> Tuple[bool, Optional[str], List[str]]:
    """Scan album_dir for cover art and validate it.

    Returns (cover_valid, cover_path, cover_issues).
    """
    issues: List[str] = []
    found_valid = False
    cover_path: Optional[str] = None

    for cover_name in COVER_FILENAMES:
        candidate_path = os.path.join(album_dir, cover_name)
        if not os.path.isfile(candidate_path):
            continue

        # Check file size
        try:
            file_size = os.path.getsize(candidate_path)
        except OSError as exc:
            issues.append(f"{cover_name}: cannot stat file: {exc}")
            continue

        if file_size < MIN_FILE_SIZE:
            issues.append(f"{cover_name}: file too small ({file_size} bytes, minimum {MIN_FILE_SIZE})")
            continue

        # Check magic bytes
        ext = os.path.splitext(cover_name)[1].lower()
        expected_fmt = "jpeg" if ext in (".jpg", ".jpeg") else "png"
        magic_issue = _validate_file_magic(candidate_path, expected_fmt)
        if magic_issue:
            issues.append(f"{cover_name}: {magic_issue}")
            continue

        if not found_valid:
            cover_path = cover_name
        found_valid = True

    if not found_valid and not issues:
        issues.append("No cover art file found")

    return found_valid, cover_path, issues


def _find_booklet_files(album_dir: str) -> List[str]:
    """Find PDF booklet files in album_dir using BOOKLET_PATTERNS.

    First matches against known booklet patterns, then falls back to any PDF.
    Returns sorted list of filenames.
    """
    if not os.path.isdir(album_dir):
        return []

    all_names = os.listdir(album_dir)

    # First pass: match against known booklet patterns
    booklet_names: List[str] = []
    for pattern in BOOKLET_PATTERNS:
        for name in all_names:
            if fnmatch.fnmatch(name, pattern) and name not in booklet_names:
                booklet_names.append(name)

    # If no pattern matches, fall back to any PDF in the directory
    if not booklet_names:
        booklet_names = [
            name for name in all_names
            if name.lower().endswith(".pdf")
        ]

    return sorted(booklet_names)


def _validate_booklet(album_dir: str) -> Tuple[bool, List[Dict], List[str]]:
    """Scan album_dir for PDF booklet files and validate them.

    Returns (has_valid_booklet, booklets_detail_list, booklet_issues).
    Each entry in booklets_detail_list has keys: path, valid, issues.
    """
    booklets: List[Dict] = []
    issues: List[str] = []

    if not os.path.isdir(album_dir):
        return False, [], ["Album directory does not exist"]

    pdf_files = _find_booklet_files(album_dir)

    if not pdf_files:
        return False, [], []

    for pdf_name in pdf_files:
        pdf_path = os.path.join(album_dir, pdf_name)
        booklet_issues: List[str] = []
        valid = True

        # Check file size
        try:
            file_size = os.path.getsize(pdf_path)
        except OSError as exc:
            booklet_issues.append(f"cannot stat file: {exc}")
            issues.append(f"{pdf_name}: cannot stat file: {exc}")
            booklets.append({"path": pdf_name, "valid": False, "issues": booklet_issues})
            continue

        if file_size < MIN_FILE_SIZE:
            booklet_issues.append(f"file too small ({file_size} bytes, minimum {MIN_FILE_SIZE})")
            issues.append(f"{pdf_name}: file too small ({file_size} bytes, minimum {MIN_FILE_SIZE})")
            booklets.append({"path": pdf_name, "valid": False, "issues": booklet_issues})
            continue

        # Check magic bytes
        magic_issue = _validate_file_magic(pdf_path, "pdf")
        if magic_issue:
            booklet_issues.append(magic_issue)
            issues.append(f"{pdf_name}: {magic_issue}")
            booklets.append({"path": pdf_name, "valid": False, "issues": booklet_issues})
            continue

        booklets.append({"path": pdf_name, "valid": True, "issues": []})

    found_valid = any(b["valid"] for b in booklets)
    return found_valid, booklets, issues


# ── Public validation utility ──

def validate_file_format(filepath, expected_type="auto"):
    """Validate that a file matches its expected format by checking magic bytes.

    Args:
        filepath: Path to the file.
        expected_type: "image", "pdf", or "auto" (detect from extension).

    Returns:
        (is_valid, reason) tuple - (True, "") if valid, (False, "reason string") if not.
    """
    if not os.path.isfile(filepath):
        return False, "file does not exist"

    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        return False, "file does not exist"

    if file_size < MIN_FILE_SIZE:
        return False, f"file too small: {file_size} bytes"

    ext = os.path.splitext(filepath)[1].lower()

    # Resolve auto-detection from extension
    if expected_type == "auto":
        if ext in (".jpg", ".jpeg", ".png"):
            expected_type = "image"
        elif ext == ".pdf":
            expected_type = "pdf"
        else:
            return False, f"unknown file type for extension: {ext}"

    # Read header bytes
    try:
        with open(filepath, "rb") as f:
            header = f.read(8)
    except OSError as exc:
        return False, f"cannot read file: {exc}"

    if expected_type == "image":
        is_jpeg = ext in (".jpg", ".jpeg")
        is_png = ext == ".png"

        if is_jpeg:
            if header[:3] != b"\xff\xd8\xff":
                return False, "invalid format: expected JPEG"
        elif is_png:
            if header[:8] != b"\x89PNG\r\n\x1a\n":
                return False, "invalid format: expected PNG"
        else:
            # Generic image check — accept either JPEG or PNG
            if not (header[:3] == b"\xff\xd8\xff" or header[:8] == b"\x89PNG\r\n\x1a\n"):
                return False, "invalid format: expected image (JPEG or PNG)"

    elif expected_type == "pdf":
        if header[:4] != b"%PDF":
            return False, "invalid format: expected PDF"
        # Verify %%EOF trailer within last 1024 bytes
        try:
            with open(filepath, "rb") as f:
                f.seek(max(0, file_size - 1024))
                tail = f.read(1024)
        except OSError:
            return False, "cannot read PDF trailer"
        if b"%%EOF" not in tail:
            return False, "invalid format: PDF trailer %%EOF not found"

    return True, ""


def inspect_album_integrity(
    album_id: str,
    album_dir: str,
    meta: dict,
    current_track_format: str,
    downloads_db: Optional[str] = None,
    repair_db: bool = False,
    legacy_formats: Sequence[str] = LEGACY_TRACK_FORMATS,
) -> IntegrityReport:
    sidecar = load_sidecar(album_dir)
    expected_tracks = build_expected_tracks(meta, current_track_format, legacy_formats=legacy_formats, sidecar=sidecar)
    files = scan_audio_files(album_dir)
    stem_map = {file_info.stem: file_info for file_info in files}
    key_map = {file_info.key: file_info for file_info in files if file_info.key is not None}
    identity_map = {file_info.tag_identity: file_info for file_info in files if any(file_info.tag_identity)}

    matched_entries = []
    missing_entries = []
    expected_naming_hits = 0
    legacy_naming_hits = 0
    tag_match_hits = 0

    for item in expected_tracks:
        matched_file = None
        match_mode = None

        if item.rel_path in stem_map:
            matched_file = stem_map[item.rel_path]
            match_mode = "expected"
            expected_naming_hits += 1
        else:
            for legacy_path in item.legacy_rel_paths:
                if legacy_path in stem_map:
                    matched_file = stem_map[legacy_path]
                    match_mode = "legacy"
                    legacy_naming_hits += 1
                    break

        if matched_file is None and item.key in key_map:
            matched_file = key_map[item.key]
            match_mode = "tags"
            tag_match_hits += 1

        if matched_file is None and item.tag_identity in identity_map and any(item.tag_identity):
            matched_file = identity_map[item.tag_identity]
            match_mode = "tags"
            tag_match_hits += 1

        if matched_file is None:
            missing_entries.append({"label": item.label, "key": item.key, "expected_rel_path": item.rel_path})
        else:
            matched_entries.append(
                {
                    "label": item.label,
                    "key": item.key,
                    "match_mode": match_mode,
                    "file": matched_file.rel_path,
                }
            )

    # ── Cover art validation ──
    cover_valid, cover_path, cover_issues = _validate_cover(album_dir)

    # ── Booklet validation ──
    booklet_found, booklets, booklet_issues = _validate_booklet(album_dir)

    # ── Completeness logic ──
    # An album is complete when:
    # 1. All expected tracks are matched, AND
    # 2. Cover art is present and valid (when meta has an image URL).
    #    If meta has no image URL, cover is not required for completeness.
    # Booklet is informational — not required for completeness.
    tracks_ok = bool(expected_tracks) and not missing_entries
    meta_has_image_url = bool(_safe_get(meta, "image", "large"))
    cover_required = meta_has_image_url
    complete = tracks_ok and (cover_valid or not cover_required)

    # ── All-extras-valid flag ──
    # True when cover is valid (or not required) and every found booklet is valid.
    all_extras_valid = (cover_valid or not cover_required) and all(b["valid"] for b in booklets)

    db_hit = bool(downloads_db and handle_download_id(downloads_db, album_id, add_id=False))
    db_stale = bool(db_hit and not complete)
    db_repaired = False
    if db_stale and repair_db and downloads_db:
        db_repaired = remove_download_id(downloads_db, album_id)
    if downloads_db:
        upsert_download_entry(
            downloads_db,
            album_id,
            {
                "item_type": "album",
                "album_id": str(album_id),
                "local_path": album_dir,
                "expected_tracks": len(expected_tracks),
                "matched_tracks": len(matched_entries),
                "last_checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "integrity_status": "complete" if complete else "incomplete",
                "folder_format": sidecar.get("folder_format") if sidecar else None,
                "track_format": sidecar.get("track_format") if sidecar else None,
                "source_quality": json.dumps((sidecar or {}).get("quality", {}).get("source_quality", {}), ensure_ascii=False) if sidecar else None,
                "actual_quality": json.dumps((sidecar or {}).get("quality", {}).get("actual_quality", {}), ensure_ascii=False) if sidecar else None,
                "bit_depth": ((sidecar or {}).get("quality", {}).get("actual_quality", {}) or {}).get("bit_depth"),
                "sampling_rate": ((sidecar or {}).get("quality", {}).get("actual_quality", {}) or {}).get("sampling_rate"),
                "sidecar_path": (sidecar or {}).get("sidecar_path"),
            },
        )

    return IntegrityReport(
        album_id=str(album_id),
        album_title=get_title(meta),
        album_dir=album_dir,
        expected_count=len(expected_tracks),
        matched_count=len(matched_entries),
        missing_count=len(missing_entries),
        complete=complete,
        db_hit=db_hit,
        db_stale=db_stale,
        db_repaired=db_repaired,
        expected_naming_hits=expected_naming_hits,
        legacy_naming_hits=legacy_naming_hits,
        tag_match_hits=tag_match_hits,
        missing_labels=[entry["label"] for entry in missing_entries],
        missing_entries=missing_entries,
        matched_entries=matched_entries,
        has_cover=cover_valid,
        has_booklet=booklet_found,
        cover_issues=cover_issues,
        booklet_issues=booklet_issues,
        cover_valid=cover_valid,
        cover_path=cover_path,
        booklets=booklets,
        all_extras_valid=all_extras_valid,
    )


def summarize_album_reports(content_name: str, content_type: str, reports: Iterable[IntegrityReport]) -> BatchCheckReport:
    report_list = list(reports)
    complete = sum(1 for report in report_list if report.complete)
    incomplete = len(report_list) - complete
    missing_tracks = sum(report.missing_count for report in report_list)
    legacy_hits = sum(report.legacy_naming_hits for report in report_list)
    stale_db = sum(1 for report in report_list if report.db_stale)
    missing_covers = sum(1 for report in report_list if not report.has_cover)
    missing_booklets = sum(1 for report in report_list if not report.has_booklet)
    return BatchCheckReport(
        content_name=content_name,
        content_type=content_type,
        total=len(report_list),
        complete=complete,
        incomplete=incomplete,
        missing_tracks=missing_tracks,
        legacy_hits=legacy_hits,
        stale_db=stale_db,
        missing_covers=missing_covers,
        missing_booklets=missing_booklets,
        reports=[report.to_dict() for report in report_list],
    )


def _safe_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _parse_year_from_path(path_value: str) -> str:
    match = re.search(r"(19|20)\d{2}", path_value or "")
    return match.group(0) if match else ""


def _split_album_dir(base_dir: str, rel_dir: str):
    normalized = rel_dir.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part and part not in (".",)]
    if parts and re.fullmatch(r"disc\s*\d+", parts[-1], flags=re.IGNORECASE):
        album_rel = os.path.join(*parts[:-1]) if len(parts) > 1 else "."
        return album_rel, parts[-1]
    return rel_dir, None


def _guess_album_identity(album_dir: str, files: Sequence[AudioFileInfo]) -> Tuple[str, str, str]:
    folder_name = os.path.basename(os.path.normpath(album_dir))
    year = _parse_year_from_path(folder_name)
    artist = ""
    album = folder_name
    if " - " in folder_name:
        artist, album = folder_name.split(" - ", 1)
    album = re.sub(r"\s*\((19|20)\d{2}\)", "", album).strip()
    guessed_artist = artist.strip()
    guessed_album = album.strip()
    for file_info in files:
        _, track_artist = file_info.tag_identity
        if track_artist and not guessed_artist:
            guessed_artist = " ".join(part.capitalize() for part in track_artist.split())
            break
    return guessed_artist, guessed_album, year


def discover_library_albums(base_dir: str, db_entries: Optional[Sequence[Dict]] = None) -> List[LibraryAlbumCandidate]:
    if not os.path.isdir(base_dir):
        return []
    db_entries = list(db_entries or [])
    db_path_index = {}
    for entry in db_entries:
        local_path = entry.get("local_path")
        if not local_path:
            continue
        db_path_index[os.path.normpath(local_path)] = entry
    grouped: Dict[str, Dict[str, object]] = {}
    for root, _, names in os.walk(base_dir):
        audio_names = [name for name in names if name.lower().endswith(AUDIO_EXTENSIONS)]
        cover_names = [name for name in names if name.lower().startswith("cover")]
        if not audio_names and not cover_names:
            continue
        rel_dir = os.path.relpath(root, base_dir)
        album_rel, disc_dir = _split_album_dir(base_dir, rel_dir)
        album_dir = os.path.normpath(os.path.join(base_dir, album_rel))
        group = grouped.setdefault(album_dir, {"audio": [], "root": [], "covers": [], "discs": set(), "album_dir": album_dir})
        if cover_names:
            group["covers"].extend([os.path.join(root, name) for name in cover_names])
        if disc_dir:
            group["discs"].add(disc_dir)
        files = scan_audio_files(root)
        for file_info in files:
            absolute_path = os.path.join(root, file_info.rel_path)
            absolute_rel = os.path.normpath(os.path.relpath(absolute_path, album_dir))
            normalized_info = AudioFileInfo(
                rel_path=absolute_rel,
                stem=os.path.splitext(absolute_rel)[0],
                extension=file_info.extension,
                key=file_info.key,
                tag_identity=file_info.tag_identity,
            )
            group["audio"].append(normalized_info)
            if not disc_dir:
                group["root"].append(normalized_info)
    candidates: List[LibraryAlbumCandidate] = []
    for album_dir, payload in sorted(grouped.items(), key=lambda item: item[0]):
        audio_files = sorted(payload["audio"], key=lambda item: item.rel_path)
        root_audio_files = sorted(payload["root"], key=lambda item: item.rel_path)
        sidecar = load_sidecar(album_dir)
        guessed_artist, guessed_album, guessed_year = _guess_album_identity(album_dir, audio_files)
        if sidecar:
            guessed_artist = sidecar.get("artist") or guessed_artist
            guessed_album = sidecar.get("album_title") or guessed_album
            guessed_year = str(sidecar.get("year") or guessed_year)
        db_entry = db_path_index.get(os.path.normpath(album_dir))
        matched_db_ids = [str(db_entry.get("id"))] if db_entry else []
        if sidecar and sidecar.get("album_id"):
            matched_db_ids = list(dict.fromkeys(matched_db_ids + [str(sidecar.get("album_id"))]))
        matched_tracks = len(audio_files)
        expected_tracks = db_entry.get("expected_tracks") if db_entry else 0
        if sidecar and sidecar.get("tracks"):
            expected_tracks = max(int(expected_tracks or 0), len(sidecar.get("tracks") or []))
        integrity_status = db_entry.get("integrity_status") if db_entry and db_entry.get("integrity_status") else "unknown"
        confidence = "medium"
        if matched_db_ids:
            confidence = "high"
        elif len(audio_files) == 1 and not payload["discs"]:
            confidence = "low"
        if expected_tracks and matched_tracks >= int(expected_tracks):
            integrity_status = "complete"
        elif expected_tracks:
            integrity_status = "incomplete"
        candidates.append(
            LibraryAlbumCandidate(
                album_key=hashlib.sha1(album_dir.encode("utf-8")).hexdigest()[:12],
                album_dir=album_dir,
                audio_files=audio_files,
                root_audio_files=root_audio_files,
                cover_files=sorted(payload["covers"]),
                matched_db_ids=matched_db_ids,
                guessed_artist=guessed_artist,
                guessed_album=guessed_album,
                guessed_year=guessed_year,
                disc_count=max(1, len(payload["discs"]) or 1),
                matched_tracks=matched_tracks,
                expected_tracks=int(expected_tracks or 0),
                integrity_status=integrity_status,
                confidence="high" if sidecar else confidence,
                sidecar=sidecar,
            )
        )
    return candidates
