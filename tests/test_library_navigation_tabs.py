from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from paper_monitor import ui_server
from paper_monitor.storage import Storage


class LibraryNavigationTabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = Storage(self.root / "paper_monitor.sqlite")
        self.original_spaces_root = ui_server.SPACES_LOCAL_COPY_ROOT
        self.original_library_root = ui_server.LIBRARY_LOCAL_COPY_ROOT
        ui_server.SPACES_LOCAL_COPY_ROOT = self.root / "Spaces"
        ui_server.LIBRARY_LOCAL_COPY_ROOT = self.root / "Library"

    def tearDown(self) -> None:
        ui_server.SPACES_LOCAL_COPY_ROOT = self.original_spaces_root
        ui_server.LIBRARY_LOCAL_COPY_ROOT = self.original_library_root
        self.storage.close()
        self.tmp.cleanup()

    def test_legacy_shortcut_slots_migrate_to_dynamic_tabs(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Focused Reading")
        self.storage.set_setting(
            "library_shortcut_tabs",
            json.dumps(
                [
                    {"folder_id": int(folder["id"]), "label": "Focus"},
                    {"folder_id": 0, "label": ""},
                    {"folder_id": 0, "label": ""},
                    {"folder_id": 0, "label": ""},
                    {"folder_id": 0, "label": ""},
                ]
            ),
        )

        tabs = ui_server.library_shortcut_tabs(self.storage)

        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["folder_id"], int(folder["id"]))
        self.assertEqual(tabs[0]["label"], "Focus")
        self.assertTrue(tabs[0]["tab_id"].startswith("shortcut-"))

    def test_shortcut_add_remove_and_reorder_do_not_change_folders(self) -> None:
        first = self.storage.create_library_folder(parent_id=1, name="First")
        second = self.storage.create_library_folder(parent_id=1, name="Second")
        first_tab = ui_server.add_library_shortcut_tab(self.storage, folder_id=int(first["id"]))
        second_tab = ui_server.add_library_shortcut_tab(self.storage, folder_id=int(second["id"]))

        reordered = ui_server.reorder_library_navigation_tabs(
            ui_server.library_shortcut_tabs(self.storage),
            [second_tab["tab_id"], first_tab["tab_id"]],
        )
        ui_server.save_library_shortcut_tabs(self.storage, reordered)
        self.assertEqual(
            [tab["folder_id"] for tab in ui_server.library_shortcut_tabs(self.storage)],
            [int(second["id"]), int(first["id"])],
        )

        ui_server.remove_library_shortcut_tab(self.storage, {"tab_id": first_tab["tab_id"]})

        self.assertIsNotNone(self.storage.get_library_folder(int(first["id"])))
        self.assertIsNotNone(self.storage.get_library_folder(int(second["id"])))
        self.assertEqual(len(ui_server.library_shortcut_tabs(self.storage)), 1)

    def test_space_add_creates_real_directory_and_empty_remove_cleans_it(self) -> None:
        tab = ui_server.add_library_workspace_tab(self.storage, name="Quantum Lab")
        folder_id = int(tab["root_folder_id"])
        folder = self.storage.get_library_folder(folder_id)
        target = ui_server.SPACES_LOCAL_COPY_ROOT / "Quantum Lab"

        self.assertIsNotNone(folder)
        self.assertIsNone(folder["parent_id"])
        self.assertTrue(target.is_dir())

        ui_server.remove_library_workspace_tab(self.storage, {"tab_id": tab["tab_id"]})

        self.assertIsNone(self.storage.get_library_folder(folder_id))
        self.assertFalse(target.exists())
        self.assertEqual(ui_server.library_workspace_tabs(self.storage), [])

    def test_space_remove_rejects_database_or_finder_contents(self) -> None:
        tab = ui_server.add_library_workspace_tab(self.storage, name="Occupied")
        folder_id = int(tab["root_folder_id"])
        child = self.storage.create_library_folder(parent_id=folder_id, name="Child")

        with self.assertRaisesRegex(ValueError, "not empty"):
            ui_server.remove_library_workspace_tab(self.storage, {"tab_id": tab["tab_id"]})

        self.storage.delete_library_folder(folder_id=int(child["id"]))
        target = ui_server.SPACES_LOCAL_COPY_ROOT / "Occupied"
        (target / "untracked.txt").write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Finder"):
            ui_server.remove_library_workspace_tab(self.storage, {"tab_id": tab["tab_id"]})

        self.assertIsNotNone(self.storage.get_library_folder(folder_id))

    def test_move_space_to_library_moves_tree_and_real_directory(self) -> None:
        destination = self.storage.create_library_folder(parent_id=1, name="Archived Spaces")
        tab = ui_server.add_library_workspace_tab(self.storage, name="Quantum Lab")
        root_id = int(tab["root_folder_id"])
        child = self.storage.create_library_folder(parent_id=root_id, name="Notes")
        source_dir = ui_server.SPACES_LOCAL_COPY_ROOT / "Quantum Lab"
        (source_dir / "Notes").mkdir(parents=True)
        (source_dir / "Notes" / "readme.txt").write_text("preserve me", encoding="utf-8")

        moved = ui_server.move_library_workspace_to_library(
            self.storage,
            {"tab_id": tab["tab_id"]},
            target_folder_id=int(destination["id"]),
        )

        target_dir = ui_server.local_copy_dir_for_library_folder(self.storage, root_id)
        self.assertEqual(int(moved["parent_id"]), int(destination["id"]))
        self.assertEqual(int(self.storage.get_library_folder(int(child["id"]))["parent_id"]), root_id)
        self.assertFalse(source_dir.exists())
        self.assertEqual((target_dir / "Notes" / "readme.txt").read_text(encoding="utf-8"), "preserve me")
        self.assertEqual(ui_server.library_workspace_tabs(self.storage), [])

    def test_move_space_to_library_rejects_name_conflict_without_changes(self) -> None:
        destination = self.storage.create_library_folder(parent_id=1, name="Destination")
        self.storage.create_library_folder(parent_id=int(destination["id"]), name="Quantum Lab")
        tab = ui_server.add_library_workspace_tab(self.storage, name="Quantum Lab")
        root_id = int(tab["root_folder_id"])

        with self.assertRaisesRegex(ValueError, "already exists"):
            ui_server.move_library_workspace_to_library(
                self.storage,
                {"tab_id": tab["tab_id"]},
                target_folder_id=int(destination["id"]),
            )

        self.assertIsNone(self.storage.get_library_folder(root_id)["parent_id"])
        self.assertTrue((ui_server.SPACES_LOCAL_COPY_ROOT / "Quantum Lab").is_dir())
        self.assertEqual(len(ui_server.library_workspace_tabs(self.storage)), 1)

    def test_move_space_to_library_remaps_managed_paper_and_resource_paths(self) -> None:
        destination = self.storage.create_library_folder(parent_id=1, name="Archive")
        tab = ui_server.add_library_workspace_tab(self.storage, name="Paper Space")
        root_id = int(tab["root_folder_id"])
        source_dir = ui_server.SPACES_LOCAL_COPY_ROOT / "Paper Space"
        pdf_path = source_dir / "paper.pdf"
        supplement_path = source_dir / "supplement.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        supplement_path.write_bytes(b"%PDF-1.4\n")
        self.storage.upsert_paper({"paper_id": "paper-1", "title": "Paper", "journal": "Test"})
        self.storage.conn.execute(
            """
            UPDATE papers
            SET main_pdf_path = ?, merged_pdf_path = ?, source_path = ?, supplement_pdf_paths = ?
            WHERE paper_id = ?
            """,
            (str(pdf_path), str(pdf_path), str(pdf_path), json.dumps([str(supplement_path)]), "paper-1"),
        )
        self.storage.add_library_item(paper_id="paper-1", folder_id=root_id)
        self.storage.conn.execute(
            """
            INSERT INTO resources (
                paper_id, source_path, stored_path, kind, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("paper-1", str(pdf_path), str(supplement_path), "attachment", "now", "now"),
        )
        self.storage.conn.commit()

        ui_server.move_library_workspace_to_library(
            self.storage,
            {"tab_id": tab["tab_id"]},
            target_folder_id=int(destination["id"]),
        )

        target_dir = ui_server.local_copy_dir_for_library_folder(self.storage, root_id)
        paper = self.storage.get_paper("paper-1")
        resource = self.storage.conn.execute("SELECT * FROM resources WHERE paper_id = ?", ("paper-1",)).fetchone()
        self.assertEqual(Path(paper["merged_pdf_path"]).resolve(), (target_dir / "paper.pdf").resolve())
        self.assertEqual(Path(paper["source_path"]).resolve(), (target_dir / "paper.pdf").resolve())
        self.assertEqual(
            [Path(path).resolve() for path in json.loads(paper["supplement_pdf_paths"])],
            [(target_dir / "supplement.pdf").resolve()],
        )
        self.assertEqual(Path(resource["stored_path"]).resolve(), (target_dir / "supplement.pdf").resolve())
        self.assertTrue((target_dir / "paper.pdf").exists())


if __name__ == "__main__":
    unittest.main()
