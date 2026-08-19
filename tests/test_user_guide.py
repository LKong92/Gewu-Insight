from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from paper_monitor import ui_server


ROOT = Path(__file__).resolve().parents[1]


class UserGuideTests(unittest.TestCase):
    def test_offline_guide_asset_is_loaded_from_the_python_package(self) -> None:
        expected = Path(ui_server.__file__).with_name("user_guide.html")
        self.assertEqual(ui_server.USER_GUIDE_PATH, expected)
        self.assertTrue(expected.is_file())
        html = ui_server.load_user_guide_html()
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertGreater(len(html), 40_000)

    def test_user_guide_route_reads_the_current_asset_without_browser_cache(self) -> None:
        handler = object.__new__(ui_server.PaperMonitorUiHandler)
        handler.path = "/user-guide"
        handler.send_text = MagicMock()

        with patch.object(ui_server, "load_user_guide_html", return_value="<html>guide</html>") as loader:
            handler.do_GET()

        loader.assert_called_once_with()
        handler.send_text.assert_called_once_with(
            "<html>guide</html>", content_type="text/html; charset=utf-8"
        )

    def test_guide_has_valid_internal_navigation_and_complete_product_coverage(self) -> None:
        html = ui_server.load_user_guide_html()
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(soup.html.get("lang"), "en")
        self.assertIsNotNone(soup.find("meta", attrs={"name": "viewport"}))
        ids = [element.get("id") for element in soup.find_all(attrs={"id": True})]
        self.assertEqual(len(ids), len(set(ids)))

        topic_ids = {article.get("id") for article in soup.select("article.guide-topic")}
        self.assertGreaterEqual(len(topic_ids), 20)
        navigation_ids = {
            button.get("data-topic") for button in soup.select("button.topic-link[data-topic]")
        }
        self.assertEqual(navigation_ids, topic_ids)
        for link in soup.select('a[href^="#"]'):
            target = link.get("href", "")[1:]
            if target:
                self.assertIn(target, ids, f"Missing guide target for #{target}")

        required_text = [
            "Guided Tour",
            "Library",
            "Folder Loader",
            "Paper Details",
            "Paper Files",
            "Associated Files",
            "Gewu Key",
            "My Publications",
            "Journal Monitor",
            "Subject Monitor",
            "Author Monitor",
            "Citation Settings",
            "Keyboard Shortcuts",
            "Back Up and Upgrade",
            "Troubleshooting",
        ]
        visible_text = soup.get_text(" ", strip=True)
        for phrase in required_text:
            self.assertIn(phrase, visible_text)

        self.assertNotIn("Development History", visible_text)
        self.assertNotIn("benchmark", visible_text.lower())

    def test_guide_is_offline_searchable_and_printable(self) -> None:
        html = ui_server.load_user_guide_html()
        self.assertIn('id="guideSearch"', html)
        self.assertIn("hashchange", html)
        self.assertIn("showTopic", html)
        self.assertIn("window.print()", html)
        self.assertIn("@media print", html)
        soup = BeautifulSoup(html, "html.parser")
        self.assertFalse(soup.select("script[src]"))
        self.assertFalse(soup.select("link[href]"))
        self.assertFalse(soup.select("img[src], video[src], audio[src], source[src]"))

    def test_release_bundle_continues_to_include_the_user_guide_asset(self) -> None:
        release_script = (ROOT / "scripts" / "make_release.sh").read_text(encoding="utf-8")
        self.assertIn('copy_item "paper_monitor"', release_script)


if __name__ == "__main__":
    unittest.main()
