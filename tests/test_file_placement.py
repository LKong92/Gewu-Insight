"""Real file/SQLite regressions for Recycle placement ownership (temporary data)."""
from contextlib import contextmanager
import json
from pathlib import Path
from paper_monitor import finder_alias
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_library_file_ops as fixtures
from paper_monitor import file_placement as placement
from paper_monitor import ui_server as ui
from paper_monitor.browser_capture import BrowserCaptureService


@contextmanager
def library(survivor=None):
    fixture = fixtures.LibraryFileOperationTests()
    fixture.setUp()
    try:
        s = fixture.storage
        special = ui.ensure_library_special_folders(s)
        a = s.create_library_folder(parent_id=1, name="Source")
        child = s.create_library_folder(parent_id=a["id"], name="Child")
        b = (s.create_library_root_folder(name="Space") if survivor == "space"
             else s.create_library_folder(parent_id=1, name="Target"))
        directory = ui.local_copy_dir_for_library_folder(s, child["id"])
        directory.mkdir(parents=True)
        original = directory / "fixture.pdf"
        original.write_bytes(b"%PDF synthetic ownership fixture")
        s.upsert_paper(dict(paper_id="fixture", title="Ownership fixture", doi="10.1234/ownership",
                            journal="Fixture", source="test", publication_date="2026-01-01"))
        s.update_download_status("fixture", status="success", main_pdf_path=str(original),
                                 merged_pdf_path=str(original), supplement_pdf_paths=[])
        s.ensure_primary_pdf_resource("fixture")
        item = s.add_library_item(paper_id="fixture", folder_id=child["id"])
        if survivor in ("library", "space"):
            s.add_library_item(paper_id="fixture", folder_id=b["id"])
            ui.sync_alias_for_library_item(s, "fixture", b["id"])
        if survivor == "publication":
            s.add_my_publication(paper_id="fixture")
            ui.sync_my_publication_alias(s, "fixture")
        replies, errors = [], []
        handler = SimpleNamespace(configured_db_path=fixture.db_path,
                                  send_json=replies.append, send_error_json=lambda *args: errors.append(args))
        yield SimpleNamespace(s=s, a=a, b=b, child=child, item=item, original=original.resolve(),
                              rid=special["recycle"]["id"], unsorted=special["unsorted"]["id"],
                              handler=handler, replies=replies, errors=errors, fixture=fixture)
        assert not errors, errors
    finally:
        fixture.tearDown()


H = ui.PaperMonitorUiHandler


