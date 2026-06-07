import argparse
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


# Keys that are masked by default in `config list` / `config get`
_SECRET_KEYS = {"password", "secrets", "user_auth_token"}
# All valid config keys
_VALID_KEYS = {
    "email", "password", "app_id", "secrets", "use_token", "user_id",
    "user_auth_token", "default_folder", "default_quality", "default_limit",
    "folder_format", "track_format", "proxies", "embed_art", "no_cover",
    "og_cover", "albums_only", "no_m3u", "no_fallback", "smart_discography",
    "force_proxy", "workers", "prefetch_workers", "max_retries", "timeout",
    "url_rate", "debug",
}


def _handle_config_command(args):
    """Handle `qdp config set|get|list` — non-interactive config management."""
    cmd = getattr(args, "config_command", None)
    if not cmd:
        console.print("[yellow]用法: qdp config set key=val | qdp config get [key] | qdp config list[/]")
        return 0

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    # DEFAULT section always exists in ConfigParser, no need to add

    if cmd == "set":
        for pair in args.pairs:
            if "=" not in pair:
                console.print(f"[red]格式错误: {pair}（需要 key=value）[/]")
                return 1
            key, _, value = pair.partition("=")
            key = key.strip()
            value = value.strip()
            if key not in _VALID_KEYS:
                console.print(f"[yellow]警告: '{key}' 不是已知配置项，但仍写入。已知项: {', '.join(sorted(_VALID_KEYS))}[/]")
            config["DEFAULT"][key] = value
            display = "***" if key in _SECRET_KEYS else value
            console.print(f"  {key} = {display}")
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            config.write(f)
        console.print(f"[green]配置已保存到 {CONFIG_FILE}[/]")
        return 0

    elif cmd == "get":
        keys = args.keys if args.keys else list(config["DEFAULT"].keys())
        for key in keys:
            value = config["DEFAULT"].get(key, "")
            if not value:
                console.print(f"  {key} = [dim](未设置)[/]")
            elif key in _SECRET_KEYS:
                console.print(f"  {key} = {'*' * min(8, max(4, len(value)))}")
            else:
                console.print(f"  {key} = {value}")
        return 0

    elif cmd == "list":
        show_secrets = getattr(args, "show_secrets", False)
        for key in sorted(config["DEFAULT"].keys()):
            value = config["DEFAULT"][key]
            if key in _SECRET_KEYS and not show_secrets:
                value = "*" * min(8, max(4, len(value)))
            console.print(f"  {key} = {value}")
        return 0

    return 0


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

    # --help / --version must work on a completely fresh machine with no config
    if any(arg in ("-h", "--help") for arg in argv):
        build_parser(
            DEFAULT_SETTINGS["default_quality"],
            DEFAULT_SETTINGS["default_limit"],
            DEFAULT_SETTINGS["default_folder"],
        ).parse_args(argv)
        return 0

    if "--version" in argv:
        from qdp import __version__
        console.print(f"qdp {__version__}")
        return 0

    # `qdp config set|get|list` — non-interactive, works without any config
    if argv and argv[0] == "config":
        # Build a dedicated parser for the config subcommand
        config_parser = argparse.ArgumentParser(prog="qdp config")
        config_sub = config_parser.add_subparsers(dest="config_command")
        cs_set = config_sub.add_parser("set", help="设置配置项")
        cs_set.add_argument("pairs", nargs="+", metavar="KEY=VALUE")
        cs_get = config_sub.add_parser("get", help="查看配置项")
        cs_get.add_argument("keys", nargs="*", metavar="KEY")
        cs_list = config_sub.add_parser("list", help="列出所有配置项")
        cs_list.add_argument("--show-secrets", action="store_true")
        config_args = config_parser.parse_args(argv[1:])
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        return _handle_config_command(config_args)

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
