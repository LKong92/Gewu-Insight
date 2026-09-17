"""Ownership transitions must move one physical file, not import an extra copy."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import ui_server as ui
from paper_monitor.file_reassignment import reassign_paper_file
from tests import test_paper_resources as fixtures


class FileOwnershipMoveTests(unittest.TestCase):
    setUp = fixtures.PaperResourceStorageTests.setUp
    tearDown = fixtures.PaperResourceStorageTests.tearDown
    add_paper = fixtures.PaperResourceStorageTests.add_paper

    def standalone(self, paper_id='standalone', name='notes.rtf'):
        self.add_paper(paper_id)
        folder = self.storage.create_library_folder(name=paper_id, parent_id=1)
        item = self.storage.add_library_item(paper_id=paper_id, folder_id=folder['id'])
        path = self.library_root / paper_id / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{\\rtf1 physical fixture}')
        r = self.storage.create_paper_resource(paper_id=paper_id, stored_path=str(path),
            source_path=str(path), display_name=name, file_type='analysis', added_via='loader')
        self.storage.conn.execute('UPDATE papers SET source_path=?, raw_json=? WHERE paper_id=?',
            (str(path), json.dumps({'import': {'stored_path': str(path)}}), paper_id))
        self.storage.conn.commit()
        return item, r, path

    def target(self):
        self.add_paper('target')
        self.storage.add_library_item(paper_id='target', folder_id=1)
        return self.storage.get_paper('target')

    def test_drag_and_menu_round_trip_preserve_one_file_and_new_identity(self):
        for menu in (False, True):
            with self.subTest(menu=menu):
                source, r, original = self.standalone('source-' + str(menu))
                target = self.target()
                old_key = self.storage.get_paper(source['paper_id'])['storage_key']
                content = original.read_bytes()
                if menu:
                    moved = reassign_paper_file(self.storage, source['paper_id'], r['id'], target_key=target['storage_key'])
                else:
                    moved = ui.convert_library_item_to_paper_attachment(self.storage,
                        source_item_id=source['id'], target_paper_id='target')
                self.assertTrue(moved['source_removed'])
                self.assertIsNone(self.storage.get_paper(source['paper_id']))
                self.assertIsNone(self.storage.get_library_item(source['id']))
                attached = self.storage.get_paper_resource(r['id'])
                attached_path = Path(attached['stored_path'])
                self.assertTrue(attached_path.is_relative_to(self.associated_root))
                self.assertEqual(attached_path.read_bytes(), content)
                self.assertFalse(original.exists())
                self.assertEqual(attached['file_type'], 'analysis')
                # Detach through the same backend as folder drop and context menu.
                detached = reassign_paper_file(self.storage, 'target', r['id'], new_title='Notes', folder_id=source['folder_id'])
                new = self.storage.get_paper(detached['target_paper_id'])
                independent = self.storage.get_paper_resource(r['id'])
                new_path = Path(independent['stored_path'])
                self.assertEqual(new_path, original)
                self.assertEqual(new_path.read_bytes(), content)
                self.assertFalse(attached_path.exists())
                self.assertNotEqual(new['storage_key'], old_key)
                self.assertEqual(self.storage.resolve_default_paper_resource(new['paper_id'])['id'], r['id'])
                self.assertEqual(json.loads(new['raw_json'])['import']['stored_path'], str(new_path))
                self.assertEqual(new['source_path'], str(new_path))
                self.assertEqual(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_remaining_file_keeps_source_identity_and_repairs_import_projection(self):
        item, first, old = self.standalone()
        remaining = old.with_name('remaining.rtf'); remaining.write_bytes(b'remaining')
        second = self.storage.create_paper_resource(paper_id=item['paper_id'], stored_path=str(remaining), file_type='summary')
        target = self.target()
        key = self.storage.get_paper(item['paper_id'])['storage_key']
        result = reassign_paper_file(self.storage, item['paper_id'], first['id'], target_key=target['storage_key'])
        self.assertFalse(result['source_removed'])
        paper = self.storage.get_paper(item['paper_id'])
        self.assertEqual(paper['storage_key'], key)
        self.assertEqual(json.loads(paper['raw_json'])['import']['stored_path'], str(remaining))
        self.assertEqual([r['id'] for r in self.storage.list_paper_resources(item['paper_id'])], [second['id']])
        self.assertTrue(remaining.exists())
        # Target gains no redundant occurrence in the source folder.
        self.assertEqual(self.storage.conn.execute("SELECT count(*) FROM library_items WHERE paper_id='target'").fetchone()[0], 1)

    def test_failed_database_update_restores_file_alias_and_ownership(self):
        item, r, original = self.standalone(); target = self.target()
        alias = original.with_name('alias.rtf'); alias.symlink_to(original)
        before = self.storage.get_paper(item['paper_id'])
        with patch('paper_monitor.file_reassignment._repair_source_pointers', side_effect=RuntimeError('database failure')):
            with self.assertRaisesRegex(RuntimeError, 'database failure'):
                reassign_paper_file(self.storage, item['paper_id'], r['id'], target_key=target['storage_key'])
        self.assertTrue(original.is_file())
        self.assertEqual(alias.resolve(), original.resolve())
        self.assertEqual(self.storage.get_paper(item['paper_id']), before)
        self.assertEqual(self.storage.get_paper_resource(r['id'])['paper_id'], item['paper_id'])
        self.assertFalse(any(p.is_file() for p in self.associated_root.rglob('*')))

    def test_collision_and_alias_cleanup_do_not_leave_a_duplicate(self):
        item, r, original = self.standalone(); target = self.target()
        alias = original.with_name('alias.rtf'); alias.symlink_to(original)
        dest = ui.associated_work_dir_for_paper(self.storage, 'target') / 'Files'
        dest.mkdir(parents=True); occupied = dest / original.name; occupied.write_bytes(b'unrelated')
        reassign_paper_file(self.storage, item['paper_id'], r['id'], target_key=target['storage_key'])
        self.assertFalse(os.path.lexists(alias))
        self.assertFalse(original.exists())
        self.assertEqual(occupied.read_bytes(), b'unrelated')
        self.assertNotEqual(self.storage.get_paper_resource(r['id'])['stored_path'], str(occupied))

    def test_external_linked_original_is_preserved(self):
        self.add_paper('linked'); target = self.target()
        external = self.root / 'external.rtf'; external.write_bytes(b'external')
        r = self.storage.create_paper_resource(paper_id='linked', stored_path=str(external), storage_mode='linked', file_type='analysis')
        reassign_paper_file(self.storage, 'linked', r['id'], target_key=target['storage_key'])
        self.assertEqual(external.read_bytes(), b'external')
        self.assertTrue(Path(self.storage.get_paper_resource(r['id'])['stored_path']).is_relative_to(self.associated_root))

    def test_shared_bytes_rejected_before_move(self):
        item, r, original = self.standalone(); target = self.target()
        self.storage.create_paper_resource(paper_id='target', stored_path=str(original), file_type='summary')
        with self.assertRaisesRegex(ValueError, 'shared'):
            reassign_paper_file(self.storage, item['paper_id'], r['id'], target_key=target['storage_key'])
        self.assertTrue(original.exists())
        self.assertIsNotNone(self.storage.get_paper(item['paper_id']))

    def test_recycle_target_rejected_without_changes(self):
        item, r, original = self.standalone()
        recycle = self.storage.ensure_library_folder(parent_id=1, name='Recycle')
        with self.assertRaisesRegex(ValueError, 'active Library folder'):
            reassign_paper_file(self.storage, item['paper_id'], r['id'], new_title='Notes', folder_id=recycle['id'])
        self.assertTrue(original.exists())
