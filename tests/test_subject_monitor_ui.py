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


if __name__ == "__main__":
    unittest.main()
