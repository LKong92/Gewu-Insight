from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup
from pypdf import PdfReader

from paper_monitor import ui_server


ROOT = Path(__file__).resolve().parents[1]


class UserGuideTests(unittest.TestCase):
    def local_handler(self):
        handler = object.__new__(ui_server.PaperMonitorUiHandler)
        handler.headers = {"Host": "127.0.0.1:8765"}
        handler.server = SimpleNamespace(server_port=8765)
        return handler

    def test_offline_guide_asset_is_loaded_from_the_python_package(self) -> None:
        expected = Path(ui_server.__file__).with_name("user_guide.html")
        self.assertEqual(ui_server.USER_GUIDE_PATH, expected)
        self.assertTrue(expected.is_file())
        html = ui_server.load_user_guide_html()
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertGreater(len(html), 40_000)

    def test_user_guide_route_reads_the_current_asset_without_browser_cache(self) -> None:
        handler = self.local_handler()
        handler.path = "/user-guide"
        handler.send_text = MagicMock()

        with patch.object(ui_server, "load_user_guide_html", return_value="<html>guide</html>") as loader:
            handler.do_GET()

        loader.assert_called_once_with()
        handler.send_text.assert_called_once_with(
            "<html>guide</html>", content_type="text/html; charset=utf-8"
        )

    def test_fixed_layout_pdf_route_serves_the_packaged_manual(self) -> None:
        handler = self.local_handler()
        handler.path = "/user-guide.pdf"
        handler.send_bytes = MagicMock()

        handler.do_GET()

        data = ui_server.USER_GUIDE_PDF_PATH.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-"))
        handler.send_bytes.assert_called_once_with(data, content_type="application/pdf")

    def test_user_guide_screenshot_route_serves_only_packaged_png_assets(self) -> None:
        handler = self.local_handler()
        handler.path = "/user-guide-assets/library-paper-files.png"
        handler.send_bytes = MagicMock()

        handler.do_GET()

        image_path = ui_server.USER_GUIDE_SCREENSHOT_ROOT / "library-paper-files.png"
        data = image_path.read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        handler.send_bytes.assert_called_once_with(data, content_type="image/png")

    def test_user_guide_calligraphy_route_uses_the_packaged_brand_asset(self) -> None:
        handler = self.local_handler()
        handler.path = "/api/about-calligraphy"
        handler.handle_about_calligraphy = MagicMock()

        handler.do_GET()

        handler.handle_about_calligraphy.assert_called_once_with()
        self.assertTrue(
            (ROOT / "assets" / "branding" / "GewuAboutCalligraphy.png").is_file()
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
            "Open Source Settings",
            "arXiv Scope Settings",
            "Field Settings",
            "Quick Look Settings",
            "Visual Identity and Cultural Elements",
            "Keyboard Shortcuts",
            "Back Up and Upgrade",
            "Troubleshooting",
        ]
        visible_text = soup.get_text(" ", strip=True)
        for phrase in required_text:
            self.assertIn(phrase, visible_text)

        self.assertNotIn("Development History", visible_text)
        self.assertNotIn("benchmark", visible_text.lower())

    def test_field_settings_topic_documents_default_visible_and_grouped_fields(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")
        article = soup.find("article", id="field-settings")
        self.assertIsNotNone(article)
        text = article.get_text(" ", strip=True)
        for phrase in (
            "Physics",
            "Quantum Information",
            "Materials Science",
            "Chemistry",
            "Astronomy & Astrophysics",
            "Particle & Nuclear Physics",
            "Other Fields",
            "All Fields",
            "Restore Defaults",
        ):
            self.assertIn(phrase, text)

    def test_visual_identity_chapter_documents_assets_sources_and_usage(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")
        article = soup.find("article", id="visual-identity")
        self.assertIsNotNone(article)
        self.assertEqual(article.get("data-group"), "About Gewu Insight")

        images = {image.get("src"): image for image in article.select("img[src]")}
        self.assertIn("/api/about-calligraphy", images)
        self.assertIn("/api/app-icon", images)
        self.assertIn("/api/startup-brand-art", images)

        source_links = {
            link.get_text(" ", strip=True): link.get("href")
            for link in article.select("table.glyph-provenance a[href]")
        }
        self.assertEqual(
            source_links,
            {
                "格": "https://www.shufa5.com/images/shufa/zi/5/35045.gif",
                "物": "https://www.shufa5.com/images/shufa/zi/6/165906.gif",
                "洞": "https://www.shufa5.com/images/shufa/zi/2/162202.gif",
                "見": "https://www.shufa5.com/images/shufa/zi/2/179662.gif",
            },
        )

        text = article.get_text(" ", strip=True)
        for phrase in [
            "祝枝山行草集字",
            "a title written by Zhu Zhishan",
            "traditional direction from right to left",
            "汉仪篆书繁",
            "The icon's two blue-violet fields",
            "Provenance and reuse",
            "Icon · recognition",
            "Calligraphy · signature",
            "Seal script · atmosphere",
        ]:
            self.assertIn(phrase, text)

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
            "arxiv-scope-settings",
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
            "Cross-platform core, platform-specific integration",
            "macOS native release",
            "Planned Windows release",
            "supported Windows package is available today",
            "What this guide covers",
            "Six main tabs",
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
            "Normalized paper-source observations are the authority",
            "first-seen and last-seen times",
            "cannot erase an earlier Journal, Subject, or Author observation",
            "compatibility projections",
            "Discovery is not storage",
        ]:
            self.assertIn(phrase, sqlite_text)

        persistent_paper_text = soup.find(
            "article", id="persistent-paper-object"
        ).get_text(" ", strip=True)
        for phrase in [
            "quarantined as an identity conflict",
            "instead of overwriting the saved paper or forcing a merge",
        ]:
            self.assertIn(phrase, persistent_paper_text)

        visible_files_text = soup.find(
            "article", id="visible-research-files"
        ).get_text(" ", strip=True)
        for phrase in [
            "do not become the automatic default",
            "annotation count",
            "computed as the resource is registered",
            "same content fingerprint",
        ]:
            self.assertIn(phrase, visible_files_text)

        versions_text = soup.find("article", id="versions-current").get_text(
            " ", strip=True
        )
        for phrase in [
            "Only the four publication types above participate in automatic selection",
            "manually choose any existing file except one classified as Invalid file",
            "manual choice is sticky",
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
            "does not create a Paper Files row until a download actually succeeds",
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
            "vertical source rail",
            "Library, shortcuts, and Spaces",
            "stays in the Library",
        ]:
            self.assertIn(phrase, navigation_text)

        guided_tour_text = soup.find("article", id="guided-tour").get_text(
            " ", strip=True
        )
        for phrase in [
            "double-click only blank title-bar space to zoom or restore the window",
            "Tabs, search and other controls do not resize it",
            "compact, flat search control",
            "Each research workspace retains its own query",
        ]:
            self.assertIn(phrase, guided_tour_text)

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
            "up to 120 seconds",
            "Automatic local-server recovery",
            "launcher starts it again",
            "stale sheet is dismissed automatically",
            "Monitor cache and macOS app identity are separate",
            "Setting > Font Size",
            "Compact",
            "Extra Large",
            "New app sessions apply the saved size automatically",
        ]:
            self.assertIn(phrase, startup_text)

        storage_text = soup.find("article", id="storage-reference").get_text(
            " ", strip=True
        )
        self.assertIn("data/cache/journal_logos", storage_text)

    def test_guide_documents_current_subject_resource_photo_and_quick_look_behavior(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")

        subject_text = soup.find("article", id="subject-monitor").get_text(" ", strip=True)
        for phrase in [
            "Moving to a date with no result does not switch",
            "calendar's day numbers describe the active subject",
            "including zero, with a superscript asterisk",
            "zero with an asterisk is not a confirmed empty result",
            "no stored results and no fetch record remains blank",
            "A later successful refresh removes the asterisk",
            "arXiv display option is enabled by default",
        ]:
            self.assertIn(phrase, subject_text)

        paper_files_text = soup.find("article", id="paper-files").get_text(" ", strip=True)
        for phrase in [
            "Click the size footer or its chevron",
            "Each card expands independently",
            "Library Paper Details no longer repeats this bundle",
            "Double-click the paper row to the left",
            "Shared files and external originals are preserved",
            "Set as Default",
            "Use Automatic Selection",
            "Understand a Missing File row",
            "SQLite still has a resource record",
            "older untyped migration alias",
        ]:
            self.assertIn(phrase, paper_files_text)

        versions_text = soup.find("article", id="versions-current").get_text(
            " ", strip=True
        )
        for phrase in [
            "recognized publisher host or a publisher-specific acquisition path",
            "generic web download with no stronger evidence remains Other",
            "Internal migration or ingestion markers are never user-facing source details",
        ]:
            self.assertIn(phrase, versions_text)

        quick_look = soup.find("article", id="quick-look")
        self.assertIsNotNone(quick_look)
        quick_look_text = quick_look.get_text(" ", strip=True)
        for phrase in [
            "document viewer starts first",
            "Page count and other metadata load in parallel",
            "bounded thumbnail cache",
            "does not change file type",
            "macOS Quick Look",
            "keyboard focus",
        ]:
            self.assertIn(phrase, quick_look_text)

        quick_look_settings = soup.find("article", id="quick-look-settings")
        self.assertIsNotNone(quick_look_settings)
        quick_look_settings_text = quick_look_settings.get_text(" ", strip=True)
        for phrase in [
            "Gewu Insight for all files",
            "Gewu Insight for PDFs, macOS for other files",
            "macOS Quick Look for all files",
            "The default",
            "keyboard focus remains in Gewu Insight",
        ]:
            self.assertIn(phrase, quick_look_settings_text)

        for phrase in [
            "remove only the selected removable resource",
            "does not delete the parent paper",
            "physical primary file used by older compatibility paths remains protected",
        ]:
            self.assertIn(phrase, paper_files_text)

        visible_files_text = soup.find("article", id="visible-research-files").get_text(
            " ", strip=True
        )
        for phrase in [
            "publisher hyperlinks",
            "internal navigation links",
            "do not make a freshly downloaded publisher or arXiv PDF",
        ]:
            self.assertIn(phrase, visible_files_text)

        author_text = soup.find("article", id="author-monitor").get_text(" ", strip=True)
        for phrase in [
            "Understand profile and publication sources",
            "automatically falls back to Semantic Scholar",
            "automatic publication refresh remains unavailable",
            "remain distinct evidence",
            "saved locally",
            "does not need to reopen SQLite or contact the image host for every row",
            "manual photo takes precedence",
        ]:
            self.assertIn(phrase, author_text)

    def test_guide_explains_influential_citations_and_comments_reports(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")
        paper_details = soup.find("article", id="paper-details").get_text(" ", strip=True)
        for phrase in [
            "Inspect influential citations",
            "Semantic Scholar’s classification",
            "cached locally for several hours",
            "temporarily throttled",
        ]:
            self.assertIn(phrase, paper_details)

        publications = soup.find("article", id="my-publications").get_text(" ", strip=True)
        for phrase in [
            "Build a citation-comments report",
            "citation-context sentences",
            "does not modify the publication metadata",
            "generated local reading artifact",
        ]:
            self.assertIn(phrase, publications)

    def test_user_manual_documents_library_and_monitor_add_workflows(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")

        organize = soup.find("article", id="organize").get_text(" ", strip=True)
        for phrase in [
            "Move an entire Space into Library",
            "Move Space to Library",
            "Destination in My Library",
            "does not create duplicate paper records",
        ]:
            self.assertIn(phrase, organize)

        imports = soup.find("article", id="import-files").get_text(" ", strip=True)
        for phrase in [
            "Add a paper by DOI, arXiv ID, URL, or title",
            "Review and confirm the resolved match",
            "reuses the canonical paper",
            "does not automatically download a PDF",
        ]:
            self.assertIn(phrase, imports)

        monitor_phrases = {
            "journal-monitor": [
                "Add a Journal result to Library",
                "Choose the target Library folder",
                "preserves its source and run provenance",
            ],
            "subject-monitor": [
                "Add a Subject result to Library",
                "preserves the matched subject, score, terms, and discovery provenance",
            ],
            "author-monitor": [
                "Add an author result to Library",
                "author-publication relationship and canonical identity remain intact",
            ],
        }
        for topic_id, phrases in monitor_phrases.items():
            topic_text = soup.find("article", id=topic_id).get_text(" ", strip=True)
            for phrase in phrases:
                self.assertIn(phrase, topic_text)
            self.assertIn("does not automatically download a PDF", topic_text)

    def test_guide_is_offline_searchable_and_printable(self) -> None:
        soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")
        settings_text = soup.find("article", id="citation-settings").get_text(" ", strip=True)
        self.assertIn("Configure Open Source Settings", settings_text)
        self.assertIn("fixed round dots by default", settings_text)
        self.assertIn("retrieved only on Show", settings_text)
        self.assertIn("cleared on Hide or when settings closes", settings_text)
        author_text = soup.find("article", id="author-monitor").get_text(" ", strip=True)
        self.assertIn("Read All", author_text)
        self.assertIn("other authors keep their unread state, even for a shared paper", author_text)
        self.assertIn("marks all authors' new publications as read", author_text)
        html = ui_server.load_user_guide_html()
        self.assertIn('id="guideSearch"', html)
        self.assertIn("hashchange", html)
        self.assertIn("showTopic", html)
        self.assertNotIn("window.print()", html)
        self.assertIn("messageHandlers?.openUserGuidePDF", html)
        self.assertIn("nativePDF.postMessage", html)
        self.assertIn("/user-guide.pdf", html)
        self.assertIn("@media print", html)
        soup = BeautifulSoup(html, "html.parser")
        self.assertFalse(soup.select("script[src]"))
        self.assertFalse(soup.select("link[href]"))
        self.assertFalse(soup.select("video[src], audio[src], source[src]"))
        self.assertEqual(
            {image.get("src") for image in soup.select("img[src]")},
            {
                "/api/about-calligraphy",
                "/api/app-icon",
                "/api/startup-brand-art",
                "/user-guide-assets/library-paper-files.png",
                "/user-guide-assets/space-workspace.png",
                "/user-guide-assets/my-publications.png",
                "/user-guide-assets/journal-monitor.png",
                "/user-guide-assets/subject-monitor.png",
                "/user-guide-assets/author-monitor.png",
                "/user-guide-assets/browser.png",
            },
        )

        screenshot_figures = soup.select("figure.guide-screenshot")
        self.assertEqual(len(screenshot_figures), 7)
        self.assertTrue(all(figure.find("figcaption") for figure in screenshot_figures))

    def test_release_bundle_continues_to_include_the_user_guide_asset(self) -> None:
        release_script = (ROOT / "scripts" / "make_release.sh").read_text(encoding="utf-8")
        self.assertIn('copy_item "paper_monitor"', release_script)
        self.assertIn('copy_item "assets"', release_script)

    def test_latex_manual_contains_the_complete_fixed_layout_guide(self) -> None:
        tex_path = ROOT / "paper_monitor" / "user_guide.tex"
        pdf_path = ui_server.USER_GUIDE_PDF_PATH
        self.assertTrue(tex_path.is_file())
        self.assertTrue(pdf_path.is_file())
        source = tex_path.read_text(encoding="utf-8")
        self.assertIn("\\documentclass", source)
        self.assertIn("\\part{Orientation}", source)
        self.assertIn("\\chapter{Welcome}", source)
        self.assertIn("\\chapter{Guided Tour}", source)
        self.assertIn("\\chapter{Your First Session}", source)
        self.assertIn("\\part{Product Concepts and Architecture}", source)
        self.assertIn("\\chapter{System Architecture at a Glance}", source)
        self.assertIn("\\chapter{The Persistent Paper Object}", source)
        self.assertIn("\\part{User Manual}", source)
        self.assertIn("\\chapter{Workspace Navigation}", source)
        self.assertIn("\\chapter{Papers and Files}", source)
        self.assertIn("\\chapter{My Publications}", source)
        self.assertIn("\\chapter{Journal Monitor}", source)
        self.assertIn("\\chapter{Subject Monitor}", source)
        self.assertIn("\\chapter{Author Monitor}", source)
        self.assertIn("\\part{Product Identity}", source)
        for title in ("Visual Identity and Cultural Elements", "The calligraphic name",
                      "The app icon and the seal-script watermark",
                      "Why the three marks are used differently"):
            self.assertIn("\\GewuIdentityChapter{" + title + "}", source)
            self.assertNotIn("\\chapter{" + title + "}", source)
        self.assertIn("\\part{Technical and Operational Reference}", source)
        self.assertIn("\\chapter{Keyboard Shortcuts}", source)
        self.assertIn("\\chapter{Storage Reference}", source)
        reader = PdfReader(str(pdf_path))
        self.assertGreater(len(reader.pages), 30)
        sample = " ".join((reader.pages[index].extract_text() or "") for index in [0, 1, len(reader.pages) - 1])
        self.assertIn("Gewu Insight", sample)
        self.assertIn("Copyright and product notice", sample)

    def test_app_builder_packages_the_fixed_layout_pdf(self) -> None:
        build_script = (ROOT / "scripts" / "build_macos_app.sh").read_text(encoding="utf-8")
        self.assertIn("Gewu_Insight_User_Guide.pdf", build_script)
        self.assertIn("Gewu Insight User Guide.pdf", build_script)


if __name__ == "__main__":
    unittest.main()
