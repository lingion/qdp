import configparser
import logging
import glob
import os
import sys

from qobuz_dl.bundle import Bundle
from qobuz_dl.commands import qobuz_dl_args
from qobuz_dl.core import QobuzDL
from qobuz_dl.utils import set_direct_mode 

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()
logging.basicConfig(level=logging.INFO, format="%(message)s")

if os.name == "nt": OS_CONFIG = os.environ.get("APPDATA")
else: OS_CONFIG = os.path.join(os.environ["HOME"], ".config")
CONFIG_PATH = os.path.join(OS_CONFIG, "qobuz-dl")
CONFIG_FILE = os.path.join(CONFIG_PATH, "config.ini")
QOBUZ_DB = os.path.join(CONFIG_PATH, "qobuz_dl.db")
ANDROID_APP_ID = "798273057"
ANDROID_SECRET = "abb21364945c0583309667d13ca3d93a"

# 莫兰迪色定义
C_TITLE = "#61afef"
C_OPT   = "#e5c07b"
C_HINT  = "#abb2bf"
C_INPUT = "#98c379"
C_BORDER= "#5c6370"

def _get_current_cwd_path(): return os.path.join(os.getcwd(), "Qobuz Downloads")

DEFAULT_SETTINGS = {
    "default_folder": _get_current_cwd_path(),
    "default_quality": "27", "default_limit": "20",
    "no_m3u": "false", "albums_only": "false", "no_fallback": "false",
    "og_cover": "false", "embed_art": "false", "no_cover": "false",
    "no_database": "false", "smart_discography": "false",
    # 强制默认格式包含采样率
    "folder_format": "{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]",
    "track_format": "{tracknumber}. {tracktitle} [{bit_depth}B-{sampling_rate}kHz]",
    "no_booklet": "false", "debug": "false", "proxies": ""
}

def _reset_config(config_file):
    console.clear()
    console.print(Panel.fit("[bold #61afef]Qobuz-DL 配置向导[/]", border_style=C_BORDER))
    config = configparser.ConfigParser()
    
    console.print(f"\n[{C_OPT}]登录方式:[/{C_OPT}]")
    console.print("[1] 邮箱/密码 (推荐! 自动生成永久 Android Token)")
    console.print("[2] Token (Telegram/Web)")
    auth_choice = console.input(f"[{C_HINT}]请选择 (默认 1): [/{C_HINT}]").strip()
    
    if auth_choice == "2":
        console.rule(f"[{C_TITLE}]Token 模式[/{C_TITLE}]")
        config["DEFAULT"]["use_token"] = "true"
        config["DEFAULT"]["email"] = ""
        config["DEFAULT"]["password"] = ""
        config["DEFAULT"]["user_id"] = console.input("User ID: ").strip()
        config["DEFAULT"]["user_auth_token"] = console.input("Token: ").strip()
        console.print(f"\n[{C_OPT}]密钥类型:[/{C_OPT}]")
        console.print("[1] 网页密钥 (自动抓取)")
        console.print("[2] 安卓密钥 (推荐)")
        key_choice = console.input(f"[{C_HINT}]请选择 (默认 1): [/{C_HINT}]").strip()
        if key_choice == "2":
            config["DEFAULT"]["app_id"] = ANDROID_APP_ID
            config["DEFAULT"]["secrets"] = ANDROID_SECRET
        else:
            try:
                bundle = Bundle()
                config["DEFAULT"]["app_id"] = str(bundle.get_app_id())
                config["DEFAULT"]["secrets"] = ",".join(bundle.get_secrets().values())
            except:
                config["DEFAULT"]["app_id"] = ANDROID_APP_ID
                config["DEFAULT"]["secrets"] = ANDROID_SECRET
    else:
        console.rule(f"[{C_TITLE}]邮箱登录[/{C_TITLE}]")
        config["DEFAULT"]["use_token"] = "false"
        config["DEFAULT"]["email"] = console.input("邮箱: ").strip()
        config["DEFAULT"]["password"] = console.input("密码: ").strip()
        config["DEFAULT"]["app_id"] = ANDROID_APP_ID
        config["DEFAULT"]["secrets"] = ANDROID_SECRET
        config["DEFAULT"]["user_id"] = ""
        config["DEFAULT"]["user_auth_token"] = ""
        
    console.rule(f"[{C_TITLE}]路径设置[/{C_TITLE}]")
    current_cwd = os.getcwd()
    console.print(f"[{C_HINT}]当前目录: {current_cwd}[/{C_HINT}]")
    folder_input = console.input(f"下载目录 [{C_HINT}]默认: 动态目录[/{C_HINT}]: ").strip()
    if not folder_input: config["DEFAULT"]["default_folder"] = "Qobuz Downloads"
    else:
        if os.path.isabs(folder_input): config["DEFAULT"]["default_folder"] = folder_input
        else: config["DEFAULT"]["default_folder"] = folder_input
        
    console.rule(f"[{C_TITLE}]画质[/{C_TITLE}]")
    console.print("5=MP3, 6=FLAC, 7=24/96, 27=Max")
    qual_in = console.input("画质代码 [27]: ").strip()
    config["DEFAULT"]["default_quality"] = qual_in if qual_in else DEFAULT_SETTINGS['default_quality']
    
    console.rule(f"[{C_TITLE}]代理池[/{C_TITLE}]")
    proxies_in = console.input("Cloudflare 域名 (逗号分隔，空则直连): ").strip()
    if proxies_in:
        proxy_list = []
        for p in proxies_in.split(','):
            p = p.strip()
            if p and not p.startswith("http"): p = "https://" + p
            if p: proxy_list.append(p)
        config["DEFAULT"]["proxies"] = ",".join(proxy_list)
    else: config["DEFAULT"]["proxies"] = ""
    
    console.rule(f"[{C_TITLE}]高级[/{C_TITLE}]")
    og_cover_in = console.input("下载原图(Max)封面? (y/N) [N]: ").strip().lower()
    config["DEFAULT"]["og_cover"] = "true" if og_cover_in == 'y' else "false"
    booklet_in = console.input("下载 PDF Booklet? (Y/n) [Y]: ").strip().lower()
    config["DEFAULT"]["no_booklet"] = "true" if booklet_in == 'n' else "false"
    debug_in = console.input("开启调试(Debug)? (y/N) [N]: ").strip().lower()
    config["DEFAULT"]["debug"] = "true" if debug_in == 'y' else "false"
    
    for k, v in DEFAULT_SETTINGS.items():
        if k not in config["DEFAULT"]: config["DEFAULT"][k] = v
    with open(config_file, "w") as configfile: config.write(configfile)
    console.print(f"\n[{C_INPUT}]配置已保存！[/{C_INPUT}]")

