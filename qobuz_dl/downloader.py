import logging
import os
import time
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests
from pathvalidate import sanitize_filename, sanitize_filepath
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    DownloadColumn,
    TaskID,
    SpinnerColumn
)
from rich.console import Console
from mutagen.flac import FLAC
from mutagen.mp3 import MP3

import qobuz_dl.metadata as metadata
from qobuz_dl.exceptions import NonStreamable
from qobuz_dl.db import handle_download_id, remove_download_id
from qobuz_dl.utils import format_proxy_url

DEFAULT_FOLDER = "{artist} - {album} ({year})"
DEFAULT_TRACK = "{artist} - {tracktitle} [{bit_depth}B-{sampling_rate}kHz]"
QL_DOWNGRADE = "FormatRestrictedByFormatAvailability"
MAX_WORKERS = 10 

console = Console()
logger = logging.getLogger(__name__)

BLACKLIST_KEYWORDS = [
    "sped up", "slowed", "reverb", "nightcore", 
    "tribute", "cover", "lullaby", "karaoke", 
    "instrumental version", "acoustic cover", "piano cover",
    "lofi", "lo-fi", "remix", "hypertechno", "techno mix"
]

# --- 莫兰迪配色 ---
C_TEXT   = "#abb2bf"
C_MAIN   = "#61afef"
C_OK     = "#98c379"
C_WARN   = "#e5c07b"
C_ERR    = "#e06c75"
C_DIM    = "#5c6370"
C_BAR_BG = "#3e4451"

