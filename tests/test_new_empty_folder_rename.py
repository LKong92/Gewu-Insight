"""Fresh UI folders may skip discovery; existing files keep the full workflow."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from paper_monitor import finder_alias, folder_rename as rename, ui_server as ui
from tests import test_folder_rename as fixtures


class NewEmptyFolderRenameTests(unittest.TestCase):
    setUp = fixtures.FolderRenameTests.setUp
    tearDown = fixtures.FolderRenameTests.tearDown
    add_paper = fixtures.FolderRenameTests.add_paper
    rows = fixtures.FolderRenameTests.rows

    def fresh(self, name='New Folder'):
        folder = self.storage.create_library_folder(parent_id=1, name=name)
        rename.remember_new_empty_folder(self.storage, folder)
        old = ui.local_copy_dir_for_library_folder(self.storage, folder['id']).resolve()
        associated = self.associated_root / 'Library' / old.name
        return folder, old, associated

    def rename_with_full_plan(self, folder, name='After', **kwargs):
        with patch.object(rename, '_plan', wraps=rename._plan) as plan:
            result = rename.rename(self.storage, folder['id'], name, **kwargs)
        self.assertEqual(plan.call_count, 1)
        return result

    def test_new_empty_folder_uses_one_reference_check_and_no_discovery(self):
        folder, old, _ = self.fresh()
        with patch.object(rename, '_plan', side_effect=AssertionError('full traversal')):
            with patch.object(rename, '_references', wraps=rename._references) as references:
                result, changes = rename.rename(self.storage, folder['id'], 'After')
        self.assertEqual(references.call_count, 1)
        self.assertEqual(result['name'], 'After')
        self.assertEqual(changes['renamed_paper_ids'], [])
        self.assertTrue(old.with_name('After').is_dir())
        self.assertFalse(old.exists())
        self.assertFalse(self.storage.conn.in_transaction)
        self.assertFalse(list(self.db_path.parent.glob('folder-rename-recovery/*/operation.json')))
        self.assertEqual(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_empty_folder_without_ui_creation_hint_keeps_full_workflow(self):
        folder = self.storage.create_library_folder(parent_id=1, name='Imported empty folder')
        self.rename_with_full_plan(folder)

    def test_unavailable_path_check_only_disables_the_hint(self):
        folder = self.storage.create_library_folder(parent_id=1, name='Before')
        with patch.object(rename, '_roots', side_effect=ValueError('unavailable scope')):
            rename.remember_new_empty_folder(self.storage, folder)
        self.rename_with_full_plan(folder)

    def test_hint_is_one_use(self):
        folder, _, _ = self.fresh()
        rename.rename(self.storage, folder['id'], 'After')
        self.rename_with_full_plan(folder, 'Again')

    def test_changed_folder_row_keeps_full_workflow(self):
        folder, _, _ = self.fresh()
        self.storage.set_library_folder_color(folder_id=folder['id'], color='#112233')
        self.rename_with_full_plan(folder)

    def test_new_subfolder_keeps_full_workflow(self):
        folder, _, _ = self.fresh()
        child = self.storage.create_library_folder(parent_id=folder['id'], name='Nested')
        self.rename_with_full_plan(folder)
        self.assertEqual(self.storage.get_library_folder(child['id'])['parent_id'], folder['id'])

    def test_metadata_only_paper_keeps_full_workflow(self):
        folder, _, _ = self.fresh()
        self.add_paper('metadata-only')
        self.storage.add_library_item(paper_id='metadata-only', folder_id=folder['id'])
        _, result = self.rename_with_full_plan(folder)
        self.assertEqual(result['renamed_paper_ids'], ['metadata-only'])

    def test_files_added_after_creation_keep_full_workflow_and_bytes(self):
        for location in ('Library', 'Associated Files'):
            with self.subTest(location=location):
                folder, old, associated = self.fresh('New ' + location)
                root = old if location == 'Library' else associated
                root.mkdir(parents=True)
                file = root / 'unregistered.bin'
                file.write_bytes(b'original bytes')
                inode = rename._identity(file)
                self.rename_with_full_plan(folder, 'Renamed ' + location)
                destination = root.with_name('Renamed ' + location) / file.name
                self.assertEqual(destination.read_bytes(), b'original bytes')
                self.assertEqual(rename._identity(destination), inode)

    def test_even_empty_existing_directory_keeps_inbound_aliases(self):
        folder, old, _ = self.fresh()
        old.mkdir(parents=True)
        alias = self.library_root / 'Existing shortcut'
        finder_alias.create(old, alias)
        self.rename_with_full_plan(folder)
        self.assertEqual(finder_alias.resolve(alias), old.with_name('After'))

    def test_existing_directory_is_not_registered_as_fresh(self):
        old = self.library_root / 'Before'
        old.mkdir(parents=True)
        file = old / 'preserve.txt'
        file.write_text('keep')
        folder = self.storage.create_library_folder(parent_id=1, name='Before')
        rename.remember_new_empty_folder(self.storage, folder)
        self.rename_with_full_plan(folder)
        self.assertEqual((old.with_name('After') / file.name).read_text(), 'keep')

    def test_missing_registered_paths_force_full_workflow(self):
        for field in ('main_pdf_path', 'merged_pdf_path', 'source_path', 'analysis_path', 'supplement_pdf_paths', 'resource'):
            with self.subTest(field=field):
                folder, old, _ = self.fresh('New ' + field)
                pid = 'paper-' + field
                self.add_paper(pid)
                missing = str(old / 'missing.pdf')
                if field == 'resource':
                    self.storage.create_paper_resource(paper_id=pid, stored_path=missing, file_type='unknown')
                else:
                    value = json.dumps([missing]) if field == 'supplement_pdf_paths' else missing
                    self.storage.conn.execute(f'UPDATE papers SET {field}=? WHERE paper_id=?', (value, pid))
                    self.storage.conn.commit()
                _, changes = self.rename_with_full_plan(folder, 'After ' + field)
                self.assertIn(pid, changes['renamed_paper_ids'])
                self.assertFalse(Path(missing).exists())

    def test_move_and_callback_operations_keep_full_workflow(self):
        folder, _, _ = self.fresh()
        parent = self.storage.create_library_folder(parent_id=1, name='Destination')
        with patch.object(rename, '_plan', wraps=rename._plan) as plan:
            rename.relocate(self.storage, folder['id'], parent_id=parent['id'])
        self.assertEqual(plan.call_count, 1)
        other, _, _ = self.fresh('Another folder')
        validated = []
        self.rename_with_full_plan(other, validate=lambda ids: validated.append(ids))
        self.assertEqual(validated, [set()])

    def test_target_collision_does_not_overwrite(self):
        folder, old, _ = self.fresh()
        destination = old.with_name('After')
        destination.mkdir(parents=True)
        file = destination / 'keep.txt'
        file.write_text('untouched')
        before = self.rows()
        with self.assertRaises(FileExistsError):
            rename.rename(self.storage, folder['id'], 'After')
        self.assertEqual(before, self.rows())
        self.assertEqual(file.read_text(), 'untouched')

    def test_sanitized_sibling_collision_rolls_back(self):
        folder, _, _ = self.fresh()
        self.storage.create_library_folder(parent_id=1, name='A:B')
        before = self.rows()
        with self.assertRaisesRegex(ValueError, 'same Finder name'):
            rename.rename(self.storage, folder['id'], 'A/B')
        self.assertEqual(before, self.rows())

    def test_failure_after_directory_creation_rolls_back(self):
        folder, old, _ = self.fresh()
        before = self.rows()
        apply = rename.RenameJournal.apply
        def fail(journal):
            apply(journal)
            raise OSError('synthetic failure')
        with patch.object(rename.RenameJournal, 'apply', fail):
            with self.assertRaisesRegex(OSError, 'synthetic failure'):
                rename.rename(self.storage, folder['id'], 'After')
        self.assertEqual(before, self.rows())
        self.assertFalse(old.with_name('After').exists())
        self.assertFalse(list(self.db_path.parent.glob('folder-rename-recovery/*/operation.json')))

    def test_file_appearing_during_save_is_retained_and_rename_rolls_back(self):
        folder, old, _ = self.fresh()
        before = self.rows()
        apply = rename.RenameJournal.apply
        def external_save(journal):
            apply(journal)
            old.mkdir(parents=True)
            (old / 'new.txt').write_text('concurrent save')
        with patch.object(rename.RenameJournal, 'apply', external_save):
            with self.assertRaisesRegex(ValueError, 'contents changed'):
                rename.rename(self.storage, folder['id'], 'After')
        self.assertEqual(before, self.rows())
        self.assertEqual((old / 'new.txt').read_text(), 'concurrent save')
        self.assertFalse(old.with_name('After').exists())

    def test_committed_empty_rename_recovers_interrupted_cleanup(self):
        folder, old, _ = self.fresh()
        with patch.object(rename.RenameJournal, 'finish', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                rename.rename(self.storage, folder['id'], 'After')
        rename.recover(self.storage)
        self.assertEqual(self.storage.get_library_folder(folder['id'])['name'], 'After')
        self.assertTrue(old.with_name('After').is_dir())
        self.assertFalse(list(self.db_path.parent.glob('folder-rename-recovery/*/operation.json')))


if __name__ == '__main__':
    unittest.main()
