"""Local Web Player server for qdp.

Kept import-light so ``python -m qdp.web.server`` can execute without the
package pre-importing ``qdp.web.server`` and triggering runpy warnings.
"""

# Single version source: reuse the package version. The try/except keeps
# the module importable when qdp/__init__.py itself imports qdp.web.
try:
    from qdp import __version__
except Exception:  # pragma: no cover - circular-import safety net
    __version__ = "0.0.0"

__all__ = ["__version__", "start_web_player", "stop_web_player"]


def __getattr__(name: str):
    if name in {"start_web_player", "stop_web_player"}:
        from .server import start_web_player, stop_web_player

        exports = {
            "start_web_player": start_web_player,
            "stop_web_player": stop_web_player,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
