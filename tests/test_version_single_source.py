"""Version single-source contract.

Three version strings had drifted historically (CLI 114.0.1, web 1.7.2,
frontend v2.14.12 in the cache-bust param). Contract now:
- The package version (qdp.__version__) is the only hand-edited version.
- qdp/web reads it from the package (fallback keeps module importable).
- The frontend cache-bust param must derive from WEB_PLAYER_VERSION —
  server.py rewrites __QDP_WEB_VERSION__ in index.html at serve time.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

import qdp
import qdp.web


def test_package_version_is_authoritative():
    assert re.match(r"\d+\.\d+\.\d+", qdp.__version__)


def test_web_module_reuses_package_version():
    assert qdp.web.__version__ == qdp.__version__


def test_server_serves_web_version_from_package():
    from qdp.web import server

    assert server.WEB_PLAYER_VERSION == qdp.__version__


def test_setup_py_version_matches_package():
    setup_text = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    match = re.search(r'version="([^"]+)"', setup_text)
    assert match and match.group(1) == qdp.__version__


def test_frontend_cache_bust_is_server_injected():
    """index.html ships a placeholder; server.py injects the real version so
    the HTML cache-bust param no longer hand-drifts."""
    html = (REPO_ROOT / "qdp/web/app/index.html").read_text(encoding="utf-8")
    assert "__QDP_WEB_VERSION__" in html
    server_py = (REPO_ROOT / "qdp/web/server.py").read_text(encoding="utf-8")
    assert "__QDP_WEB_VERSION__" in server_py
