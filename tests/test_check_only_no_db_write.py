"""--check-only promises "只校验，不下载、不落盘" but the integrity check
path unconditionally upserts into the downloads DB. Contract: check-only
must not mutate the DB.

Covers both entry points that run checks:
- core.QobuzDL._check_collection_albums (playlist/artist/label batch check)
- downloader.inspect_album / inspect_album_integrity with repair_db=False
"""
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from qdp import integrity
from qdp.db import create_db
from qdp.downloader import Download
from qdp.integrity import inspect_album_integrity


def _empty_db(tmp: Path) -> str:
    db = str(tmp / "downloads.db")
    create_db(db)
    return db


def _meta() -> dict:
    return {
        "title": "T",
        "tracks": {"items": [{"id": 1, "title": "s", "track_number": 1}]},
        "image": {"large": "https://static.qobuz.com/img/cover/none_og.jpg"},
    }


@pytest.fixture()
def isolated_downloader():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        dl = Download.__new__(Download)
        dl.path = str(tmp_path)
        dl.downloads_db = None
        dl.track_format = "5"
        dl.folder_format = "{artist} - {album}"
        dl.client = mock.Mock()
        dl.client.api_call = mock.Mock(return_value={})
        yield dl, tmp_path


def test_inspect_album_integrity_does_not_write_db(isolated_downloader, tmp_path):
    db = _empty_db(tmp_path)
    with mock.patch.object(integrity, "upsert_download_entry") as upsert:
        inspect_album_integrity(
            album_id="42",
            album_dir=str(tmp_path / "no_such_dir"),
            meta=_meta(),
            current_track_format="5",
            downloads_db=db,
            repair_db=False,
            write_db=False,
        )
    upsert.assert_not_called()
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    assert count == 0


def test_inspect_album_integrity_still_writes_when_write_db_true(tmp_path):
    db = _empty_db(tmp_path)
    inspect_album_integrity(
        album_id="42",
        album_dir=str(tmp_path / "no_such_dir"),
        meta=_meta(),
        current_track_format="5",
        downloads_db=db,
        repair_db=False,
    )
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    assert count == 1


def test_downloader_check_only_gates_db_writes(isolated_downloader, tmp_path):
    dl, tmp = isolated_downloader
    dl.downloads_db = _empty_db(tmp)
    dl.check_only = True
    album_dir = tmp / "artist - T"
    album_dir.mkdir()
    with mock.patch.object(dl, "_get_album_meta_cached", return_value={**_meta(), "streamable": True}), \
         mock.patch.object(dl, "_cache_album_artifacts", return_value=str(album_dir)), \
         mock.patch.object(integrity, "upsert_download_entry") as upsert, \
         mock.patch.object(integrity, "handle_download_id", return_value=False):
        report, _, _ = dl.inspect_album("42", announce=False)
    assert report is not None
    upsert.assert_not_called()


def test_downloader_normal_mode_keeps_db_writes(isolated_downloader, tmp_path):
    dl, tmp = isolated_downloader
    dl.downloads_db = _empty_db(tmp)
    dl.check_only = False
    album_dir = tmp / "artist - T"
    album_dir.mkdir()
    with mock.patch.object(dl, "_get_album_meta_cached", return_value={**_meta(), "streamable": True}), \
         mock.patch.object(dl, "_cache_album_artifacts", return_value=str(album_dir)), \
         mock.patch.object(integrity, "upsert_download_entry") as upsert, \
         mock.patch.object(integrity, "handle_download_id", return_value=False):
        report, _, _ = dl.inspect_album("42", announce=False)
    assert report is not None
    upsert.assert_called_once()
