import unittest

from paper_monitor.ui_server import INDEX_HTML


class SubjectMonitorUiTests(unittest.TestCase):
    def test_subject_toolbar_has_refresh_and_arxiv_hidden_by_default(self):
        toolbar = INDEX_HTML.split('id="themeToolbarActions"', 1)[1].split('</div>', 1)[0]

        self.assertIn('id="forceThemeFetch"', toolbar)
        self.assertIn('>Refresh</button>', toolbar)
        self.assertIn('id="themeArxivToggle"', toolbar)
        self.assertNotIn('id="themeArxivToggle" checked', toolbar)

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

    def test_arxiv_filter_is_display_only(self):
        visible = INDEX_HTML.split('function themeVisiblePapers', 1)[1].split(
            'function themePaperMatchesGroup', 1
        )[0]

        self.assertIn('state.showThemeArxiv || !themePaperIsArxiv(paper)', visible)
        self.assertNotIn('/api/', visible)

    def test_subject_keyboard_navigation_reuses_report_interactions(self):
        keyboard = INDEX_HTML.split('function handleReportKeydown', 1)[1].split(
            'function renderArxivUpdateCountdown', 1
        )[0]
        switcher = INDEX_HTML.split('function switchReportJournalTab', 1)[1].split(
            'function openSelectedReportPaperQuickLook', 1
        )[0]

        self.assertIn("['report', 'theme'].includes(state.mode)", keyboard)
        self.assertIn('return switchThemeSubjectTab(delta);', switcher)

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
        self.assertIn('Generate 10–14 English keyword phrases', prompt_logic)
        self.assertIn('one keyword phrase per line', prompt_logic)
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


if __name__ == "__main__":
    unittest.main()
