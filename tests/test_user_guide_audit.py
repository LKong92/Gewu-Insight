"""Guard the concrete documentation drift found in the September 2026 audit."""
import re
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from paper_monitor import ui_server
from paper_monitor.storage import PAPER_FILE_TYPES

ROOT = Path(__file__).resolve().parents[1]


class GuideAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.soup = BeautifulSoup(ui_server.load_user_guide_html(), "html.parser")

    def topic(self, identifier):
        return self.soup.find("article", id=identifier).get_text(" ", strip=True)

    def test_audit_inventory_covers_every_registered_topic(self):
        audit = (ROOT / "docs/USER_GUIDE_AUDIT.md").read_text()
        documented = re.findall(r'user_guide\.html#([a-z-]+)\)', audit)
        topics = [article["id"] for article in self.soup.select("article.guide-topic")]
        self.assertCountEqual(documented, topics)
        self.assertIn("September 7, 2026", self.topic("welcome"))
        self.assertNotIn("five top-level areas", self.topic("personal-research-workspace"))
        self.assertIn("sixth main tab", self.topic("personal-research-workspace"))

    def test_file_labels_match_runtime_choices_not_retired_attachment_roles(self):
        function = ui_server.INDEX_HTML.split("function paperFileRoleOptions(file)", 1)[1].split("return options.map", 1)[0]
        choices = dict(re.findall(r'\["([a-z_]+)", "([^"]+)"\]', function))
        self.assertEqual(set(choices), set(PAPER_FILE_TYPES))
        for label in choices.values():
            self.assertIn(label, self.topic("versions-current"))
        adoption = self.topic("drag-attach")
        self.assertNotIn("Choose Image, Data, Code", adoption)
        self.assertIn("Supplementary material", adoption)
        self.assertIn("Other", adoption)
        self.assertIn("physical primary", self.topic("troubleshooting"))
        self.assertIn("switching defaults does not guarantee", self.topic("troubleshooting"))

    def test_profile_and_loader_instructions_use_real_labels_and_context(self):
        profile_button = BeautifulSoup(ui_server.INDEX_HTML, "html.parser").find(id="findMyPublications")
        self.assertIn(profile_button.get_text(strip=True), self.topic("my-publications"))
        self.assertNotIn("Find by Name", self.topic("my-publications"))
        self.assertIn("does not upload", self.topic("my-publications"))
        self.assertIn("Outside Browser", self.topic("folder-loader"))

    def test_shortcut_rows_distinguish_tabs_quick_look_and_workspace_search(self):
        rows = self.soup.find("article", id="keyboard").select("tr")
        mapping = {row.find("td").get_text("", strip=True): row.find_all("td")[1].get_text(" ", strip=True)
                   for row in rows if row.find("td")}
        self.assertIn("new webpage tab", mapping["⌘T"])
        self.assertIn("source workspace", mapping["⌘["])
        self.assertIn("Command-left bracket", self.topic("browser"))
        for boundary in ("selected webpage tab", "last creates Home", "Quick Look", "window"):
            self.assertIn(boundary, mapping["⌘W"])
        self.assertIn("workspace search", mapping["⌘F"])
        self.assertIn("not restored", mapping["⌘Q"])

    def test_browser_privacy_and_lifecycle_limits_are_explicit(self):
        browser = self.topic("browser")
        self.assertIn("Source follows the PDF’s actual website", browser)
        self.assertIn("Local files use User import without a webpage source", browser)
        self.assertIn("Exact duplicates retain their existing source", browser)
        self.assertNotIn("Source is User import", browser)
        for phrase in ("local history suggestions", "not live Google suggestions", "memory",
                       "not restored after App quit", "Passkey", "successful filling are not guaranteed"):
            self.assertIn(phrase, browser)
        backup = self.topic("backup-migrate")
        for phrase in ("outside this project", "Apple Passwords", "sign in again", "API keys", "memory-only"):
            self.assertIn(phrase, backup)
        self.assertIn("Home displays local Favorites without a Google request", self.topic("troubleshooting"))
        self.assertIn("even after restarting the App", browser)
        self.assertIn("Reload on Home refreshes local bookmarks", browser)
        self.assertNotIn("Native zoom fits Google", browser)
        self.assertIn("origin and sandbox rules", browser)
        troubleshooting = self.topic("troubleshooting")
        self.assertIn("verification can still reject an embedded browser", troubleshooting)
        self.assertIn("without sharing cookies or passwords", troubleshooting)
        self.assertIn("not Browser's Clear History", self.topic("startup"))
        for hour in (ui_server.AUTO_JOURNAL_MONITOR_HOUR, ui_server.AUTO_SUBJECT_MONITOR_HOUR,
                     ui_server.AUTO_AUTHOR_MONITOR_HOUR):
            self.assertIn(f"{hour:02d}:00", self.topic("startup"))

    def test_browser_figure_uses_real_app_capture_not_the_synthetic_fixture(self):
        figure = self.soup.find("article", id="browser").find("figure")
        caption = figure.find("figcaption").get_text(" ", strip=True)
        self.assertIn("Captured from the original App", caption)
        self.assertIn("Nature's research articles", caption)
        self.assertIn("real bookmark collection", caption)
        self.assertIn("not a generated demonstration", caption)
        self.assertNotIn("public sample bookmarks", caption)
        self.assertNotIn("earlier screenshot", caption)
        renderer = (ROOT / "scripts/render_browser_guide_example.cjs").read_text()
        self.assertIn("paper_monitor/browser_ui.css", renderer)
        self.assertIn("paper_monitor/browser_ui.js", renderer)
        self.assertIn("route.abort()", renderer)
        self.assertIn("require('node:os').tmpdir()", renderer)
        self.assertNotIn("assets/user-guide/screenshots/browser.png", renderer)
