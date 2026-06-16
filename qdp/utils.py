import configparser
import logging
import os
import re
import string
import threading
import time
from urllib.parse import quote

import requests

from mutagen.flac import FLAC
from mutagen.mp3 import EasyMP3

logger = logging.getLogger(__name__)

EXTENSIONS = (".mp3", ".flac")

# --- 全局直连开关 ---
FORCE_DIRECT_MODE = False
_PROXY_LOCK = threading.Lock()
_PROXY_CURSOR = 0


def set_direct_mode(enabled: bool):
    global FORCE_DIRECT_MODE
    FORCE_DIRECT_MODE = enabled


def reset_proxy_cycle():
    global _PROXY_CURSOR
    with _PROXY_LOCK:
        _PROXY_CURSOR = 0


def get_config_path():
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA"), "qobuz-dl", "config.ini")
    return os.path.join(os.environ["HOME"], ".config", "qobuz-dl", "config.ini")


def get_proxy_list():
    """获取所有配置的代理列表"""
    if FORCE_DIRECT_MODE:
        return []
    try:
        path = get_config_path()
        if os.path.isfile(path):
            config = configparser.ConfigParser()
            config.read(path)
            proxies_str = config.get("DEFAULT", "proxies", fallback="")
            if proxies_str:
                return [p.strip().rstrip("/") for p in proxies_str.split(",") if p.strip()]
    except (configparser.Error, OSError) as exc:
        logger.debug("Failed to read proxy config: %s", exc)
    return []


def get_active_proxy():
    """按配置顺序轮询返回一个代理；未配置时返回 None。"""
    global _PROXY_CURSOR
    proxies = get_proxy_list()
    if not proxies:
        return None
    with _PROXY_LOCK:
        index = _PROXY_CURSOR % len(proxies)
        proxy = proxies[index]
        _PROXY_CURSOR = (_PROXY_CURSOR + 1) % len(proxies)
    return proxy


def format_proxy_url(raw_url):
    """文件下载用的代理封装。"""
    proxy_host = get_active_proxy()
    if proxy_host:
        encoded_url = quote(raw_url, safe="")
        return f"{proxy_host}/proxy?url={encoded_url}"
    return raw_url


def get_api_base_url():
    """获取初始 API 地址"""
    proxy_host = get_active_proxy()
    if proxy_host:
        return f"{proxy_host}/api.json/0.2/"
    return "https://www.qobuz.com/api.json/0.2/"


def get_bundle_base_url():
    proxy_host = get_active_proxy()
    if proxy_host:
        return proxy_host
    return "https://play.qobuz.com"


