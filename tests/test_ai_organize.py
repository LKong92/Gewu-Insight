"""Organization uses disposable SQLite/files only, including failure injection."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from paper_monitor import ai_service, ai_store, ai_organize, folder_rename, finder_alias, ui_server as ui, mcp_server
from paper_monitor.ai_contract import WRITE_SCOPES, ORGANIZE_TOOLS
from paper_monitor.file_layout import reconcile
from tests import test_file_layout as fixtures


class AIOrganizeTests(unittest.TestCase):
    tearDown = fixtures.FileLayoutTests.tearDown
    add_paper = fixtures.FileLayoutTests.add_paper
    fixture = fixtures.FileLayoutTests.fixture

    def setUp(self):
        fixtures.FileLayoutTests.setUp(self)
        self.items, self.resources, self.paths = self.fixture()
        reconcile(self.storage, 'work')
        self.key = self.storage.get_paper('work')['storage_key']
        self.space = self.storage.create_library_root_folder(name='Research')
        self.folder = self.storage.create_library_folder(parent_id=self.space['id'], name='Destination')
        self.storage.set_setting('ai_access_enabled', 'true')
        self.token = self.grant()
        self.sequence = 0

    def grant(self, roots=None, scopes=None):
        return ai_store.create_connection(self.storage, {'name': 'Organizer', 'scopes': scopes or ['papers:read', 'folders:read', *set(WRITE_SCOPES.values())],
            'selection': {'kind': 'saved'}, 'write_folder_ids': roots if roots is not None else [1, self.space['id']]})['token']

    def call(self, operation, args, *, token=None):
        self.sequence += 1
        args = {'request_id': 'organize-request-%03d' % self.sequence, **args}
        return ai_service.execute(self.storage, 'Bearer ' + (token or self.token), operation, args)

    def source(self, index=1):
        return {'membership_id': self.items[index]['id']}

    def file_source(self, index=0):
        return {'gewu_key': self.key, 'file_id': self.resources[index]['id']}

    def canonical(self):
        return ui.canonical_file_path_for_paper(self.storage.get_paper('work'))

    def snapshot(self):
        return {t: [tuple(r) for r in self.storage.conn.execute('SELECT * FROM ' + t + ' ORDER BY 1')]
                for t in ('papers', 'resources', 'library_items', 'library_folders', 'ai_write_requests')}

    def assert_error(self, code, operation, args, **kwargs):
        with self.assertRaises(ai_store.APIError) as caught:
            self.call(operation, args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_move_canonical_membership_across_space_preserves_files_and_aliases(self):
        before = self.storage.get_paper('work')
        data = {r['id']: Path(r['stored_path']).read_bytes() for r in self.storage.list_paper_resources('work')}
        args = {'source': self.source(), 'target': {'folder_id': self.folder['id']}, 'request_id': 'move-canonical-001'}
        result = self.call('move_file', args)
        self.assertFalse(result['layout_pending'])
        self.assertEqual(result['membership_id'], self.items[1]['id'])
        self.assertEqual(self.canonical().parent, ui.local_copy_dir_for_library_folder(self.storage, self.folder['id']).resolve())
        self.assertFalse(self.paths[1].exists())
        self.assertEqual(finder_alias.resolve(self.paths[0]), self.canonical())
        self.assertIn('/Spaces/Research/Destination/', ui.existing_associated_work_dir(self.storage, 'work').as_posix())
        for r in self.storage.list_paper_resources('work'):
            self.assertEqual(Path(r['stored_path']).read_bytes(), data[r['id']])
        after = self.storage.get_paper('work')
        for key in ('storage_key', 'doi', 'primary_resource_id', 'preferred_resource_id', 'preferred_resource_manual'):
            self.assertEqual(before[key], after[key])
        self.assertTrue(self.call('move_file', args)['reused_request'])
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_alias_only_membership_rename_preserves_canonical_filename(self):
        main = self.canonical()
        result = self.call('rename_file', {'source': self.source(0), 'name': 'Reading copy'})
        self.assertFalse(result['layout_pending'])
        self.assertEqual(self.canonical(), main)
        self.assertFalse(self.paths[0].exists())
        alias = self.paths[0].with_name('Reading copy.pdf')
        self.assertEqual(finder_alias.resolve(alias), main)

    def test_rename_default_file_keeps_name_after_reconcile_and_moves_bundle(self):
        result = self.call('rename_file', {'source': self.file_source(1), 'name': 'Renamed.pdf'})
        self.assertEqual(self.canonical().name, 'Renamed.pdf')
        self.assertFalse(result['layout_pending'])
        reconcile(self.storage, 'work')
        self.assertEqual(self.canonical().name, 'Renamed.pdf')
        self.assertTrue(ui.existing_associated_work_dir(self.storage, 'work').name.startswith('Renamed ['))
        self.assertEqual(finder_alias.resolve(self.paths[0]), self.canonical())
        self.assertEqual(self.storage.resolve_default_paper_resource('work')['id'], self.resources[1]['id'])

    def test_rename_attachment_changes_only_name_and_path(self):
        resource = self.storage.get_paper_resource(self.resources[0]['id'])
        old = Path(resource['stored_path']); content = old.read_bytes()
        result = self.call('rename_file', {'source': self.file_source(), 'name': 'Attachment.pdf'})
        current = self.storage.get_paper_resource(resource['id'])
        self.assertFalse(old.exists())
        self.assertEqual(Path(current['stored_path']).name, 'Attachment.pdf')
        self.assertEqual(Path(current['stored_path']).read_bytes(), content)
        for key in ('id', 'paper_id', 'file_type', 'file_source', 'source_path', 'added_via'):
            self.assertEqual(resource[key], current[key])
        self.assertEqual(result['files'][0]['name'], 'Attachment.pdf')

    def test_folder_move_carries_empty_and_unregistered_contents(self):
        source = self.paths[1].parent
        (source / 'empty').mkdir()
        (source / 'unregistered.txt').write_bytes(b'user contents')
        before = self.storage.get_paper('work')
        args = {'folder_id': self.items[1]['folder_id'], 'parent_id': self.folder['id'], 'request_id': 'folder-whole-001'}
        result = self.call('move_folder', args)
        target = ui.local_copy_dir_for_library_folder(self.storage, result['folder_id'])
        self.assertFalse(source.exists())
        self.assertEqual((target / 'unregistered.txt').read_bytes(), b'user contents')
        self.assertTrue((target / 'empty').is_dir())
        self.assertEqual(finder_alias.resolve(self.paths[0]), self.canonical())
        self.assertEqual(self.storage.get_paper('work')['storage_key'], before['storage_key'])
        self.assertTrue(self.call('move_folder', args)['reused_request'])

    def test_folder_rename_and_space_label_persist(self):
        self.call('rename_folder', {'folder_id': self.space['id'], 'name': 'Research renamed'})
        self.assertEqual(self.storage.get_library_folder(self.space['id'])['name'], 'Research renamed')
        self.assertTrue((self.spaces_root / 'Research renamed').is_dir())

    def test_conflicts_and_bad_names_do_not_change_database_or_bytes(self):
        old = self.canonical()
        collision = old.with_name('Occupied.pdf'); collision.write_bytes(b'unrelated')
        before = self.snapshot()
        self.assert_error('organization_conflict', 'rename_file', {'source': self.file_source(1), 'name': collision.name})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(collision.read_bytes(), b'unrelated')
        self.assertEqual(self.canonical(), old)
        self.assert_error('extension_changed', 'rename_file', {'source': self.file_source(0), 'name': 'Not a PDF.md'})
        self.assert_error('invalid_filename', 'rename_file', {'source': self.file_source(0), 'name': '../escape.pdf'})
        self.assert_error('folder_cycle', 'move_folder', {'folder_id': self.space['id'], 'parent_id': self.folder['id']})
        self.assert_error('protected_folder', 'rename_folder', {'folder_id': 1, 'name': 'Not Library'})

    def test_rollback_after_files_move_restores_receipt_paths_and_aliases(self):
        before = self.snapshot()
        content = self.canonical().read_bytes()
        with patch.object(ai_organize, 'save_receipt', side_effect=OSError('synthetic receipt failure')):
            self.assert_error('organization_unavailable', 'move_file', {'source': self.source(), 'target': {'folder_id': self.folder['id']}})
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.canonical(), self.paths[1])
        self.assertEqual(self.canonical().read_bytes(), content)
        self.assertEqual(finder_alias.resolve(self.paths[0]), self.canonical())
        self.assertFalse(list((self.storage.db_path.parent / 'folder-rename-recovery').glob('*/operation.json')))

    def test_layout_retry_never_repeats_the_move(self):
        args = {'source': self.source(), 'name': 'New label', 'request_id': 'retry-layout-001'}
        with patch('paper_monitor.file_layout.reconcile', side_effect=OSError('synthetic alias failure')):
            self.assertTrue(self.call('rename_file', args)['layout_pending'])
        current = self.canonical()
        with patch('paper_monitor.file_organize.organize', side_effect=AssertionError('must not repeat')):
            result = self.call('rename_file', args)
        self.assertFalse(result['layout_pending'])
        self.assertTrue(result['reused_request'])
        self.assertEqual(self.canonical(), current)

    def test_permissions_are_explicit_and_cover_every_location(self):
        old = self.grant(scopes=['papers:read', 'files:add'])
        self.assert_error('permission_required', 'rename_file', {'source': self.source(), 'name': 'No'}, token=old)
        narrow = self.grant(roots=[self.items[1]['folder_id']])
        self.assert_error('write_scope_required', 'rename_file', {'source': self.source(), 'name': 'No'}, token=narrow)
        library_only = self.grant(roots=[1])
        self.assert_error('write_scope_required', 'move_file', {'source': self.source(), 'target': {'folder_id': self.folder['id']}}, token=library_only)
        for name in ORGANIZE_TOOLS:
            self.assertFalse(mcp_server.tool_allowed(name, ['papers:read', 'files:add']))
            self.assertTrue(mcp_server.tool_allowed(name, ['papers:read', WRITE_SCOPES[name]]))

    def test_transfer_attachment_and_detach_non_pdf_preserve_file_id(self):
        self.add_paper('target')
        self.storage.add_library_item(paper_id='target', folder_id=self.folder['id'])
        target_key = self.storage.get_paper('target')['storage_key']
        args = {'source': self.file_source(), 'target': {'gewu_key': target_key}, 'request_id': 'transfer-file-001'}
        old_bytes = Path(self.storage.get_paper_resource(self.resources[0]['id'])['stored_path']).read_bytes()
        result = self.call('move_file', args)
        self.assertFalse(result['source_removed'])
        self.assertTrue(self.call('move_file', args)['reused_request'])
        current = self.storage.get_paper_resource(self.resources[0]['id'])
        self.assertEqual(current['paper_id'], 'target')
        self.assertEqual(Path(current['stored_path']).read_bytes(), old_bytes)
        note = ui.attach_file_to_paper(self.storage, paper_id='work', filename='Review.md', content=b'# Review', file_type='other')
        args = {'source': {'gewu_key': self.key, 'file_id': note['id']}, 'target': {'folder_id': self.folder['id']}, 'request_id': 'detach-note-001'}
        detached = self.call('move_file', args)
        self.assertTrue(detached['created_item'])
        current = self.storage.get_paper_resource(note['id'])
        self.assertEqual(current['id'], note['id'])
        self.assertEqual(Path(current['stored_path']).parent, ui.local_copy_dir_for_library_folder(self.storage, self.folder['id']).resolve())
        self.assertEqual(Path(current['stored_path']).read_bytes(), b'# Review')
        paper = self.storage.get_paper(current['paper_id'])
        self.assertEqual(paper['type'], 'imported_file')
        self.assertFalse(paper['doi'])
        self.assertFalse(paper['main_pdf_path'])
        self.assertTrue(self.call('move_file', args)['reused_request'])

    def test_move_last_file_retires_source_and_exact_retry_survives(self):
        self.add_paper('single')
        item = self.storage.add_library_item(paper_id='single', folder_id=1)
        file = ui.attach_file_to_paper(self.storage, paper_id='single', filename='Single.md', content=b'single note', file_type='other')
        args = {'source': {'membership_id': item['id']}, 'target': {'gewu_key': self.key}, 'request_id': 'retire-single-001'}
        result = self.call('move_file', args)
        self.assertTrue(result['source_removed'])
        self.assertIsNone(self.storage.get_paper('single'))
        self.assertEqual(self.storage.get_paper_resource(file['id'])['paper_id'], 'work')
        self.assertTrue(self.call('move_file', args)['reused_request'])

    def test_duplicate_membership_merges_placement_without_losing_files(self):
        result = self.call('move_file', {'source': self.source(), 'target': {'folder_id': self.items[0]['folder_id']}})
        self.assertEqual(result['membership_id'], self.items[0]['id'])
        self.assertIsNone(self.storage.get_library_item(self.items[1]['id']))
        self.assertEqual(self.canonical().parent, self.paths[0].parent)
        self.assertEqual(len(self.storage.list_paper_resources('work')), 2)

    def test_alias_move_into_existing_canonical_membership_removes_only_old_projection(self):
        main = self.canonical()
        result = self.call('move_file', {'source': self.source(0), 'target': {'folder_id': self.items[1]['folder_id']}})
        self.assertEqual(result['membership_id'], self.items[1]['id'])
        self.assertEqual(self.canonical(), main)
        self.assertFalse(self.paths[0].exists())
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM library_items WHERE paper_id=?', ('work',)).fetchone()[0], 1)

    def test_alias_move_to_existing_alias_membership_and_new_folder(self):
        third = self.storage.add_library_item(paper_id='work', folder_id=self.folder['id'])
        reconcile(self.storage, 'work')
        main = self.canonical()
        result = self.call('move_file', {'source': self.source(0), 'target': {'folder_id': self.folder['id']}})
        self.assertEqual(result['membership_id'], third['id'])
        self.assertEqual(self.canonical(), main)
        self.assertFalse(self.paths[0].exists())
        result = self.call('move_file', {'source': {'membership_id': third['id']}, 'target': {'folder_id': 1}})
        self.assertEqual(self.canonical(), main)
        self.assertEqual(finder_alias.resolve(self.library_root / '1.nmat.pdf'), main)

    def test_my_publications_and_external_original_are_not_modified(self):
        self.storage.add_my_publication(paper_id='work')
        self.assert_error('write_scope_required', 'rename_file', {'source': self.file_source(), 'name': 'No.pdf'})
        self.assert_error('write_scope_required', 'move_folder', {'folder_id': self.items[1]['folder_id'], 'parent_id': self.folder['id']})
        self.storage.conn.execute("DELETE FROM my_publications WHERE paper_id='work'"); self.storage.conn.commit()
        old = self.canonical()
        external = self.root / 'External.pdf'; old.rename(external)
        ui.update_paper_file_path_references(self.storage, 'work', old, external)
        self.assert_error('organization_conflict', 'rename_file', {'source': self.file_source(1), 'name': 'No.pdf'})
        self.assertTrue(external.exists())

    def test_transfer_receipt_failure_rolls_back_ownership_and_paths(self):
        self.add_paper('target'); self.storage.add_library_item(paper_id='target', folder_id=self.folder['id'])
        before = self.snapshot()
        file = self.storage.get_paper_resource(self.resources[0]['id']); path = Path(file['stored_path']); data = path.read_bytes()
        with patch.object(ai_organize, 'save_receipt', side_effect=OSError('synthetic write failure')):
            self.assert_error('organization_unavailable', 'move_file', {'source': self.file_source(), 'target': {'gewu_key': self.storage.get_paper('target')['storage_key']}})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(path.read_bytes(), data)

    def test_folder_receipt_failure_rolls_back_whole_tree(self):
        before = self.snapshot()
        with patch.object(ai_organize, 'save_receipt', side_effect=OSError('synthetic write failure')):
            self.assert_error('organization_unavailable', 'move_folder', {'folder_id': self.items[1]['folder_id'], 'parent_id': self.folder['id']})
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.paths[1].exists())
        self.assertEqual(finder_alias.resolve(self.paths[0]), self.paths[1])

    def test_changed_request_and_revoked_scope_cannot_replay(self):
        args = {'source': self.source(), 'name': 'One', 'request_id': 'stable-rename-001'}
        self.call('rename_file', args)
        self.assert_error('request_conflict', 'rename_file', {**args, 'name': 'Two'})
        self.storage.conn.execute("UPDATE ai_connections SET scopes_json=? WHERE name='Organizer'", (json.dumps(['papers:read']),))
        self.storage.conn.commit()
        self.assert_error('permission_required', 'rename_file', args)

    def test_space_move_to_library_and_empty_folder_move(self):
        result = self.call('move_folder', {'folder_id': self.space['id'], 'parent_id': 1})
        self.assertEqual(result['kind'], 'folder')
        self.assertTrue((self.library_root / 'Research').is_dir())
        self.assertFalse(any(t.get('root_folder_id') == self.space['id'] for t in ui.library_workspace_tabs(self.storage)))
        result = self.call('move_folder', {'folder_id': self.folder['id'], 'parent_id': 1})
        self.assertTrue((self.library_root / 'Destination').is_dir())
        self.assertEqual(result['parent_id'], 1)

    def test_case_only_file_rename_and_rollback(self):
        old = self.canonical()
        before = self.snapshot()
        with patch.object(ai_organize, 'save_receipt', side_effect=OSError('synthetic write failure')):
            self.assert_error('organization_unavailable', 'rename_file', {'source': self.file_source(1), 'name': old.name.upper()})
        self.assertEqual(self.snapshot(), before)
        self.assertIn(old.name, [p.name for p in old.parent.iterdir()])
        result = self.call('rename_file', {'source': self.file_source(1), 'name': old.name.upper()})
        self.assertFalse(result['layout_pending'])
        self.assertEqual(self.canonical().name, old.name.upper())

    def test_unregistered_shortcut_outside_grant_blocks_global_retargeting(self):
        self.publications_root.mkdir(parents=True, exist_ok=True)
        alias = self.publications_root / 'Unregistered alias.pdf'
        alias = finder_alias.create(self.canonical(), alias)
        before = self.snapshot()
        self.assert_error('write_scope_required', 'rename_file', {'source': self.file_source(1), 'name': 'Changed.pdf'})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(finder_alias.resolve(alias), self.canonical())
        self.assert_error('write_scope_required', 'move_folder', {'folder_id': self.items[1]['folder_id'], 'parent_id': self.folder['id']})

    def test_child_only_grant_can_rename_its_own_empty_root(self):
        token = self.grant(roots=[self.folder['id']], scopes=['papers:read', 'folders:rename'])
        result = self.call('rename_folder', {'folder_id': self.folder['id'], 'name': 'Child only'}, token=token)
        self.assertEqual(result['name'], 'Child only')


if __name__ == '__main__':
    unittest.main()
