import configparser
import glob
import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional

from rich.console import Console
from rich.panel import Panel

from qdp.bundle import Bundle
from qdp.accounts import save_current_as_account

logger = logging.getLogger(__name__)

if os.name == "nt":
    OS_CONFIG = os.environ.get("APPDATA")
else:
    OS_CONFIG = os.path.join(os.environ["HOME"], ".config")

CONFIG_PATH = os.path.join(OS_CONFIG, "qobuz-dl")
CONFIG_FILE = os.path.join(CONFIG_PATH, "config.ini")
QOBUZ_DB = os.path.join(CONFIG_PATH, "qdp.db")

ANDROID_APP_ID = "798273057"
ANDROID_SECRET = "abb21364945c0583309667d13ca3d93a"

# 莫兰迪柔和配色
C_TITLE = "#8e9aaf"
C_OPT = "#d4b483"
C_HINT = "#9ca3af"
C_INPUT = "#8fb996"
C_BORDER = "#b0b7c3"


def _get_current_cwd_path():
    return os.path.join(os.getcwd(), "Qobuz Downloads")


DEFAULT_SETTINGS = {
    "default_folder": _get_current_cwd_path(),
    "default_quality": "27",
    "default_limit": "20",
    "no_m3u": "false",
    "albums_only": "false",
    "no_fallback": "false",
    "og_cover": "false",
    "embed_art": "false",
    "no_cover": "false",
    "no_database": "false",
    "smart_discography": "false",
    "verify_existing": "false",
    "folder_format": "{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]",
    "track_format": "{tracknumber}. {tracktitle} [{bit_depth}B-{sampling_rate}kHz]",
    "no_booklet": "false",
    "debug": "false",
    "proxies": "",
    # download/pipeline defaults
    "workers": "4",
    "prefetch_workers": "",
    "max_retries": "4",
    "timeout": "30",
    "url_rate": "8",
    "force_proxy": "false",
    # account meta
    "region": "--",
    "expiry_date": "",
    "label": "",
}


@dataclass
class ConfigPaths:
    config_path: str = CONFIG_PATH
    config_file: str = CONFIG_FILE
    db_path: str = QOBUZ_DB


def ensure_config_dir(paths: ConfigPaths = ConfigPaths()):
    os.makedirs(paths.config_path, exist_ok=True)


def load_config(config_file: str = CONFIG_FILE) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(config_file)
    return config


def load_config_defaults(config_file: str = CONFIG_FILE) -> Dict[str, str]:
    config = load_config(config_file)
    defaults = dict(DEFAULT_SETTINGS)
    if config.has_section("DEFAULT") or "DEFAULT" in config:
        defaults.update(dict(config["DEFAULT"]))
    return defaults


def save_config(config: configparser.ConfigParser, config_file: str = CONFIG_FILE):
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, "w") as fp:
        config.write(fp)


def _prompt_with_default(console: Console, label, default_value, secret=False):
    shown = default_value if default_value not in (None, "") else ""
    if secret and shown:
        masked = "*" * min(max(len(str(shown)), 8), 12)
        suffix = f" [{masked}]"
    else:
        suffix = f" [{shown}]" if shown else ""
    prompt = f"{label}{suffix}: "
    value = console.input(prompt).strip()
    return value if value else (default_value or "")


def _prompt_template(console: Console, label, default_value, templates):
    value = _prompt_with_default(console, label, default_value)
    normalized = value.strip()
    if normalized in templates:
        return templates[normalized]
    return value


def _prompt_yes_no(console: Console, label, default_bool=False):
    suffix = "Y/n" if default_bool else "y/N"
    default_hint = "Y" if default_bool else "N"
    raw = console.input(f"{label}? ({suffix}) [{default_hint}]: ").strip().lower()
    if not raw:
        return default_bool
    return raw in ("y", "yes", "1", "true")


def _mask_value(value):
    if not value:
        return "未配置"
    value = str(value)
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "***" + value[-2:]