def fetch_web_player_credentials(proxy_url=None):
    """自动从 play.qobuz.com bundle.js 提取最新 app_id 和 app_secret。
    对齐 QBDLX / qobuz-dl 逻辑：通过 seed+info+extras base64 解码提取 secret。
    
    Args:
        proxy_url: 显式代理 URL（如 http://127.0.0.1:7897），None 时自动探测
    
    Returns:
        tuple: (app_id, dict_of_secrets_by_timezone) 或 (None, None) 如果提取失败
        secrets dict 示例: {"london": "abc...", "berlin": "def...", "abidjan": "ghi..."}
    """
    import base64
    from collections import OrderedDict
    
    # 自动探测常见代理端口
    if proxy_url is None:
        for port in [7897, 7890, 1080, 1087, 8080]:
            test_url = f"http://127.0.0.1:{port}"
            try:
                r = requests.get("https://play.qobuz.com/favicon.ico",
                    proxies={"http": test_url, "https": test_url},
                    timeout=5)
                if r.status_code == 200:
                    proxy_url = test_url
                    logger.info("自动检测到代理: %s", proxy_url)
                    break
            except Exception:
                continue
    
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    
    s = requests.Session()
    if proxies:
        s.proxies = proxies
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
    })
    
    # 1. 获取 login 页面，提取 bundle.js 路径
    try:
        r = s.get("https://play.qobuz.com/login", timeout=15)
        r.raise_for_status()
    except Exception as e:
        logger.warning("获取 play.qobuz.com/login 失败: %s", e)
        return None, None
    
    bundle_match = re.search(r'<script src="(/resources/[\d.]+-[a-z]\d{3}/bundle\.js)"></script>', r.text)
    if not bundle_match:
        logger.warning("未在 login 页面中找到 bundle.js 路径")
        return None, None
    
    bundle_path = bundle_match.group(1)
    bundle_url = f"https://play.qobuz.com{bundle_path}"
    logger.info("正在从 %s 提取凭据...", bundle_url)
    
    # 2. 下载 bundle.js
    try:
        r = s.get(bundle_url, timeout=30, stream=True)
        r.raise_for_status()
    except Exception as e:
        logger.warning("下载 bundle.js 失败: %s", e)
        return None, None
    
    bundle_text = ""
    for chunk in r.iter_content(chunk_size=1024*512, decode_unicode=True):
        bundle_text += chunk
    
    # 3. 提取 app_id（production 环境）
    app_id_match = re.search(r'production:\s*\{[^}]*api:\s*\{appId:\s*"(\d{9})",\s*appSecret:\s*"\w{32}"', bundle_text)
    if not app_id_match:
        # fallback: 任何 appId
        app_id_match = re.search(r'appId:\s*"(\d{9})"', bundle_text)
    if not app_id_match:
        logger.warning("未能从 bundle.js 提取到 app_id")
        return None, None
    app_id = app_id_match.group(1)
    
    # 4. 通过 seed+timezone+info+extras base64 解码提取 secrets（对齐 qobuz-dl）
    _SEED_TZ_RE = re.compile(r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)')
    _INFO_EXTRAS_RE = None  # 需要 timezone 列表构建
    
    seed_matches = list(_SEED_TZ_RE.finditer(bundle_text))
    secrets = OrderedDict()
    for m in seed_matches:
        seed, tz = m.group("seed", "timezone")
        secrets[tz] = [seed]
    
    if not secrets:
        logger.warning("未找到 seed entries")
        return None, None
    
    # 构建 info/extras 正则
    keypairs = list(secrets.items())
    # move_to_end 把第一个移到最后（qobuz-dl 的逻辑）
    if len(keypairs) > 1:
        secrets.move_to_end(keypairs[0][0], last=True)
    
    tz_pattern = "|".join(tz.capitalize() for tz in secrets)
    _INFO_EXTRAS_RE = re.compile(
        rf'name:"\w+/(?P<timezone>{tz_pattern})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
    )
    
    for m in _INFO_EXTRAS_RE.finditer(bundle_text):
        tz, info, extras = m.group("timezone", "info", "extras")
        secrets[tz.lower()] += [info, extras]
    
    # base64 解码（去掉末尾 44 字符的 padding，qobuz-dl 的逻辑）
    decoded_secrets = {}
    for tz in secrets:
        raw = "".join(secrets[tz])
        if len(raw) > 44:
            try:
                decoded = base64.standard_b64decode(raw[:-44]).decode("utf-8")
                decoded_secrets[tz] = decoded
            except Exception as e:
                logger.warning("解码 secret (%s) 失败: %s", tz, e)
    
    if not decoded_secrets:
        logger.warning("解码后无有效 secret")
        return None, None
    
    # 返回所有解码后的 secret（qopy.py 的 cfg_setup/test_secret 会找出正确的）
    logger.info("提取到 app_id=%s, secrets (%d 个 timezone)", app_id, len(decoded_secrets))
    return app_id, list(decoded_secrets.values())


class PartialFormatter(string.Formatter):
    def __init__(self, missing="n/a", bad_fmt="n/a"):
        self.missing, self.bad_fmt = missing, bad_fmt

    def get_field(self, field_name, args, kwargs):
        try:
            val = super(PartialFormatter, self).get_field(field_name, args, kwargs)
        except (KeyError, AttributeError):
            val = None, field_name
        return val

    def format_field(self, value, spec):
        if not value:
            return self.missing
        try:
            return super(PartialFormatter, self).format_field(value, spec)
        except ValueError:
            if self.bad_fmt:
                return self.bad_fmt
            raise


