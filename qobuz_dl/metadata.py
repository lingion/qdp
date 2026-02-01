import re
import os
import logging

from mutagen.flac import FLAC, Picture
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError

logger = logging.getLogger(__name__)

# 符号定义
COPYRIGHT, PHON_COPYRIGHT = "\u2117", "\u00a9"
# FLAC 封面最大块大小 (约16MB)
FLAC_MAX_BLOCKSIZE = 16777215

ID3_LEGEND = {
    "album": id3.TALB,
    "albumartist": id3.TPE2,
    "artist": id3.TPE1,
    "comment": id3.COMM,
    "composer": id3.TCOM,
    "copyright": id3.TCOP,
    "date": id3.TDAT,
    "genre": id3.TCON,
    "isrc": id3.TSRC,
    "label": id3.TPUB,
    "performer": id3.TOPE,
    "title": id3.TIT2,
    "year": id3.TYER,
}

def _get_title(track_dict):
    title = track_dict["title"]
    version = track_dict.get("version")
    if version:
        title = f"{title} ({version})"
    if track_dict.get("work"):
        title = f"{track_dict['work']}: {title}"
    return title

def _format_copyright(s: str) -> str:
    if s:
        s = s.replace("(P)", PHON_COPYRIGHT)
        s = s.replace("(C)", COPYRIGHT)
    return s

def _format_genres(genres: list) -> str:
    genres = re.findall(r"([^\u2192\/]+)", "/".join(genres))
    no_repeats = []
    [no_repeats.append(g) for g in genres if g not in no_repeats]
    return ", ".join(no_repeats)

def _find_cover(root_dir, final_name):
    """
    智能寻找封面图片：
    1. 优先找与音频同名的 .jpg 文件 (适合歌单模式)
    2. 其次找当前目录下的 cover.jpg (适合专辑模式)
    3. 最后尝试父目录下的 cover.jpg (适合 Disc 1/Disc 2 专辑子目录)
    """
    options = []
    # 1. 同名图片路径
    if final_name:
        options.append(os.path.splitext(final_name)[0] + ".jpg")
    # 2. 当前目录 cover.jpg
    options.append(os.path.join(root_dir, "cover.jpg"))
    # 3. 上级目录 cover.jpg
    options.append(os.path.join(os.path.abspath(os.path.join(root_dir, os.pardir)), "cover.jpg"))

    for opt in options:
        if os.path.isfile(opt):
            return opt
    return None

def _embed_flac_img(root_dir, audio: FLAC, final_name):
    cover_image = _find_cover(root_dir, final_name)
    if not cover_image:
        return

    try:
        if os.getsize(cover_image) > FLAC_MAX_BLOCKSIZE:
            return 
        image = Picture()
        image.type = 3
        image.mime = "image/jpeg"
        image.desc = "cover"
        with open(cover_image, "rb") as img:
            image.data = img.read()
        audio.add_picture(image)
    except:
        pass

def _embed_id3_img(root_dir, audio: id3.ID3, final_name):
    cover_image = _find_cover(root_dir, final_name)
    if not cover_image:
        return

    try:
        with open(cover_image, "rb") as cover:
            audio.add(id3.APIC(3, "image/jpeg", 3, "", cover.read()))
    except:
        pass

def tag_flac(filename, root_dir, final_name, d: dict, album, istrack=True, em_image=False):
    """给 FLAC 文件写入标签"""
    try:
        audio = FLAC(filename)
        audio["TITLE"] = _get_title(d)
        audio["TRACKNUMBER"] = str(d.get("track_number", 0))
        if "Disc " in final_name:
            audio["DISCNUMBER"] = str(d.get("media_number", 1))
        
        artist_ = d.get("performer", {}).get("name")
        curr_album = d.get("album", album)
        
        audio["ARTIST"] = artist_ or curr_album["artist"]["name"]
        audio["ALBUMARTIST"] = curr_album["artist"]["name"]
        audio["ALBUM"] = curr_album["title"]
        audio["GENRE"] = _format_genres(curr_album.get("genres_list", []))
        audio["DATE"] = curr_album.get("release_date_original", "")
        audio["LABEL"] = curr_album.get("label", {}).get("name", "n/a")
        audio["COPYRIGHT"] = _format_copyright(curr_album.get("copyright") or "n/a")

        if em_image:
            _embed_flac_img(root_dir, audio, final_name)

        audio.save()
    except Exception as e:
        logger.error(f"FLAC 标签写入失败: {e}")

def tag_mp3(filename, root_dir, final_name, d, album, istrack=True, em_image=False):
    """给 MP3 文件写入标签"""
    try:
        try:
            audio = id3.ID3(filename)
        except ID3NoHeaderError:
            audio = id3.ID3()

        curr_album = d.get("album", album)
        tags = {
            "title": _get_title(d),
            "artist": d.get("performer", {}).get("name") or curr_album["artist"]["name"],
            "albumartist": curr_album["artist"]["name"],
            "album": curr_album["title"],
            "date": curr_album.get("release_date_original", ""),
            "genre": _format_genres(curr_album.get("genres_list", [])),
            "copyright": _format_copyright(curr_album.get("copyright") or "n/a"),
        }
        tags["year"] = tags["date"][:4]

        audio["TRCK"] = id3.TRCK(encoding=3, text=f'{d.get("track_number", 0)}/{curr_album.get("tracks_count", 0)}')
        audio["TPOS"] = id3.TPOS(encoding=3, text=str(d.get("media_number", 1)))

        for k, v in tags.items():
            if k in ID3_LEGEND and v:
                id3tag = ID3_LEGEND[k]
                audio[id3tag.__name__] = id3tag(encoding=3, text=v)

        if em_image:
            _embed_id3_img(root_dir, audio, final_name)

        audio.save(filename, "v2_version=3")
    except Exception as e:
         logger.error(f"MP3 标签写入失败: {e}")