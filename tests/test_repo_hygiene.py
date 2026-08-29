"""Repo hygiene contract: runtime cache artifacts must not be tracked by git.

qdp/cache/ is the web player's runtime audio cache (server.py _AUDIO_CACHE_ROOT).
Anything written at runtime inside the repo tree must be git-ignored.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def _path_is_ignored(rel_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel_path], cwd=REPO_ROOT
    )
    return result.returncode == 0


def test_no_tracked_files_under_runtime_cache_dir():
    tracked = [p for p in _git("ls-files", "qdp/cache/").splitlines() if p]
    assert tracked == [], f"runtime audio cache tracked by git: {tracked}"


def test_cache_dir_is_git_ignored():
    assert _path_is_ignored("qdp/cache/anything.mp3"), (
        "qdp/cache/ must be in .gitignore so runtime downloads never land in git"
    )


def test_gitignore_covers_part_and_tmp_artifacts():
    assert _path_is_ignored("qdp/cache/x_5.mp3.part")
    assert _path_is_ignored("qdp/cache/.01.123.tmp")


def test_discover_saved_page_assets_are_not_tracked():
    """The 12MB Discover - Qobuz_files saved-page asset dump (trackers, GTM,
    mixpanel bundles) is dead weight in git — only the HTML is referenced by
    server.py (_INDEX_FILE). The files themselves can stay on disk, but they
    must not be tracked."""
    tracked = [
        p
        for p in _git("ls-files", "qdp/web/static/").splitlines()
        if "Discover - Qobuz_files" in p
    ]
    assert tracked == [], f"saved-page asset dump tracked by git: {tracked[:5]}..."


def test_index_html_still_tracked():
    """server.py serves _INDEX_FILE from static root — the HTML itself must
    stay tracked or the web player breaks on fresh clone."""
    tracked = _git("ls-files", "qdp/web/static/Discover - Qobuz.html").splitlines()
    assert tracked == ["qdp/web/static/Discover - Qobuz.html"]
    assert os.path.isfile(REPO_ROOT / "qdp/web/static/Discover - Qobuz.html")