def build_config_preview(config_defaults: Dict[str, str]) -> str:
    lines = [
        f"登录方式: {'Token' if config_defaults.get('use_token') == 'true' else '邮箱/密码'}",
        f"邮箱: {_mask_value(config_defaults.get('email')) if config_defaults.get('use_token') != 'true' else '未使用'}",
        f"密码: {_mask_value(config_defaults.get('password')) if config_defaults.get('use_token') != 'true' else '未使用'}",
        f"User ID: {_mask_value(config_defaults.get('user_id'))}",
        f"Token: {_mask_value(config_defaults.get('user_auth_token'))}",
        f"App ID: {_mask_value(config_defaults.get('app_id'))}",
        f"Secrets: {'已配置' if config_defaults.get('secrets') else '未配置'}",
        f"下载目录: {config_defaults.get('default_folder')}",
        f"专辑命名: {config_defaults.get('folder_format')}",
        f"曲目命名: {config_defaults.get('track_format')}",
        f"默认画质: {config_defaults.get('default_quality')}",
        f"搜索每页数量: {config_defaults.get('default_limit')}",
        f"workers: {config_defaults.get('workers')} | prefetch_workers: {config_defaults.get('prefetch_workers') or '跟随 workers'}",
        f"url_rate: {config_defaults.get('url_rate')} | timeout: {config_defaults.get('timeout')} | max_retries: {config_defaults.get('max_retries')}",
        f"force_proxy: {config_defaults.get('force_proxy')}",
        f"region: {config_defaults.get('region', '--')} | expiry: {config_defaults.get('expiry_date', '') or '未记录'} | label: {config_defaults.get('label', '') or '未记录'}",
        f"代理池: {_mask_value(config_defaults.get('proxies')) if config_defaults.get('proxies') else '未配置'}",
        f"原图封面: {config_defaults.get('og_cover')}",
        f"下载 booklet: {'false' if config_defaults.get('no_booklet') == 'true' else 'true'}",
        f"默认完整性修复: {config_defaults.get('verify_existing')}",
        f"默认嵌入封面: {config_defaults.get('embed_art')}",
        f"智能艺人筛选: {config_defaults.get('smart_discography')}",
        f"Debug: {config_defaults.get('debug')}",
    ]
    return "\n".join(lines)


def confirm_config_preview(console: Console, config: configparser.ConfigParser) -> str:
    while True:
        console.print(Panel.fit(build_config_preview(dict(config['DEFAULT'])), title='配置预览', border_style=C_BORDER))
        console.print('[1] 确认保存  [2] 返回修改  [0] 取消')
        choice = console.input('请选择: ').strip()
        if choice in {'1', '2', '0'}:
            return choice
        console.print('[bold red]请输入 1 / 2 / 0[/]')


