"""embed_art 配置项接线测试。

审计发现 P1: embed_art 配置全链路传入 Download, 但 tag 调用硬编码
em_image=False, 封面嵌入永不执行(死开关)。
"""
import tempfile
import unittest
from unittest.mock import patch

import requests
from rich.progress import Progress

import qdp.metadata as metadata
from qdp.downloader import Download


class _FakeResponse:
    status_code = 200
    headers = {"content-length": "4"}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=32768):
        yield b"data"


class EmbedArtWiringTests(unittest.TestCase):
    def _tag_em_image(self, embed_art):
        client = type("Client", (), {})()
        d = Download(client, "album-1", tempfile.mkdtemp(), 27, embed_art=embed_art)
        track = {"id": "t1", "title": "Song", "track_number": 1, "media_number": 1}
        url_dict = {"url": "https://example.com/t.flac", "bit_depth": 16, "sampling_rate": 44.1}
        with patch.object(metadata, "tag_flac", wraps=metadata.tag_flac) as tag_flac:
            with patch.object(requests, "get", return_value=_FakeResponse()):
                with Progress() as progress:
                    task_id = progress.add_task("x", total=4)
                    d._download_and_tag(
                        tempfile.mkdtemp(), 1, url_dict, track,
                        {"title": "Album", "image": {}}, False, False, None,
                        progress=progress, task_id=task_id, ind_cover=False,
                        track_fmt="{tracktitle}",
                    )
        return tag_flac.call_args.kwargs.get("em_image") if tag_flac.call_args else None

    def test_embed_art_true_reaches_tag_call(self):
        self.assertIs(self._tag_em_image(True), True)

    def test_embed_art_false_stays_off(self):
        self.assertIs(self._tag_em_image(False), False)


if __name__ == "__main__":
    unittest.main()
