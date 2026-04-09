from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    # Safety net: even if the installed console entry still points at qdp.__main__,
    # default behavior of `qdp` must remain the TUI/legacy CLI.
    from .cli import main as legacy_main

    argv = list(sys.argv[1:] if argv is None else argv)

    # explicit web launcher shortcut
    if argv and argv[0].strip().lower() in {"web", "webui"}:
        from .web.server import main as web_main
        return int(web_main(argv[1:]) or 0)

    return int(legacy_main(argv) or 0)


if __name__ == '__main__':
    raise SystemExit(main())
