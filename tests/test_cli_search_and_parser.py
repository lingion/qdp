import unittest
from unittest.mock import patch

from qdp.commands import build_parser
from qdp.core import QobuzDL


class FakeSearchClient:
    def __init__(self):
        self.calls = []

    def api_call(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return {
            kwargs["type"]: {
                "items": [
                    {
                        "id": "11",
                        "title": "Album 1",
                        "artist": {"name": "Artist 1"},
                        "streamable": True,
                        "maximum_bit_depth": 16,
                        "maximum_sampling_rate": 44.1,
                        "release_date_original": "2024-01-01",
                    }
                ]
            }
        }


class SearchInteractionTests(unittest.TestCase):
    def test_parser_supports_new_maintenance_flags(self):
        args = build_parser().parse_args([
            "--scan-library",
            "--doctor",
            "--rename-library",
            "--dry-run",
            "-v",
            "--debug",
            "--workers",
            "8",
            "--prefetch-workers",
            "6",
            "--max-retries",
            "5",
            "--timeout",
            "25",
            "--url-rate",
            "9",
        ])
        self.assertTrue(args.scan_library)
        self.assertTrue(args.doctor)
        self.assertTrue(args.rename_library)
        self.assertTrue(args.dry_run)
        self.assertTrue(args.verbose)
        self.assertTrue(args.debug)
        self.assertEqual(args.workers, 8)
        self.assertEqual(args.prefetch_workers, 6)
        self.assertEqual(args.max_retries, 5)
        self.assertEqual(args.timeout, 25)
        self.assertEqual(args.url_rate, 9)

    def test_search_shortcuts_update_offset_and_query(self):
        q = QobuzDL(check_only=True)
        q.client = FakeSearchClient()
        # interactive_search_compound drives input now; use 'q' to exit without execution
        with patch(
            "qdp.ui_search.Console.input",
            side_effect=["n", "p", "/", "new term", "q"],
        ):
            q.run_search("test", "album", 5)
        offsets = [call[1]["offset"] for call in q.client.calls]
        queries = [call[1]["query"] for call in q.client.calls]
        # First render at offset=0, then n => offset=5, then p => 0, then / => query changes and offset=0
        self.assertEqual(offsets, [0, 5, 0, 0])
        self.assertEqual(queries[-1], "new term")

    def test_search_numeric_selection_triggers_download_urls(self):
        q = QobuzDL(check_only=True)
        q.client = FakeSearchClient()
        captured = []
        with patch.object(q, "download_list_of_urls", side_effect=lambda urls: captured.extend(urls)):
            # 1: select first item, y: confirm execution
            with patch("qdp.ui_search.Console.input", side_effect=["1", "y"]):
                q.run_search("test", "album", 5)
        self.assertEqual(captured, ["https://open.qobuz.com/album/11"])


if __name__ == "__main__":
    unittest.main()
