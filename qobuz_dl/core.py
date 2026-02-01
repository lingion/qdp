import logging
import os
import re
import requests
from bs4 import BeautifulSoup as bso
from pathvalidate import sanitize_filename

from . import downloader, qopy
from .bundle import Bundle
from .color import OFF
from .exceptions import NonStreamable
from .db import create_db, handle_download_id
from .utils import (
    get_url_info, make_m3u, smart_discography_filter, create_and_return_dir
)
from rich.console import Console
from rich.table import Table

console = Console()
logger = logging.getLogger(__name__)

QUALITIES = {5: "5 - MP3", 6: "6 - 16 bit, 44.1kHz", 7: "7 - 24 bit, <96kHz", 27: "27 - 24 bit, >96kHz"}

# 莫兰迪配色 (全局一致)
C_TEXT   = "#abb2bf" # 灰白
C_TITLE  = "#c678dd" # 淡紫
C_ARTIST = "#98c379" # 淡绿
C_INDEX  = "#61afef" # 淡蓝
C_MAIN   = "#61afef" # 主色
C_WARN   = "#e5c07b" # 淡黄
C_ERR    = "#e06c75" # 淡红
C_DIM    = "#5c6370" # 深灰

class QobuzDL:
    def __init__(self, directory="Qobuz Downloads", quality=6, embed_art=False, ignore_singles_eps=False, no_m3u_for_playlists=False, quality_fallback=True, cover_og_quality=False, no_cover=False, downloads_db=None, folder_format="{artist} - {album} ({year})", track_format="{tracknumber}. {tracktitle}", smart_discography=False, no_booklet=False):
        self.directory = create_and_return_dir(directory)
        self.quality = quality
        self.embed_art = embed_art
        self.ignore_singles_eps = ignore_singles_eps
        self.no_m3u_for_playlists = no_m3u_for_playlists
        self.quality_fallback = quality_fallback
        self.cover_og_quality = cover_og_quality
        self.no_cover = no_cover
        self.downloads_db = create_db(downloads_db) if downloads_db else None
        self.folder_format = folder_format
        self.track_format = track_format
        self.smart_discography = smart_discography
        self.no_booklet = no_booklet 

    def initialize_client(self, email, pwd, app_id, secrets, use_token, user_id, user_auth_token):
        self.client = qopy.Client(email, pwd, app_id, secrets, use_token, user_id, user_auth_token)
        console.print(f"[{C_TEXT}]最高画质: {QUALITIES[int(self.quality)]}[/{C_TEXT}]\n")

    def run_search(self, initial_query, type, limit):
        query = initial_query
        offset = 0
        
        while True:
            page_num = (offset // limit) + 1
            console.print(f"[{C_WARN}]🔍 正在搜索 {type}: {query} (第 {page_num} 页)...[/{C_WARN}]")
            
            try:
                api_type = type + "s"
                data = self.client.api_call("catalog/search", query=query, type=api_type, limit=limit, offset=offset)
                
                items = []
                if api_type in data and "items" in data[api_type]:
                    items = data[api_type]["items"]

                if not items:
                    console.print(f"[{C_ERR}]❌ 未找到结果[/{C_ERR}]")
                    if offset > 0:
                        console.print(f"[{C_TEXT}]已到达末尾，返回上一页...[/{C_TEXT}]")
                        offset -= limit
                        continue
                else:
                    table = Table(title=f"搜索结果: {query} ({type})", title_style=C_TEXT, border_style=C_DIM)
                    table.add_column("序号", justify="right", style=C_INDEX, no_wrap=True)
                    table.add_column("标题", style=C_TITLE)
                    table.add_column("艺术家", style=C_ARTIST)
                    
                    if type == "album" or type == "track":
                        table.add_column("规格", justify="center", style=C_WARN)
                        table.add_column("年份", justify="center", style=C_TEXT)

                    results = []
                    for idx, item in enumerate(items):
                        idx_str = str(idx + 1)
                        title = item.get("title", "Unknown")
                        if "version" in item and item["version"]: title += f" ({item['version']})"
                        
                        if type == "artist": artist = item.get("name", "Unknown")
                        else: artist = item.get("artist", {}).get("name") or item.get("performer", {}).get("name", "Unknown")
                        
                        row_data = [idx_str, title, artist]
                        if type == "album" or type == "track":
                            hires = "Hi-Res" if item.get("hires_streamable") else "Lossless"
                            if not item.get("streamable"): hires = f"[{C_ERR}]不可用[/{C_ERR}]"
                            
                            bit_depth = item.get("maximum_bit_depth", 16)
                            sample_rate = item.get("maximum_sampling_rate", 44.1)
                            quality_str = f"{bit_depth}-Bit / {sample_rate} kHz"
                            if bit_depth > 16: quality_str = f"[bold]{quality_str}[/bold]"
                            
                            date_str = item.get("release_date_original", "")[:4] if type == "album" else ""
                            row_data.extend([quality_str, date_str])
                        
                        table.add_row(*row_data)
                        results.append(item)

                    console.print(table)
                    console.print(f"\n[{C_TEXT}]操作: 输入序号 (多选逗号分隔) | 'n' 下一页 | 'p' 上一页 | '0' 退出[/{C_TEXT}]")
                    selection = console.input(f"[{C_INDEX}]指令: [/{C_INDEX}]").strip().lower()
                    
                    if selection == "0": break
                    elif selection == "n":
                        offset += limit
                        continue
                    elif selection == "p":
                        if offset >= limit: offset -= limit
                        continue
                    
                    if selection.replace(",", "").isdigit():
                        selected_indices = [int(x.strip()) for x in selection.split(",") if x.strip().isdigit()]
                        urls = []
                        for i in selected_indices:
                            if 1 <= i <= len(results):
                                item = results[i-1]
                                if type == "album": url = f"https://open.qobuz.com/album/{item['id']}"
                                elif type == "track": url = f"https://open.qobuz.com/track/{item['id']}"
                                elif type == "artist": url = f"https://open.qobuz.com/artist/{item['id']}"
                                urls.append(url)
                        
                        if urls: self.download_list_of_urls(urls)
            
            except Exception as e:
                console.print(f"[{C_ERR}]搜索出错: {e}[/{C_ERR}]")
            
            console.rule(f"[{C_MAIN}]当前任务结束[/{C_MAIN}]")
            next_step = console.input("是否继续搜索? (输入关键词，或回车退出): ").strip()
            if not next_step: break
            else:
                query = next_step
                offset = 0

    def download_from_id(self, item_id, album=True, alt_path=None):
        if handle_download_id(self.downloads_db, item_id, add_id=False): pass 
        try:
            dloader = downloader.Download(self.client, item_id, alt_path or self.directory, int(self.quality), self.embed_art, self.ignore_singles_eps, self.quality_fallback, self.cover_og_quality, self.no_cover, self.folder_format, self.track_format, downloads_db=self.downloads_db, no_booklet=self.no_booklet, root_folder=self.directory)
            dloader.download_id_by_type(not album)
            handle_download_id(self.downloads_db, item_id, add_id=True)
        except (requests.exceptions.RequestException, NonStreamable) as e: console.print(f"[{C_ERR}]资源错误: {e}[/{C_ERR}]")

    def handle_url(self, url):
        possibles = {"playlist": {"func": self.client.get_plist_meta, "iterable_key": "tracks"}, "artist": {"func": self.client.get_artist_meta, "iterable_key": "albums"}, "label": {"func": self.client.get_label_meta, "iterable_key": "albums"}, "album": {"album": True, "func": None}, "track": {"album": False, "func": None}}
        try:
            url_type, item_id = get_url_info(url)
            type_dict = possibles[url_type]
        except Exception as e:
            console.print(f"[{C_ERR}]跳过无效链接: {url}[/{C_ERR}]")
            return

        if type_dict.get("func"):
            try:
                content = [item for item in type_dict["func"](item_id)]
                if not content: return
                content_name = content[0]["name"]
                console.print(f"[{C_WARN}]正在获取 {url_type}: {content_name}[/{C_WARN}]")
                new_path = create_and_return_dir(os.path.join(self.directory, sanitize_filename(content_name)))
                if self.smart_discography and url_type == "artist": items = smart_discography_filter(content, save_space=True, skip_extras=True)
                else:
                    items = []
                    key = type_dict["iterable_key"]
                    for page in content:
                        if key in page and "items" in page[key]: items.extend(page[key]["items"])
                console.print(f"[{C_TEXT}]包含 {len(items)} 个项目，准备并发下载...[/{C_TEXT}]")
                
                # --- 关键修改：提取 Artist ID 并传递 ---
                target_artist_id = item_id if url_type == "artist" else None
                
                dloader = downloader.Download(self.client, item_id, new_path, int(self.quality), self.embed_art, self.ignore_singles_eps, self.quality_fallback, self.cover_og_quality, self.no_cover, self.folder_format, self.track_format, downloads_db=self.downloads_db, no_booklet=self.no_booklet, root_folder=self.directory)
                dloader.download_batch(items, content_name=content_name, target_artist_id=target_artist_id)
                
                if url_type == "playlist" and not self.no_m3u_for_playlists:
                    make_m3u(new_path)
            except Exception as e: console.print(f"[{C_ERR}]批量处理出错: {e}[/{C_ERR}]")
        else: self.download_from_id(item_id, type_dict["album"])

    def download_list_of_urls(self, raw_args):
        if not raw_args: return
        valid_urls = []
        for arg in raw_args:
            arg = arg.strip()
            if "qobuz.com" in arg and "http" in arg: valid_urls.append(arg)
            elif os.path.isfile(arg): self.download_from_txt_file(arg)
            elif "last.fm" in arg: self.download_lastfm_pl(arg)
        if not valid_urls and not any(os.path.isfile(x) or "last.fm" in x for x in raw_args):
            full_text = " ".join(raw_args)
            qobuz_pattern = r"(https?://(?:open|play|www)\.qobuz\.com/[^\s\"']+)"
            extracted = re.findall(qobuz_pattern, full_text)
            if extracted: valid_urls.extend(extracted)
        if not valid_urls: return
        unique_urls = list(set(valid_urls))
        console.print(f"[{C_MAIN}]识别到 {len(unique_urls)} 个链接，开始处理...[/{C_MAIN}]")
        for url in unique_urls: self.handle_url(url)

    def download_from_txt_file(self, txt_file):
        with open(txt_file, "r") as txt:
            urls = [l.strip() for l in txt.readlines() if not l.strip().startswith("#")]
            self.download_list_of_urls(urls)

    def download_lastfm_pl(self, playlist_url):
        try: r = requests.get(playlist_url, timeout=10)
        except: pass