import re
import string
import os
import logging
import time
import random
import configparser
from urllib.parse import urlparse, unquote, quote

from mutagen.mp3 import EasyMP3
from mutagen.flac import FLAC

logger = logging.getLogger(__name__)

EXTENSIONS = (".mp3", ".flac")

# --- 全局直连开关 ---
FORCE_DIRECT_MODE = False

def set_direct_mode(enabled: bool):
    global FORCE_DIRECT_MODE
    FORCE_DIRECT_MODE = enabled

def get_config_path():
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA"), "qobuz-dl", "config.ini")
    else:
        return os.path.join(os.environ["HOME"], ".config", "qobuz-dl", "config.ini")

def get_proxy_list():
    """获取所有配置的代理列表"""
    if FORCE_DIRECT_MODE: return []
    try:
        path = get_config_path()
        if os.path.isfile(path):
            config = configparser.ConfigParser()
            config.read(path)
            proxies_str = config.get("DEFAULT", "proxies", fallback="")
            if proxies_str:
                # 返回清理过斜杠的列表
                return [p.strip().rstrip('/') for p in proxies_str.split(',') if p.strip()]
    except: pass
    return []

def get_active_proxy():
    """随机返回一个代理"""
    proxies = get_proxy_list()
    if proxies:
        return random.choice(proxies)
    return None

def format_proxy_url(raw_url):
    """文件下载用的代理封装 (这里还是随机选一个，由downloader负责重试)"""
    proxy_host = get_active_proxy()
    if proxy_host:
        encoded_url = quote(raw_url, safe='')
        return f"{proxy_host}/proxy?url={encoded_url}"
    else:
        return raw_url

def get_api_base_url():
    """获取初始 API 地址"""
    proxy_host = get_active_proxy()
    if proxy_host:
        return f"{proxy_host}/api.json/0.2/"
    return "https://www.qobuz.com/api.json/0.2/"

def get_bundle_base_url():
    proxy_host = get_active_proxy()
    if proxy_host: return proxy_host
    return "https://play.qobuz.com"
# --------------------

# (以下部分保持不变，为了篇幅省略，请确保保留原文件下半部分)
# 从 class PartialFormatter 开始直到文件结束的内容保持原样即可
# 为防出错，这里还是完整贴出：

class PartialFormatter(string.Formatter):
    def __init__(self, missing="n/a", bad_fmt="n/a"):
        self.missing, self.bad_fmt = missing, bad_fmt
    def get_field(self, field_name, args, kwargs):
        try: val = super(PartialFormatter, self).get_field(field_name, args, kwargs)
        except (KeyError, AttributeError): val = None, field_name
        return val
    def format_field(self, value, spec):
        if not value: return self.missing
        try: return super(PartialFormatter, self).format_field(value, spec)
        except ValueError:
            if self.bad_fmt: return self.bad_fmt
            raise

def make_m3u(pl_directory):
    track_list = ["#EXTM3U"]
    rel_folder = os.path.basename(os.path.normpath(pl_directory))
    pl_name = rel_folder + ".m3u"
    for local, dirs, files in os.walk(pl_directory):
        dirs.sort()
        audio_rel_files = [os.path.join(os.path.basename(os.path.normpath(local)), file_) for file_ in files if os.path.splitext(file_)[-1] in EXTENSIONS]
        audio_files = [os.path.abspath(os.path.join(local, file_)) for file_ in files if os.path.splitext(file_)[-1] in EXTENSIONS]
        if not audio_files or len(audio_files) != len(audio_rel_files): continue
        for audio_rel_file, audio_file in zip(audio_rel_files, audio_files):
            try:
                pl_item = (EasyMP3(audio_file) if ".mp3" in audio_file else FLAC(audio_file))
                title = pl_item["TITLE"][0]; artist = pl_item["ARTIST"][0]; length = int(pl_item.info.length)
                index = "#EXTINF:{}, {} - {}\n{}".format(length, artist, title, audio_rel_file)
            except: continue
            track_list.append(index)
    if len(track_list) > 1:
        with open(os.path.join(pl_directory, pl_name), "w") as pl: pl.write("\n\n".join(track_list))

def smart_discography_filter(contents: list, save_space: bool = False, skip_extras: bool = False) -> list:
    if not contents: return []
    raw_items = []
    if isinstance(contents[0], dict) and "albums" in contents[0]:
        for page in contents:
            if "albums" in page and "items" in page["albums"]: raw_items.extend(page["albums"]["items"])
    else: raw_items = contents
    TYPE_REGEXES = {"remaster": r"(?i)(re)?master(ed)?", "extra": r"(?i)(anniversary|deluxe|live|collector|demo|expanded)"}
    def is_type(album_t: str, album: dict) -> bool:
        version = album.get("version", ""); title = album.get("title", ""); regex = TYPE_REGEXES[album_t]
        return re.search(regex, f"{title} {version}") is not None
    def essence(album: dict) -> str:
        r = re.match(r"([^\(]+)(?:\s*[\(\[][^\)][\)\]])*", album)
        return r.group(1).strip().lower() if r else album.strip().lower()
    try:
        if isinstance(contents, list) and isinstance(contents[0], dict) and "name" in contents[0]: requested_artist = contents[0]["name"]
        elif raw_items and "artist" in raw_items[0]: requested_artist = raw_items[0]["artist"]["name"]
        else: return raw_items
    except: return raw_items
    title_grouped = dict()
    for item in raw_items:
        if not isinstance(item, dict) or "title" not in item: continue
        title_ = essence(item["title"])
        if title_ not in title_grouped: title_grouped[title_] = []
        title_grouped[title_].append(item)
    items = []
    for albums in title_grouped.values():
        best_bit_depth = max(a.get("maximum_bit_depth", 16) for a in albums)
        get_best = min if save_space else max
        best_sampling_rate = get_best(a.get("maximum_sampling_rate", 44.1) for a in albums if a.get("maximum_bit_depth") == best_bit_depth)
        filtered = [a for a in albums if a.get("maximum_bit_depth") == best_bit_depth and a.get("maximum_sampling_rate") == best_sampling_rate]
        if filtered: items.append(filtered[0])
    return items

def format_duration(duration): return time.strftime("%H:%M:%S", time.gmtime(duration))
def create_and_return_dir(directory):
    fix = os.path.normpath(directory); os.makedirs(fix, exist_ok=True); return fix

def get_url_info(url):
    clean_url = url.split('?')[0].split('#')[0].strip().rstrip('/')
    valid_types = ['album', 'artist', 'track', 'playlist', 'label']
    url_type = None
    for t in valid_types:
        if f"/{t}/" in clean_url: url_type = t; break
    if not url_type: raise ValueError("无法识别链接类型")
    item_id = clean_url.split('/')[-1]
    if not item_id: raise ValueError("无法提取 ID")
    return url_type, item_id