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

        topic_order = [article.get("id") for article in soup.select("article.guide-topic")]
        topic_ids = set(topic_order)
        self.assertGreaterEqual(len(topic_ids), 40)
        navigation_order = [
            button.get("data-topic") for button in soup.select("button.topic-link[data-topic]")
        ]
        self.assertEqual(navigation_order, topic_order)
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

    def test_original_topics_are_preserved_around_the_new_architecture_section(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")
        topic_order = [article["id"] for article in soup.select("article.guide-topic")]
        original_topic_ids = [
            "welcome",
            "guided-tour",
            "first-session",
            "library-layout",
            "navigation",
            "organize",
            "search-views",
            "import-files",
            "paper-details",
            "identifiers",
            "paper-files",
            "versions-current",
            "attachments",
            "download-sync",
            "drag-attach",
            "recycle",
            "folder-loader",
            "loader-maintenance",
            "desktop-copy",
            "backup-migrate",
            "my-publications",
            "journal-monitor",
            "subject-monitor",
            "author-monitor",
            "citation-settings",
            "naming",
            "storage-model",
            "privacy",
            "keyboard",
            "network-access",
            "startup",
            "troubleshooting",
            "storage-reference",
        ]
        self.assertEqual(
            [topic_id for topic_id in topic_order if topic_id in original_topic_ids],
            original_topic_ids,
        )

        architecture_topic_ids = [
            "system-overview",
            "persistent-paper-object",
            "sqlite-core",
            "visible-research-files",
            "personal-research-workspace",
            "research-loop",
            "state-and-scope",
        ]
        first_architecture_topic = topic_order.index("system-overview")
        self.assertEqual(topic_order[first_architecture_topic - 1], "first-session")
        self.assertEqual(
            topic_order[first_architecture_topic : first_architecture_topic + 7],
            architecture_topic_ids,
        )
        self.assertEqual(topic_order[first_architecture_topic + 7], "library-layout")

    def test_start_here_builds_philosophy_orientation_and_a_complete_first_session(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")
        welcome = soup.find("article", id="welcome")
        guided_tour = soup.find("article", id="guided-tour")
        first_session = soup.find("article", id="first-session")

        for article in [welcome, guided_tour, first_session]:
            self.assertIsNotNone(article)
            self.assertEqual(article.get("data-group"), "Start Here")
            self.assertGreaterEqual(len(article.select("h2")), 6)
            self.assertIsNotNone(article.select_one(".see-also"))

        welcome_text = welcome.get_text(" ", strip=True)
        for phrase in [
            "格物致知",
            "格物 · Gewu",
            "洞见 · Insight",
            "Keep research objects visible, evidence traceable, and insight cumulative.",
            "Five design commitments",
            "Local-first does not mean offline-only",
            "What this guide covers",
            "Five areas of the app",
            "Open this guide again",
        ]:
            self.assertIn(phrase, welcome_text)
        self.assertEqual(len(welcome.select("figure.architecture-map")), 2)
        self.assertIsNotNone(welcome.select_one(".credo"))

        guided_text = guided_tour.get_text(" ", strip=True)
        for phrase in [
            "Read the interface as a sentence",
            "The Library window",
            "Follow selection from broad to specific",
            "Tabs across the top",
            "Watch one paper move through the workspace",
            "Resize a pane",
            "Recognize stable and temporary state",
        ]:
            self.assertIn(phrase, guided_text)
        self.assertGreaterEqual(len(guided_tour.select("figure.architecture-map")), 2)

        first_session_text = first_session.get_text(" ", strip=True)
        for phrase in [
            "Choose your starting route",
            "Add and inspect a paper",
            "Understand what may now exist",
            "Verify the identity before enriching it",
            "Complete the first Paper Files bundle",
            "It may have no local file",
            "cataloged-only state is valid",
            "Cataloged and organized",
            "File-backed",
            "Show in Finder",
            "Optional: verify shared identity",
            "Next useful actions",
            "Finish with a safe baseline",
            "Create the backup habit early",
        ]:
            self.assertIn(phrase, first_session_text)
        self.assertIsNotNone(first_session.select_one("figure.architecture-map"))
        self.assertIn(
            "Show in Finder",
            [element.get_text(" ", strip=True) for element in first_session.select(".ui")],
        )

        search_expectations = {
            "格物 洞见": welcome,
            "visual grammar": guided_tour,
            "cataloged file-backed": first_session,
        }
        for query, article in search_expectations.items():
            searchable = " ".join(
                [
                    article.get("data-title", ""),
                    article.get("data-group", ""),
                    article.get("data-keywords", ""),
                    article.get_text(" ", strip=True),
                ]
            ).lower()
            self.assertTrue(
                all(term in searchable for term in query.lower().split()),
                f"Expected search phrase {query!r} to find {article.get('id')}",
            )

    def test_architecture_topics_explain_the_state_and_file_model_in_depth(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")
        architecture_topic_ids = [
            "system-overview",
            "persistent-paper-object",
            "sqlite-core",
            "visible-research-files",
            "personal-research-workspace",
            "research-loop",
            "state-and-scope",
        ]
        architecture_group = next(
            group
            for group in soup.select("section.nav-group")
            if group.select_one(".nav-heading")
            and group.select_one(".nav-heading").get_text(" ", strip=True)
            == "Understand the System"
        )
        self.assertEqual(
            [button["data-topic"] for button in architecture_group.select("button.topic-link")],
            architecture_topic_ids,
        )

        for topic_id in architecture_topic_ids:
            article = soup.find("article", id=topic_id)
            self.assertIsNotNone(article)
            self.assertEqual(article.get("data-group"), "Understand the System")
            self.assertTrue(article.get("data-keywords"))
            self.assertTrue(article.select_one("h1").get_text(" ", strip=True))
            self.assertTrue(article.select_one(".lead").get_text(" ", strip=True))
            self.assertIsNotNone(article.select_one(".see-also"))

        architecture_text = " ".join(
            soup.find("article", id=topic_id).get_text(" ", strip=True)
            for topic_id in architecture_topic_ids
        )
        for phrase in [
            "Persistent Paper Object",
            "Personal Research Workspace",
            "Visible Research Files",
            "SQLite is the source of truth",
            "WAL",
            "JSON",
            "one shared paper identity",
        ]:
            self.assertIn(phrase, architecture_text)

        search_expectations = {
            "wal": "sqlite-core",
            "Gewu Key": "persistent-paper-object",
            "visible research files": "visible-research-files",
            "cooldown": "research-loop",
            "scope deletion": "state-and-scope",
        }
        for query, topic_id in search_expectations.items():
            article = soup.find("article", id=topic_id)
            searchable = " ".join(
                [
                    article.get("data-title", ""),
                    article.get("data-group", ""),
                    article.get("data-keywords", ""),
                    article.get_text(" ", strip=True),
                ]
            ).lower()
            self.assertTrue(
                all(term in searchable for term in query.lower().split()),
                f"Expected search phrase {query!r} to find {topic_id}",
            )

        self.assertTrue(soup.select("figure.architecture-map"))
        for figure in soup.select("figure.architecture-map"):
            self.assertFalse(figure.select("img[src], video[src], audio[src], source[src]"))

    def test_guide_documents_resource_and_provenance_invariants_without_becoming_a_changelog(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")

        sqlite_text = soup.find("article", id="sqlite-core").get_text(" ", strip=True)
        for phrase in [
            "Paper-level Monitor provenance",
            "canonical paper",
            "fetch run",
            "Repeated observation",
            "Discovery is not storage",
        ]:
            self.assertIn(phrase, sqlite_text)

        visible_files_text = soup.find(
            "article", id="visible-research-files"
        ).get_text(" ", strip=True)
        for phrase in [
            "Supplements and other attachments are never eligible to become current",
            "annotation count",
            "computed as the resource is registered",
            "same content fingerprint",
        ]:
            self.assertIn(phrase, visible_files_text)

        versions_text = soup.find("article", id="versions-current").get_text(
            " ", strip=True
        )
        for phrase in [
            "Only publication versions can be current",
            "Other File attachments cannot become current",
            "does not automatically displace it",
        ]:
            self.assertIn(phrase, versions_text)

        download_text = soup.find("article", id="download-sync").get_text(
            " ", strip=True
        )
        for phrase in [
            "Validation before replacement",
            "Structural PDF validation",
            "temporary file",
            "existing valid file remains untouched",
            "skipped operation does not relabel the existing file",
        ]:
            self.assertIn(phrase, download_text)

        conversion_text = soup.find("article", id="drag-attach").get_text(
            " ", strip=True
        )
        for phrase in [
            "If the conversion cannot finish",
            "restores the original standalone files",
            "fingerprint fields",
        ]:
            self.assertIn(phrase, conversion_text)

        journal_text = soup.find("article", id="journal-monitor").get_text(
            " ", strip=True
        )
        for phrase in [
            "How discovery provenance is preserved",
            "canonical paper",
            "fetch run",
            "Later runs remain separately traceable",
            "do not automatically add a Library placement",
        ]:
            self.assertIn(phrase, journal_text)

        complete_text = soup.get_text(" ", strip=True)
        self.assertNotIn("schema 10", complete_text.lower())
        self.assertNotIn("ca63009", complete_text)

    def test_guide_documents_current_persistence_navigation_and_rendering_behavior(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")

        sqlite_text = soup.find("article", id="sqlite-core").get_text(" ", strip=True)
        for phrase in [
            "Durable preferences and shipped defaults",
            "one-time seed",
            "does not silently re-enable a journal",
            "reads the database schema version",
        ]:
            self.assertIn(phrase, sqlite_text)

        navigation_text = soup.find("article", id="navigation").get_text(" ", strip=True)
        for phrase in [
            "Library and Space columns",
            "main Library, a shortcut, and every Space",
            "returns to the same paper",
        ]:
            self.assertIn(phrase, navigation_text)

        journal_text = soup.find("article", id="journal-monitor").get_text(" ", strip=True)
        for phrase in [
            "enabled list, disabled history",
            "independent of Field Filter",
            "downloaded into a local cache",
            "changing to another date and back should not be necessary",
            "Su–Schrieffer–Heeger",
            "Monte Carlo",
        ]:
            self.assertIn(phrase, journal_text)

        startup_text = soup.find("article", id="startup").get_text(" ", strip=True)
        for phrase in [
            "Dock tile, native startup panel, and in-window loading state",
            "Web cache and macOS app identity are separate",
        ]:
            self.assertIn(phrase, startup_text)

        storage_text = soup.find("article", id="storage-reference").get_text(
            " ", strip=True
        )
        self.assertIn("data/cache/journal_logos", storage_text)

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