def collect_config(console: Console, previous: Dict[str, str]) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config['DEFAULT'] = {}
    use_token_default = previous.get('use_token', 'false') == 'true'
    auth_default = '2' if use_token_default else '1'
    console.print(f"\n[{C_OPT}]登录方式:[/{C_OPT}]")
    console.print('[1] 邮箱/密码 (推荐! 自动生成永久 Android Token)')
    console.print('[2] Token (Telegram/Web)')
    auth_choice = _prompt_with_default(console, '请选择', auth_default)
    if auth_choice == '2':
        console.rule(f"[{C_TITLE}]Token 模式[/{C_TITLE}]")
        config['DEFAULT']['use_token'] = 'true'
        config['DEFAULT']['email'] = ''
        config['DEFAULT']['password'] = ''
        config['DEFAULT']['user_id'] = _prompt_with_default(console, 'User ID', previous.get('user_id', ''))
        config['DEFAULT']['user_auth_token'] = _prompt_with_default(console, 'Token', previous.get('user_auth_token', ''), secret=True)
        config['DEFAULT']['region'] = _prompt_with_default(console, '地区/区域(例如 US/JP)', previous.get('region', '--'))
        config['DEFAULT']['expiry_date'] = _prompt_with_default(console, '到期日期(YYYY-MM-DD，可空)', previous.get('expiry_date', ''))
        console.print(f"\n[{C_OPT}]密钥类型:[/{C_OPT}]")
        console.print('[1] 网页密钥 (自动抓取)')
        console.print('[2] 安卓密钥 (推荐)')
        secret_default = '2' if previous.get('app_id') == ANDROID_APP_ID else '1'
        key_choice = _prompt_with_default(console, '请选择', secret_default)
        if key_choice == '2':
            config['DEFAULT']['app_id'] = ANDROID_APP_ID
            config['DEFAULT']['secrets'] = ANDROID_SECRET
        else:
            try:
                bundle = Bundle()
                config['DEFAULT']['app_id'] = str(bundle.get_app_id())
                config['DEFAULT']['secrets'] = ','.join(bundle.get_secrets().values())
            except Exception as exc:
                logger.warning('Bundle bootstrap failed, fallback to Android secret: %s', exc)
                config['DEFAULT']['app_id'] = ANDROID_APP_ID
                config['DEFAULT']['secrets'] = ANDROID_SECRET
        config['DEFAULT']['label'] = previous.get('label', '')
    else:
        console.rule(f"[{C_TITLE}]邮箱登录[/{C_TITLE}]")
        config['DEFAULT']['use_token'] = 'false'
        config['DEFAULT']['email'] = _prompt_with_default(console, '邮箱', previous.get('email', ''))
        config['DEFAULT']['password'] = _prompt_with_default(console, '密码', previous.get('password', ''), secret=True)
        config['DEFAULT']['app_id'] = previous.get('app_id', ANDROID_APP_ID) or ANDROID_APP_ID
        config['DEFAULT']['secrets'] = previous.get('secrets', ANDROID_SECRET) or ANDROID_SECRET
        config['DEFAULT']['user_id'] = ''
        config['DEFAULT']['user_auth_token'] = ''
        config['DEFAULT']['region'] = _prompt_with_default(console, '地区/区域(例如 US/JP)', previous.get('region', '--'))
        config['DEFAULT']['expiry_date'] = _prompt_with_default(console, '到期日期(YYYY-MM-DD，可空)', previous.get('expiry_date', ''))
        config['DEFAULT']['label'] = previous.get('label', '')

    console.rule(f"[{C_TITLE}]路径与命名[/{C_TITLE}]")
    console.print(f"[{C_HINT}]当前目录: {os.getcwd()}[/{C_HINT}]")
    config['DEFAULT']['default_folder'] = _prompt_with_default(console, '下载目录', previous.get('default_folder', 'Qobuz Downloads'))
    folder_templates = {'1': '{artist} - {album} ({year})', '2': '{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]', '3': '{year} - {album}'}
    config['DEFAULT']['folder_format'] = _prompt_template(console, '专辑文件夹命名规则', previous.get('folder_format', DEFAULT_SETTINGS['folder_format']), folder_templates)
    track_templates = {'1': '{tracknumber}. {tracktitle}', '2': '{artist} - {tracktitle}', '3': '{tracknumber}. {artist} - {tracktitle} [{bit_depth}B-{sampling_rate}kHz]'}
    config['DEFAULT']['track_format'] = _prompt_template(console, '音频文件命名规则', previous.get('track_format', DEFAULT_SETTINGS['track_format']), track_templates)

    console.rule(f"[{C_TITLE}]画质与搜索[/{C_TITLE}]")
    console.print('5=MP3, 6=FLAC, 7=24/96, 27=Max')
    config['DEFAULT']['default_quality'] = _prompt_with_default(console, '默认画质代码', previous.get('default_quality', DEFAULT_SETTINGS['default_quality']))
    config['DEFAULT']['default_limit'] = _prompt_with_default(console, '搜索结果每页数量', previous.get('default_limit', DEFAULT_SETTINGS['default_limit']))

    console.rule(f"[{C_TITLE}]代理池[/{C_TITLE}]")
    proxies_in = _prompt_with_default(console, 'Cloudflare 域名 (逗号分隔，空则直连)', previous.get('proxies', ''))
    if proxies_in:
        proxy_list = []
        for proxy in proxies_in.split(','):
            proxy = proxy.strip()
            if proxy and not proxy.startswith('http'):
                proxy = 'https://' + proxy
            if proxy:
                proxy_list.append(proxy)
        config['DEFAULT']['proxies'] = ','.join(proxy_list)
    else:
        config['DEFAULT']['proxies'] = ''

    console.rule(f"[{C_TITLE}]下载与稳定性[/{C_TITLE}]")
    console.print(f"[{C_HINT}]线路策略: 优先代理（健康度排序），失败后自动直连兜底（除非强制代理）。[/{C_HINT}]")
    config['DEFAULT']['workers'] = _prompt_with_default(console, '默认下载并发 workers', previous.get('workers', DEFAULT_SETTINGS['workers']))
    config['DEFAULT']['prefetch_workers'] = _prompt_with_default(console, '默认 URL 预热并发 prefetch_workers(空=跟随 workers)', previous.get('prefetch_workers', DEFAULT_SETTINGS['prefetch_workers']))
    config['DEFAULT']['url_rate'] = _prompt_with_default(console, 'track/getFileUrl 限速 url_rate(每秒)', previous.get('url_rate', DEFAULT_SETTINGS['url_rate']))
    config['DEFAULT']['timeout'] = _prompt_with_default(console, '单次请求超时 timeout(秒)', previous.get('timeout', DEFAULT_SETTINGS['timeout']))
    config['DEFAULT']['max_retries'] = _prompt_with_default(console, '下载最大重试 max_retries', previous.get('max_retries', DEFAULT_SETTINGS['max_retries']))
    config['DEFAULT']['force_proxy'] = 'true' if _prompt_yes_no(console, '强制只走代理(代理全挂也不直连)', str(previous.get('force_proxy', 'false')).lower() == 'true') else 'false'

    console.rule(f"[{C_TITLE}]高级[/{C_TITLE}]")
    config['DEFAULT']['og_cover'] = 'true' if _prompt_yes_no(console, '下载原图(Max)封面', previous.get('og_cover', 'false') == 'true') else 'false'
    config['DEFAULT']['no_booklet'] = 'false' if _prompt_yes_no(console, '下载 PDF Booklet', previous.get('no_booklet', 'false') != 'true') else 'true'
    config['DEFAULT']['verify_existing'] = 'true' if _prompt_yes_no(console, '默认启用专辑完整性校验/修复', previous.get('verify_existing', 'false') == 'true') else 'false'
    config['DEFAULT']['embed_art'] = 'true' if _prompt_yes_no(console, '默认嵌入封面到音频文件', previous.get('embed_art', 'false') == 'true') else 'false'
    config['DEFAULT']['smart_discography'] = 'true' if _prompt_yes_no(console, '默认启用艺人智能筛选', previous.get('smart_discography', 'false') == 'true') else 'false'
    config['DEFAULT']['debug'] = 'true' if _prompt_yes_no(console, '开启调试(Debug)', previous.get('debug', 'false') == 'true') else 'false'

    for key, value in DEFAULT_SETTINGS.items():
        if key not in config['DEFAULT']:
            config['DEFAULT'][key] = previous.get(key, value)
    return config


