import unittest

from paper_monitor.ui_server import INDEX_HTML


class SubjectMonitorUiTests(unittest.TestCase):
    def test_subject_toolbar_has_refresh_and_optional_sources_hidden_by_default(self):
        toolbar = INDEX_HTML.split('id="themeToolbarActions"', 1)[1].split('</div>', 1)[0]

        self.assertIn('id="forceThemeFetch"', toolbar)
        self.assertIn('>Refresh</button>', toolbar)
        self.assertIn('id="themeArxivToggle"', toolbar)
        self.assertIn('id="themeZenodoToggle"', toolbar)
        self.assertNotIn('id="themeArxivToggle" checked', toolbar)
        self.assertNotIn('id="themeZenodoToggle" checked', toolbar)

    def test_subjects_render_as_journal_style_tabs(self):
        render_tabs = INDEX_HTML.split('function renderThemeTabs', 1)[1].split(
            'function activeThemePapers', 1
        )[0]

        self.assertIn('journal-tab subject-tab', render_tabs)
        self.assertIn('journal-tab-count', render_tabs)
        self.assertIn('subject-add-tab', render_tabs)
        self.assertIn('showThemeContextMenu', render_tabs)
        self.assertIn('moveThemeGroup', render_tabs)
        self.assertLess(render_tabs.index('subject-add-tab'), render_tabs.index('groups.forEach'))

    def test_subject_fetch_scope_includes_all_configured_subjects(self):
        selection = INDEX_HTML.split('function selectedThemeGroupKeys', 1)[1].split(
            'function selectedThemeGroupParam', 1
        )[0]

        self.assertIn('return knownThemeGroupKeys();', selection)

    def test_arxiv_and_zenodo_filters_are_display_only(self):
        visible = INDEX_HTML.split('function themeVisiblePapers', 1)[1].split(
            'function themePaperMatchesGroup', 1
        )[0]

        self.assertIn('state.showThemeArxiv || !themePaperIsArxiv(paper)', visible)
        self.assertIn('state.showThemeZenodo || !themePaperIsZenodo(paper)', visible)
        self.assertNotIn('/api/', visible)
        self.assertIn('doi.startsWith("10.5281/zenodo.")', INDEX_HTML)
        self.assertIn('url.includes("zenodo.org/")', INDEX_HTML)

    def test_figure_mode_keeps_a_stable_column_when_image_lookup_fails(self):
        render_paper = INDEX_HTML.split('function renderPaper', 1)[1].split(
            'function themePaperMetaMarkup', 1
        )[0]
        hydrate = INDEX_HTML.split('async function hydratePaperFigure', 1)[1].split(
            'function openInternalBrowser', 1
        )[0]

        self.assertIn('const reserveFigure = state.showFigures;', render_paper)
        self.assertIn('showReportFigurePlaceholderForArticle(article)', render_paper)
        self.assertNotIn('article.classList.remove("with-figure")', render_paper)
        self.assertIn('showReportFigurePlaceholder(paperId)', hydrate)
        self.assertIn('.paper-figure.missing {', INDEX_HTML)

    def test_journal_and_subject_paper_titles_use_the_same_black_color(self):
        render_paper = INDEX_HTML.split('function renderPaper', 1)[1].split(
            'function themePaperMetaMarkup', 1
        )[0]
        title_css = INDEX_HTML.split('.paper h3 {', 1)[1].split('}', 1)[0]

        self.assertIn('color: var(--ink)', title_css)
        self.assertNotIn('style="color:${paper.section_color}"', render_paper)

    def test_subject_keyboard_navigation_reuses_report_interactions(self):
        keyboard = INDEX_HTML.split('function handleReportKeydown', 1)[1].split(
            'function renderArxivUpdateCountdown', 1
        )[0]
        selection = INDEX_HTML.split('function selectReportPaper', 1)[1].split(
            'function switchReportJournalTab', 1
        )[0]
        switcher = INDEX_HTML.split('function switchReportJournalTab', 1)[1].split(
            'function openSelectedReportPaperQuickLook', 1
        )[0]

        self.assertIn("['report', 'theme'].includes(state.mode)", keyboard)
        self.assertIn('return switchThemeSubjectTab(delta);', switcher)
        self.assertIn('state.libraryQuickLookOpen', selection)
        self.assertIn('refreshSelectedReportPaperQuickLook({open: true})', selection)
        self.assertIn('quickLookLibraryPdf(previewPaper, {silent: true})', INDEX_HTML)
        self.assertIn('showLibraryQuickLookPlaceholder({open: true})', INDEX_HTML)

    def test_subject_dialog_points_to_codex_instead_of_recommending_keywords(self):
        dialog = INDEX_HTML.split('id="themeGroupBackdrop"', 1)[1].split(
            'id="citationSettingsBackdrop"', 1
        )[0]

        self.assertIn("Use Codex AI to generate relevant keywords.", dialog)
        self.assertNotIn("Recommend Keywords", dialog)
        self.assertNotIn('id="recommendThemeKeywords"', INDEX_HTML)
        self.assertNotIn("function recommendThemeKeywords()", INDEX_HTML)

    def test_subject_dialog_copies_a_title_specific_codex_prompt(self):
        dialog = INDEX_HTML.split('id="themeGroupBackdrop"', 1)[1].split(
            'id="citationSettingsBackdrop"', 1
        )[0]
        prompt_logic = INDEX_HTML.split('function suggestedThemeKeywordPrompt', 1)[1].split(
            'function closeThemeGroupDialog', 1
        )[0]

        self.assertIn('id="copyThemeKeywordPrompt"', dialog)
        self.assertIn('Copy Suggested Prompt', dialog)
        self.assertIn('type="button" disabled', dialog)
        self.assertIn('`Subject: "${subjectName}"`', prompt_logic)
        self.assertIn('Create a minimal, non-redundant keyword list', prompt_logic)
        self.assertIn('Usually 4–10 terms are enough', prompt_logic)
        self.assertIn('remove the longer candidate because it adds no recall', prompt_logic)
        self.assertIn('one term per line', prompt_logic)
        self.assertNotIn('Generate 10–14 English keyword phrases', prompt_logic)
        self.assertIn('no bullets', prompt_logic)
        self.assertIn('no blank lines', prompt_logic)
        self.assertIn('copyTextToClipboard(suggestedThemeKeywordPrompt(subjectName))', prompt_logic)
        self.assertIn('button.textContent = "Copied"', prompt_logic)

    def test_subject_tab_can_refresh_only_that_subject(self):
        menu = INDEX_HTML.split('function showThemeContextMenu', 1)[1].split(
            'function confirmThemeGroupDelete', 1
        )[0]
        refresh = INDEX_HTML.split('async function forceFetchSelectedThemeDate', 1)[1].split(
            'function cancelThemeFetch', 1
        )[0]

        self.assertIn('Refresh This Subject', menu)
        self.assertIn('refreshThemeGroupForDate(group)', menu)
        self.assertIn('forceFetchSelectedThemeDate(group.key)', refresh)
        self.assertIn('groups=${groups}&auto_fetch=1&force_fetch=1', refresh)
        self.assertIn('forceFetchSelectedThemeDate("ALL")', INDEX_HTML)

    def test_subject_fetch_progress_is_resumed_after_switching_back(self):
        open_monitor = INDEX_HTML.split('async function openThemeMonitor', 1)[1].split(
            'async function runThemeSearch', 1
        )[0]
        load_report = INDEX_HTML.split('async function loadThemeReportForDate', 1)[1].split(
            'async function loadThemeCachedReportAfterFailure', 1
        )[0]

        self.assertIn('await resumeActiveThemeFetch(state.selectedDate)', open_monitor)
        self.assertIn('progress.active === false', open_monitor)
        self.assertIn('state.themeFetchingDates.add(selectedDate)', open_monitor)
        self.assertIn('watchThemeFetchCompletion(selectedDate, selectedThemeGroupParam())', open_monitor)
        self.assertIn('supersededWhileFetchContinues', load_report)
        self.assertIn('state.themeFetchCompletionWatchers.has(themeFetchCompletionKey', load_report)
        self.assertIn('if (!supersededWhileFetchContinues)', load_report)

    def test_browsing_subject_dates_never_starts_a_network_fetch(self):
        load_report = INDEX_HTML.split('async function loadThemeReportForDate', 1)[1].split(
            'async function loadThemeCachedReportAfterFailure', 1
        )[0]

        self.assertIn('options.autoFetch === true && !hasCompleteFetchRecord', load_report)
        self.assertNotIn('options.autoFetch !== false', load_report)
        self.assertIn('const autoFetch = shouldFetchRemote ? "1" : "0"', load_report)

    def test_journal_tab_uses_custom_single_journal_refresh_menu(self):
        tabs = INDEX_HTML.split('function renderReportTabs', 1)[1].split(
            'function updateReportTabsOverflow', 1
        )[0]
        menu = INDEX_HTML.split('function showJournalContextMenu', 1)[1].split(
            'function showThemeContextMenu', 1
        )[0]
        refresh = INDEX_HTML.split('function refreshCurrentJournalDate', 1)[1].split(
            'async function refreshCurrentArxivDate', 1
        )[0]

        self.assertIn('button.addEventListener("contextmenu"', tabs)
        self.assertIn('showJournalContextMenu(event, group.journal)', tabs)
        self.assertIn('Refresh This Journal', menu)
        self.assertIn('refreshCurrentJournalDate(journalName)', menu)
        self.assertIn('refreshJournal: journalName', refresh)
        self.assertIn('refresh_journal=${encodeURIComponent(refreshJournal)}', INDEX_HTML)

    def test_monitor_status_and_progress_stay_outside_the_scrolling_paper_list(self):
        layout = INDEX_HTML.split('<section class="report-column">', 1)[1].split(
            '</section>', 1
        )[0]
        theme_render = INDEX_HTML.split('function renderThemeMonitor', 1)[1].split(
            'function themeLastFetchLabel', 1
        )[0]
        theme_progress = INDEX_HTML.split('function updateThemeFetchProgressDisplay', 1)[1].split(
            'function themeFetchProgressMarkup', 1
        )[0]
        journal_render = INDEX_HTML.split('function renderReport()', 1)[1].split(
            'function renderLateArrivalsBanner', 1
        )[0]

        self.assertLess(layout.index('id="autoUpdateStatus"'), layout.index('id="reportTabs"'))
        self.assertLess(layout.index('id="reportTabs"'), layout.index('id="fetchProgressHost"'))
        self.assertLess(layout.index('id="fetchProgressHost"'), layout.index('id="monitorStatusHost"'))
        self.assertLess(layout.index('id="monitorStatusHost"'), layout.index('id="papers"'))
        self.assertIn('const root = $("fetchProgressHost")', theme_progress)
        self.assertNotIn('$("papers")?.querySelector("[data-theme-fetch-progress]")', theme_progress)
        self.assertIn('updateThemeFetchProgressDisplay(state.selectedDate)', theme_render)
        self.assertNotIn('root.insertAdjacentHTML("beforeend", themeFetchProgressMarkup', theme_render)
        self.assertNotIn('renderLateArrivalsBanner(statusRoot)', journal_render)
        self.assertIn('renderArxivUpdateCountdown(statusRoot', journal_render)
        self.assertIn('renderMonitorPaperList(root, activePapers, "report")', journal_render)

    def test_monitor_header_stats_updates_and_late_arrivals_move_to_the_sidebar(self):
        sidebar = INDEX_HTML.split('<aside class="sidebar">', 1)[1].split('</aside>', 1)[0]
        toolbar = INDEX_HTML.split('<div class="toolbar">', 1)[1].split(
            '<div class="summary" id="summary">', 1
        )[0]
        sidebar_render = INDEX_HTML.split('function renderMonitorSidebarSummary()', 1)[1].split(
            'function renderReport()', 1
        )[0]
        auto_status = INDEX_HTML.split('function renderAutoMonitorStatus()', 1)[1].split(
            'async function refreshAutoMonitorStatus', 1
        )[0]

        self.assertIn('id="monitorSidebarSummary"', sidebar)
        self.assertIn('id="autoUpdateStatus"', toolbar)
        self.assertIn('.app.report-mode .summary,', INDEX_HTML)
        self.assertIn('.app.theme-mode .summary {', INDEX_HTML)
        self.assertIn('"Papers", `${state.papers.length} total · ${filtered.length} shown`', sidebar_render)
        self.assertIn('"Results", `${saved} saved · ${raw} raw hits`', sidebar_render)
        self.assertIn('"Last fetch", lastFetch', sidebar_render)
        self.assertIn('"Updates", updates', sidebar_render)
        self.assertIn('if (state.mode === "report") renderLateArrivalsBanner(root)', sidebar_render)
        self.assertIn('.app.report-mode .auto-update-status.open,', INDEX_HTML)
        self.assertIn('renderMonitorSidebarSummary();', auto_status)

    def test_automatic_update_status_is_polled_and_failed_subject_fetches_are_incomplete(self):
        completeness = INDEX_HTML.split('function themeFetchRecordIsComplete', 1)[1].split(
            'function themePapersCacheKey', 1
        )[0]
        polling = INDEX_HTML.split('function refreshAutoMonitorStatus', 1)[1].split(
            'function setPrimaryView', 1
        )[0]
        load_report = INDEX_HTML.split('async function loadThemeReportForDate', 1)[1].split(
            'async function loadThemeCachedReportAfterFailure', 1
        )[0]

        self.assertIn('["success", "empty"]', completeness)
        self.assertIn('themeFetchRecordIsComplete(lastFetch, requestedGroupParam)', load_report)
        self.assertIn('fetchJson("/api/monitor-auto-status"', polling)
        self.assertIn('window.setInterval(refreshAutoMonitorStatus, 60000)', polling)
        self.assertIn('still incomplete after 3 retries', INDEX_HTML)

    def test_subject_progress_distinguishes_partial_waiting_and_failure(self):
        status = INDEX_HTML.split('function themeFetchSubjectStatus', 1)[1].split(
            'function themeFetchSubjectMeta', 1
        )[0]

        self.assertIn('status === "partial"', status)
        self.assertIn('label: "Partial"', status)
        self.assertIn('status === "waiting"', status)
        self.assertIn('label: "Waiting"', status)
        self.assertIn('status === "error"', status)
        self.assertIn('label: "Failed"', status)


if __name__ == "__main__":
    unittest.main()