def _remove_leftovers(directory):
    directory = os.path.join(directory, "**", ".*.tmp")
    for i in glob.glob(directory, recursive=True):
        try: os.remove(i)
        except: pass

def _initial_checks():
    if not os.path.isdir(CONFIG_PATH) or not os.path.isfile(CONFIG_FILE):
        os.makedirs(CONFIG_PATH, exist_ok=True)
        _reset_config(CONFIG_FILE)

def main():
    _initial_checks()
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    try:
        d = config["DEFAULT"]
        secrets = [s for s in d["secrets"].split(",") if s]
        debug_mode = config.getboolean("DEFAULT", "debug", fallback=False)
        logging.basicConfig(level=logging.DEBUG if debug_mode else logging.INFO, format="%(message)s")
        if debug_mode: console.print("[bold yellow][DEBUG MODE][/]")
        args = qobuz_dl_args(d["default_quality"], d["default_limit"], d["default_folder"]).parse_args()
        
        if args.direct:
            set_direct_mode(True)
            console.print("[bold red]⚠ 已开启强制直连模式 (忽略代理池)[/]")

    except Exception:
        console.print("[bold red]配置文件损坏，正在重置...[/]")
        _reset_config(CONFIG_FILE)
        return

    if args.reset:
        _reset_config(CONFIG_FILE)
        return
    if args.purge:
        try: os.remove(QOBUZ_DB)
        except: pass
        return

    search_query = args.search or args.search_album or args.search_track or args.search_artist
    search_type = "album"
    if args.search_track: search_type = "track"
    if args.search_artist: search_type = "artist"

    if not args.urls and not search_query:
        console.print("[bold red]错误: 未提供 URL 或搜索关键词。[/]")
        return

    qobuz = QobuzDL(
        args.directory,
        args.quality,
        args.embed_art or config.getboolean("DEFAULT", "embed_art"),
        ignore_singles_eps=args.albums_only or config.getboolean("DEFAULT", "albums_only"),
        no_m3u_for_playlists=args.no_m3u or config.getboolean("DEFAULT", "no_m3u"),
        quality_fallback=not args.no_fallback, 
        cover_og_quality=args.og_cover or config.getboolean("DEFAULT", "og_cover"),
        no_cover=args.no_cover or config.getboolean("DEFAULT", "no_cover"),
        downloads_db=None if args.no_db else QOBUZ_DB,
        # 这里会优先使用 DEFAULT_SETTINGS 中的新格式
        folder_format=args.folder_format or d.get("folder_format", DEFAULT_SETTINGS["folder_format"]),
        track_format=args.track_format or d.get("track_format", DEFAULT_SETTINGS["track_format"]),
        smart_discography=args.smart_discography or config.getboolean("DEFAULT", "smart_discography"),
        no_booklet=config.getboolean("DEFAULT", "no_booklet", fallback=False)
    )

    try:
        qobuz.initialize_client(
            d["email"], d["password"], d["app_id"], secrets, 
            d["use_token"], d["user_id"], d["user_auth_token"]
        )
        if search_query:
            qobuz.run_search(search_query, search_type, args.limit)
        else:
            qobuz.download_list_of_urls(args.urls)
    except KeyboardInterrupt:
        console.print("\n[red]用户强制停止。[/]")
    finally:
        _remove_leftovers(qobuz.directory)

if __name__ == "__main__":
    sys.exit(main())