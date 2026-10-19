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

    def test_keyboard_navigation_moves_between_library_content_and_vertical_tabs(self) -> None:
        rail_keys = INDEX_HTML.split("function handleLibraryNavigationRailKeydown", 1)[1].split(
            "function handleLibraryKeydown", 1
        )[0]
        library_keys = INDEX_HTML.split("function handleLibraryKeydown", 1)[1].split(
            "function updatePaperState", 1
        )[0]

        self.assertIn("function libraryNavigationKeyboardButtons()", INDEX_HTML)
        self.assertIn("function focusLibraryNavigationRail()", INDEX_HTML)
        button_order = INDEX_HTML.split("function libraryNavigationKeyboardButtons", 1)[1].split(
            "function currentLibraryNavigationButton", 1
        )[0]
        self.assertIn("data-root-tab", button_order)
        self.assertIn("data-shortcut-tab", button_order)
        self.assertIn("data-workspace-tab", button_order)
        self.assertIn('key === "ArrowUp" || key === "ArrowDown"', rail_keys)
        self.assertIn('if (key === "ArrowRight")', rail_keys)
        self.assertIn("activateLibraryNavigationButton(next, {enterContent: false})", rail_keys)
        self.assertIn("focusLibraryContentAfterNavigation();", rail_keys)
        self.assertIn(
            "eventButton || (state.libraryNavigationRailFocus ? currentLibraryNavigationButton() : null)",
            rail_keys,
        )
        self.assertIn("const displayRootId = Number(libraryDisplayRootId()", library_keys)
        self.assertIn("return focusLibraryNavigationRail();", library_keys)
        self.assertNotIn("activatePrimaryKeyboardRoot()", library_keys)
        self.assertIn(".library-tab-rail .library-tab:focus-visible", INDEX_HTML)
        self.assertIn(".library-tab-rail.keyboard-active .library-tab:focus", INDEX_HTML)
        self.assertIn(".library-shell.navigation-rail-focus-active .library-row.active", INDEX_HTML)
        self.assertIn("libraryNavigationRailFocus: false", INDEX_HTML)
        self.assertIn("libraryNavigationFocusRevision: 0", INDEX_HTML)
        self.assertIn("function setLibraryNavigationRailFocus(active)", INDEX_HTML)

    def test_navigation_rail_focus_survives_async_renders_without_stealing_content_focus(self) -> None:
        focus_setter = INDEX_HTML.split("function setLibraryNavigationRailFocus", 1)[1].split(
            "function focusLibraryContentAfterNavigation", 1
        )[0]
        focus_restorer = INDEX_HTML.split("function focusCurrentLibraryNavigationButton", 1)[1].split(
            "function activateLibraryNavigationButton", 1
        )[0]
        activation = INDEX_HTML.split("function activateLibraryNavigationButton", 1)[1].split(
            "function handleLibraryNavigationRailKeydown", 1
        )[0]
        tab_render = INDEX_HTML.split("function renderLibraryShortcutTabs", 1)[1].split(
            "function captureLibraryNavigationScroll", 1
        )[0]

        self.assertIn("state.libraryNavigationFocusRevision", focus_setter)
        self.assertIn("if (!state.libraryNavigationRailFocus) return;", focus_restorer)
        self.assertIn("expectedRevision", focus_restorer)
        self.assertIn("setLibraryNavigationRailFocus(true)", activation)
        self.assertIn("focusCurrentLibraryNavigationButton(focusRevision)", activation)
        self.assertIn("if (state.libraryNavigationRailFocus)", tab_render)
        self.assertIn("focusCurrentLibraryNavigationButton(state.libraryNavigationFocusRevision)", tab_render)

    def test_live_navigation_tab_switches_keep_a_visible_root_entry_selected(self) -> None:
        root_selection = INDEX_HTML.split("function selectLibraryDisplayRootEntry", 1)[1].split(
            "function selectLibraryColumnFolder", 1
        )[0]
        shortcut_open = INDEX_HTML.split("async function openLibraryShortcutTab", 1)[1].split(
            "async function assignLibraryShortcutTab", 1
        )[0]
        workspace_open = INDEX_HTML.split("async function openLibraryWorkspaceTab", 1)[1].split(
            "async function renameLibraryWorkspace", 1
        )[0]

        self.assertIn("const remembered = ensureLibraryColumnSelection(displayRootId);", root_selection)
        self.assertIn("libraryEntriesForFolder(displayRootId)[0]", root_selection)
        self.assertIn("setLibraryColumnSelection(displayRootId, remembered || firstEntry);", root_selection)
        self.assertIn("selectLibraryDisplayRootEntry(folderId);", shortcut_open)
        self.assertIn("selectLibraryDisplayRootEntry(folderId);", workspace_open)
        self.assertNotIn('state.librarySelection = {type: "folder", id: folderId};', shortcut_open)
        self.assertNotIn('state.librarySelection = {type: "folder", id: folderId};', workspace_open)

    def test_navigation_rail_exposes_add_remove_and_reorder_actions(self) -> None:
        self.assertIn('data-nav-add="shortcut"', INDEX_HTML)
        self.assertIn('data-nav-remove="shortcut"', INDEX_HTML)
        self.assertIn('data-nav-add="workspace"', INDEX_HTML)
        self.assertNotIn('data-nav-remove="workspace"', INDEX_HTML)
        self.assertIn("wireLibraryNavigationTabDrag(button, \"shortcut\")", INDEX_HTML)
        self.assertIn("wireLibraryNavigationTabDrag(button, \"workspace\")", INDEX_HTML)
        self.assertIn('data-nav-draggable="true"', INDEX_HTML)
        self.assertIn('button.addEventListener("pointerdown"', INDEX_HTML)
        self.assertIn('button.addEventListener("pointermove"', INDEX_HTML)
        self.assertIn('button.addEventListener("pointerup"', INDEX_HTML)
        self.assertIn("document.elementFromPoint(clientX, clientY)", INDEX_HTML)
        self.assertIn("async function moveLibraryNavigationTab", INDEX_HTML)
        self.assertIn('}-tabs/reorder`, {', INDEX_HTML)
        self.assertIn("state.libraryNavDropTargetId", INDEX_HTML)
        self.assertIn("if (shouldCommit)", INDEX_HTML)
        self.assertNotRegex(INDEX_HTML, r'\stype="button"\s+draggable="true"\s+data-shortcut-tab')
        self.assertNotRegex(INDEX_HTML, r'\stype="button"\s+draggable="true"\s+data-workspace-tab')
        self.assertNotIn('if (!window.confirm(message)) return;', INDEX_HTML)

    def test_shortcut_and_space_context_menu_exposes_compact_actions(self) -> None:
        menu_markup = INDEX_HTML.split(
            '<div class="library-context-menu library-tab-context-menu" id="libraryTabContextMenu">',
            1,
        )[1].split('<div class="library-context-menu" id="libraryContextMenu">', 1)[0]
        menu_logic = INDEX_HTML.split("function showLibraryTabContextMenu", 1)[1].split(
            "function hideLibraryTabContextMenu", 1
        )[0]
        self.assertIn('data-action="remove-tab"', menu_markup)
        self.assertIn('data-action="rename-tab"', menu_markup)
        self.assertIn('"Remove Empty Space"', menu_logic)
        self.assertIn('"Remove Shortcut"', menu_logic)
        self.assertIn("renameButton", menu_logic)

    def test_navigation_rail_uses_soft_borderless_tabs_without_a_left_inset(self) -> None:
        rail_css = INDEX_HTML.split(".library-tab-rail {", 1)[1].split("}", 1)[0]
        tab_css = INDEX_HTML.split(".library-tab-rail .library-tab {", 1)[1].split("}", 1)[0]
        idle_css = INDEX_HTML.split(".library-tab-rail .library-tab:not(.active) {", 1)[1].split("}", 1)[0]
        active_css = INDEX_HTML.split(".library-tab-rail .library-tab.active {", 1)[1].split("}", 1)[0]
        self.assertIn("--library-vertical-tab-thickness: 30px;", rail_css)
        self.assertIn("left: 0;", tab_css)
        self.assertIn("border-radius: 13px 13px 0 0;", tab_css)
        self.assertIn("border: 0;", tab_css)
        self.assertIn("background: transparent;", tab_css)
        self.assertIn("opacity: 1;", idle_css)
        self.assertIn("filter: none;", idle_css)
        self.assertIn("background: transparent;", idle_css)
        self.assertIn("color: color-mix(in srgb, var(--library-tab-color) 80%, white);", idle_css)
        self.assertIn("color: #173f69;", active_css)
        self.assertIn("background: #dceafb;", active_css)
        self.assertIn("box-shadow: inset 0 2px 0 #4d8fd1;", active_css)
        tools_css = INDEX_HTML.split(".library-tab-section-tools {", 1)[1].split(
            ".library-tab-section.workspace-section", 1
        )[0]
        self.assertIn("width: 30px;", tools_css)
        self.assertIn("border: 0;", tools_css)
        self.assertIn("opacity: 1;", tools_css)
        self.assertIn("filter: none;", tools_css)
        self.assertNotIn("opacity: 0.34;", tools_css)
        self.assertIn(".library-tab-section-tools button:disabled { color: #667085;", INDEX_HTML)

    def test_root_shortcut_and_space_tabs_share_the_soft_active_palette(self) -> None:
        root_css = INDEX_HTML.split(".library-tab.root-tab {", 1)[1].split("}", 1)[0]
        shortcut_css = INDEX_HTML.split(".library-tab.shortcut-tab {", 1)[1].split("}", 1)[0]
        workspace_css = INDEX_HTML.split(".library-tab.workspace-tab {", 1)[1].split("}", 1)[0]
        for css in (root_css, shortcut_css, workspace_css):
            self.assertIn("--library-tab-active-bg: #dceafb;", css)
            self.assertIn("--library-tab-active-border: transparent;", css)
            self.assertIn("--library-tab-active-color: #173f69;", css)
        self.assertIn("--library-tab-idle-opacity: 0.38;", root_css)
        self.assertIn("--library-tab-idle-opacity: 0.44;", shortcut_css)
        self.assertIn("--library-tab-idle-opacity: 0.5;", workspace_css)

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

    def test_runtime_errors_do_not_replace_an_already_loaded_app(self) -> None:
        self.assertIn("let appBootCompleted = false;", INDEX_HTML)
        self.assertIn("appBootCompleted = true;", INDEX_HTML)
        self.assertIn("function handleGlobalUiError(error, source)", INDEX_HTML)
        self.assertIn("if (!appBootCompleted) {", INDEX_HTML)
        self.assertNotIn(
            'window.addEventListener("error", (event) => showBootError',
            INDEX_HTML,
        )

    def test_folder_navigation_avoids_full_index_and_listener_rebuilds(self) -> None:
        apply_children = INDEX_HTML.split("function applyLibraryFolderChildren", 1)[1].split(
            "function libraryFolderLoaded", 1
        )[0]
        select_entry = INDEX_HTML.split("function selectLibraryEntry", 1)[1].split(
            "function focusLibraryFolder", 1
        )[0]
        interactions = INDEX_HTML.split("function wireLibraryInteractions", 1)[1].split(
            "function libraryDragPayload", 1
        )[0]

        self.assertIn("state.libraryItemsByFolder.set(", apply_children)
        self.assertIn("state.libraryChildFoldersByParent.set(", apply_children)
        self.assertNotIn("rebuildLibraryIndexes()", apply_children)
        self.assertIn('if (type === "folder" && !options.extendRange && !libraryFolderLoaded(id))', select_entry)
        self.assertIn("loadLibraryFolderAndRender(id);", select_entry)
        self.assertIn('shell.addEventListener("click"', interactions)
        self.assertIn('shell.addEventListener("dragover"', interactions)
        self.assertNotIn('shell.querySelectorAll(".library-row").forEach', interactions)

    def test_partial_library_render_rebinds_paper_file_mouse_interactions(self) -> None:
        partial_render = INDEX_HTML.split("function renderLibraryNavigationContent", 1)[1].split(
            "function libraryViewTitle", 1
        )[0]
        resource_interactions = INDEX_HTML.split("function wireLibraryResourceInteractions", 1)[1].split(
            "function wireLibraryInteractions", 1
        )[0]
        full_interactions = INDEX_HTML.split("function wireLibraryInteractions", 1)[1].split(
            "function libraryDragPayload", 1
        )[0]

        self.assertIn("renderLibraryColumns({preserveRows})", partial_render)
        self.assertIn("renderLibraryDetail();", partial_render)
        self.assertIn("wireLibraryResourceInteractions(shell);", partial_render)
        self.assertIn('card.addEventListener("click"', resource_interactions)
        self.assertIn('card.addEventListener("contextmenu"', resource_interactions)
        self.assertIn("wireLibraryResourceInteractions(shell);", full_interactions)

    def test_partial_library_render_rebinds_column_marquee_interactions(self) -> None:
        partial_render = INDEX_HTML.split("function renderLibraryNavigationContent", 1)[1].split(
            "function libraryViewTitle", 1
        )[0]
        column_interactions = INDEX_HTML.split("function wireLibraryColumnInteractions", 1)[1].split(
            "function wireLibraryInteractions", 1
        )[0]
        full_interactions = INDEX_HTML.split("function wireLibraryInteractions", 1)[1].split(
            "function libraryDragPayload", 1
        )[0]

        self.assertIn("wireLibraryColumnInteractions(shell);", partial_render)
        self.assertIn('column.addEventListener("pointerdown"', column_interactions)
        self.assertIn('startDragSelection(event, "library")', column_interactions)
        self.assertIn("wireLibraryColumnInteractions(shell);", full_interactions)

    def test_delete_key_in_paper_files_deletes_only_the_selected_resource(self) -> None:
        resource_keydown = INDEX_HTML.split("function handleLibraryPaperResourceKeydown", 1)[1].split(
            "function quickLookLibraryPaperResource", 1
        )[0]
        resource_delete = INDEX_HTML.split("async function deleteSelectedLibraryPaperResource", 1)[1].split(
            "function handleLibraryPaperResourceKeydown", 1
        )[0]
        library_keydown = INDEX_HTML.split("function handleLibraryKeydown", 1)[1].split(
            "function renderLibraryDetail", 1
        )[0]

        self.assertIn('"Delete", "Backspace"', resource_keydown)
        self.assertIn("deleteSelectedLibraryPaperResource(selected);", resource_keydown)
        self.assertIn("event.stopImmediatePropagation", resource_keydown)
        self.assertNotIn("if (file?.is_primary)", resource_delete)
        self.assertNotIn("The current file cannot be deleted", resource_delete)
        self.assertIn("await deletePaperFile(paperId, resourceId)", resource_delete)
        self.assertNotIn("deleteSelectedLibraryEntries", resource_delete)
        self.assertLess(
            library_keydown.index("handleLibraryPaperResourceKeydown(event, key)"),
            library_keydown.index("runLibraryMenuAction(deleteSelectedLibraryEntries)"),
        )

    def test_internal_item_drag_does_not_arm_the_native_attachment_bridge(self) -> None:
        drag_start = INDEX_HTML.split('shell.addEventListener("dragstart"', 1)[1].split(
            'shell.addEventListener("dragend"', 1
        )[0]
        mouse_down = INDEX_HTML.split('shell.addEventListener("mousedown"', 1)[1].split(
            'shell.addEventListener("keydown"', 1
        )[0]

        self.assertIn('application/x-paper-monitor-library', drag_start)
        self.assertNotIn("armNativeLibraryItemDrop", drag_start)
        # File-icon gestures now carry the same typed payload as DOM drags.
        # This replaced the separate bridge in the September 17 drag fix.
        self.assertIn("prepareNativeFileDrag(handle)", mouse_down)
        native_prepare = INDEX_HTML.split("function prepareNativeFileDrag(handle)", 1)[1].split("function armNativeFolderDrag", 1)[0]
        self.assertIn('type: "item"', native_prepare)
        self.assertIn("library_payload: payload", native_prepare)

    def test_remote_avatar_fallbacks_do_not_access_a_removed_parent(self) -> None:
        self.assertNotIn("this.remove(); this.parentElement", INDEX_HTML)
        self.assertIn('data-fallback="${escapeAttr(initials)}"', INDEX_HTML)
        self.assertIn("if (this.parentElement) this.parentElement.textContent=this.dataset.fallback", INDEX_HTML)

    def test_completed_loader_summary_is_not_promoted_to_error_by_zero_failed_count(self) -> None:
        classifier = INDEX_HTML.split("function loaderLogKind(entry)", 1)[1].split(
            "function loaderLogLabel", 1
        )[0]
        done_index = classifier.index('message.startsWith("Done:")')
        error_text_index = classifier.index('/failed|error/i.test(message)')
        self.assertLess(done_index, error_text_index)
        self.assertLess(classifier.index('if (level === "warn")'), error_text_index)

    def test_returning_to_library_restores_the_last_navigation_location(self) -> None:
        self.assertIn("libraryLastLocation: null", INDEX_HTML)
        self.assertIn("function rememberLibraryLocation()", INDEX_HTML)
        self.assertIn("function restoreLibraryLastLocation()", INDEX_HTML)
        self.assertIn("if (!options.root) restoreLibraryLastLocation();", INDEX_HTML)
        self.assertIn("if (options.root) selectLibraryDisplayRootEntry(state.libraryRootId);", INDEX_HTML)
        self.assertIn("else if (!restoreLibraryLastLocation()) resetLibraryRootSelection();", INDEX_HTML)
        self.assertIn("loadLibrary({root: true})", INDEX_HTML)

    def test_space_dialog_explains_real_directory_semantics(self) -> None:
        self.assertIn('id="libraryNavBackdrop"', INDEX_HTML)
        self.assertIn("A matching folder will be created immediately under data/Spaces.", INDEX_HTML)
        self.assertIn("The Space becomes a normal folder with the same name", INDEX_HTML)

    def test_shortcut_and_space_move_use_column_folder_picker(self) -> None:
        self.assertIn('id="libraryNavFolderPicker"', INDEX_HTML)
        self.assertIn("function renderLibraryNavigationFolderPicker", INDEX_HTML)
        self.assertNotIn('id="libraryShortcutFolderSelect"', INDEX_HTML)
        self.assertIn('data-action="move-tab-library"', INDEX_HTML)
        self.assertNotIn('id="workspaceMoveToLibraryButton"', INDEX_HTML)
        self.assertIn("Move Space to Library", INDEX_HTML)
        self.assertIn("/api/library/workspace-tabs/move-to-library", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