class Download:
    def __init__(self, client, item_id, path, quality, embed_art=False, albums_only=False, downgrade_quality=False, cover_og_quality=False, no_cover=False, folder_format=None, track_format=None, downloads_db=None, no_booklet=False, root_folder=None):
        self.client = client
        self.item_id = item_id
        self.path = path
        self.quality = quality
        self.albums_only = albums_only
        self.embed_art = embed_art
        self.downgrade_quality = downgrade_quality
        self.cover_og_quality = cover_og_quality
        self.no_cover = no_cover
        self.folder_format = folder_format or DEFAULT_FOLDER
        self.track_format = track_format or DEFAULT_TRACK
        self.downloads_db = downloads_db
        self.no_booklet = no_booklet
        
        self.root_folder = root_folder if root_folder else path

        self.fmt_album = "{tracknumber} {artist} - {tracktitle} [{bit_depth}B-{sampling_rate}kHz]"
        self.fmt_single = "{artist} - {tracktitle} [{bit_depth}B-{sampling_rate}kHz]"

    def download_id_by_type(self, track=True):
        if not track: self.download_release()
        else: self.download_track()

    def _get_max_quality_url(self, url):
        if not url: return None
        if self.cover_og_quality:
            return url.replace("_600.", "_org.").replace("_small.", "_org.").replace("_medium.", "_org.")
        return url

    def _process_single_track(self, i, count, total_items, meta, dirn, is_multiple, progress, overall_task_id, failed_list, ind_cover, track_fmt):
        if not i: return
        title = i.get('title', 'Unknown')
        if len(title) > 25: title = title[:24] + "…"
        display_name = f"[{C_DIM}]({count:02d}/{total_items:02d})[/{C_DIM}] [{C_WARN}]{title}[/{C_WARN}]"
        
        task_id = progress.add_task(f"", filename=display_name, start=False, visible=True)
        progress.update(task_id, description=f"[{C_DIM}]等待...[/{C_DIM}] {display_name}")

        try:
            if "_manual_dir" in i:
                self._process_real_track(i, count, total_items, i.get('album'), i['_manual_dir'], i.get('_is_multiple'), progress, task_id, False, self.fmt_album, failed_list)
            elif "tracks_count" in i and "track_number" not in i:
                self._process_album_batch(i, count, total_items, dirn, progress, task_id, failed_list)
            else:
                self._process_real_track(i, count, total_items, meta, dirn, is_multiple, progress, task_id, ind_cover, track_fmt, failed_list)
        except Exception as e:
            # --- 修复核心：唯一添加错误的地方 ---
            # 统一提取日志所需信息
            try:
                album_name = i.get('album', {}).get('title', 'Unknown Album')
                target_path = i.get('_manual_dir', dirn)
            except:
                album_name = "Unknown"
                target_path = "Unknown"
            
            # 存入 (item, error, album, path) 4元组
            failed_list.append((i, str(e), album_name, target_path))
            progress.console.print(f"[{C_ERR}]失败 {display_name}: {e}[/{C_ERR}]")
        finally:
            progress.update(overall_task_id, advance=1)
            progress.remove_task(task_id)

    def _flatten_albums_to_tracks(self, album_list, base_path):
        console.print(f"[{C_MAIN}]预解析 {len(album_list)} 张专辑元数据...[/{C_MAIN}]")
        flat_tracks = []
        skipped_count = 0
        with Progress(SpinnerColumn(style=C_MAIN), TextColumn(f"[{C_TEXT}]解析中...[/{C_TEXT}]"), BarColumn(bar_width=20, style=C_BAR_BG, complete_style=C_MAIN), TextColumn(f"[{C_DIM}]{{task.completed}}/{{task.total}}[/{C_DIM}]"), console=console, transient=True) as progress:
            task = progress.add_task("Parsing", total=len(album_list))
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(self._fetch_and_prep_album, album, base_path): album for album in album_list}
                for future in as_completed(futures):
                    result = future.result()
                    progress.advance(task)
                    if result: flat_tracks.extend(result)
                    else: skipped_count += 1
        if skipped_count > 0: console.print(f"[{C_DIM}]已跳过 {skipped_count} 张 (已完成/无效)[/{C_DIM}]")
        return flat_tracks

    def _check_and_clean_db(self, album_id, dirn):
        if not self.downloads_db: return False
        is_in_db = handle_download_id(self.downloads_db, album_id, add_id=False)
        if is_in_db:
            if os.path.exists(dirn) and len(os.listdir(dirn)) > 0: return True
            else:
                remove_download_id(self.downloads_db, album_id)
                return False
        return False

    def _download_booklet(self, meta, save_dir):
        if self.no_booklet or "goodies" not in meta: return
        try:
            count = 1
            for g in meta["goodies"]:
                if g.get("file_format_id") == 21:
                    fname = "Digital Booklet.pdf" if count == 1 else f"Digital Booklet {count}.pdf"
                    console.print(f"[{C_MAIN}]PDF Booklet: {fname}[/{C_MAIN}]")
                    url = format_proxy_url(g["url"])
                    _get_extra_proxy(url, save_dir, fname)
                    count += 1
        except Exception: pass

    # --- 统一封面下载 ---
    def _download_cover_art(self, meta, save_dir, filename="cover.jpg"):
        if self.no_cover: return
        try:
            img_url = meta.get("image", {}).get("large")
            if not img_url: return
            
            if self.cover_og_quality:
                img_url = img_url.replace("_600.", "_org.") \
                                 .replace("_small.", "_org.") \
                                 .replace("_medium.", "_org.") \
                                 .replace("_230.", "_org.")
            
            url = format_proxy_url(img_url)
            _get_extra_proxy(url, save_dir, filename)
        except Exception: pass

    def _fetch_and_prep_album(self, album_simple, base_path):
        album_id = str(album_simple['id'])
        if self.downloads_db and handle_download_id(self.downloads_db, album_id, add_id=False): return None
        try:
            meta = self.client.get_album_meta(album_id)
            if not meta.get("streamable"): return None
            
            album_title = _get_title(meta)
            format_info = self._get_format(meta)
            file_format, _, bit_depth, sampling_rate = format_info
            album_attr = self._get_album_attr(meta, album_title, file_format, bit_depth, sampling_rate)
            sanitized_title = sanitize_filepath(self.folder_format.format(**album_attr))
            album_dir = os.path.join(base_path, sanitized_title)
            
            if self._check_and_clean_db(album_id, album_dir): return None
            
            os.makedirs(album_dir, exist_ok=True)
            
            # 使用统一封面函数
            self._download_cover_art(meta, album_dir, "cover.jpg")
            
            self._download_booklet(meta, album_dir)

            tracks = meta["tracks"]["items"]
            is_multiple = len({t.get("media_number", 1) for t in tracks}) > 1
            prepared_tracks = []
            for t in tracks:
                t['_manual_dir'] = album_dir
                t['_is_multiple'] = is_multiple
                t['album'] = meta 
                prepared_tracks.append(t)
            return prepared_tracks
        except: return None

    def download_batch(self, track_list, content_name="歌单", target_artist_id=None):
        final_list = track_list
        batch_ind_cover = True
        if track_list and "tracks_count" in track_list[0] and "artist" in track_list[0]:
            target_artist = content_name 
            console.print(f"[{C_WARN}]主艺人锁定: {target_artist} (ID: {target_artist_id or 'Auto'})[/{C_WARN}]")
            filtered_items = []
            for item in track_list:
                item_artist_name = item.get('artist', {}).get('name', '')
                item_artist_id = str(item.get('artist', {}).get('id'))
                item_title = item.get('title', '')
                is_spam = False
                for keyword in BLACKLIST_KEYWORDS:
                    if keyword in item_title.lower():
                        is_spam = True; break
                if is_spam: continue

                is_relevant = False
                if target_artist_id:
                    if item_artist_id == str(target_artist_id): is_relevant = True
                else:
                    if target_artist.lower() in item_artist_name.lower(): is_relevant = True

                if is_relevant: filtered_items.append(item)
            
            console.print(f"[{C_OK}]净化结果: {len(track_list)} -> {len(filtered_items)} 专辑[/{C_OK}]")
            final_list = filtered_items
            console.print(f"[{C_MAIN}]🚀 正在启动全速模式 (扁平化任务)...[/{C_MAIN}]")
            final_list = self._flatten_albums_to_tracks(final_list, self.path)
            console.print(f"[{C_OK}]🔥 任务队列已重组: {len(final_list)} 首单曲[/{C_OK}]")
            batch_ind_cover = False

        self._run_multithreaded_download(final_list, self.path, None, False, ind_cover=batch_ind_cover, track_fmt=self.fmt_single)
        console.print(f"[{C_OK}]✔ {content_name} 任务结束[/{C_OK}]")
        console.print(f"[{C_MAIN}]📂 保存于: {os.path.abspath(self.path)}[/{C_MAIN}]")

    def _process_album_batch(self, album_simple_meta, album_idx, total_albums, base_dir, progress, task_id, failed_list):
        # 兼容旧逻辑，但也要修复错误收集
        album_id = str(album_simple_meta['id'])
        try:
            progress.update(task_id, description=f"({album_idx}/{total_albums}) 获取元数据...")
            meta = self.client.get_album_meta(album_id)
            if not meta.get("streamable"): return

            album_title = _get_title(meta)
            format_info = self._get_format(meta)
            file_format, _, bit_depth, sampling_rate = format_info
            album_attr = self._get_album_attr(meta, album_title, file_format, bit_depth, sampling_rate)
            sanitized_title = sanitize_filepath(self.folder_format.format(**album_attr))
            album_dir = os.path.join(base_dir, sanitized_title)
            
            if self._check_and_clean_db(album_id, album_dir):
                progress.update(task_id, description=f"({album_idx}/{total_albums}) [已完成]", completed=100, total=100)
                return

            os.makedirs(album_dir, exist_ok=True)
            self._download_cover_art(meta, album_dir, "cover.jpg")
            self._download_booklet(meta, album_dir)

            tracks = meta["tracks"]["items"]
            total_tracks = len(tracks)
            is_multiple = len({t.get("media_number", 1) for t in tracks}) > 1
            for idx, track in enumerate(tracks):
                # 递归调用单曲下载，错误由外层 _process_single_track 捕获吗？
                # 不，_process_album_batch 被 _process_single_track 调用
                # 所以这里必须抛出异常，让外层捕获
                try:
                    parse = self.client.get_track_url(track["id"], fmt_id=self.quality)
                    if "sample" not in parse and parse["sampling_rate"]:
                        is_mp3 = True if int(self.quality) == 5 else False
                        self._download_and_tag(album_dir, idx + 1, parse, track, meta, False, is_mp3, track.get("media_number") if is_multiple else None, progress, task_id, ind_cover=False, track_fmt=self.fmt_album)
                except Exception as e:
                    # 这里是循环内部，不能直接抛出，否则整个专辑停止
                    # 必须手动添加错误到 failed_list (注意：这里添加了，外层就不能再添加了)
                    # 这是一个结构问题，为了简单，我们选择抛出异常中断当前专辑的剩余部分
                    raise e 
            
            if self.downloads_db: handle_download_id(self.downloads_db, album_id, add_id=True)
        except Exception as e: 
            # 抛出异常，让最外层捕获
            raise e

    def _process_real_track(self, i, count, total_items, meta, dirn, is_multiple, progress, task_id, ind_cover, track_fmt, failed_list):
        # 纯下载逻辑，不涉及异常捕获和列表添加
        title = i.get('title', 'Unknown')
        album_meta = meta
        if not album_meta: album_meta = i.get('album') or i 
        
        display_desc = f"({count}/{total_items}) {title[:20]}"
        if "_manual_dir" in i:
            album_name = i.get('album', {}).get('title', '')[:10]
            display_desc = f"({count}/{total_items}) {album_name}.. - {title[:15]}"
        
        progress.update(task_id, description=display_desc)
        try:
            parse = self.client.get_track_url(i["id"], fmt_id=self.quality)
            if not parse or "url" not in parse:
                if "sample" not in parse: raise Exception("无效链接")
                return 
        except Exception as e: raise Exception(f"API异常: {e}")

        if parse.get("sampling_rate"):
            is_mp3 = True if int(self.quality) == 5 else False
            self._download_and_tag(dirn, count, parse, i, album_meta, False, is_mp3, i.get("media_number") if is_multiple else None, progress, task_id, ind_cover=ind_cover, track_fmt=track_fmt)
        else: progress.console.print(f"[{C_WARN}]跳过试听: {title}[/{C_WARN}]")

    def download_release(self):
        console.print(f"[{C_DIM}]正在获取专辑信息...[/{C_DIM}]")
        with console.status(f"[{C_MAIN}]API 请求中...", spinner="dots"):
            meta = self.client.get_album_meta(self.item_id)
        if not meta.get("streamable"): raise NonStreamable("不可串流")
        
        album_title = _get_title(meta)
        format_info = self._get_format(meta)
        file_format, quality_met, bit_depth, sampling_rate = format_info
        album_attr = self._get_album_attr(meta, album_title, file_format, bit_depth, sampling_rate)
        sanitized_title = sanitize_filepath(self.folder_format.format(**album_attr))
        dirn = os.path.join(self.path, sanitized_title)
        
        console.print(f"[{C_DIM}]目录: {sanitized_title}[/{C_DIM}]")
        if self._check_and_clean_db(self.item_id, dirn):
            console.print(f"[{C_OK}]✔ 本地已存在，跳过[/{C_OK}]")
            return

        os.makedirs(dirn, exist_ok=True)
        
        self._download_cover_art(meta, dirn, "cover.jpg")
        self._download_booklet(meta, dirn)

        tracks = meta["tracks"]["items"]
        is_multiple = len({t.get("media_number", 1) for t in tracks}) > 1
        self._run_multithreaded_download(tracks, dirn, meta, is_multiple, ind_cover=False, track_fmt=self.fmt_album)
        
        if self.downloads_db: handle_download_id(self.downloads_db, self.item_id, add_id=True)
        console.print(f"[{C_OK}]✔ 专辑下载完成: {album_title}[/{C_OK}]")
        console.print(f"[{C_MAIN}]📂 保存于: {os.path.abspath(dirn)}[/{C_MAIN}]")

    def _run_multithreaded_download(self, tracks, dirn, meta, is_multiple, ind_cover, track_fmt):
        queue_items = tracks
        max_attempts = 4 
        
        for attempt in range(max_attempts):
            failed_list = [] 
            total_items = len(queue_items)
            
            if total_items == 0: break
            
            if attempt > 0:
                console.rule(f"[{C_WARN}]第 {attempt} 次重试 (剩余 {total_items} 项)[/{C_WARN}]")
            
            progress = Progress(
                TextColumn("{task.description}", justify="left"),
                BarColumn(bar_width=15, style=f"{C_BAR_BG}", complete_style=f"{C_MAIN}", finished_style=f"{C_OK}"),
                TextColumn(f"[{C_WARN}]{{task.percentage:>3.0f}}%[/{C_WARN}]"),
                DownloadColumn(binary_units=True),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console, 
                transient=True
            )
            
            with progress:
                overall_task_id = progress.add_task(f"[{C_MAIN}]总进度 ({total_items})[/{C_MAIN}]", filename="Batch", total=total_items)
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    futures = []
                    for idx, item in enumerate(queue_items):
                        count = idx + 1 
                        # 传递的是 failed_list 的引用，只有 _process_single_track 会往里 append
                        futures.append(executor.submit(self._process_single_track, item, count, total_items, meta, dirn, is_multiple, progress, overall_task_id, failed_list, ind_cover, track_fmt))
                    for future in as_completed(futures): 
                        try: future.result()
                        except Exception: pass
            
            if not failed_list: break
            # failed_list 元素是 (item, err, album, path)，取第0个元素 item 放入重试队列
            queue_items = [f[0] for f in failed_list]
            if attempt < max_attempts - 1: time.sleep(2)

        if failed_list:
            console.rule(f"[{C_ERR}]下载完成，但存在无法修复的错误[/{C_ERR}]")
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            log_filename = f".qd_error_{timestamp}.txt"
            
            if not hasattr(self, 'root_folder') or not self.root_folder:
                self.root_folder = self.path
            
            log_path = os.path.join(self.root_folder, log_filename)
            
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"--- Qobuz-DL Error Log {timestamp} ---\n")
                    f.write(f"Total Failed: {len(failed_list)}\n\n")
                    for item, err, album, path in failed_list:
                        name = item.get('title', 'Unknown')
                        msg = f"[Track] {name}\n[Album] {album}\n[Path] {path}\n[Error] {err}\n{'-'*40}\n"
                        console.print(f"[{C_ERR}]❌ {name}[/{C_ERR}]")
                        f.write(msg)
                
                if os.name == 'nt':
                    try: os.system(f'attrib +h "{log_path}"')
                    except: pass

                console.print(f"\n[{C_WARN}]详细错误日志已保存至 (隐藏文件):[/{C_WARN}]")
                console.print(f"[{C_MAIN}]{log_path}[/{C_MAIN}]")
            except Exception as e:
                console.print(f"[{C_ERR}]日志写入失败: {e}[/{C_ERR}]")
                
            console.print(f"[{C_WARN}]建议检查网络或账号权限。[/{C_WARN}]")
        else:
            console.print(f"[{C_OK}]✨ 全部内容下载成功！[/{C_OK}]")

    def download_track(self):
        try:
            console.print(f"[{C_DIM}]正在获取单曲信息...[/{C_DIM}]")
            meta = self.client.get_track_meta(self.item_id)
            parse = self.client.get_track_url(self.item_id, self.quality)
            progress = Progress(TextColumn("{task.description}", justify="left"), BarColumn(bar_width=15, style=C_BAR_BG, complete_style=C_MAIN), TextColumn(f"[{C_WARN}]{{task.percentage:>3.0f}}%[/{C_WARN}]"), DownloadColumn(), TransferSpeedColumn(), TimeRemainingColumn(), console=console, transient=True)
            with progress:
                track_num = meta.get('track_number', 0)
                disp_name = f"{track_num:02d}. {meta.get('title', 'Unknown')}"[:30]
                task_id = progress.add_task(description=f"[{C_MAIN}]{disp_name}[/{C_MAIN}]", filename=disp_name, start=False)
                is_mp3 = True if int(self.quality) == 5 else False
                try:
                    self._download_and_tag(self.path, 1, parse, meta, meta, True, is_mp3, None, progress, task_id, ind_cover=True, track_fmt=self.fmt_single)
                    console.print(f"\n[{C_MAIN}]📂 保存于: {os.path.abspath(self.path)}[/{C_MAIN}]")
                except Exception as e: console.print(f"[{C_ERR}]下载失败: {e}[/{C_ERR}]")
        except Exception as e: console.print(f"[{C_ERR}]元数据错误: {e}[/{C_ERR}]")

    def _download_and_tag(self, root_dir, tmp_count, track_url_dict, track_metadata, album_or_track_metadata, is_track, is_mp3, multiple, progress, task_id, ind_cover, track_fmt):
        extension = ".mp3" if is_mp3 else ".flac"
        try: url = format_proxy_url(track_url_dict["url"])
        except: return

        if multiple: root_dir = os.path.join(root_dir, f"Disc {multiple}")
        os.makedirs(root_dir, exist_ok=True)
        filename = os.path.join(root_dir, f".{tmp_count:02}.tmp")
        artist = _safe_get(track_metadata, "performer", "name") or "Unknown"
        filename_attr = self._get_filename_attr(artist, track_metadata, track_metadata.get("title", "Unknown"), track_url_dict)
        formatted_name = sanitize_filename(track_fmt.format(**filename_attr))
        final_file = os.path.join(root_dir, formatted_name)[:240] + extension
        
        if os.path.isfile(final_file):
            if os.path.getsize(final_file) < 1024: os.remove(final_file)
            else:
                try:
                    if is_mp3: MP3(final_file)
                    else: FLAC(final_file)
                    progress.update(task_id, visible=False)
                    return
                except Exception: os.remove(final_file)

        max_retries = 3
        success = False
        last_error = None

        for attempt in range(max_retries):
            try:
                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()
                total_length = int(response.headers.get("content-length", 0))
                progress.update(task_id, completed=0, total=total_length)
                progress.start_task(task_id)
                with open(filename, "wb") as file:
                    for chunk in response.iter_content(chunk_size=32768):
                        if chunk:
                            file.write(chunk)
                            progress.advance(task_id, len(chunk))
                if os.path.getsize(filename) != total_length: raise Exception("文件大小不匹配")
                success = True
                break 
            except Exception as e:
                last_error = e
                if ind_cover: console.print(f"[{C_WARN}]重试 ({attempt + 1}/{max_retries})...[/{C_WARN}]")
                time.sleep(3)
                if os.path.exists(filename): 
                    try: os.remove(filename)
                    except: pass
                progress.update(task_id, completed=0)

        if not success: raise Exception(f"重试失败: {last_error}")

        try:
            # 强制 em_image=False
            metadata.tag_mp3(filename, root_dir, final_file, track_metadata, album_or_track_metadata, is_track, em_image=False) if is_mp3 else \
            metadata.tag_flac(filename, root_dir, final_file, track_metadata, album_or_track_metadata, is_track, em_image=False)
        except: pass
        if os.path.exists(filename):
            try: os.rename(filename, final_file)
            except: pass
            
        if ind_cover and not self.no_cover:
            try:
                img_url = album_or_track_metadata.get("image", {}).get("large") or track_metadata.get("album", {}).get("image", {}).get("large")
                if img_url:
                    track_img_path = final_file.rsplit('.', 1)[0] + ".jpg"
                    if not os.path.exists(track_img_path):
                        # 使用 unified cover downloader logic
                        final_img_url = self._get_max_quality_url(img_url)
                        url = format_proxy_url(final_img_url)
                        _get_extra_proxy(url, root_dir, track_img_path.split(os.sep)[-1])
            except: pass

    @staticmethod
    def _get_filename_attr(artist, track_metadata, track_title, url_dict=None):
        sr = track_metadata.get("maximum_sampling_rate", 44.1)
        if url_dict and url_dict.get("sampling_rate"): sr = url_dict["sampling_rate"]
        if sr > 1000: sr = sr / 1000
        sr_str = f"{sr:g}"
        bd = track_metadata.get("maximum_bit_depth", 16)
        if url_dict and url_dict.get("bit_depth"): bd = url_dict["bit_depth"]
        return {"artist": artist, "bit_depth": bd, "sampling_rate": sr_str, "tracktitle": track_title, "tracknumber": f"{track_metadata.get('track_number', 0):02}"}

    @staticmethod
    def _get_album_attr(meta, album_title, file_format, bit_depth, sampling_rate):
        return {"artist": meta["artist"]["name"], "album": album_title, "year": meta["release_date_original"].split("-")[0], "format": file_format, "bit_depth": bit_depth, "sampling_rate": sampling_rate}

    def _get_format(self, item_dict, is_track_id=False, track_url_dict=None):
        quality_met = True
        if int(self.quality) == 5: return ("MP3", quality_met, None, None)
        track_dict = item_dict if is_track_id else item_dict["tracks"]["items"][0]
        try:
            new_track_dict = self.client.get_track_url(track_dict["id"], fmt_id=self.quality) if not track_url_dict else track_url_dict
            if int(self.quality) > 6 and new_track_dict.get("bit_depth") == 16: quality_met = False
            return ("FLAC", quality_met, new_track_dict["bit_depth"], new_track_dict["sampling_rate"])
        except: return ("Unknown", quality_met, None, None)

def _get_title(item_dict):
    album_title = item_dict["title"]
    version = item_dict.get("version")
    if version: album_title = f"{album_title} ({version})" if version.lower() not in album_title.lower() else album_title
    return album_title

def _get_extra_proxy(proxy_url, dirn, filename, og_quality=False):
    extra_file = os.path.join(dirn, filename)
    if os.path.isfile(extra_file): return
    try:
        r = requests.get(proxy_url, timeout=10)
        if r.status_code == 200:
            with open(extra_file, "wb") as f: f.write(r.content)
    except: pass

def _get_extra(item, dirn, extra="cover.jpg", og_quality=False):
    pass

def _safe_get(d: dict, *keys, default=None):
    curr = d
    for key in keys:
        try: curr = curr[key]
        except: return default
    return curr