from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import ui_server


SVG_LOGO = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>'


class JournalLogoCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        ui_server.JOURNAL_LOGO_CACHE.clear()
        ui_server.JOURNAL_LOGO_FAILED.clear()

    def tearDown(self) -> None:
        ui_server.JOURNAL_LOGO_CACHE.clear()
        ui_server.JOURNAL_LOGO_FAILED.clear()

    def test_configured_journals_expose_only_local_logo_urls(self) -> None:
        journals = ui_server.journals_for_api(
            {
                "journals": [
                    {"name": "Nature", "logo_url": "https://publisher.example/nature.svg"},
                    {"name": "arXiv", "logo_url": "https://publisher.example/arxiv.svg"},
                ]
            }
        )

        self.assertEqual(journals[0]["logo_url"], "/api/journal-logo-image?name=Nature")
        self.assertEqual(journals[1]["logo_url"], "")

    def test_downloaded_logo_is_reused_from_disk_after_memory_cache_is_cleared(self) -> None:
        class Response:
            content = SVG_LOGO
            headers = {"Content-Type": "image/svg+xml"}
            url = "https://publisher.example/nature.svg"

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paper_monitor.sqlite"
            configured = {"name": "Nature", "logo_url": Response.url}
            with patch("paper_monitor.ui_server.request_with_retries", return_value=Response()) as request:
                first = ui_server.cache_journal_logo(db_path, "Nature", configured)
                ui_server.JOURNAL_LOGO_CACHE.clear()
                second = ui_server.cache_journal_logo(db_path, "Nature", configured)
                saved_content = first.read_bytes() if first else b""

        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(saved_content, SVG_LOGO)
        self.assertEqual(request.call_count, 1)
        self.assertIn("cache/journal_logos", first.as_posix())

    def test_prewarm_only_downloads_configured_or_known_direct_logos(self) -> None:
        raw = {
            "journals": [
                {"name": "Nature", "logo_url": ""},
                {"name": "Example Journal", "logo_url": "https://publisher.example/example.svg"},
                {"name": "Unknown Journal", "logo_url": ""},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paper_monitor.sqlite"
            with (
                patch("paper_monitor.ui_server.read_config_json", return_value=raw),
                patch("paper_monitor.ui_server.cache_journal_logo") as cache,
            ):
                ui_server.prewarm_configured_journal_logos(db_path)

        self.assertEqual(
            [(call.args[1], call.args[2]["name"]) for call in cache.call_args_list],
            [("Nature", "Nature"), ("Example Journal", "Example Journal")],
        )

    def test_html_response_is_not_saved_as_a_logo(self) -> None:
        class Response:
            content = b"<html><body>blocked</body></html>"
            headers = {"Content-Type": "text/html"}
            url = "https://publisher.example/logo.svg"

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paper_monitor.sqlite"
            configured = {"name": "Nature", "logo_url": Response.url}
            with patch("paper_monitor.ui_server.request_with_retries", return_value=Response()):
                result = ui_server.cache_journal_logo(db_path, "Nature", configured)
            cache_dir = ui_server.journal_logo_cache_dir(db_path)
            saved = list(cache_dir.iterdir()) if cache_dir.exists() else []

        self.assertIsNone(result)
        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