def run_config_wizard(console: Optional[Console] = None, config_file: str = CONFIG_FILE):
    console = console or Console()
    console.clear()
    console.print(Panel.fit('[bold #61afef]qdp 配置向导[/]', border_style=C_BORDER))
    existing = configparser.ConfigParser()
    existing.read(config_file)
    previous = dict(DEFAULT_SETTINGS)
    if existing.has_section('DEFAULT') or 'DEFAULT' in existing:
        previous.update(dict(existing['DEFAULT']))
    while True:
        config = collect_config(console, previous)
        choice = confirm_config_preview(console, config)
        if choice == '1':
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            with open(config_file, 'w') as configfile:
                config.write(configfile)
            try:
                account_name = config['DEFAULT'].get('active_account') or config['DEFAULT'].get('email') or config['DEFAULT'].get('user_id') or 'default'
                save_current_as_account(account_name, defaults=dict(config['DEFAULT']), config_file=config_file)
            except Exception:
                pass
            console.print(f"\n[{C_INPUT}]配置已保存！[/{C_INPUT}]")
            return
        if choice == '0':
            console.print('[bold yellow]已取消，本次不会保存任何配置。[/]')
            return
        previous.update(dict(config['DEFAULT']))
        console.print('[bold cyan]返回修改。请重新输入需要调整的项。[/]')


def initial_checks(console: Optional[Console] = None, config_file: str = CONFIG_FILE):
    console = console or Console()
    if not os.path.isdir(CONFIG_PATH) or not os.path.isfile(config_file):
        os.makedirs(CONFIG_PATH, exist_ok=True)
        run_config_wizard(console=console, config_file=config_file)


def remove_leftovers(directory: str):
    directory = os.path.join(directory, '**', '.*.tmp')
    for item in glob.glob(directory, recursive=True):
        try:
            os.remove(item)
        except OSError as exc:
            logger.debug('Failed to remove temp file %s: %s', item, exc)
