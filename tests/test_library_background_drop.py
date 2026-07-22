from __future__ import annotations

import unittest

from paper_monitor.ui_server import INDEX_HTML


def js_function(name: str) -> str:
    marker = f"function {name}"
    start = INDEX_HTML.index(marker)
    candidates = [
        position
        for position in (
            INDEX_HTML.find("\n    function ", start + len(marker)),
            INDEX_HTML.find("\n    async function ", start + len(marker)),
        )
        if position >= 0
    ]
    return INDEX_HTML[start : min(candidates) if candidates else len(INDEX_HTML)]


class LibraryBackgroundDropUiTests(unittest.TestCase):
    def test_finder_drop_starts_background_import_without_opening_loader(self) -> None:
        drop_handler = js_function("handleNativeFinderDrop")

        self.assertIn("await runLibraryDroppedPathsImport(droppedPaths, targetFolderId, targetPath);", drop_handler)
        self.assertNotIn("openLibraryLoaderWindow", drop_handler)
        self.assertNotIn("saveLibraryImportDraft", drop_handler)

    def test_background_drop_always_skips_metadata(self) -> None:
        import_handler = js_function("runLibraryDroppedPathsImport")

        self.assertIn('metadata_mode: "skip"', import_handler)
        self.assertIn('state.libraryImportMetadataMode = "skip";', import_handler)
        self.assertNotIn("state.libraryLoaderOpen = true", import_handler)
        self.assertNotIn("renderLibraryLoader();", import_handler)

    def test_background_drop_reports_progress_in_library_status_bar(self) -> None:
        progress_handler = js_function("refreshLibraryImportJob")

        self.assertIn("function libraryDroppedImportActivityText", INDEX_HTML)
        self.assertIn("updateLibraryDroppedImportActivity(job);", progress_handler)
        self.assertIn("updateLibraryActivityStatus(libraryDroppedImportActivityText(job)", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
