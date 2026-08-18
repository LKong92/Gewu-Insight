from __future__ import annotations

import unittest
from pathlib import Path

from paper_monitor.ui_server import INDEX_HTML


ROOT = Path(__file__).resolve().parents[1]


class PaperFilesUiTests(unittest.TestCase):
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
        self.assertIn('["publication_version:other", "Imported PDF"]', INDEX_HTML)
        self.assertIn('["publication_version:version_of_record", "Published Version"]', INDEX_HTML)
        self.assertIn('["publication_version:accepted_manuscript", "Accepted Manuscript"]', INDEX_HTML)
        self.assertIn('["publication_version:preprint", "Preprint"]', INDEX_HTML)
        self.assertIn('["figure", "Image"]', INDEX_HTML)
        self.assertIn('["supplement", "Supplement"]', INDEX_HTML)
        self.assertIn('["note", "Note"]', INDEX_HTML)
        self.assertIn('["presentation", "Presentation"]', INDEX_HTML)
        self.assertIn('["data", "Data"]', INDEX_HTML)
        self.assertIn('["code", "Code"]', INDEX_HTML)
        self.assertIn('["other", "Other File"]', INDEX_HTML)
        self.assertNotIn('"First Published"', INDEX_HTML)
        self.assertIn("async function setPaperFileRole", INDEX_HTML)
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