def make_m3u(pl_directory):
    track_list = ["#EXTM3U"]
    rel_folder = os.path.basename(os.path.normpath(pl_directory))
    pl_name = rel_folder + ".m3u"
    for local, dirs, files in os.walk(pl_directory):
        dirs.sort()
        audio_rel_files = [os.path.join(os.path.basename(os.path.normpath(local)), file_) for file_ in files if os.path.splitext(file_)[-1] in EXTENSIONS]
        audio_files = [os.path.abspath(os.path.join(local, file_)) for file_ in files if os.path.splitext(file_)[-1] in EXTENSIONS]
        if not audio_files or len(audio_files) != len(audio_rel_files):
            continue
        for audio_rel_file, audio_file in zip(audio_rel_files, audio_files):
            try:
                pl_item = EasyMP3(audio_file) if ".mp3" in audio_file else FLAC(audio_file)
                title = pl_item["TITLE"][0]
                artist = pl_item["ARTIST"][0]
                length = int(pl_item.info.length)
                index = "#EXTINF:{}, {} - {}\n{}".format(length, artist, title, audio_rel_file)
            except Exception as exc:
                logger.debug("Skip M3U entry for %s: %s", audio_file, exc)
                continue
            track_list.append(index)
    if len(track_list) > 1:
        with open(os.path.join(pl_directory, pl_name), "w") as pl:
            pl.write("\n\n".join(track_list))


def smart_discography_filter(contents: list, save_space: bool = False, skip_extras: bool = False) -> list:
    if not contents:
        return []
    raw_items = []
    if isinstance(contents[0], dict) and "albums" in contents[0]:
        for page in contents:
            if "albums" in page and "items" in page["albums"]:
                raw_items.extend(page["albums"]["items"])
    else:
        raw_items = contents

    def essence(album: dict) -> str:
        raw_title = album if isinstance(album, str) else album.get("title", "")
        match = re.match(r"([^\(]+)(?:\s*[\(\[][^\)\]]*[\)\]])*", raw_title)
        return match.group(1).strip().lower() if match else raw_title.strip().lower()

    try:
        if isinstance(contents, list) and isinstance(contents[0], dict) and "name" in contents[0]:
            requested_artist = contents[0]["name"]
        elif raw_items and "artist" in raw_items[0]:
            requested_artist = raw_items[0]["artist"]["name"]
        else:
            return raw_items
    except Exception as exc:
        logger.debug("Discography filter fallback: %s", exc)
        return raw_items

    logger.debug("Applying smart discography filter for artist %s", requested_artist)
    title_grouped = {}
    for item in raw_items:
        if not isinstance(item, dict) or "title" not in item:
            continue
        title_ = essence(item["title"])
        title_grouped.setdefault(title_, []).append(item)

    items = []
    for albums in title_grouped.values():
        best_bit_depth = max(a.get("maximum_bit_depth", 16) for a in albums)
        get_best = min if save_space else max
        best_sampling_rate = get_best(
            a.get("maximum_sampling_rate", 44.1)
            for a in albums
            if a.get("maximum_bit_depth") == best_bit_depth
        )
        filtered = [
            a for a in albums
            if a.get("maximum_bit_depth") == best_bit_depth and a.get("maximum_sampling_rate") == best_sampling_rate
        ]
        if filtered:
            items.append(filtered[0])
    return items


def format_duration(duration):
    return time.strftime("%H:%M:%S", time.gmtime(duration))


def create_and_return_dir(directory):
    fix = os.path.normpath(directory)
    os.makedirs(fix, exist_ok=True)
    return fix


def get_url_info(url):
    clean_url = url.split("?")[0].split("#")[0].strip().rstrip("/")
    valid_types = ["album", "artist", "track", "playlist", "label"]
    url_type = None
    for item_type in valid_types:
        if f"/{item_type}/" in clean_url:
            url_type = item_type
            break
    if not url_type:
        raise ValueError("无法识别链接类型")
    item_id = clean_url.split("/")[-1]
    if not item_id:
        raise ValueError("无法提取 ID")
    return url_type, item_id
