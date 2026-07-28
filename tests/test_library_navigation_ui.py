from __future__ import annotations

import unittest

from paper_monitor.ui_server import INDEX_HTML


class LibraryNavigationUiTests(unittest.TestCase):
    def test_navigation_rail_is_dynamic_and_independently_scrollable(self) -> None:
        self.assertIn('data-library-tab-section="shortcut"', INDEX_HTML)
        self.assertIn('data-library-tab-section="workspace"', INDEX_HTML)
        self.assertIn('data-library-tab-scroll="shortcut"', INDEX_HTML)
        self.assertIn('data-library-tab-scroll="workspace"', INDEX_HTML)
        self.assertIn("state.libraryShortcutTabs.map", INDEX_HTML)
        self.assertIn("state.libraryWorkspaceTabs.map", INDEX_HTML)
        self.assertIn("function updateLibraryNavigationRailLayout()", INDEX_HTML)
        self.assertIn("function libraryNavigationTabLength(label)", INDEX_HTML)
        self.assertIn("function libraryNavigationTabLayout(tabs, labelForTab)", INDEX_HTML)
        self.assertIn("--library-tab-length:", INDEX_HTML)
        self.assertNotIn("index * 92", INDEX_HTML)
        self.assertNotIn("LIBRARY_SHORTCUT_TAB_COUNT", INDEX_HTML)
        self.assertNotIn("LIBRARY_WORKSPACE_TAB_COUNT", INDEX_HTML)

    def test_navigation_rail_exposes_add_remove_and_reorder_actions(self) -> None:
        self.assertIn('data-nav-add="shortcut"', INDEX_HTML)
        self.assertIn('data-nav-remove="shortcut"', INDEX_HTML)
        self.assertIn('data-nav-add="workspace"', INDEX_HTML)
        self.assertNotIn('data-nav-remove="workspace"', INDEX_HTML)
        self.assertIn("wireLibraryNavigationTabDrag(button, \"shortcut\")", INDEX_HTML)
        self.assertIn("wireLibraryNavigationTabDrag(button, \"workspace\")", INDEX_HTML)
        self.assertIn("async function moveLibraryNavigationTab", INDEX_HTML)
        self.assertIn('}-tabs/reorder`, {', INDEX_HTML)
        self.assertIn("state.libraryNavDropTargetId", INDEX_HTML)
        self.assertIn("if (shouldCommit)", INDEX_HTML)
        self.assertNotIn('if (!window.confirm(message)) return;', INDEX_HTML)

    def test_shortcut_and_space_context_menu_uses_library_style_without_rename(self) -> None:
        menu_markup = INDEX_HTML.split(
            '<div class="library-context-menu library-tab-context-menu" id="libraryTabContextMenu">',
            1,
        )[1].split("</div>", 1)[0]
        menu_logic = INDEX_HTML.split("function showLibraryTabContextMenu", 1)[1].split(
            "function hideLibraryTabContextMenu", 1
        )[0]
        self.assertIn('data-action="remove-tab"', menu_markup)
        self.assertNotIn('data-action="rename-tab"', menu_markup)
        self.assertIn('"Remove Empty Space"', menu_logic)
        self.assertIn('"Remove Shortcut"', menu_logic)
        self.assertNotIn("renameButton", menu_logic)

    def test_only_navigation_tabs_fade_while_section_tools_stay_emphasized(self) -> None:
        self.assertIn(".library-tab-rail .library-tab:not(.active)", INDEX_HTML)
        self.assertIn("filter: saturate(0.28) brightness(1.12);", INDEX_HTML)
        tools_css = INDEX_HTML.split(".library-tab-section-tools {", 1)[1].split(
            ".library-tab-section.workspace-section", 1
        )[0]
        self.assertIn("opacity: 1;", tools_css)
        self.assertIn("filter: none;", tools_css)
        self.assertNotIn("opacity: 0.34;", tools_css)
        self.assertIn(".library-tab-section-tools button:disabled { color: #667085;", INDEX_HTML)

    def test_navigation_rail_never_scrolls_horizontally(self) -> None:
        rail_css = INDEX_HTML.split(".library-tab-rail {", 1)[1].split("}", 1)[0]
        scroll_css = INDEX_HTML.split(".library-tab-scroll {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-x: hidden;", rail_css)
        self.assertIn("overflow-x: hidden;", scroll_css)
        self.assertNotIn("overflow-x: visible;", rail_css)
        self.assertNotIn("overflow-x: visible;", scroll_css)

    def test_dynamic_tab_measurement_does_not_emit_javascript_nul_bytes(self) -> None:
        self.assertNotIn("\x00", INDEX_HTML)
        self.assertIn("character.codePointAt(0)", INDEX_HTML)

    def test_library_boot_failure_replaces_the_startup_cover(self) -> None:
        self.assertIn("Promise.resolve().then(loadLibrary).catch((error) => {", INDEX_HTML)
        self.assertIn("showBootError(error);", INDEX_HTML)

    def test_space_dialog_explains_real_directory_semantics(self) -> None:
        self.assertIn('id="libraryNavBackdrop"', INDEX_HTML)
        self.assertIn("A matching folder will be created immediately under data/Spaces.", INDEX_HTML)
        self.assertIn("The Space becomes a normal folder with the same name", INDEX_HTML)

    def test_shortcut_and_space_move_use_column_folder_picker(self) -> None:
        self.assertIn('id="libraryNavFolderPicker"', INDEX_HTML)
        self.assertIn("function renderLibraryNavigationFolderPicker", INDEX_HTML)
        self.assertNotIn('id="libraryShortcutFolderSelect"', INDEX_HTML)
        self.assertIn('id="workspaceMoveToLibraryButton"', INDEX_HTML)
        self.assertIn("Move Space to Library", INDEX_HTML)
        self.assertIn("/api/library/workspace-tabs/move-to-library", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
