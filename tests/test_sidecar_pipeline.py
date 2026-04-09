import os
import tempfile
import unittest
from unittest.mock import patch

from qdp.downloader import Download
from qdp.sidecar import load_sidecar, get_sidecar_path


class _Report:
    def __init__(self, complete, expected_count, matched_count):
        self.complete = complete
        self.expected_count = expected_count
        self.matched_count = matched_count

    def to_dict(self):
        return {
            "complete": self.complete,
            "expected_count": self.expected_count,
            "matched_count": self.matched_count,
        }


class FakePipelineClient:
    def get_album_meta(self, album_id):
        return {
            "id": str(album_id),
            "title": "Album",
            "streamable": True,
            "artist": {"name": "Artist"},
            "release_date_original": "2024-01-01",
            "tracks": {
                "items": [
                    {
                        "id": "t1",
                        "title": "Song 1",
                        "track_number": 1,
                        "media_number": 1,
                        "performer": {"name": "Artist"},
                        "maximum_sampling_rate": 44.1,
                        "maximum_bit_depth": 16,
                    }
                ]
            },
        }

    def get_track_url(self, track_id, fmt_id):
        return {"url": f"https://example.com/{track_id}", "sampling_rate": 44.1, "bit_depth": 16}


class SidecarPipelineTests(unittest.TestCase):
    def test_album_download_writes_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakePipelineClient()
            d = Download(client, "album-1", tmp, 27)
            album_dir = os.path.join(tmp, "Artist - Album (2024)")

            def fake_run(tracks, *_args, **_kwargs):
                for track in tracks:
                    track.update(
                        {
                            "_download_status": "downloaded",
                            "_actual_quality": {"quality_code": 6, "bit_depth": 16, "sampling_rate": 44.1},
                            "_source_quality": {"quality_code": 27},
                            "_expected_filename": "01. Song 1.flac",
                            "_expected_rel_path": "01. Song 1.flac",
                        }
                    )
                return {"success": 1}

            with patch.object(
                Download,
                "inspect_album",
                side_effect=[
                    (_Report(False, 1, 0), client.get_album_meta("album-1"), album_dir),
                    (_Report(True, 1, 1), client.get_album_meta("album-1"), album_dir),
                ],
            ), patch.object(Download, "_download_cover_art", return_value=None), patch.object(Download, "_download_booklet", return_value=None), patch.object(Download, "_run_multithreaded_download", side_effect=fake_run):
                d.download_release()

            sidecar_path = get_sidecar_path(album_dir)
            self.assertTrue(os.path.isfile(sidecar_path))
            sidecar = load_sidecar(album_dir)
            self.assertEqual(sidecar["album_id"], "album-1")
            self.assertEqual(sidecar["quality"]["actual_quality"]["quality_code"], 6)
            self.assertEqual(sidecar["tracks"][0]["expected_filename"], "01. Song 1.flac")


if __name__ == "__main__":
    unittest.main()
