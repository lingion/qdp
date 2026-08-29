"""Stale .tmp cleanup: partial downloads survive a crashed/killed process as
hidden .NN.PID.tmp files in album dirs. Normal flow already removes them
(exception path deletes, success path os.replace), so only orphans from dead
processes need sweeping. Contract:
- files matching .NN.PID.tmp whose PID is no longer alive get removed
- files whose PID is still alive are left alone (concurrent downloads)
- regular files and non-matching names are untouched
"""
import os
import tempfile
from pathlib import Path

import pytest

from qdp.downloader import Download, cleanup_stale_tmp_files

_SKIP = {"skip": True}


@pytest.fixture()
def dl():
    d = Download.__new__(Download)
    yield d


def _make_tmp(dir_path: str, name: str, size: int = 10) -> str:
    p = os.path.join(dir_path, name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    return p


def test_removes_tmp_of_dead_pid():
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_tmp(tmp, ".01.999999999.tmp")
        removed = cleanup_stale_tmp_files(tmp)
        assert p in removed
        assert not os.path.exists(p)


def test_keeps_tmp_of_live_pid():
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_tmp(tmp, f".01.{os.getpid()}.tmp")
        removed = cleanup_stale_tmp_files(tmp)
        assert p not in removed
        assert os.path.exists(p)


def test_ignores_regular_and_odd_names():
    with tempfile.TemporaryDirectory() as tmp:
        keep = [
            _make_tmp(tmp, "01. Song.flac"),
            _make_tmp(tmp, "cover.jpg"),
            _make_tmp(tmp, ".hidden.tmp"),
            _make_tmp(tmp, ".01.notapid.tmp"),
        ]
        removed = cleanup_stale_tmp_files(tmp)
        assert removed == []
        for p in keep:
            assert os.path.exists(p)


def test_recursive_sweep_from_root_folder(dl):
    with tempfile.TemporaryDirectory() as root:
        sub = os.path.join(root, "Artist - Album")
        os.makedirs(sub)
        p = _make_tmp(sub, ".03.999999998.tmp")
        removed = Download._sweep_stale_tmp(dl, root)
        assert p in removed
        assert not os.path.exists(p)


def test_sweep_returns_empty_on_missing_dir(dl):
    assert Download._sweep_stale_tmp(dl, "/nonexistent/xyz") == []
