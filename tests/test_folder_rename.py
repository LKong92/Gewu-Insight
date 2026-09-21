"""Folder rename integrity and failure recovery with disposable data only."""
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from paper_monitor import folder_rename as rename, finder_alias, ui_server as ui
from paper_monitor.download import paper_download_lock
from paper_monitor.storage import Storage
from tests import test_file_layout as fixtures


class FolderRenameTests(unittest.TestCase):
    setUp = fixtures.FileLayoutTests.setUp
    tearDown = fixtures.FileLayoutTests.tearDown
    add_paper = fixtures.FileLayoutTests.add_paper
    fixture = fixtures.FileLayoutTests.fixture

    def prepared(self):
        items, resources, paths = self.fixture()
        ui.sync_all_pdf_aliases_for_paper(self.storage, 'work', preserve_canonical_name=True)
        folder_id = items[1]['folder_id']
        old = ui.local_copy_dir_for_library_folder(self.storage, folder_id).resolve()
        (old / 'empty' / 'nested').mkdir(parents=True)
        (old / 'unregistered.bin').write_bytes(b'not a registered Paper File')
        self.original_files = {p: (p.read_bytes(), rename._identity(p)) for root in
            (self.library_root, self.associated_root) for p in rename._walk(root.resolve())
            if p.is_file() and not finder_alias.is_alias(p)}
        return folder_id, old

    def rows(self):
        return {table: [tuple(r) for r in self.storage.conn.execute(f'SELECT * FROM {table} ORDER BY 1')]
                for table in ('papers', 'resources', 'library_items', 'library_folders', 'app_settings')}

    def assert_restored(self, before, old):
        self.assertEqual(self.rows(), before)
        for path, (content, inode) in self.original_files.items():
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(rename._identity(path), inode)
        self.assertTrue((old / 'empty' / 'nested').is_dir())
        self.assertFalse(old.with_name('After').exists())
        self.assertEqual(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertFalse(list((self.db_path.parent / 'folder-rename-recovery').glob('*/operation.json')))
        paper = self.storage.get_paper('work')
        canonical = ui.canonical_file_path_for_paper(paper)
        alias = self.library_root / 'Crystal' / 'High P.pdf'
        self.assertEqual(finder_alias.resolve(alias), canonical)
        bundle = ui.existing_associated_work_dir(self.storage, 'work')
        for path in ui.parse_raw_json(paper)['file_layout']['associated_aliases']:
            self.assertEqual(finder_alias.resolve(Path(path)), bundle.resolve())

    def test_library_rename_preserves_identity_default_bytes_and_all_aliases(self):
        folder_id, old = self.prepared()
        before = self.storage.get_paper('work')
        original_resources = self.storage.list_paper_resources('work', ensure_primary=False)
        folder, result = rename.rename(self.storage, folder_id, 'After')
        new = old.with_name('After')
        self.assertEqual(folder['name'], 'After')
        self.assertFalse(old.exists())
        self.assertTrue((new / 'empty' / 'nested').is_dir())
        self.assertEqual((new / 'unregistered.bin').read_bytes(), b'not a registered Paper File')
        after = self.storage.get_paper('work')
        for field in ('storage_key', 'primary_resource_id', 'preferred_resource_id', 'preferred_resource_manual', 'doi'):
            self.assertEqual(before[field], after[field])
        for original in original_resources:
            resource = self.storage.get_paper_resource(original['id'])
            self.assertEqual(resource['source_path'], original['source_path'])
            self.assertEqual(resource['file_type'], original['file_type'])
            self.assertEqual(Path(resource['stored_path']).read_bytes(), self.original_files[Path(original['stored_path'])][0])
            self.assertIn('/After/', resource['stored_path'])
        main = ui.canonical_file_path_for_paper(after)
        self.assertEqual(finder_alias.resolve(self.library_root / 'Crystal' / 'High P.pdf'), main)
        bundle = ui.existing_associated_work_dir(self.storage, 'work')
        for path in ui.parse_raw_json(after)['file_layout']['associated_aliases']:
            self.assertEqual(finder_alias.resolve(Path(path)), bundle.resolve())
        self.assertEqual(result['renamed_paper_ids'], ['work'])
        self.assertFalse(self.storage.conn.execute("SELECT 1 FROM app_settings WHERE key LIKE 'folder_rename_committed:%'").fetchone())

    def test_alias_only_folder_moves_links_without_moving_original(self):
        self.prepared()
        folder = next(f for f in self.storage.list_library_folders() if f['name'] == 'Crystal')
        before = self.storage.get_paper('work')['merged_pdf_path']
        rename.rename(self.storage, folder['id'], 'After')
        self.assertEqual(self.storage.get_paper('work')['merged_pdf_path'], before)
        self.assertEqual(finder_alias.resolve(self.library_root / 'After' / 'High P.pdf'), Path(before))
        raw = ui.parse_raw_json(self.storage.get_paper('work'))
        self.assertTrue(all('/After/' in p for p in raw['file_layout']['associated_aliases']))

    def test_move_failure_restores_whole_operation(self):
        folder_id, old = self.prepared(); before = self.rows()
        original = rename._move
        calls = []
        def fail(source, destination):
            calls.append(source)
            if len(calls) == 4:
                raise OSError('synthetic move failure')
            return original(source, destination)
        with patch.object(rename, '_move', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                rename.rename(self.storage, folder_id, 'After')
        self.assert_restored(before, old)

    def test_database_failure_after_file_moves_restores_all_rows_and_aliases(self):
        folder_id, old = self.prepared(); before = self.rows()
        original = ui.update_paper_file_path_references
        calls = []
        def fail(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('synthetic database failure')
            return original(*args, **kwargs)
        with patch.object(ui, 'update_paper_file_path_references', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                rename.rename(self.storage, folder_id, 'After')
        self.assert_restored(before, old)

    def test_alias_creation_failure_restores_original_bookmarks(self):
        folder_id, old = self.prepared(); before = self.rows()
        with patch.object(finder_alias, 'create', side_effect=OSError('synthetic alias failure')):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                rename.rename(self.storage, folder_id, 'After')
        self.assert_restored(before, old)

    def test_interruption_before_commit_is_recovered_on_reopen(self):
        folder_id, old = self.prepared(); before = self.rows()
        with patch.object(ui, 'update_paper_file_path_references', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                rename.rename(self.storage, folder_id, 'After')
        self.storage.close()
        self.storage = Storage(self.db_path)
        rename.recover(self.storage)
        self.assert_restored(before, old)

    def test_interruption_after_commit_keeps_new_paths(self):
        folder_id, old = self.prepared()
        with patch.object(rename.RenameJournal, 'finish', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                rename.rename(self.storage, folder_id, 'After')
        self.storage.close(); self.storage = Storage(self.db_path)
        rename.recover(self.storage)
        self.assertEqual(self.storage.get_library_folder(folder_id)['name'], 'After')
        self.assertFalse(old.exists())
        for resource in self.storage.list_paper_resources('work', ensure_primary=False):
            self.assertTrue(Path(resource['stored_path']).is_file())
            self.assertIn('/After/', resource['stored_path'])
        self.assertFalse(list((self.db_path.parent / 'folder-rename-recovery').glob('*/operation.json')))

    def test_collision_never_merges_or_overwrites_an_existing_folder(self):
        folder_id, old = self.prepared(); before = self.rows()
        collision = old.with_name('After'); collision.mkdir()
        other = collision / 'keep.bin'; other.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            rename.rename(self.storage, folder_id, 'After')
        self.assertEqual(before, self.rows()); self.assertEqual(other.read_bytes(), b'existing')

    def test_case_only_and_same_sanitized_path_renames(self):
        folder_id, old = self.prepared()
        rename.rename(self.storage, folder_id, 'pressure')
        canonical = ui.canonical_file_path_for_paper(self.storage.get_paper('work'))
        self.assertEqual(canonical.parent.name, 'pressure')
        self.assertTrue(canonical.is_file())
        self.assertEqual(finder_alias.resolve(self.library_root / 'Crystal' / 'High P.pdf'), canonical)
        # Both UI labels map to the same safe Finder component.
        rename.rename(self.storage, folder_id, 'A:B')
        rename.rename(self.storage, folder_id, 'A/B')
        self.assertEqual(ui.canonical_file_path_for_paper(self.storage.get_paper('work')).parent.name, 'A-B')

    def test_case_only_failure_restores_actual_directory_spelling(self):
        folder_id, old = self.prepared(); before = self.rows()
        with patch.object(ui, 'update_paper_file_path_references', side_effect=OSError('synthetic')):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                rename.rename(self.storage, folder_id, 'pressure')
        self.assertEqual(self.rows(), before)
        self.assertTrue(old.is_dir())
        self.assertIn('Pressure', [p.name for p in old.parent.iterdir()])
        for path, (content, _) in self.original_files.items():
            self.assertEqual(path.read_bytes(), content)

    def test_space_root_label_commits_with_paths_and_rolls_back_on_error(self):
        space = self.storage.create_library_root_folder(name='Space')
        directory = ui.local_copy_dir_for_library_folder(self.storage, space['id'])
        directory.mkdir(parents=True); (directory / 'data.txt').write_text('kept')
        tabs = [{'tab_id': 'space-1', 'root_folder_id': space['id'], 'label': 'Space'}]
        ui.save_library_workspace_tabs(self.storage, tabs)
        before = self.rows()
        with patch.object(rename.RenameJournal, 'apply', side_effect=OSError('synthetic')):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                rename.rename(self.storage, space['id'], 'After', workspace_tabs=tabs)
        self.assertEqual(self.rows(), before)
        rename.rename(self.storage, space['id'], 'After', workspace_tabs=tabs)
        self.assertEqual(ui.library_workspace_tabs(self.storage)[0]['label'], 'After')
        self.assertEqual((directory.with_name('After') / 'data.txt').read_text(), 'kept')

    def test_empty_logical_folder_gets_real_directory(self):
        folder = self.storage.create_library_folder(parent_id=1, name='Before')
        rename.rename(self.storage, folder['id'], 'After')
        self.assertTrue((self.library_root / 'After').is_dir())

    def test_missing_file_stays_missing_with_updated_registration(self):
        folder_id, old = self.prepared()
        resource = self.storage.list_paper_resources('work', ensure_primary=False)[0]
        Path(resource['stored_path']).unlink()
        rename.rename(self.storage, folder_id, 'After')
        resource = self.storage.get_paper_resource(resource['id'])
        self.assertIn('/After/', resource['stored_path'])
        self.assertEqual(resource['missing_status'], 'missing')
        self.assertFalse(Path(resource['stored_path']).exists())

    def test_busy_download_is_rejected_without_any_changes(self):
        folder_id, old = self.prepared(); before = self.rows()
        ready, finish = threading.Event(), threading.Event()
        def download():
            with paper_download_lock(self.db_path, 'work'):
                ready.set(); finish.wait(10)
        thread = threading.Thread(target=download); thread.start(); ready.wait(5)
        try:
            with self.assertRaisesRegex(ValueError, 'download is still running'):
                rename.rename(self.storage, folder_id, 'After')
        finally:
            finish.set(); thread.join(5)
        self.assert_restored(before, old)

    def test_shared_path_owner_and_standalone_file_keep_their_keys(self):
        folder_id, old = self.prepared()
        self.add_paper('shared')
        main = self.storage.get_paper('work')['merged_pdf_path']
        self.storage.conn.execute('UPDATE papers SET main_pdf_path=?, merged_pdf_path=? WHERE paper_id=?', (main,main,'shared'))
        self.storage.conn.commit()
        self.add_paper('note')
        note = old / 'standalone.md'; note.write_text('# ordinary file')
        self.storage.create_paper_resource(paper_id='note', stored_path=str(note), file_type='other')
        self.storage.update_paper_raw_json('note', {'import': {'stored_path': str(note)}, 'file': {'extension': '.md'}})
        self.storage.add_library_item(paper_id='note', folder_id=folder_id)
        keys = {pid:self.storage.get_paper(pid)['storage_key'] for pid in ('work','shared','note')}
        rename.rename(self.storage, folder_id, 'After')
        for pid, key in keys.items():
            self.assertEqual(self.storage.get_paper(pid)['storage_key'], key)
        self.assertEqual(self.storage.get_paper('shared')['merged_pdf_path'], self.storage.get_paper('work')['merged_pdf_path'])
        self.assertEqual(Path(ui.parse_raw_json(self.storage.get_paper('note'))['import']['stored_path']).read_text(), '# ordinary file')

    def test_discovery_walks_each_managed_root_once(self):
        folder_id, old = self.prepared()
        original = rename._walk; calls = []
        def walk(root):
            calls.append(root)
            yield from original(root)
        with patch.object(rename, '_walk', side_effect=walk):
            rename.rename(self.storage, folder_id, 'After')
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(set(calls)), 4)

    def test_external_and_dangling_symlinks_keep_targets_without_importing_bytes(self):
        folder_id, old = self.prepared()
        external = self.root / 'external.txt'; external.write_text('external content')
        os.symlink(external, old / 'external link.txt')
        missing = self.root / 'missing.txt'
        os.symlink(missing, old / 'missing link.txt')
        rename.rename(self.storage, folder_id, 'After')
        for name, target in [('external link.txt', external), ('missing link.txt', missing)]:
            alias = old.with_name('After') / name
            self.assertTrue(finder_alias.is_alias(alias))
            self.assertEqual(finder_alias.resolve(alias), target.resolve())
        self.assertEqual(external.read_text(), 'external content')
        self.assertFalse(missing.exists())

    def test_interrupted_exclusive_link_is_recovered_without_duplicate_files(self):
        folder_id, old = self.prepared(); before = self.rows()
        original = rename._move
        def interrupt(source, destination):
            if source.suffix == '.pdf':
                os.link(source, destination, follow_symlinks=False)
                raise KeyboardInterrupt()
            return original(source, destination)
        with patch.object(rename, '_move', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                rename.rename(self.storage, folder_id, 'After')
        self.storage.close(); self.storage = Storage(self.db_path)
        rename.recover(self.storage)
        self.assert_restored(before, old)

    def test_rollback_never_overwrites_a_new_finder_file(self):
        folder_id, old = self.prepared()
        conflict = old / 'unregistered.bin'
        def fail(*args, **kwargs):
            conflict.write_bytes(b'new file saved in Finder')
            raise OSError('synthetic late failure')
        with patch.object(ui, 'update_paper_file_path_references', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'recovery is pending'):
                rename.rename(self.storage, folder_id, 'After')
        self.assertEqual(conflict.read_bytes(), b'new file saved in Finder')
        self.assertEqual((old.with_name('After') / conflict.name).read_bytes(), self.original_files[conflict][0])
        # Removing only the synthetic conflicting save lets recovery finish.
        conflict.unlink()
        rename.recover(self.storage)
        self.assertEqual(conflict.read_bytes(), self.original_files[conflict][0])

    def test_rename_avoids_sanitized_name_collision_with_another_logical_folder(self):
        folder_id, old = self.prepared()
        self.storage.create_library_folder(parent_id=1, name='A:B')
        with self.assertRaisesRegex(ValueError, 'same Finder name'):
            rename.rename(self.storage, folder_id, 'A/B')
        self.assertEqual(self.storage.get_library_folder(folder_id)['name'], 'Pressure')
        self.assertTrue(old.is_dir())

    def test_empty_recovery_never_scans_the_library(self):
        with patch.object(rename, '_plan', side_effect=AssertionError('unexpected scan')):
            rename.recover(self.storage)
        self.assertFalse(self.storage.conn.in_transaction)

    def test_startup_recovers_rename_before_background_workers(self):
        from tests import test_startup_move_recovery as startup
        folder_id, old = self.prepared()
        with patch.object(ui, 'update_paper_file_path_references', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                rename.rename(self.storage, folder_id, 'After')
        self.storage.close(); self.storage = Storage(self.db_path)
        def recovered():
            self.assertEqual(self.storage.get_library_folder(folder_id)['name'], 'Pressure')
            self.assertFalse(old.with_name('After').exists())
            for path, (content, _) in self.original_files.items():
                self.assertEqual(path.read_bytes(), content)
        startup.StartupMoveRecoveryTests.launch(self, before_workers=recovered)
        recovered()

    def test_case_only_failure_before_staging_leaves_original_files(self):
        folder_id, old = self.prepared(); before = self.rows()
        with patch.object(rename.RenameJournal, 'apply', side_effect=OSError('synthetic pre-stage failure')):
            with self.assertRaisesRegex(OSError, 'synthetic pre-stage'):
                rename.rename(self.storage, folder_id, 'pressure')
        self.assertEqual(self.rows(), before)
        for path, (content, inode) in self.original_files.items():
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(rename._identity(path), inode)
        self.assertFalse(list((self.db_path.parent / 'folder-rename-recovery').glob('*/operation.json')))
