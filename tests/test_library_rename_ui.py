import unittest
import inspect
from pathlib import Path
import shutil
import subprocess

from paper_monitor import ui_server
from paper_monitor.ui_server import INDEX_HTML


class LibraryRenameUiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_rename_refreshes_paths_and_ignores_old_pending_responses(self):
        result = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("folder_rename_ui_probe.cjs"))],
                                input=INDEX_HTML, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_table_view_renders_the_shared_rename_input(self):
        table_markup = INDEX_HTML.split("function libraryTableRowMarkup", 1)[1].split(
            "function libraryPaperTableFallbackParts", 1
        )[0]
        self.assertIn("const renaming =", table_markup)
        self.assertIn('const rowTag = renaming ? "div" : "button";', table_markup)
        self.assertIn("data-library-rename-input", table_markup)
        self.assertIn("${titleMarkup}", table_markup)

    def test_rename_completion_restores_library_keyboard_focus(self):
        self.assertIn("function restoreLibraryKeyboardFocus()", INDEX_HTML)
        self.assertIn('updateLibraryActivityStatus("Rename complete."', INDEX_HTML)
        self.assertIn('updateLibraryActivityStatus(`Rename failed:', INDEX_HTML)
        self.assertGreaterEqual(INDEX_HTML.count("restoreLibraryKeyboardFocus();"), 2)

    def test_escape_clears_a_stale_rename_state(self):
        key_handler = INDEX_HTML.split("function handleLibraryKeydown", 1)[1].split(
            "function renderLibraryContextMenu", 1
        )[0]
        self.assertIn('key === "Escape" && renameActive', key_handler)
        self.assertIn("cancelLibraryEntryRename();", key_handler)

    def test_shortcut_rename_returns_and_applies_only_one_item(self):
        handler = inspect.getsource(ui_server.PaperMonitorUiHandler.handle_rename_library_item)
        self.assertNotIn("library_snapshot", handler)
        self.assertIn("library_item_to_api(item, paper)", handler)
        self.assertIn('"item": item_api', handler)

        commit = INDEX_HTML.split("async function commitLibraryEntryRename", 1)[1].split(
            "async function commitLibraryFolderRename", 1
        )[0]
        self.assertIn("upsertLibraryItemLocal(data.item);", commit)
        self.assertIn("upsertLibraryFolderLocal(data.folder);", commit)
        self.assertIn("snapshot: false", commit)


if __name__ == "__main__":
    unittest.main()
