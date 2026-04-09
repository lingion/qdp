import configparser
import logging
import os
import sys

from rich.console import Console

from qdp.commands import build_parser
from qdp.config import CONFIG_FILE, DEFAULT_SETTINGS, QOBUZ_DB, initial_checks, load_config_defaults, remove_leftovers, run_config_wizard
from qdp.core import QobuzDL
from qdp.ui import run_ui
from qdp.utils import set_direct_mode

console = Console()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _to_int(val, fallback):
    try:
        return int(val)
    except Exception:
        return fallback


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # explicit shortcut: `qdp ui`
    if len(argv) == 1 and argv[0].strip().lower() == "ui":
        run_ui(argv_entry="qdp ui")
        return 0

    # no args -> modern UI by default
    if not argv:
        run_ui(argv_entry="qdp")
        return 0

    initial_checks(console=console, config_file=CONFIG_FILE)
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    defaults = load_config_defaults(CONFIG_FILE)

    config_debug_mode = str(defaults.get("debug", "false")).lower() == "true"

    cfg_workers = _to_int(defaults.get("workers", "4"), 4)
    cfg_prefetch = (defaults.get("prefetch_workers") or "").strip()
    cfg_prefetch_workers = _to_int(cfg_prefetch, None) if cfg_prefetch else None
    cfg_max_retries = _to_int(defaults.get("max_retries", "4"), 4)
    cfg_timeout = _to_int(defaults.get("timeout", "30"), 30)
    cfg_url_rate = _to_int(defaults.get("url_rate", "8"), 8)
    cfg_force_proxy = str(defaults.get("force_proxy", "false")).lower() == "true"

    try:
        args = build_parser(
            defaults.get("default_quality", DEFAULT_SETTINGS["default_quality"]),
            defaults.get("default_limit", DEFAULT_SETTINGS["default_limit"]),
            defaults.get("default_folder", DEFAULT_SETTINGS["default_folder"]),
            default_workers=cfg_workers,
            default_prefetch_workers=cfg_prefetch_workers,
            default_max_retries=cfg_max_retries,
            default_timeout=cfg_timeout,
            default_url_rate=cfg_url_rate,
            default_force_proxy=cfg_force_proxy,
        ).parse_args(argv)
    except SystemExit:
        # argparse already printed help
        return 2

    effective_debug = config_debug_mode or getattr(args, "debug", False)
    effective_verbose = getattr(args, "verbose", False) or effective_debug
    logging.getLogger().setLevel(logging.DEBUG if effective_debug else (logging.INFO if effective_verbose else logging.WARNING))

    if args.ui:
        run_ui(argv_entry="qdp --ui")
        return 0

    if getattr(args, "direct", False):
        set_direct_mode(True)
        console.print("[bold red]已开启强制直连模式（忽略代理池）[/]")
        if cfg_force_proxy:
            console.print("[bold yellow]注意：你在配置里开启了强制代理(force_proxy)，但当前 --direct 会禁用代理。[/]")

    if args.reset:
        run_config_wizard(console=console, config_file=CONFIG_FILE)
        return 0

    if args.purge:
        try:
            os.remove(QOBUZ_DB)
        except OSError as exc:
            logger.info("Skip purge, DB not removed: %s", exc)
        return 0

    search_query = args.search or args.search_album or args.search_track or args.search_artist
    search_type = "album"
    if args.search_track:
        search_type = "track"
    if args.search_artist:
        search_type = "artist"

    needs_network = not (args.scan_library or args.doctor or args.rename_library)

    # If user invoked `qdp` with only maintenance flags / empty, do not block.
    if not args.urls and not search_query and not (args.scan_library or args.doctor or args.rename_library):
        console.print("[yellow]未提供 URL/搜索关键词，进入 UI。[/]")
        run_ui(argv_entry="qdp")
        return 0

    qobuz = QobuzDL(
        args.directory,
        args.quality,
        args.embed_art or config.getboolean("DEFAULT", "embed_art", fallback=False),
        ignore_singles_eps=args.albums_only or config.getboolean("DEFAULT", "albums_only", fallback=False),
        no_m3u_for_playlists=args.no_m3u or config.getboolean("DEFAULT", "no_m3u", fallback=False),
        quality_fallback=not args.no_fallback,
        cover_og_quality=args.og_cover or config.getboolean("DEFAULT", "og_cover", fallback=False),
        no_cover=args.no_cover or config.getboolean("DEFAULT", "no_cover", fallback=False),
        downloads_db=None if args.no_db else QOBUZ_DB,
        folder_format=args.folder_format or defaults.get("folder_format", DEFAULT_SETTINGS["folder_format"]),
        track_format=args.track_format or defaults.get("track_format", DEFAULT_SETTINGS["track_format"]),
        smart_discography=args.smart_discography or config.getboolean("DEFAULT", "smart_discography", fallback=False),
        no_booklet=config.getboolean("DEFAULT", "no_booklet", fallback=False),
        verify_existing=args.verify or config.getboolean("DEFAULT", "verify_existing", fallback=False),
        check_only=args.check_only,
        workers=args.workers,
        prefetch_workers=args.prefetch_workers,
        max_retries=args.max_retries,
        timeout=args.timeout,
        url_rate=args.url_rate,
        force_proxy=args.force_proxy,
    )

    try:
        if needs_network:
            secrets = [s for s in (defaults.get("secrets") or "").split(",") if s]
            qobuz.initialize_client(
                defaults.get("email", ""),
                defaults.get("password", ""),
                defaults.get("app_id", ""),
                secrets,
                defaults.get("use_token", "false"),
                defaults.get("user_id", ""),
                defaults.get("user_auth_token", ""),
            )
        if args.check_only:
            console.print("[bold cyan]当前为 check-only 模式：只校验，不会下载任何音频/封面/booklet。[/]")

        if args.scan_library:
            qobuz.scan_library()
        elif args.doctor:
            qobuz.doctor(defaults)
        elif args.rename_library:
            qobuz.rename_library(dry_run=args.dry_run)
        elif search_query:
            qobuz.run_search(search_query, search_type, args.limit)
        else:
            qobuz.download_list_of_urls(args.urls)
    except KeyboardInterrupt:
        console.print("\n[red]用户强制停止。[/]")
    finally:
        try:
            remove_leftovers(qobuz.directory)
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
