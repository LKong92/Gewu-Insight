from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import ui_server
from paper_monitor.storage import APS_RECLASSIFICATION_SETTING, STORAGE_SCHEMA_VERSION, Storage


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
        helper_source = (ROOT / "Gewu Insight.app" / "Contents" / "MacOS" / "Gewu Insight Server").read_text()

        self.assertIn('parsed.path == "/api/health"', route_source)
        self.assertIn('@"api/health"', launcher_source)
        self.assertIn('HEALTH_URL="$URL/api/health"', helper_source)
        self.assertNotIn('curl -fsS "$URL"', helper_source)

    def test_storage_runs_schema_and_seed_work_only_once_per_database_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                schema_version = int(
                    storage.conn.execute("PRAGMA user_version").fetchone()[0]
                )
            finally:
                storage.close()

            with patch.object(
                Storage,
                "_ensure_schema_columns",
                side_effect=AssertionError("schema migration repeated"),
            ):
                reopened = Storage(db_path)
                reopened.close()

        self.assertEqual(schema_version, STORAGE_SCHEMA_VERSION)

    def test_storage_runs_versioned_aps_cleanup_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                completed = storage.conn.execute(
                    "SELECT value FROM app_settings WHERE key = ?",
                    (APS_RECLASSIFICATION_SETTING,),
                ).fetchone()
            finally:
                storage.close()

            with patch.object(
                Storage,
                "_apply_aps_record_reclassification",
                side_effect=AssertionError("APS cleanup repeated"),
            ):
                reopened = Storage(db_path)
                reopened.close()

        self.assertIsNotNone(completed)

    def test_loaded_library_navigation_preserves_the_existing_shell(self) -> None:
        partial_renderer = self.js_function("renderLibraryNavigationContent")
        self.assertIn("renderLibraryColumns();", partial_renderer)
        self.assertIn("renderLibraryDetail();", partial_renderer)
        self.assertNotIn("root.innerHTML", partial_renderer)
        self.assertNotIn("wireLibraryInteractions();", partial_renderer)

        for function_name in (
            "loadLibraryFolderAndRender",
            "selectLibraryEntry",
            "focusLibraryFolder",
        ):
            function_body = self.js_function(function_name)
            self.assertIn("renderLibraryNavigationContent();", function_body, function_name)
            self.assertNotIn("renderLibrary();", function_body, function_name)

    def test_author_monitor_card_cache_is_a_rebuildable_sqlite_index(self) -> None:
        schema = ui_server.Storage.__module__
        self.assertEqual(schema, "paper_monitor.storage")
        storage_source = inspect.getsource(Storage)
        self.assertIn("list_author_monitor_card_cache_candidates", storage_source)
        self.assertIn("upsert_author_monitor_card_cache", storage_source)
        self.assertIn("list_author_monitor_cached_cards", storage_source)
        self.assertIn("author_monitor_card_cache_status", storage_source)
        self.assertIn("request_author_monitor_card_cache_build(db_path)", inspect.getsource(ui_server.run_ui_server))

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

    def test_journal_library_round_trip_restores_the_monitor_viewport(self) -> None:
        show_in_library = self.js_function("showPaperInLibrary")
        add_to_library = self.js_function("addPaperToLibrary")
        open_monitor = self.js_function("openJournalMonitor")

        self.assertIn("captureMonitorViewport(article)", show_in_library)
        self.assertIn("state.monitorReturnViewports[monitorViewport.mode] = monitorViewport", show_in_library)
        self.assertIn("renderCurrentPaperSurface({monitorViewport})", add_to_library)
        self.assertIn("const returnViewport = state.monitorReturnViewports.report", open_monitor)
        self.assertGreater(
            open_monitor.index("restoreMonitorViewport(returnViewport)"),
            open_monitor.index("await Promise.all([reportPromise, monthPromise])"),
        )
        self.assertIn("state.monitorReturnViewports.report = null", open_monitor)

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

    def test_my_publications_uses_one_bottom_activity_bar_without_guidance(self) -> None:
        status_text = self.js_function("myPublicationSearchStatusText")
        status_items = self.js_function("myPublicationStatusItems")
        profile_markup = self.js_function("myPublicationScholarProfileMarkup")
        search_results = self.js_function("myPublicationSearchResultsMarkup")
        renderer = self.js_function("renderMyPublications")

        self.assertNotIn("myPublicationNameHint", ui_server.INDEX_HTML)
        self.assertNotIn("Use DOI/arXiv/title, or search by name", ui_server.INDEX_HTML)
        self.assertNotIn("Working on the lookup", ui_server.INDEX_HTML)
        self.assertIn('if (!results.length) return "";', search_results)
        self.assertIn('return state.myPublicationSearchStatus || "";', status_text)
        self.assertIn('class="my-publications-status-bar" aria-live="polite"', renderer)
        self.assertIn("myPublicationStatusBarMarkup()", renderer)
        self.assertIn('grid-template-rows: minmax(0, 1fr) 28px;', ui_server.INDEX_HTML)
        self.assertIn('.my-publications-status-bar .publication-search-status:empty', ui_server.INDEX_HTML)
        self.assertIn('.my-publications-status-bar .publication-search-status.secondary', ui_server.INDEX_HTML)
        publication_status_css = ui_server.INDEX_HTML.split(".publication-search-status {", 1)[1].split("}", 1)[0]
        publication_live_css = ui_server.INDEX_HTML.split(".publication-search-status.live {", 1)[1].split("}", 1)[0]
        library_live_css = ui_server.INDEX_HTML.split(".library-activity-status.live {", 1)[1].split("}", 1)[0]
        author_live_css = ui_server.INDEX_HTML.split(".author-monitor-status-bar .library-activity-status.live {", 1)[1].split("}", 1)[0]
        self.assertIn("font-size: 12px;", publication_status_css)
        self.assertIn("line-height: 16px;", publication_status_css)
        self.assertIn("font-weight: 700;", publication_live_css)
        self.assertIn("animation: statusLiveBreath 1.8s", publication_live_css)
        self.assertIn("animation: statusLiveBreath 1.8s", library_live_css)
        self.assertIn("animation: statusLiveBreath 1.8s", author_live_css)
        self.assertIn("@keyframes statusDotBreath", ui_server.INDEX_HTML)
        self.assertIn("rgba(190, 216, 241, 0.58)", ui_server.INDEX_HTML)
        self.assertIn("color: rgba(31, 79, 122, 0.38);", ui_server.INDEX_HTML)
        self.assertIn("color: rgba(31, 79, 122, 1);", ui_server.INDEX_HTML)
        self.assertNotIn("@keyframes statusFlow", ui_server.INDEX_HTML)
        self.assertNotIn(".publication-search-status.live::after", ui_server.INDEX_HTML)
        self.assertNotIn(".library-activity-status.live::after", ui_server.INDEX_HTML)
        self.assertNotIn(".author-monitor-status-bar .library-activity-status.live::after", ui_server.INDEX_HTML)
        status_bar_css = ui_server.INDEX_HTML.split(".my-publications-status-bar {", 1)[1].split("}", 1)[0]
        self.assertIn("background: #f2f2f2;", status_bar_css)
        self.assertIn("state.myPublicationActivities", status_items)
        self.assertIn("slice(0, 2)", status_items)
        self.assertIn("const profileLabel = `Using ${profile.name", profile_markup)
        self.assertNotIn("state.myPublicationSearchStatus", profile_markup)
        self.assertNotIn("state.myPublicationActivities", profile_markup)
        self.assertIn('.library-controls:has(.my-publications-tools.open)', ui_server.INDEX_HTML)
        self.assertIn('margin: 2px 0 10px;', ui_server.INDEX_HTML)
        profile_host_css = ui_server.INDEX_HTML.split("#myPublicationProfileStripHost {", 1)[1].split("}", 1)[0]
        avatar_css = ui_server.INDEX_HTML.split(".my-publications-profile-avatar {", 1)[1].split("}", 1)[0]
        clear_css = ui_server.INDEX_HTML.split(".my-publications-profile-clear {", 1)[1].split("}", 1)[0]
        self.assertIn("height: 28px;", profile_host_css)
        self.assertIn("max-height: 28px;", profile_host_css)
        self.assertIn("width: 42px;", avatar_css)
        self.assertIn("height: 42px;", avatar_css)
        self.assertIn("width: 18px;", clear_css)
        self.assertIn("height: 18px;", clear_css)
        tools_markup = ui_server.INDEX_HTML.split('<div class="my-publications-tools" id="myPublicationsTools">', 1)[1].split('</div>\n          </div>\n          <div class="papers"', 1)[0]
        self.assertNotIn('id="publicationSearchStatus"', tools_markup)

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
        self.assertIn("--monitor-calendar-width: 254px;", ui_server.INDEX_HTML)
        self.assertIn("width: var(--monitor-calendar-width);", ui_server.INDEX_HTML)
        self.assertNotIn("--monitor-calendar-width: 100%;", ui_server.INDEX_HTML)

    def test_monitor_calendar_updates_existing_day_buttons_without_rebuilding(self) -> None:
        render_calendar = self.js_function("renderCalendar")
        update_day = self.js_function("updateCalendarDayButton")

        self.assertIn("if (root.dataset.structureKey !== structureKey)", render_calendar)
        self.assertIn('root.querySelectorAll(".day[data-date]")', render_calendar)
        self.assertIn("updateCalendarDayButton(button, iso, day)", render_calendar)
        self.assertIn("if (button.className !== className)", update_day)
        self.assertIn("if (button.innerHTML !== markup)", update_day)
        self.assertIn("transition: none;", ui_server.INDEX_HTML)

    def test_journal_and_subject_context_menus_share_library_styling(self) -> None:
        journal_menu = self.js_function("showJournalContextMenu")
        subject_menu = self.js_function("showThemeContextMenu")

        shared_classes = "library-context-menu open theme-context-menu"
        self.assertIn(shared_classes, journal_menu)
        self.assertIn(shared_classes, subject_menu)
        self.assertIn('class="library-menu-separator" role="separator"', subject_menu)
        self.assertIn(".library-context-menu.theme-context-menu", ui_server.INDEX_HTML)

    def test_journal_sidebar_filters_use_flat_grouped_rows(self) -> None:
        journal_filters = self.js_function("renderFilters")
        subject_filters = self.js_function("renderSubjectFilters")

        self.assertIn(".journal-sidebar-filter .journal-toggle.active", ui_server.INDEX_HTML)
        self.assertIn("#subjectFilters .subject-option.active", ui_server.INDEX_HTML)
        self.assertIn('class="journal-add-panel"', ui_server.INDEX_HTML)
        self.assertNotIn(".journal-setting-row + .journal-setting-row", ui_server.INDEX_HTML)
        self.assertIn(".journal-add-panel .search", ui_server.INDEX_HTML)
        self.assertIn('label.className = `journal-toggle journal-sortable${selected ? " active" : ""}`', journal_filters)
        self.assertIn('option.innerHTML = `<input type="checkbox" ${selected ? "checked" : ""}>', subject_filters)
        self.assertIn('option.querySelector("input").addEventListener("change", () => {', subject_filters)
        self.assertIn("grid-template-columns: 18px minmax(0, 1fr) auto;", ui_server.INDEX_HTML)

    def test_journal_filter_counts_ignore_the_field_filter(self) -> None:
        journal_filters = self.js_function("renderFilters")

        self.assertIn(".filter((paper) => !isPreprintPaper(paper))", journal_filters)
        self.assertNotIn("subjectMatches(paper)", journal_filters)

    def test_report_sidebar_filter_and_settings_rows_are_compact(self) -> None:
        report_sidebar_css = ui_server.INDEX_HTML.split(
            ".app.report-mode .journal-sidebar-filter .journal-toggle,", 1
        )[1].split("/* Earlier shared controls retain", 1)[0]

        self.assertIn("min-height: 26px;", report_sidebar_css)
        self.assertIn("padding-top: 1px;", report_sidebar_css)
        self.assertIn("padding: 1px 0 1px 39px;", report_sidebar_css)

    def test_primary_reading_surfaces_share_flat_visual_language(self) -> None:
        html = ui_server.INDEX_HTML

        self.assertIn("--flat-divider:", html)
        self.assertIn(".app.report-mode .calendar", html)
        self.assertIn(".app.report-mode .journal-tab.active", html)
        self.assertIn(".app.report-mode .paper.report-selected", html)
        self.assertIn(".app.author-mode .author-paper-card.report-selected", html)
        self.assertIn(".library-detail .citation-source-cell.active", html)
        self.assertIn(".library-detail .library-detail-abstract", html)
        self.assertIn("background: #e3e5e7;", html)
        self.assertNotIn('id="jumpToday"', html)

    def test_monitor_calendars_render_only_the_weeks_the_month_uses(self) -> None:
        calendar = self.js_function("renderCalendar")
        primary_view = self.js_function("setPrimaryView")

        self.assertIn("const calendarCells = Math.ceil(occupiedCells / 7) * 7", calendar)
        self.assertIn("const trailingBlanks = calendarCells - occupiedCells", calendar)
        self.assertIn('blank.setAttribute("aria-hidden", "true")', calendar)
        self.assertIn("if (sidebar) sidebar.scrollTop = 0", primary_view)

    def test_arrow_navigation_can_move_between_content_and_primary_tabs(self) -> None:
        primary = self.js_function("handlePrimaryKeyboardNavigation")
        switcher = self.js_function("switchPrimaryKeyboardView")
        focus_content = self.js_function("focusPrimarySurfaceContent")
        report = self.js_function("handleReportKeydown")
        author = self.js_function("handleAuthorMonitorKeydown")
        library = self.js_function("handleLibraryKeydown")

        self.assertIn('PRIMARY_KEYBOARD_VIEWS = ["library", "my-publications", "report", "theme", "author"]', ui_server.INDEX_HTML)
        self.assertIn("switchPrimaryKeyboardView", primary)
        self.assertIn("focusPrimarySurfaceContent", primary)
        self.assertIn("activatePrimaryKeyboardRoot()", report)
        self.assertIn("activatePrimaryKeyboardRoot()", author)
        self.assertNotIn("activatePrimaryKeyboardRoot()", library)
        self.assertIn("focusLibraryNavigationRail()", library)
        self.assertIn("handleLibraryNavigationRailKeydown(event, key)", library)
        self.assertIn("handlePrimaryKeyboardNavigation(event)", ui_server.INDEX_HTML)
        self.assertIn(".view-switcher.keyboard-active .view-switch.active", ui_server.INDEX_HTML)
        self.assertIn(".view-switch:focus-visible", ui_server.INDEX_HTML)
        self.assertIn("border-bottom-color: transparent;", ui_server.INDEX_HTML)
        self.assertNotIn("box-shadow: inset 0 0 0 2px rgba(15, 107, 110, 0.68);", ui_server.INDEX_HTML)
        self.assertIn('if (key === "ArrowUp") return true;', primary)
        self.assertIn("Math.min(PRIMARY_KEYBOARD_VIEWS.length - 1, currentIndex + delta)", switcher)
        self.assertIn("if (nextIndex === currentIndex)", switcher)
        self.assertNotIn("% PRIMARY_KEYBOARD_VIEWS.length", switcher)
        self.assertIn(
            'state.authorMonitorKeyboardPane === "authors" ? "authors" : "papers"',
            focus_content,
        )
        self.assertIn(".author-monitor-paper-list .author-paper-card", focus_content)
        self.assertIn(".author-monitor-author", focus_content)

    def test_monitor_source_navigation_stops_at_each_end(self) -> None:
        journal = self.js_function("switchReportJournalTab")
        subject = self.js_function("switchThemeSubjectTab")

        for switcher in (journal, subject):
            self.assertIn("Math.max(0, Math.min(groups.length - 1, baseIndex + delta))", switcher)
            self.assertIn("if (nextIndex === baseIndex) return true;", switcher)
            self.assertNotIn("% groups.length", switcher)

    def test_monitor_calendar_keyboard_navigation_updates_content_but_keeps_focus(self) -> None:
        keyboard = self.js_function("handleReportKeydown")
        move_cursor = self.js_function("moveMonitorCalendarCursor")
        enter_date = self.js_function("enterMonitorCalendarDate")
        return_to_calendar = self.js_function("returnMonitorFocusToCalendar")
        journal_open = self.js_function("openJournalMonitor")
        subject_open = self.js_function("openThemeMonitor")

        self.assertIn('"ArrowLeft": -1', keyboard)
        self.assertIn('"ArrowRight": 1', keyboard)
        self.assertIn('"ArrowUp": -7', keyboard)
        self.assertIn('"ArrowDown": 7', keyboard)
        self.assertIn("moveMonitorCalendarCursor(calendarDeltas[key])", keyboard)
        self.assertIn("enterMonitorCalendarDate()", keyboard)
        self.assertIn("setCalendarDateForActiveMode(nextIso)", move_cursor)
        self.assertIn("loadThemeReportForDate(nextIso)", move_cursor)
        self.assertIn("loadReport()", move_cursor)
        self.assertIn("focusMonitorCalendarCursor(mode)", move_cursor)
        self.assertIn('state.monitorKeyboardPanes[mode] = "papers"', enter_date)
        self.assertIn("focusMonitorPaperSelection(mode, {scroll: true})", enter_date)
        self.assertNotIn("loadReport()", enter_date)
        self.assertIn('key === "Escape"', keyboard)
        self.assertIn("returnMonitorFocusToCalendar()", keyboard)
        self.assertIn("state.monitorCalendarCursorDates[mode] = iso", return_to_calendar)
        self.assertIn("focusMonitorCalendarCursor(mode)", return_to_calendar)
        self.assertIn('restoreMonitorKeyboardFocus("report")', journal_open)
        self.assertIn('restoreMonitorKeyboardFocus("theme")', subject_open)
        self.assertIn(".day.keyboard-current:not(.active)", ui_server.INDEX_HTML)
        subject_render = self.js_function("renderThemeMonitor")
        self.assertIn(
            'if (!currentGroup) setActiveThemeGroupKey(groups[0]?.key || "", {renderCalendar: false})',
            subject_render,
        )
        self.assertNotIn("firstNonEmptyGroup", subject_render)


if __name__ == "__main__":
    unittest.main()