class FilePlacementTests(unittest.TestCase):
    def assert_file_and_aliases(self, c, *, recycled=False):
        paper = c.s.get_paper("fixture")
        path = ui.canonical_pdf_path_for_paper(paper)
        self.assertIsNotNone(path)
        self.assertEqual(path.read_bytes(), b"%PDF synthetic ownership fixture")
        self.assertEqual(placement.in_recycle(path), recycled)
        for row in c.s.conn.execute("SELECT * FROM library_items WHERE paper_id='fixture'"):
            alias = ui.library_item_local_pdf_path(c.s, dict(row), paper)
            self.assertIsNotNone(alias, dict(row))
            self.assertEqual(finder_alias.resolve(alias), path)
        if ui.paper_has_my_publication_reference(c.s, "fixture"):
            self.assertTrue(any(finder_alias.resolve(p) == path for p in ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT.iterdir()))
        self.assertEqual(c.s.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        return path

    def test_folder_delete_preserves_library_space_and_publication_owners(self):
        for survivor in ("library", "space", "publication"):
            with self.subTest(survivor=survivor), library(survivor) as c:
                key = c.s.get_paper("fixture")["storage_key"]
                H.delete_library_entry_in_storage(None, c.s, "folder", c.a["id"])
                path = self.assert_file_and_aliases(c)
                self.assertEqual(c.s.get_paper("fixture")["storage_key"], key)
                expected = (ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT if survivor == "publication"
                            else ui.local_copy_dir_for_library_folder(c.s, c.b["id"]))
                self.assertEqual(path.parent, expected.resolve())

    def test_drag_item_and_folder_to_recycle_root_or_child_preserves_owners(self):
        for kind in ("item", "folder"):
            for nested in (False, True):
                for survivor in ("library", "space", "publication"):
                    with self.subTest(kind=kind, nested=nested, survivor=survivor), library(survivor) as c:
                        target = c.rid
                        if nested:
                            target = c.s.create_library_folder(parent_id=c.rid, name="Trash child")["id"]
                        H.handle_move_library_entry(c.handler, dict(type=kind, id=c.item["id"] if kind == "item" else c.a["id"],
                                                                   target_folder_id=target, snapshot=False))
                        self.assert_file_and_aliases(c)

    def test_last_reference_can_enter_recycle(self):
        for kind in ("item", "folder"):
            with self.subTest(kind=kind), library() as c:
                H.delete_library_entry_in_storage(None, c.s, kind, c.item["id"] if kind == "item" else c.a["id"])
                self.assert_file_and_aliases(c, recycled=True)

    def test_second_recycle_move_only_moves_bytes_after_last_active_reference(self):
        with library("library") as c:
            H.delete_library_entry_in_storage(None, c.s, "folder", c.a["id"])
            self.assert_file_and_aliases(c)
            H.delete_library_entry_in_storage(None, c.s, "folder", c.b["id"])
            self.assert_file_and_aliases(c, recycled=True)

    def test_copy_recycled_item_or_tree_rescues_original(self):
        for kind in ("item", "folder"):
            with self.subTest(kind=kind), library() as c:
                identity = c.item["id"] if kind == "item" else c.a["id"]
                H.delete_library_entry_in_storage(None, c.s, kind, identity)
                H.paste_library_entry_in_storage(None, c.s, kind, identity, c.b["id"])
                self.assert_file_and_aliases(c)

    def test_monitor_add_rescues_original_with_explicit_or_default_destination(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit), library() as c:
                H.delete_library_entry_in_storage(None, c.s, "item", c.item["id"])
                payload = dict(paper_id="fixture", snapshot=False)
                if explicit:
                    payload["folder_id"] = c.b["id"]
                H.handle_add_library_item(c.handler, payload)
                self.assert_file_and_aliases(c)

    def test_browser_save_reuses_key_and_rescues_existing_recycled_file(self):
        with library() as c:
            key = c.s.get_paper("fixture")["storage_key"]
            H.delete_library_entry_in_storage(None, c.s, "item", c.item["id"])
            service = BrowserCaptureService()
            with patch.object(service, "resolve", return_value=None):
                capture = service.begin(c.fixture.db_path, dict(url="https://example.org/article",
                    metadata={"doi": "10.1234/ownership", "title": "Ownership fixture"}))
            try:
                service.review(capture, c.s, {})
                result = service.save(capture, c.s, dict(folder_id=c.b["id"], folder_selection_explicit=True))
                self.assertTrue(result["ok"])
                self.assertEqual(result["gewu_key"], key)
                self.assert_file_and_aliases(c)
            finally:
                service.cancel(c.fixture.db_path, capture.token)

    def test_publications_add_rescues_original(self):
        with library() as c:
            H.delete_library_entry_in_storage(None, c.s, "item", c.item["id"])
            c.s.add_my_publication(paper_id="fixture")
            ui.sync_my_publication_alias(c.s, "fixture")
            path = self.assert_file_and_aliases(c)
            self.assertEqual(path.parent, ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT.resolve())

    def test_recover_item_uses_unsorted_if_its_original_folder_was_recycled(self):
        with library() as c:
            H.delete_library_entry_in_storage(None, c.s, "item", c.item["id"])
            H.delete_library_entry_in_storage(None, c.s, "folder", c.a["id"])
            H.recover_library_entry_in_storage(None, c.s, "item", c.item["id"])
            self.assertEqual(c.s.get_library_item(c.item["id"])["folder_id"], c.unsorted)
            self.assert_file_and_aliases(c)

    def test_recover_folder_uses_library_if_its_original_parent_was_recycled(self):
        with library() as c:
            H.delete_library_entry_in_storage(None, c.s, "folder", c.child["id"])
            H.delete_library_entry_in_storage(None, c.s, "folder", c.a["id"])
            H.recover_library_entry_in_storage(None, c.s, "folder", c.child["id"])
            self.assertEqual(c.s.get_library_folder(c.child["id"])["parent_id"], 1)
            self.assert_file_and_aliases(c)

    def test_active_references_to_shared_bytes_protect_all_registered_paths(self):
        for reference in ("primary", "resource", "supplement"):
            with self.subTest(reference=reference), library() as c:
                c.s.upsert_paper(dict(paper_id="other", title="Other owner", source="test", journal="Fixture"))
                if reference == "primary":
                    c.s.update_download_status("other", status="success", main_pdf_path=str(c.original),
                                             merged_pdf_path=str(c.original), supplement_pdf_paths=[])
                elif reference == "resource":
                    resource = c.s.create_paper_resource(paper_id="other", stored_path=str(c.original), file_role="other")
                else:
                    c.s.conn.execute("UPDATE papers SET supplement_pdf_paths=? WHERE paper_id='other'", (json.dumps([str(c.original)]),))
                    c.s.conn.commit()
                c.s.add_library_item(paper_id="other", folder_id=c.b["id"])
                H.delete_library_entry_in_storage(None, c.s, "folder", c.a["id"])
                path = self.assert_file_and_aliases(c)
                if reference == "primary":
                    self.assertEqual(ui.canonical_pdf_path_for_paper(c.s.get_paper("other")), path)
                elif reference == "resource":
                    self.assertEqual(Path(c.s.get_paper_resource(resource["id"])["stored_path"]), path)
                else:
                    self.assertEqual(json.loads(c.s.get_paper("other")["supplement_pdf_paths"]), [str(path)])

    def test_conflicting_target_name_never_overwrites_other_bytes(self):
        with library("library") as c:
            target = ui.local_copy_dir_for_library_folder(c.s, c.b["id"]) / c.original.name
            from paper_monitor.desktop_files import placement_path
            placement_path(target).unlink()
            target.write_bytes(b"unrelated existing file")
            H.delete_library_entry_in_storage(None, c.s, "folder", c.a["id"])
            self.assert_file_and_aliases(c)
            self.assertEqual(target.read_bytes(), b"unrelated existing file")

    def test_move_and_readd_preserve_file_ids_classification_default_and_analysis(self):
        with library("library") as c:
            paper = c.s.get_paper("fixture")
            primary_id = paper["primary_resource_id"]
            c.s.set_preferred_paper_resource("fixture", primary_id)
            bundle = ui.associated_work_dir_for_paper(c.s, "fixture")
            bundle.mkdir(parents=True)
            notes = bundle / "notes.md"
            notes.write_text("# Preserved analysis\n", encoding="utf-8")
            preprint = bundle / "preprint.pdf"
            preprint.write_bytes(b"%PDF preserved preprint")
            note = c.s.create_paper_resource(paper_id="fixture", stored_path=str(notes), file_type="other", file_role="note")
            version = c.s.create_paper_resource(paper_id="fixture", stored_path=str(preprint), file_type="preprint", file_role="publication_version")
            c.s.conn.execute("UPDATE papers SET analysis_path=?,supplement_pdf_paths=? WHERE paper_id='fixture'",
                             (str(notes), json.dumps([str(preprint)])))
            c.s.conn.commit()
            before = c.s.get_paper("fixture")
            protected_fields = ("id", "paper_id", "file_type", "file_type_override", "file_role", "version_role",
                                "file_source", "annotation_status", "added_via", "sha256")
            resources_before = {r["id"]: {k: r.get(k) for k in protected_fields}
                                for r in c.s.list_paper_resources("fixture", ensure_primary=False)}

            H.delete_library_entry_in_storage(None, c.s, "folder", c.a["id"])
            self.assert_file_and_aliases(c)
            H.delete_library_entry_in_storage(None, c.s, "folder", c.b["id"])
            self.assert_file_and_aliases(c, recycled=True)
            H.handle_add_library_item(c.handler, dict(paper_id="fixture", folder_id=c.unsorted, snapshot=False))
            self.assert_file_and_aliases(c)
            after = c.s.get_paper("fixture")
            for key in ("storage_key", "primary_resource_id", "preferred_resource_id", "preferred_resource_manual"):
                self.assertEqual(after[key], before[key], key)
            resources_after = {r["id"]: {k: r.get(k) for k in protected_fields}
                               for r in c.s.list_paper_resources("fixture", ensure_primary=False)}
            self.assertEqual(resources_after, resources_before)
            note_path = Path(c.s.get_paper_resource(note["id"])["stored_path"])
            version_path = Path(c.s.get_paper_resource(version["id"])["stored_path"])
            self.assertEqual(note_path.read_text(), "# Preserved analysis\n")
            self.assertEqual(version_path.read_bytes(), b"%PDF preserved preprint")
            self.assertEqual(Path(after["analysis_path"]), note_path)
            self.assertEqual(json.loads(after["supplement_pdf_paths"]), [str(version_path)])
            self.assertNotIn("Recycle", note_path.parts)

    def test_recycled_alias_recovery_rescues_original_from_a_different_recycled_folder(self):
        with library("library") as c:
            H.delete_library_entry_in_storage(None, c.s, "folder", c.a["id"])
            H.delete_library_entry_in_storage(None, c.s, "folder", c.b["id"])
            H.recover_library_entry_in_storage(None, c.s, "folder", c.a["id"])
            self.assert_file_and_aliases(c)

    def test_failed_sql_move_restores_file_alias_and_all_records(self):
        with library("library") as c:
            before = dict(c.s.get_paper("fixture"))
            resources = [dict(r) for r in c.s.conn.execute("SELECT * FROM resources")]
            alias = ui.local_copy_dir_for_library_folder(c.s, c.b["id"]) / c.original.name
            c.s.conn.execute("CREATE TRIGGER fail_move BEFORE UPDATE OF stored_path ON resources BEGIN SELECT RAISE(FAIL, 'fixture path failure'); END")
            c.s.conn.commit()
            with self.assertRaisesRegex(Exception, "fixture path failure"):
                placement.move_original(c.s, "fixture", c.original, alias.parent)
            self.assertEqual(dict(c.s.get_paper("fixture")), before)
            self.assertEqual([dict(r) for r in c.s.conn.execute("SELECT * FROM resources")], resources)
            from paper_monitor.desktop_files import placement_path
            self.assertTrue(finder_alias.is_alias(placement_path(alias)))
            self.assert_file_and_aliases(c)

    def test_failed_filesystem_move_leaves_registered_paths_unchanged(self):
        with library("library") as c:
            before = dict(c.s.get_paper("fixture"))
            with patch.object(placement.shutil, "move", side_effect=OSError("fixture disk failure")):
                with self.assertRaisesRegex(OSError, "fixture disk failure"):
                    placement.move_original(c.s, "fixture", c.original, ui.local_copy_dir_for_library_folder(c.s, c.b["id"]))
            self.assertEqual(dict(c.s.get_paper("fixture")), before)
            self.assert_file_and_aliases(c)

    def test_regular_copy_does_not_scan_all_folders_or_reconcile_all_aliases(self):
        with library() as c:
            with patch.object(placement, "active_directories") as lookup, patch.object(ui, "sync_all_pdf_aliases_for_paper") as sync:
                H.paste_library_entry_in_storage(None, c.s, "item", c.item["id"], c.b["id"])
            lookup.assert_not_called()
            sync.assert_not_called()
            self.assert_file_and_aliases(c)

    def test_operation_responses_refresh_cached_paper_files_paths(self):
        for operation in ("delete", "recover", "paste", "paste-batch", "add"):
            with self.subTest(operation=operation), library("library" if operation == "delete" else None) as c:
                c.handler.delete_library_entry_in_storage = lambda *args, **kwargs: H.delete_library_entry_in_storage(None, *args, **kwargs)
                c.handler.recover_library_entry_in_storage = lambda *args: H.recover_library_entry_in_storage(None, *args)
                c.handler.paste_library_entry_in_storage = lambda *args: H.paste_library_entry_in_storage(None, *args)
                if operation == "delete":
                    H.handle_delete_library_entry(c.handler, dict(type="folder", id=c.a["id"], snapshot=False))
                else:
                    H.delete_library_entry_in_storage(None, c.s, "item", c.item["id"])
                    payload = dict(type="item", id=c.item["id"], target_folder_id=c.b["id"], snapshot=False)
                    if operation == "recover":
                        H.handle_recover_library_entry(c.handler, payload)
                    elif operation == "paste":
                        H.handle_paste_library_entry(c.handler, payload)
                    elif operation == "paste-batch":
                        H.handle_paste_library_entries(c.handler, dict(entries=[payload], target_folder_id=c.b["id"], snapshot=False))
                    else:
                        H.handle_add_library_item(c.handler, dict(paper_id="fixture", folder_id=c.b["id"], snapshot=False))
                path = self.assert_file_and_aliases(c)
                payload = next(p for p in c.replies[-1]["paper_files"] if p["paper_id"] == "fixture")
                self.assertEqual(Path(payload["paper"]["merged_pdf_path"]), path)
                self.assertTrue(payload["files"])
