import tempfile
import unittest
from pathlib import Path

from paper_monitor.storage import Storage
from paper_monitor.ui_server import library_add_targets_snapshot, library_workspace_tabs


class LibraryAddTargetsTests(unittest.TestCase):
    def test_snapshot_lists_library_and_three_named_space_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                tabs = library_workspace_tabs(storage)
                self.assertEqual(len(tabs), 3)
                renamed = storage.rename_library_folder(folder_id=int(tabs[1]["root_folder_id"]), name="Quantum Lab")
                child = storage.create_library_folder(parent_id=int(renamed["id"]), name="References")

                snapshot = library_add_targets_snapshot(storage)
                self.assertEqual(snapshot["root_id"], 1)
                self.assertEqual([tab["label"] for tab in snapshot["workspace_tabs"]], ["Space 1", "Quantum Lab", "Space 3"])
                root_ids = [int(tab["root_folder_id"]) for tab in snapshot["workspace_tabs"]]
                folders = {int(folder["id"]): folder for folder in snapshot["folders"]}
                self.assertTrue(all(folders[root_id]["parent_id"] is None for root_id in root_ids))
                self.assertEqual(folders[int(child["id"])]["parent_id"], int(renamed["id"]))
                self.assertNotIn("native_folder_path", folders[int(child["id"])])
            finally:
                storage.close()


if __name__ == "__main__":
    unittest.main()
