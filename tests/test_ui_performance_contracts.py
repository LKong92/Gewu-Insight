from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from paper_monitor import ui_server


ROOT = Path(__file__).resolve().parents[1]


class UiPerformanceContractTests(unittest.TestCase):
    @staticmethod
    def js_function(name: str) -> str:
        marker = f"function {name}"
        start = ui_server.INDEX_HTML.index(marker)
        candidates = [
            position
            for position in (
                ui_server.INDEX_HTML.find("\n    function ", start + len(marker)),
                ui_server.INDEX_HTML.find("\n    async function ", start + len(marker)),
            )
            if position >= 0
        ]
        end = min(candidates) if candidates else len(ui_server.INDEX_HTML)
        return ui_server.INDEX_HTML[start:end]

    def test_launcher_uses_small_health_endpoint(self) -> None:
        route_source = inspect.getsource(ui_server.PaperMonitorUiHandler.do_GET)
        launcher_source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()
        helper_source = (ROOT / "Daiqo.app" / "Contents" / "MacOS" / "Paper Monitor Server").read_text()

        self.assertIn('parsed.path == "/api/health"', route_source)
        self.assertIn('@"api/health"', launcher_source)
        self.assertIn('HEALTH_URL="$URL/api/health"', helper_source)
        self.assertNotIn('curl -fsS "$URL"', helper_source)

    def test_navigation_refresh_does_not_replace_library_with_navigation_only_data(self) -> None:
        refresh = self.js_function("refreshLibrarySnapshotForNavigation")

        self.assertIn('/api/library/paper-locations', refresh)
        self.assertIn("applyLibraryNavigationSnapshot(data);", refresh)
        self.assertNotIn("applyLibrarySnapshot(data);", refresh)

    def test_common_library_mutations_request_incremental_responses(self) -> None:
        for function_name in (
            "commitLibraryEntryRename",
            "moveLibraryEntry",
            "deleteLibraryEntry",
            "recoverLibraryEntry",
        ):
            function_body = self.js_function(function_name)
            self.assertIn("snapshot: false", function_body, function_name)

    def test_import_completion_uses_bootstrap_refresh(self) -> None:
        for function_name in ("refreshLibraryAfterImportReady", "refreshLibraryAfterImportCompletion"):
            function_body = self.js_function(function_name)
            self.assertIn("refreshMainLibrarySnapshot", function_body, function_name)
            self.assertNotIn('fetch("/api/library")', function_body, function_name)
            self.assertNotIn("applyLibrarySnapshot", function_body, function_name)

    def test_my_publication_field_updates_return_one_publication(self) -> None:
        for handler_name in (
            "handle_star_my_publication",
            "handle_my_publication_head",
            "handle_my_publication_roles",
            "handle_my_publication_author_marks",
            "handle_my_publication_manual_metadata",
        ):
            source = inspect.getsource(getattr(ui_server.PaperMonitorUiHandler, handler_name))
            self.assertIn('"publication":', source, handler_name)
            self.assertNotIn("list_my_publications", source, handler_name)

    def test_journal_monitor_renders_before_independent_month_refresh(self) -> None:
        open_monitor = self.js_function("openJournalMonitor")

        self.assertIn("loadReport({showLoading: true})", open_monitor)
        self.assertIn("const monthPromise = loadMonth()", open_monitor)
        self.assertIn("Promise.all([reportPromise, monthPromise])", open_monitor)
        self.assertLess(open_monitor.index("loadReport({showLoading: true})"), open_monitor.index("loadMonth()"))

    def test_subject_monitor_replaces_old_surface_before_network_wait(self) -> None:
        open_monitor = self.js_function("openThemeMonitor")
        transition = self.js_function("renderThemeTransitionSurface")

        self.assertLess(open_monitor.index("renderThemeTransitionSurface()"), open_monitor.index("await ensureThemeGroupsLoaded()"))
        self.assertIn("const monthPromise = loadThemeMonth()", open_monitor)
        self.assertIn("Promise.all([monthPromise, reportPromise])", open_monitor)
        self.assertNotIn("loadThemeMonth({force: true})", open_monitor)
        self.assertIn('showMonitorStatusMessage("Loading subject papers for this date...")', transition)

    def test_my_publications_uses_one_background_load_and_stable_skeleton(self) -> None:
        loader = self.js_function("loadMyPublications")
        ensure = self.js_function("ensureMyPublicationsLoaded")
        renderer = self.js_function("renderMyPublications")

        self.assertLess(loader.index("renderMyPublications({loading:"), loader.index("await ensureMyPublicationsLoaded()"))
        self.assertIn("state.myPublicationsLoadingPromise", ensure)
        self.assertIn('fetch("/api/my-publications")', ensure)
        self.assertIn("myPublicationsLoadingRowsMarkup()", renderer)
        self.assertIn("myPublicationsLoadingStatsMarkup()", renderer)
        self.assertIn("myPublicationsLoadingDetailMarkup()", renderer)
        self.assertIn("scheduleMyPublicationsPrefetch();", ui_server.INDEX_HTML)

    def test_monitor_switch_preserves_loaded_paper_images(self) -> None:
        stasher = self.js_function("stashCurrentMonitorPaperSurface")
        renderer = self.js_function("renderMonitorPaperList")
        primary_view = self.js_function("setPrimaryView")
        journal_render = self.js_function("renderReport()")
        subject_render = self.js_function("renderThemeMonitor")

        self.assertIn("document.createDocumentFragment()", stasher)
        self.assertIn("state.monitorPaperDomCache[mode]", stasher)
        self.assertIn("cached.fragment", renderer)
        self.assertIn("root.dataset.monitorSignature === signature", renderer)
        self.assertIn("stashCurrentMonitorPaperSurface(paperRoot)", primary_view)
        self.assertIn('renderMonitorPaperList(root, activePapers, "report")', journal_render)
        self.assertIn('renderMonitorPaperList(root, activePapers, "theme")', subject_render)

    def test_monitor_sidebar_reserves_the_same_scrollbar_width(self) -> None:
        self.assertIn("scrollbar-gutter: stable;", ui_server.INDEX_HTML)
        self.assertIn("overflow-x: hidden;", ui_server.INDEX_HTML)
        self.assertIn("--monitor-calendar-width: 280px;", ui_server.INDEX_HTML)
        self.assertIn("width: var(--monitor-calendar-width);", ui_server.INDEX_HTML)

    def test_monitor_calendars_always_render_six_week_rows(self) -> None:
        calendar = self.js_function("renderCalendar")
        primary_view = self.js_function("setPrimaryView")

        self.assertIn("const trailingBlanks = 42 - startOffset - days", calendar)
        self.assertIn('blank.setAttribute("aria-hidden", "true")', calendar)
        self.assertIn("if (sidebar) sidebar.scrollTop = 0", primary_view)


if __name__ == "__main__":
    unittest.main()
