from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from paper_monitor import ui_server
from paper_monitor.storage import Storage


class LibraryNavigationTabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = Storage(self.root / "paper_monitor.sqlite")
        self.original_spaces_root = ui_server.SPACES_LOCAL_COPY_ROOT
        self.original_library_root = ui_server.LIBRARY_LOCAL_COPY_ROOT
        self.extra_roots = [patch.object(ui_server, name, self.root / subdir) for name, subdir in (
            ('ASSOCIATED_FILES_ROOT', 'Associated Files'),
            ('MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'My Publications'), ('DEFAULT_PDF_DIR', 'pdfs'))]
        for active_patch in self.extra_roots:
            active_patch.start()
        ui_server.SPACES_LOCAL_COPY_ROOT = self.root / "Spaces"
        ui_server.LIBRARY_LOCAL_COPY_ROOT = self.root / "Library"

    def tearDown(self) -> None:
        ui_server.SPACES_LOCAL_COPY_ROOT = self.original_spaces_root
        ui_server.LIBRARY_LOCAL_COPY_ROOT = self.original_library_root
        for active_patch in reversed(self.extra_roots):
            active_patch.stop()
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

    def test_space_add_target_accepts_current_nested_folder(self) -> None:
        tab = ui_server.add_library_workspace_tab(self.storage, name="Quantum Lab")
        root_id = int(tab["root_folder_id"])
        level_one = self.storage.create_library_folder(parent_id=root_id, name="Level One")
        level_two = self.storage.create_library_folder(
            parent_id=int(level_one["id"]),
            name="Level Two",
        )

        target_id = ui_server.library_workspace_add_target_folder_id(
            self.storage,
            root_folder_id=root_id,
            requested_folder_id=int(level_two["id"]),
        )

        self.assertEqual(target_id, int(level_two["id"]))

    def test_space_add_target_rejects_folder_outside_current_space(self) -> None:
        tab = ui_server.add_library_workspace_tab(self.storage, name="Quantum Lab")
        other_tab = ui_server.add_library_workspace_tab(self.storage, name="Other Lab")

        with self.assertRaisesRegex(ValueError, "not inside this Space"):
            ui_server.library_workspace_add_target_folder_id(
                self.storage,
                root_folder_id=int(tab["root_folder_id"]),
                requested_folder_id=int(other_tab["root_folder_id"]),
            )

    def test_shortcut_add_target_accepts_current_nested_folder(self) -> None:
        shortcut_root = self.storage.create_library_folder(parent_id=1, name="Shortcut Root")
        level_one = self.storage.create_library_folder(
            parent_id=int(shortcut_root["id"]),
            name="Level One",
        )
        level_two = self.storage.create_library_folder(
            parent_id=int(level_one["id"]),
            name="Level Two",
        )

        target_id = ui_server.library_navigation_add_target_folder_id(
            self.storage,
            root_folder_id=int(shortcut_root["id"]),
            requested_folder_id=int(level_two["id"]),
            root_label="Shortcut",
        )

        self.assertEqual(target_id, int(level_two["id"]))

    def test_main_library_add_target_accepts_nested_folder_and_rejects_space(self) -> None:
        level_one = self.storage.create_library_folder(parent_id=1, name="Level One")
        level_two = self.storage.create_library_folder(
            parent_id=int(level_one["id"]),
            name="Level Two",
        )
        space = ui_server.add_library_workspace_tab(self.storage, name="Separate Space")

        target_id = ui_server.library_navigation_add_target_folder_id(
            self.storage,
            root_folder_id=1,
            requested_folder_id=int(level_two["id"]),
            root_label="Library",
        )

        self.assertEqual(target_id, int(level_two["id"]))
        with self.assertRaisesRegex(ValueError, "not inside this Library"):
            ui_server.library_navigation_add_target_folder_id(
                self.storage,
                root_folder_id=1,
                requested_folder_id=int(space["root_folder_id"]),
                root_label="Library",
            )

    def test_space_title_query_uses_shared_title_identifier_resolution(self) -> None:
        resolved = {
            "paper_id": "resolved-paper",
            "doi": "10.1234/resolved",
            "title": "Resolved Paper Title",
            "journal": "Resolved Journal",
            "publication_date": "2026-07-27",
        }
        with patch.object(
            ui_server,
            "identifier_from_title_lookup",
            return_value={
                "kind": "doi",
                "identifier": "10.1234/resolved",
                "source": "title_crossref",
            },
        ) as lookup, patch.object(
            ui_server,
            "publication_metrics_metadata_from_doi",
            return_value=resolved,
        ) as metadata:
            paper = ui_server.library_workspace_publication_from_query(
                "Resolved Paper Title"
            )

        self.assertEqual(paper, resolved)
        lookup.assert_called_once_with("Resolved Paper Title")
        metadata.assert_called_once_with(
            "10.1234/resolved",
            timeout=14,
            max_retries=1,
        )

    def test_space_title_query_can_resolve_doi_through_openalex(self) -> None:
        response = MagicMock()
        response.json.return_value = {
            "results": [
                {
                    "title": "A Precise OpenAlex Paper Title",
                    "doi": "https://doi.org/10.1234/openalex",
                    "type": "article",
                }
            ]
        }
        resolved = {
            "paper_id": "openalex-paper",
            "doi": "10.1234/openalex",
            "title": "A Precise OpenAlex Paper Title",
        }
        with patch.object(
            ui_server,
            "search_crossref_publications",
            return_value=[],
        ), patch.object(
            ui_server,
            "openalex_request",
            return_value=response,
        ) as openalex, patch.object(
            ui_server,
            "publication_metrics_metadata_from_doi",
            return_value=resolved,
        ) as metadata:
            paper = ui_server.library_workspace_publication_from_query(
                "A Precise OpenAlex Paper Title"
            )

        self.assertEqual(paper, resolved)
        openalex.assert_called_once()
        metadata.assert_called_once_with(
            "10.1234/openalex",
            timeout=14,
            max_retries=1,
        )

    def test_title_identifier_lookup_can_fall_back_to_semantic_scholar(self) -> None:
        openalex_response = MagicMock()
        openalex_response.json.return_value = {"results": []}
        semantic_response = MagicMock()
        semantic_response.json.return_value = {
            "data": [
                {
                    "title": "A Semantic Scholar Identifier Match",
                    "externalIds": {"ArXiv": "2607.12345"},
                    "year": 2026,
                }
            ]
        }
        with patch.object(
            ui_server,
            "search_crossref_publications",
            return_value=[],
        ), patch.object(
            ui_server,
            "openalex_request",
            return_value=openalex_response,
        ), patch.object(
            ui_server,
            "semantic_scholar_request",
            return_value=semantic_response,
        ):
            found = ui_server.identifier_from_title_lookup(
                "A Semantic Scholar Identifier Match"
            )

        self.assertEqual(found["kind"], "arxiv")
        self.assertEqual(found["identifier"], "2607.12345")
        self.assertEqual(found["source"], "title_semantic")

    def test_title_identifier_lookup_distinguishes_all_service_failures(self) -> None:
        with patch.object(
            ui_server,
            "search_crossref_publications",
            side_effect=RuntimeError("Crossref offline"),
        ), patch.object(
            ui_server,
            "openalex_request",
            side_effect=RuntimeError("OpenAlex offline"),
        ), patch.object(
            ui_server,
            "semantic_scholar_request",
            side_effect=RuntimeError("Semantic Scholar offline"),
        ):
            found = ui_server.identifier_from_title_lookup(
                "A title lookup with unavailable identifier services"
            )

        self.assertEqual(found["lookup_status"], "unavailable")
        self.assertIn("Crossref offline", found["lookup_error"])
        self.assertIn("OpenAlex offline", found["lookup_error"])
        self.assertIn("Semantic Scholar offline", found["lookup_error"])

    def test_space_add_and_library_location_ui_contract(self) -> None:
        html = ui_server.INDEX_HTML
        context = html.split("function activeLibraryNavigationToolContext()", 1)[1].split(
            "function updateToolbarLibraryImport()", 1
        )[0]
        add_paper = html.split("async function submitLibraryInlineAddPaper()", 1)[1].split(
            "function renderMyPublications", 1
        )[0]
        menu = html.split("function showLibraryTabContextMenu", 1)[1].split(
            "function hideLibraryTabContextMenu", 1
        )[0]
        search_row = html.split("function librarySearchResultRowMarkup", 1)[1].split(
            "function libraryRowMarkup", 1
        )[0]
        files = html.split("function libraryDetailFilesMarkup", 1)[1].split(
            "function libraryIdentifierFromFilesButtonMarkup", 1
        )[0]
        navigation = html.split("async function navigateToPaperInLibrary", 1)[1].split(
            "async function showPaperInLibrary", 1
        )[0]
        folder_occurrences = html.split("function libraryOccurrenceTreeForPaper", 1)[1].split(
            "function libraryNonPdfDetailMarkup", 1
        )[0]
        native_drag = html.split("function prepareNativeFolderDrag", 1)[1].split(
            "function fileNameFromPath", 1
        )[0]

        self.assertNotIn("workspaceToolsMarkup", html)
        self.assertIn('type: "shortcut"', context)
        self.assertIn('type: "workspace"', context)
        self.assertIn('"/api/library/navigation-tabs/add-paper"', add_paper)
        self.assertIn("tab_type: context.tab_type", add_paper)
        self.assertIn("folder_id: targetFolderId", add_paper)
        self.assertIn("state.libraryInlineAddBusy = true", add_paper)
        self.assertIn("state.libraryInlineAddBusy = false", add_paper)
        self.assertIn("Finding paper and adding it to", add_paper)
        self.assertIn("Add Paper failed:", add_paper)
        self.assertIn("renameLibraryShortcutTab(i)", menu)
        self.assertIn("renameLibraryWorkspaceFromTab(i)", menu)
        self.assertIn('data-action="show-library-search-result"', search_row)
        self.assertIn(">Show in Library</button>", search_row)
        self.assertNotIn("paper.journal", search_row)
        self.assertIn('class="library-file-line"', files)
        self.assertIn("paper?.merged_pdf_path || paper?.native_file_path", files)
        self.assertNotIn('data-action="show-file-in-library"', files)
        self.assertNotIn("local_file_path", files)
        self.assertIn('data-action="show-library-occurrence"', folder_occurrences)
        self.assertIn("chain.push({id: currentId, name: current.name", folder_occurrences)
        self.assertIn("selectLibraryItemInColumns(item)", navigation)
        self.assertIn('state.query = ""', navigation)
        self.assertIn("/api/library/folders/prepare-drag", native_drag)
        self.assertIn("cleanup_path: result.cleanup_path", native_drag)

    def test_main_library_inline_add_paper_ui_contract(self) -> None:
        html = ui_server.INDEX_HTML
        inline = html.split("function beginLibraryInlineAddPaper(folderId)", 1)[1].split(
            "function renderMyPublications", 1
        )[0]
        markup = html.split("function libraryInlineAddPaperMarkup(folderId", 1)[1].split(
            "function libraryColumnMarkup", 1
        )[0]
        context_menu = html.split("function showLibraryContextMenu(event", 1)[1].split(
            "function hideLibraryContextMenu", 1
        )[0]

        self.assertIn('data-action="add-paper">Add Paper</button>', html)
        self.assertIn('"/api/library/add-paper"', inline)
        self.assertIn("folder_id: targetFolderId", inline)
        self.assertIn("state.libraryInlineAddBusy = true", inline)
        self.assertIn("state.libraryInlineAddError = error.message", inline)
        self.assertIn("resetLibraryInlineAddPaper()", inline)
        self.assertIn('placeholder="DOI, arXiv ID, or title"', markup)
        self.assertIn("data-library-inline-add-paper-submit", markup)
        self.assertIn("libraryInlineAddAllowed(targetFolderId)", context_menu)
        self.assertIn("!hasEntry", context_menu)
        self.assertIn("beginLibraryInlineAddPaper(targetFolderId)", context_menu)

    def test_library_search_covers_library_and_every_space(self) -> None:
        html = ui_server.INDEX_HTML
        search = html.split("function librarySearchResults()", 1)[1].split(
            "function libraryVisibleEntries()", 1
        )[0]

        self.assertIn(
            "new Set(state.libraryFolders.map((folder) => Number(folder.id)))",
            search,
        )
        self.assertIn("libraryGlobalFolderPath(item.folder_id)", search)
        self.assertIn('type: "item"', search)
        self.assertNotIn('type: "folder"', search)
        self.assertNotIn("libraryDisplayRootId()", search)
        self.assertNotIn("libraryDescendantFolderIds(", search)
        self.assertIn('aria-label="Search Library and all Spaces"', html)
        self.assertIn("/api/library/search?q=", html)
        self.assertIn("requestRemoteLibrarySearch(nextQuery)", html)

    def test_library_search_snapshot_returns_files_but_never_folders(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Quantum Search Folder")
        self.storage.upsert_paper(
            {
                "paper_id": "searchable-paper",
                "doi": "10.1234/searchable",
                "title": "A directly searchable quantum paper",
                "journal": "Test Journal",
                "publication_date": "2026-07-28",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        item = self.storage.add_library_item(
            paper_id="searchable-paper",
            folder_id=int(folder["id"]),
        )

        by_title = ui_server.library_file_search_snapshot(
            self.storage,
            "directly searchable",
        )

        self.assertEqual(by_title["total"], 1)
        self.assertEqual(by_title["results"][0]["type"], "item")
        self.assertEqual(by_title["results"][0]["id"], int(item["id"]))
        self.assertIn("Quantum Search Folder", by_title["results"][0]["path"])

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
            [Path(resource["stored_path"]).resolve()],
        )
        self.assertTrue(Path(resource["stored_path"]).resolve().is_relative_to(ui_server.ASSOCIATED_FILES_ROOT.resolve()))
        self.assertEqual(Path(resource["stored_path"]).read_bytes(), b"%PDF-1.4\n")
        self.assertTrue((target_dir / "paper.pdf").exists())


if __name__ == "__main__":
    unittest.main()
