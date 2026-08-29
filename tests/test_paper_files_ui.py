from __future__ import annotations

import unittest
from pathlib import Path

from paper_monitor.ui_server import INDEX_HTML


ROOT = Path(__file__).resolve().parents[1]


class PaperFilesUiTests(unittest.TestCase):
    def test_non_pdf_quick_look_uses_the_selected_engine_and_keeps_browser_fallback(self) -> None:
        quicklook = INDEX_HTML.split("function nativeQuickLookBridgeAvailable", 1)[1].split(
            "async function openNativeTarget", 1
        )[0]
        self.assertIn("messageHandlers?.nativeQuickLook", quicklook)
        self.assertIn('postNativeQuickLook(action, path)', quicklook)
        self.assertIn('state.libraryQuickLookKind = "native-file"', quicklook)
        self.assertIn("const useNativeQuickLook = nativeQuickLookBridgeAvailable()", quicklook)
        self.assertIn("options.forceNative || quickLookUsesNativeForPaper(paper)", quicklook)
        self.assertIn("if (useNativeQuickLook)", quicklook)
        self.assertIn("renderLibraryQuickLookFilePreview(paper, token)", quicklook)
        self.assertIn('state.libraryQuickLookKind = "file"', quicklook)
        self.assertIn("window.closeGewuInsightNativeQuickLookFromNative", INDEX_HTML)
        self.assertIn("window.handleGewuInsightNativeQuickLookKey", INDEX_HTML)
        self.assertIn("handleGewuInsightWindowKeydown({", INDEX_HTML)
        self.assertIn('target: document.body', INDEX_HTML)
        self.assertNotIn('new KeyboardEvent("keydown"', INDEX_HTML)
        self.assertIn(
            'window.addEventListener("keydown", handleGewuInsightWindowKeydown, true)',
            INDEX_HTML,
        )
        self.assertIn('state.libraryQuickLookKind === "pdf"', INDEX_HTML)

    def test_shared_paper_details_show_gewu_key_without_repeating_title(self) -> None:
        metadata = INDEX_HTML.split("function libraryDetailMetadataMarkup", 1)[1].split(
            "function libraryDetailFolderOccurrencesMarkup", 1
        )[0]
        self.assertIn("<dt>Gewu Key</dt>", metadata)
        self.assertIn("paper.storage_key", metadata)
        self.assertIn("gewu-storage-key", metadata)
        self.assertNotIn("<dt>Title</dt>", metadata)
        self.assertGreaterEqual(INDEX_HTML.count("libraryDetailMetadataMarkup(paper"), 6)

    def test_preprint_identifier_can_be_edited_inline_from_shared_paper_details(self) -> None:
        metadata = INDEX_HTML.split("function libraryDetailMetadataMarkup", 1)[1].split(
            "function libraryDetailFolderOccurrencesMarkup", 1
        )[0]
        self.assertIn('class="library-preprint-identifier"', metadata)
        self.assertIn('data-action="edit-preprint-identifier"', metadata)
        self.assertIn('title="Click to edit the arXiv identifier"', metadata)
        self.assertIn('class="preprint-identifier-input"', metadata)
        self.assertIn('main.classList.add("is-editing")', metadata)
        self.assertIn('fetch("/api/library/preprint-identifier"', metadata)
        self.assertIn('if (event.key === "Enter"', metadata)
        self.assertIn('if (event.key === "Escape"', metadata)
        self.assertNotIn("showPreprintIdentifierContextMenu", metadata)
        self.assertNotIn("openPreprintIdentifierEditor", metadata)
        self.assertGreaterEqual(INDEX_HTML.count("wirePreprintIdentifierControls(root, paper)"), 5)

    def test_shared_paper_details_keep_an_empty_preprint_row_editable(self) -> None:
        metadata = INDEX_HTML.split("function libraryDetailMetadataMarkup", 1)[1].split(
            "function libraryDetailFolderOccurrencesMarkup", 1
        )[0]
        self.assertIn("const showPreprintRow = options.hidePreprint !== true", metadata)
        self.assertIn("const preprintDisplay = preprintId ? escapeHtml", metadata)
        self.assertIn(': "—"', metadata)
        self.assertIn("<dt>DOI</dt>", metadata)
        self.assertIn("${showPreprintRow ? `<dt>arXiv</dt>", metadata)
        self.assertIn('preprint-identifier-value${preprintId ? "" : " is-empty"}', metadata)
        self.assertIn('${preprintId ? `<button class="action preprint-icon-action"', metadata)

    def test_managed_works_can_download_latest_or_sync_all_arxiv_versions(self) -> None:
        metadata = INDEX_HTML.split("function libraryDetailMetadataMarkup", 1)[1].split(
            "function libraryDetailFolderOccurrencesMarkup", 1
        )[0]
        self.assertIn('data-action="download-arxiv-latest"', metadata)
        self.assertIn("options.managePreprintFiles", metadata)
        self.assertIn('data-action="sync-arxiv-versions"', INDEX_HTML)
        self.assertIn('fetch("/api/paper-files/arxiv"', INDEX_HTML)
        self.assertIn('mode: syncAll ? "all" : "latest"', INDEX_HTML)
        self.assertGreaterEqual(INDEX_HTML.count("managePreprintFiles: true"), 4)
        author_detail = INDEX_HTML.split("function renderAuthorMonitorPaperDetail", 1)[1].split(
            "async function downloadAuthorMonitorPdf", 1
        )[0]
        self.assertNotIn("managePreprintFiles: true", author_detail)

    def test_paper_detail_actions_are_compact_and_preprint_actions_use_icons(self) -> None:
        self.assertIn(".library-detail > .actions .action", INDEX_HTML)
        self.assertIn("min-height: 26px;", INDEX_HTML)
        self.assertIn(".preprint-identifier-actions .preprint-icon-action", INDEX_HTML)
        metadata = INDEX_HTML.split("function libraryDetailMetadataMarkup", 1)[1].split(
            "function libraryDetailFolderOccurrencesMarkup", 1
        )[0]
        self.assertIn('aria-label="Open arXiv page"', metadata)
        self.assertIn('aria-hidden="true">↗</span>', metadata)
        self.assertIn('aria-label="Download latest arXiv PDF"', metadata)
        self.assertIn('aria-hidden="true">↓</span>', metadata)
        self.assertNotIn('data-action="open-preprint-page" data-preprint-url="${escapeAttr(preprintUrl)}">Open</button>', metadata)

    def test_single_line_metadata_rows_and_identifier_controls_share_a_compact_height(self) -> None:
        self.assertIn("gap: 6px 18px;", INDEX_HTML)
        self.assertIn(".library-detail dt { min-height: 22px;", INDEX_HTML)
        self.assertIn(".library-detail dd { min-height: 22px;", INDEX_HTML)
        self.assertIn(".library-detail .library-detail-doi > .action", INDEX_HTML)
        self.assertIn("height: 22px;", INDEX_HTML)
        doi_markup = INDEX_HTML.split("function libraryDetailDoiMarkup", 1)[1].split(
            "function libraryDetailFilesMarkup", 1
        )[0]
        self.assertIn('const value = paper?.doi || ""', doi_markup)
        self.assertIn('placeholder="Enter DOI"', doi_markup)

    def test_library_and_my_publications_share_the_files_panel(self) -> None:
        self.assertIn("function paperFilesPanelMarkup(paper)", INDEX_HTML)
        self.assertGreaterEqual(INDEX_HTML.count("${paperFilesPanelMarkup(paper)}"), 2)
        self.assertIn(">Add File</button>", INDEX_HTML)
        self.assertIn("Published Version", INDEX_HTML)
        self.assertIn("Accepted Manuscript", INDEX_HTML)
        self.assertIn("Preprint", INDEX_HTML)

    def test_library_paper_row_opens_a_resource_column(self) -> None:
        self.assertIn("function libraryPaperResourcesColumnMarkup(item)", INDEX_HTML)
        self.assertIn("library-resource-column", INDEX_HTML)
        self.assertIn("data-library-resource-path", INDEX_HTML)
        self.assertIn('const meta = "›";', INDEX_HTML)

    def test_resource_column_uses_an_attachment_inspector_instead_of_folder_rows(self) -> None:
        resources = INDEX_HTML.split("function libraryPaperResourcesColumnMarkup", 1)[1].split(
            "function libraryColumnFolderIds", 1
        )[0]
        self.assertIn("library-resource-inspector-head", resources)
        self.assertIn(">Paper Files</strong>", resources)
        self.assertIn("library-resource-section", resources)
        self.assertIn("library-resource-card", resources)
        self.assertIn('CURRENT: "Primary file"', resources)
        self.assertIn('VERSIONS: "Other versions"', resources)
        self.assertIn('FILES: "Attachments"', resources)
        self.assertIn("library-resource-state", resources)
        self.assertNotIn("library-resource-row", resources)

    def test_empty_and_loading_file_states_share_a_compact_inline_component(self) -> None:
        resources = INDEX_HTML.split("function libraryPaperResourcesColumnMarkup", 1)[1].split(
            "function libraryColumnFolderIds", 1
        )[0]
        panel = INDEX_HTML.split("function paperFilesPanelMarkup", 1)[1].split(
            "async function loadPaperFiles", 1
        )[0]

        self.assertIn("function paperFilesStatusMarkup(kind)", INDEX_HTML)
        self.assertIn('paperFilesStatusMarkup(snapshot ? "empty" : "loading")', resources)
        self.assertIn('paperFilesStatusMarkup("loading")', panel)
        self.assertIn('paperFilesStatusMarkup("empty")', panel)
        self.assertIn('class="paper-files-status ', INDEX_HTML)
        self.assertIn('class="paper-files-status-title"', INDEX_HTML)
        self.assertIn('class="paper-files-status-hint"', INDEX_HTML)
        self.assertIn('class="paper-files-status-spinner"', INDEX_HTML)
        self.assertNotIn('<div class="empty">', resources)
        self.assertNotIn("No local files attached.", INDEX_HTML)

    def test_library_folder_loading_and_empty_states_use_the_same_compact_component(self) -> None:
        columns = INDEX_HTML.split("function libraryColumnMarkup", 1)[1].split(
            "function renderLibrarySearchResults", 1
        )[0]

        self.assertIn("function surfaceInlineStatusMarkup", INDEX_HTML)
        self.assertIn('surfaceInlineStatusMarkup("loading", "Loading folder")', columns)
        self.assertIn('surfaceInlineStatusMarkup("empty", "Empty folder"', columns)
        self.assertNotIn('<div class="empty">Loading folder...</div>', columns)
        self.assertNotIn('<div class="empty">Right-click to create a folder', columns)

    def test_resource_cards_select_on_click_and_open_only_on_double_click(self) -> None:
        interactions = INDEX_HTML.split('shell.querySelectorAll(".library-resource-card[data-library-resource-id]")', 1)[1].split(
            'shell.querySelectorAll("[data-library-resource-role]")', 1
        )[0]
        self.assertIn('card.addEventListener("click"', interactions)
        self.assertIn("setLibraryPaperResourceSelection", interactions)
        self.assertNotIn("openNativePaperFile", interactions.split('card.addEventListener("dblclick"', 1)[0])
        self.assertIn('card.addEventListener("dblclick"', interactions)
        self.assertIn("openLibraryPaperResource(file)", interactions)
        self.assertIn('card.addEventListener("contextmenu"', interactions)
        self.assertIn("showPaperResourceContextMenu", interactions)
        self.assertIn("library-resource-card.is-selected", INDEX_HTML)

    def test_current_file_identity_is_separate_from_paper_files_focus(self) -> None:
        self.assertNotIn(".library-resource-card.is-primary {", INDEX_HTML)
        self.assertNotIn(".library-resource-card.is-primary .library-resource-icon-tile", INDEX_HTML)
        self.assertIn(".library-shell.paper-files-focus-active .library-row.active", INDEX_HTML)
        selector = INDEX_HTML.split("function setLibraryPaperResourceSelection", 1)[1].split(
            "function clearLibraryPaperResourceSelection", 1
        )[0]
        self.assertIn('classList.toggle("paper-files-focus-active"', selector)
        clearer = INDEX_HTML.split("function clearLibraryPaperResourceSelection", 1)[1].split(
            "function activateLibraryPaperFiles", 1
        )[0]
        self.assertIn('classList.remove("paper-files-focus-active")', clearer)
        renderer = INDEX_HTML.split("function renderLibrary()", 1)[1].split(
            "function renderLibrarySearchResults", 1
        )[0]
        self.assertIn('paperFilesFocusActive ? " paper-files-focus-active" : ""', renderer)

    def test_resource_cards_have_direct_file_type_picker(self) -> None:
        resources = INDEX_HTML.split("function libraryPaperResourcesColumnMarkup", 1)[1].split(
            "function libraryColumnFolderIds", 1
        )[0]
        self.assertIn("data-library-resource-role", resources)
        self.assertIn("paperFileRoleOptions(file)", resources)
        self.assertIn("paper-file-version-arrows", resources)
        interactions = INDEX_HTML.split('shell.querySelectorAll("[data-library-resource-role]")', 1)[1].split(
            'shell.querySelectorAll("[data-library-resource-paper]")', 1
        )[0]
        self.assertIn('select.addEventListener("change"', interactions)
        self.assertIn("setPaperFileRole", interactions)
        self.assertIn('event.stopPropagation()', interactions)

    def test_paper_files_use_a_dedicated_context_menu(self) -> None:
        self.assertIn('id="paperResourceContextMenu"', INDEX_HTML)
        self.assertIn('data-action="open-paper-resource"', INDEX_HTML)
        self.assertIn('data-action="quicklook-paper-resource"', INDEX_HTML)
        self.assertIn('data-action="reveal-paper-resource"', INDEX_HTML)
        self.assertIn('data-action="prefer-paper-resource"', INDEX_HTML)
        self.assertIn('data-action="auto-paper-resource"', INDEX_HTML)
        self.assertIn('data-paper-resource-role-select', INDEX_HTML)
        self.assertIn('data-action="delete-paper-resource"', INDEX_HTML)
        menu = INDEX_HTML.split("function showPaperResourceContextMenu", 1)[1].split(
            "function wireLibraryInteractions", 1
        )[0]
        self.assertIn("event.stopPropagation()", menu)
        self.assertIn("hideLibraryContextMenu()", menu)
        self.assertIn('deleteButton.style.display = file && !file.is_primary', menu)
        self.assertIn('addButton.style.display = file ? "none" : ""', menu)
        self.assertIn('syncButton.style.display = !file && paper?.preprint_id', menu)

    def test_paper_files_keyboard_navigation_is_continuous_with_library_columns(self) -> None:
        keyboard = INDEX_HTML.split("function handleLibraryKeydown", 1)[1].split(
            "function switchReportJournalTab", 1
        )[0]
        availability = INDEX_HTML.split("function libraryPaperFilesNavigationEnabled", 1)[1].split(
            "function setLibraryPaperResourceSelection", 1
        )[0]
        self.assertIn('state.mode === "library"', availability)
        self.assertIn('["my-publications", "loader"]', availability)
        self.assertIn("libraryPaperFilesNavigationEnabled()", keyboard)
        self.assertIn("handleLibraryPaperResourceKeydown(event, key)", keyboard)
        self.assertIn('key === "ArrowRight"', keyboard)
        self.assertIn("activateLibraryPaperFiles()", keyboard)
        resource_keyboard = INDEX_HTML.split("function handleLibraryPaperResourceKeydown", 1)[1].split(
            "function quickLookLibraryPaperResource", 1
        )[0]
        self.assertIn(
            '["ArrowUp", "ArrowDown", "ArrowLeft", " ", "Escape", "Delete", "Backspace"]',
            resource_keyboard,
        )
        self.assertIn("moveLibraryPaperResourceSelection", resource_keyboard)
        self.assertIn("quickLookLibraryPaperResource(selected", resource_keyboard)
        self.assertIn("clearLibraryPaperResourceSelection({focusPaper: true})", resource_keyboard)

        pdf_keys = INDEX_HTML.split("function handleLibraryQuickLookPdfKeydown", 1)[1].split(
            "function reclaimLibraryQuickLookFocus", 1
        )[0]
        self.assertIn("libraryPaperFilesNavigationEnabled()", pdf_keys)
        main_selection = INDEX_HTML.split("function setLibraryColumnSelection", 1)[1].split(
            "function setLibraryRangeSelection", 1
        )[0]
        self.assertIn('libraryPaperResourceSelection = {paperId: "", resourceId: 0}', main_selection)

    def test_open_quicklook_follows_paper_file_arrow_selection(self) -> None:
        mover = INDEX_HTML.split("function moveLibraryPaperResourceSelection", 1)[1].split(
            "function handleLibraryPaperResourceKeydown", 1
        )[0]
        self.assertIn("orderedLibraryPaperResources", mover)
        self.assertIn("if (state.libraryQuickLookOpen) quickLookLibraryPaperResource(next", mover)
        pdf_keys = INDEX_HTML.split("function handleLibraryQuickLookPdfKeydown", 1)[1].split(
            "function reclaimLibraryQuickLookFocus", 1
        )[0]
        self.assertIn("handleLibraryPaperResourceKeydown(event, key)", pdf_keys)

    def test_library_item_can_be_dragged_into_the_selected_paper_files(self) -> None:
        self.assertIn('fetch("/api/library/items/attach"', INDEX_HTML)
        self.assertIn("async function convertLibraryItemToAttachment", INDEX_HTML)
        self.assertIn('shell.querySelectorAll("[data-library-resource-paper]")', INDEX_HTML)
        self.assertIn('payload.type !== "item"', INDEX_HTML)
        self.assertIn('target.classList.add("library-attachment-drop-target")', INDEX_HTML)
        self.assertIn('event.dataTransfer.dropEffect = "move"', INDEX_HTML)
        self.assertIn('content: "Move into Paper Files"', INDEX_HTML)
        self.assertIn("let pendingAttachmentPayload = null", INDEX_HTML)
        self.assertIn("libraryDragPayload(event) || cachedPayload", INDEX_HTML)
        self.assertIn("pendingAttachmentPayload = {payload, updatedAt: Date.now()}", INDEX_HTML)
        self.assertIn("Could not read the dropped Library item", INDEX_HTML)
        self.assertIn("libraryAttachmentDropInFlight: new Set()", INDEX_HTML)
        self.assertIn("function armNativeLibraryItemDrop", INDEX_HTML)
        self.assertIn("async function handleNativeLibraryItemDrop", INDEX_HTML)
        self.assertIn("document.elementFromPoint(x, y)", INDEX_HTML)
        self.assertIn('element?.closest?.("[data-library-resource-paper]")', INDEX_HTML)
        self.assertIn('element?.closest?.("[data-paper-files-panel]")', INDEX_HTML)
        self.assertIn("window.handleNativeLibraryItemDrop = handleNativeLibraryItemDrop", INDEX_HTML)
        launcher = (ROOT / "scripts" / "PaperMonitorApp.m").read_text(encoding="utf-8")
        self.assertIn('addScriptMessageHandler:self name:@"libraryItemDrag"', launcher)
        self.assertIn("pendingLibraryItemDragId", launcher)
        self.assertIn("handleNativeLibraryItemDrop", launcher)
        self.assertIn("convertPointFromScreen", launcher)

    def test_resource_actions_use_explicit_file_endpoints(self) -> None:
        self.assertIn('fetch(`/api/paper-files?paper_id=', INDEX_HTML)
        self.assertIn('fetch("/api/paper-files", {method: "POST", body: form})', INDEX_HTML)
        self.assertIn('fetch("/api/paper-files/preferred", {', INDEX_HTML)
        self.assertIn('fetch("/api/paper-files/delete", {', INDEX_HTML)
        self.assertIn('fetch("/api/paper-files/arxiv", {', INDEX_HTML)
        self.assertIn('fetch("/api/paper-files/role", {', INDEX_HTML)

    def test_pdf_download_refreshes_the_files_resource_cache(self) -> None:
        downloader = INDEX_HTML.split("async function downloadLibraryPdf", 1)[1].split(
            "function captureLibraryQuickLookReturnFocus", 1
        )[0]
        self.assertIn("await loadPaperFiles(paper.paper_id, {force: true});", downloader)

    def test_every_paper_file_type_is_an_inline_compact_popup(self) -> None:
        self.assertIn('class="paper-file-version-picker"', INDEX_HTML)
        self.assertIn('class="paper-file-version-select"', INDEX_HTML)
        self.assertIn('class="paper-file-version-arrows"', INDEX_HTML)
        self.assertIn('data-action="set-paper-file-role"', INDEX_HTML)
        self.assertIn('["publication_version:other:plain", "Imported PDF"]', INDEX_HTML)
        self.assertIn('["publication_version:other:annotated", "Imported PDF · Annotated"]', INDEX_HTML)
        self.assertIn('["publication_version:version_of_record:plain", "Published Version"]', INDEX_HTML)
        self.assertIn('["publication_version:version_of_record:annotated", "Published Version · Annotated"]', INDEX_HTML)
        self.assertIn('["publication_version:accepted_manuscript:plain", "Accepted Manuscript"]', INDEX_HTML)
        self.assertIn('["publication_version:accepted_manuscript:annotated", "Accepted Manuscript · Annotated"]', INDEX_HTML)
        self.assertIn('["publication_version:preprint:plain", "Preprint"]', INDEX_HTML)
        self.assertIn('["publication_version:preprint:annotated", "Preprint · Annotated"]', INDEX_HTML)
        self.assertIn('["figure", "Image"]', INDEX_HTML)
        self.assertIn('["supplement", "Supplement"]', INDEX_HTML)
        self.assertIn('["note", "Note"]', INDEX_HTML)
        self.assertIn('["presentation", "Presentation"]', INDEX_HTML)
        self.assertIn('["data", "Data"]', INDEX_HTML)
        self.assertIn('["code", "Code"]', INDEX_HTML)
        self.assertIn('["other", "Other File"]', INDEX_HTML)
        self.assertNotIn('"First Published"', INDEX_HTML)
        self.assertIn("async function setPaperFileRole", INDEX_HTML)
        self.assertIn("annotationChoice === \"annotated\"", INDEX_HTML)
        self.assertIn("font-size: 9px;", INDEX_HTML)

    def test_add_file_and_files_panel_drop_import_before_classification(self) -> None:
        panel = INDEX_HTML.split("function paperFilesPanelMarkup", 1)[1].split(
            "async function loadPaperFiles", 1
        )[0]
        self.assertNotIn("data-paper-file-role", panel)
        self.assertIn('data-action="choose-paper-file"', panel)

        association_target = INDEX_HTML.split("function libraryFileAssociationTargetFromPoint", 1)[1].split(
            "function libraryPdfDropTargetFromPoint", 1
        )[0]
        self.assertIn('fileRole: "other"', association_target)
        self.assertIn('versionRole: ""', association_target)
        self.assertNotIn('panel.querySelector("[data-paper-file-role]")', association_target)

        uploader = INDEX_HTML.split("async function uploadPaperFiles", 1)[1].split(
            "async function setPreferredPaperFile", 1
        )[0]
        self.assertIn('form.append("file_role", "other")', uploader)
        self.assertIn('fileRole: "other"', uploader)
        self.assertNotIn('role = "figure"', uploader)

    def test_files_panel_can_collapse_and_non_primary_files_can_be_deleted(self) -> None:
        self.assertIn('data-action="toggle-paper-files"', INDEX_HTML)
        self.assertIn('paper-files-panel.is-collapsed .paper-files-body', INDEX_HTML)
        self.assertIn('expandedPaperFiles: new Set()', INDEX_HTML)
        self.assertIn('const collapsed = !state.expandedPaperFiles.has(paperId);', INDEX_HTML)
        self.assertIn('Current · ${paperFileRoleLabel(currentFile)}', INDEX_HTML)
        self.assertIn('paper-files-current-summary', INDEX_HTML)
        self.assertIn('data-action="delete-paper-file"', INDEX_HTML)
        self.assertIn('!file.is_primary', INDEX_HTML)
        launcher = (ROOT / "scripts" / "PaperMonitorApp.m").read_text(encoding="utf-8")
        self.assertIn("runJavaScriptConfirmPanelWithMessage", launcher)
        self.assertIn('addButtonWithTitle:@"Delete"', launcher)

    def test_unknown_legacy_pdf_is_not_presented_as_published_version(self) -> None:
        self.assertIn(
            'file.added_via === "legacy_backfill" ? "Imported PDF" : "Unclassified PDF"',
            INDEX_HTML,
        )

    def test_native_app_uses_a_real_file_chooser_for_add_file(self) -> None:
        launcher = (ROOT / "scripts" / "PaperMonitorApp.m").read_text(encoding="utf-8")
        self.assertIn('addScriptMessageHandler:self name:@"paperFileChooser"', launcher)
        self.assertIn("showPaperFileChooserWithPayload", launcher)
        self.assertIn("window.handleNativePaperFileSelection", launcher)
        self.assertIn("window.webkit?.messageHandlers?.paperFileChooser", INDEX_HTML)

    def test_finder_drop_on_a_paper_associates_instead_of_running_loader(self) -> None:
        handler = INDEX_HTML.split("async function handleNativeFinderDrop", 1)[1].split(
            "function libraryPdfDropTargetFromPoint", 1
        )[0]
        self.assertIn("libraryFileAssociationTargetFromPoint", handler)
        self.assertIn("uploadPaperFilePaths", handler)
        self.assertLess(handler.index("libraryFileAssociationTargetFromPoint"), handler.index("runLibraryDroppedPathsImport"))
        self.assertIn('versionRole: "preprint"', INDEX_HTML)

    def test_library_move_refreshes_associated_file_paths_before_render(self) -> None:
        move_handler = INDEX_HTML.split("async function moveLibraryEntry", 1)[1].split(
            "async function moveLibraryEntries", 1
        )[0]
        self.assertIn("applyPaperFilesPayloads(data.paper_files)", move_handler)
        self.assertLess(
            move_handler.index("applyPaperFilesPayloads(data.paper_files)"),
            move_handler.index("renderLibrary()"),
        )

    def test_use_refreshes_both_resource_column_and_details(self) -> None:
        use_handler = INDEX_HTML.split("async function setPreferredPaperFile", 1)[1].split(
            "async function deletePaperFile", 1
        )[0]
        self.assertIn("state.paperFilesByPaperId[String(paperId)] = data", use_handler)
        self.assertIn("else renderLibrary();", use_handler)
        self.assertNotIn("else renderLibraryDetail();", use_handler)


if __name__ == "__main__":
    unittest.main()
