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
    1. 优先找与音频同名的图片文件 (.jpg/.jpeg/.png) (适合歌单模式)
    2. 其次找当前目录下的 cover 图片 (cover.jpg/cover.png) (适合专辑模式)
    3. 最后尝试父目录下的 cover 图片 (适合 Disc 1/Disc 2 专辑子目录)
    """
    options = []
    # 1. 同名图片路径（尝试 jpg 和 png）
    if final_name:
        base = os.path.splitext(final_name)[0]
        options.append(base + ".jpg")
        options.append(base + ".jpeg")
        options.append(base + ".png")
    # 2. 当前目录 cover 图片
    options.append(os.path.join(root_dir, "cover.jpg"))
    options.append(os.path.join(root_dir, "cover.jpeg"))
    options.append(os.path.join(root_dir, "cover.png"))
    # 3. 上级目录 cover 图片
    parent = os.path.abspath(os.path.join(root_dir, os.pardir))
    options.append(os.path.join(parent, "cover.jpg"))
    options.append(os.path.join(parent, "cover.jpeg"))
    options.append(os.path.join(parent, "cover.png"))

    for opt in options:
        if os.path.isfile(opt):
            return opt
    return None

def _embed_flac_img(root_dir, audio: FLAC, final_name):
    cover_image = _find_cover(root_dir, final_name)
    if not cover_image:
        logger.debug("FLAC 封面嵌入跳过: 未找到封面文件 (root=%s, name=%s)", root_dir, final_name)
        return

    try:
        file_size = os.path.getsize(cover_image)
        if file_size < 64:
            logger.warning("FLAC 封面嵌入跳过: 封面文件过小 (%d bytes): %s", file_size, cover_image)
            return
        if file_size > FLAC_MAX_BLOCKSIZE:
            logger.warning("FLAC 封面嵌入跳过: 封面文件超过 FLAC 最大块大小 (%d bytes): %s", file_size, cover_image)
            return

        with open(cover_image, "rb") as img:
            img_data = img.read()

        # 验证 JPEG/PNG 魔数
        if img_data[:3] == b'\xff\xd8\xff':
            mime = "image/jpeg"
        elif img_data[:4] == b'\x89PNG':
            mime = "image/png"
        else:
            logger.warning("FLAC 封面嵌入跳过: 封面文件格式无效 (非 JPEG/PNG): %s", cover_image)
            return

        # 清除已有封面，避免重复嵌入（重试时不会叠加）
        audio.clear_pictures()

        image = Picture()
        image.type = 3  # Cover (front)
        image.mime = mime
        image.desc = "cover"
        image.data = img_data
        audio.add_picture(image)
        logger.debug("FLAC 封面嵌入成功: %s (%d bytes, %s)", cover_image, file_size, mime)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("FLAC 封面嵌入失败: %s", exc)

def _embed_id3_img(root_dir, audio: id3.ID3, final_name):
    cover_image = _find_cover(root_dir, final_name)
    if not cover_image:
        logger.debug("ID3 封面嵌入跳过: 未找到封面文件 (root=%s, name=%s)", root_dir, final_name)
        return

    try:
        file_size = os.path.getsize(cover_image)
        if file_size < 64:
            logger.warning("ID3 封面嵌入跳过: 封面文件过小 (%d bytes): %s", file_size, cover_image)
            return

        with open(cover_image, "rb") as cover:
            img_data = cover.read()

        # 验证 JPEG/PNG 魔数
        if img_data[:3] == b'\xff\xd8\xff':
            mime = "image/jpeg"
        elif img_data[:4] == b'\x89PNG':
            mime = "image/png"
        else:
            logger.warning("ID3 封面嵌入跳过: 封面文件格式无效 (非 JPEG/PNG): %s", cover_image)
            return

        # 删除已有 APIC 帧，避免重复嵌入
        if "APIC" in audio:
            del audio["APIC"]

        audio.add(id3.APIC(3, mime, 3, "cover", img_data))
        logger.debug("ID3 封面嵌入成功: %s (%d bytes, %s)", cover_image, file_size, mime)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("ID3 封面嵌入失败: %s", exc)

def _quality_str(meta: dict) -> str:
    if not meta:
        return ""
    q = meta.get("_actual_quality") or {}
    code = q.get("quality_code")
    bd = q.get("bit_depth")
    sr = q.get("sampling_rate")
    parts = []
    if code is not None:
        parts.append(f"code={code}")
    if bd:
        parts.append(f"bd={bd}")
    if sr:
        parts.append(f"sr={sr}")
    reason = meta.get("_fallback_reason")
    if reason:
        parts.append(f"reason={reason}")
    return ",".join(parts)


def tag_flac(filename, root_dir, final_name, d: dict, album, istrack=True, em_image=False):
    """给 FLAC 文件写入标签"""
    try:
        audio = FLAC(filename)
    except Exception as e:
        logger.error(f"FLAC 打开失败 (无法解析): {filename}: {e}")
        return

    try:
        audio["TITLE"] = _get_title(d)
        audio["TRACKNUMBER"] = str(d.get("track_number", 0))
        if int(d.get("media_number", 1) or 1) > 1:
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

        # Persist actual downloaded quality info in tags.
        quality_payload = _quality_str(d)
        if quality_payload:
            audio["QDP_QUALITY"] = quality_payload

        # Cover art embedding — isolated so a cover failure doesn't kill the tags
        if em_image:
            try:
                _embed_flac_img(root_dir, audio, final_name)
            except Exception as cover_exc:
                logger.warning("FLAC 封面嵌入失败 (标签仍会写入): %s", cover_exc)

        audio.save()
    except Exception as e:
        logger.error(f"FLAC 标签写入失败: {filename}: {e}")


def tag_mp3(filename, root_dir, final_name, d, album, istrack=True, em_image=False):
    """给 MP3 文件写入标签"""
    try:
        try:
            audio = id3.ID3(filename)
        except ID3NoHeaderError:
            audio = id3.ID3()
    except Exception as e:
        logger.error(f"MP3 ID3 打开失败: {filename}: {e}")
        return

    try:
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

        # Persist actual downloaded quality in a custom TXXX frame.
        quality_payload = _quality_str(d)
        if quality_payload:
            audio.add(id3.TXXX(encoding=3, desc="QDP_QUALITY", text=quality_payload))

        # Cover art embedding — isolated so a cover failure doesn't kill the tags
        if em_image:
            try:
                _embed_id3_img(root_dir, audio, final_name)
            except Exception as cover_exc:
                logger.warning("MP3 封面嵌入失败 (标签仍会写入): %s", cover_exc)

        audio.save(filename, "v2_version=3")
    except Exception as e:
        logger.error(f"MP3 标签写入失败: {filename}: {e}")
