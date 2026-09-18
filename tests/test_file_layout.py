"""Disposable file/SQLite fixtures; no running App or personal Library access."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from paper_monitor import finder_alias as aliases, ui_server as ui
from paper_monitor.file_layout import reconcile, sync_associated_aliases
from paper_monitor.file_layout_journal import MoveJournal, recover
from paper_monitor.file_layout_migration import migrate
from paper_monitor.importers.inventory import build_inventory_from_folder, import_library_inventory
from tests import test_paper_resources as fixtures


class FileLayoutTests(unittest.TestCase):
    setUp = fixtures.PaperResourceStorageTests.setUp
    tearDown = fixtures.PaperResourceStorageTests.tearDown
    add_paper = fixtures.PaperResourceStorageTests.add_paper

    def fixture(self):
        self.add_paper('work')
        a = self.storage.create_library_folder(name='Crystal', parent_id=1)
        b = self.storage.create_library_folder(name='Pressure', parent_id=1)
        resources, paths, items = [], [], []
        for folder, name, content in ((a, 'High P.pdf', b'%PDF-1.4 first bytes'),
                                      (b, '1.nmat.pdf', b'%PDF-1.4 different bytes')):
            item = self.storage.add_library_item(paper_id='work', folder_id=folder['id'])
            item = self.storage.rename_library_item(item_id=item['id'], name=name)
            path = ui.local_copy_dir_for_library_folder(self.storage, folder['id']) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            resource = self.storage.create_paper_resource(paper_id='work', stored_path=str(path),
                source_path=str(self.root / 'external' / name), file_role='publication_version',
                file_type='unknown', added_via='legacy_backfill')
            items.append(item); paths.append(path); resources.append(resource)
        self.storage.conn.execute('UPDATE papers SET main_pdf_path=?,merged_pdf_path=?,primary_resource_id=? WHERE paper_id=?',
                                 (str(paths[1]), str(paths[1]), resources[1]['id'], 'work'))
        self.storage.conn.commit()
        return items, resources, paths

    def assert_alias(self, path, target):
        self.assertTrue(aliases.is_alias(path), path)
        self.assertEqual(aliases.resolve(path), target.resolve())
        if sys.platform == 'darwin':
            self.assertFalse(path.is_symlink())
            info = aliases.get_attribute(path, 'com.apple.FinderInfo')
            self.assertTrue(int.from_bytes(info[8:10], 'big') & 0x8000)

    def test_legacy_pair_becomes_one_main_two_resources_and_native_aliases(self):
        items, resources, paths = self.fixture()
        content = [p.read_bytes() for p in paths]
        key = self.storage.get_paper('work')['storage_key']
        reconcile(self.storage, 'work')
        files = self.storage.list_paper_resources('work')
        self.assertEqual([r['id'] for r in files], [r['id'] for r in resources])
        self.assertEqual([r['file_type'] for r in files], ['unknown', 'unknown'])
        self.assertEqual([r['id'] for r in files if r['is_default']], [resources[1]['id']])
        attachment = Path(files[0]['stored_path'])
        self.assertTrue(attachment.is_relative_to(self.associated_root / 'Library' / 'Pressure'))
        self.assertEqual([Path(r['stored_path']).read_bytes() for r in files], content)
        self.assert_alias(paths[0], paths[1])
        bundle = ui.existing_associated_work_dir(self.storage, 'work')
        folder_alias = self.associated_root / 'Library' / 'Crystal' / f'High P [{key}]'
        self.assert_alias(folder_alias, bundle)
        before = [(r['id'], r['stored_path']) for r in files]
        reconcile(self.storage, 'work')
        self.assertEqual(before, [(r['id'], r['stored_path']) for r in self.storage.list_paper_resources('work')])
        self.assertEqual(self.storage.get_paper('work')['storage_key'], key)
        self.assertEqual(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_manual_default_then_auto_and_folder_move_keep_links_and_bytes(self):
        items, resources, paths = self.fixture()
        reconcile(self.storage, 'work')
        ui.set_preferred_paper_file(self.storage, 'work', resources[0]['id'])
        main = Path(self.storage.resolve_default_paper_resource('work')['stored_path'])
        self.assertEqual(main.parent, paths[1].parent)
        self.assertEqual(main.read_bytes(), b'%PDF-1.4 first bytes')
        self.storage.conn.execute("UPDATE resources SET file_type='published_version' WHERE id=?", (resources[1]['id'],))
        self.storage.conn.commit()
        reconcile(self.storage, 'work')
        self.assertEqual(self.storage.resolve_default_paper_resource('work')['id'], resources[0]['id'])
        ui.set_preferred_paper_file(self.storage, 'work', None)
        self.assertEqual(self.storage.resolve_default_paper_resource('work')['id'], resources[1]['id'])
        third = self.storage.create_library_folder(name='Moved', parent_id=1)
        item = self.storage.get_library_item(items[1]['id'])
        ui.move_or_alias_library_item_pdf(self.storage, item=item, target_folder_id=third['id'])
        self.storage.move_library_item(item_id=item['id'], folder_id=third['id'])
        ui.sync_all_pdf_aliases_for_paper(self.storage, 'work')
        main = ui.canonical_file_path_for_paper(self.storage.get_paper('work'))
        self.assertEqual(main.parent, self.library_root / 'Moved')
        bundle = ui.existing_associated_work_dir(self.storage, 'work')
        self.assertEqual(bundle.parent, self.associated_root / 'Library' / 'Moved')
        self.assert_alias(paths[0], main)
        for value in json.loads(self.storage.get_paper('work')['raw_json'])['file_layout']['associated_aliases']:
            self.assert_alias(Path(value), bundle)

    def test_failed_second_move_restores_database_files_and_displaced_alias(self):
        items, resources, paths = self.fixture()
        third = paths[0].with_name('third.pdf'); third.write_bytes(b'%PDF third')
        self.storage.create_paper_resource(paper_id='work', stored_path=str(third), file_type='unknown')
        before = [dict(r) for r in self.storage.conn.execute('SELECT * FROM resources')]
        original = ui.update_paper_file_path_references
        calls = []
        def fail(storage, paper_id, source, target, **kwargs):
            calls.append(source)
            if len(calls) == 2:
                raise OSError('synthetic write failure')
            return original(storage, paper_id, source, target, **kwargs)
        with patch.object(ui, 'update_paper_file_path_references', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                reconcile(self.storage, 'work')
        self.assertEqual(before, [dict(r) for r in self.storage.conn.execute('SELECT * FROM resources')])
        self.assertEqual(paths[0].read_bytes(), b'%PDF-1.4 first bytes')
        self.assertEqual(third.read_bytes(), b'%PDF third')
        self.assertFalse(list((self.db_path.parent / 'file-layout-recovery').glob('*.json')))

    def test_native_file_and_folder_aliases_survive_target_rename_and_restore(self):
        for directory in (False, True):
            target = self.root / ('folder' if directory else 'sample.rtf')
            target.mkdir() if directory else target.write_bytes(b'RTF content')
            alias = self.root / ('folder alias' if directory else 'sample alias.rtf')
            aliases.create(target, alias)
            self.assert_alias(alias, target)
            saved = aliases.snapshot(alias); alias.unlink(); aliases.restore(alias, saved)
            new = target.with_name(target.name + ' renamed'); target.rename(new)
            if sys.platform == 'darwin':
                self.assert_alias(alias, new)

    def test_existing_symlink_converts_without_overwriting_a_real_collision(self):
        _, _, paths = self.fixture()
        link = paths[1].with_name('Old link.pdf'); link.symlink_to(paths[1])
        ui.create_pdf_alias(paths[1], link.parent, link.name)
        self.assert_alias(link, paths[1])
        other = link.with_name('Occupied.pdf'); other.write_bytes(b'unrelated')
        created = ui.create_pdf_alias(paths[1], other.parent, other.name)
        self.assertNotEqual(created, other)
        self.assertEqual(other.read_bytes(), b'unrelated')
        self.assert_alias(created, paths[1])

    def test_only_unknown_file_gets_automatic_default_and_non_pdf_alias(self):
        self.add_paper('notes')
        folder = self.storage.create_library_folder(name='Notes copy', parent_id=1)
        item = self.storage.add_library_item(paper_id='notes', folder_id=1)
        self.storage.rename_library_item(item_id=item['id'], name='Notes.rtf')
        item = self.storage.add_library_item(paper_id='notes', folder_id=folder['id'])
        self.storage.rename_library_item(item_id=item['id'], name='Notes.rtf')
        path = self.library_root / 'Notes.rtf'; path.parent.mkdir(parents=True); path.write_bytes(b'{\\rtf1 notes}')
        file = self.storage.create_paper_resource(paper_id='notes', stored_path=str(path), file_type='unknown')
        reconcile(self.storage, 'notes')
        self.assertEqual(self.storage.resolve_default_paper_resource('notes')['id'], file['id'])
        self.assertEqual(ui.canonical_file_path_for_paper(self.storage.get_paper('notes')), path)
        self.assert_alias(path.parent / 'Notes copy' / 'Notes.rtf', path)
        self.assertEqual(self.storage.get_paper('notes')['preferred_resource_manual'], 0)

    def test_recovery_rolls_back_uncommitted_move_but_keeps_committed_move(self):
        _, resources, paths = self.fixture()
        for committed in (False, True):
            journal = MoveJournal(self.storage, 'work')
            target = paths[0].with_name('moved.pdf')
            journal.move(paths[0], target, resources[0]['id'])
            if committed:
                self.storage.conn.execute('UPDATE resources SET stored_path=? WHERE id=?', (str(target), resources[0]['id']))
                self.storage.conn.commit()
            self.assertEqual(recover(self.storage), 1)
            self.assertEqual(target.exists(), committed)
            self.assertEqual(paths[0].exists(), not committed)

    def test_startup_migration_keeps_backup_and_does_not_repeat(self):
        _, resources, paths = self.fixture()
        report = migrate(self.storage)
        self.assertFalse(report['errors'])
        self.assertTrue(Path(report['backup']).is_file())
        self.assert_alias(paths[0], paths[1])
        self.assertEqual(migrate(self.storage), {'skipped': 'already reconciled'})

    def test_reimported_originals_reuse_moved_resources(self):
        # Real Loader path, synthetic RTFs; a filename identity yields one work
        # on repeat without treating Finder bookmarks as document contents.
        source = self.root / 'Outside'; source.mkdir()
        (source / 'Notes.rtf').write_bytes(b'{\\rtf1 original}')
        inventory = self.root / 'inventory.json'
        build_inventory_from_folder(source, output_path=inventory, parse_pdfs=False)
        for _ in range(2):
            result = import_library_inventory(inventory, copy_mode='copy', preserve_folders=True,
                dedupe_by=('doi', 'arxiv', 'path'), dry_run=False, storage=self.storage,
                target_root=self.library_root)
            self.assertFalse(result['errors'])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resources').fetchone()[0], 1)
        self.assertEqual((source / 'Notes.rtf').read_bytes(), b'{\\rtf1 original}')

    def test_loader_two_different_pdfs_same_doi_and_repeat_preserve_versions(self):
        from pypdf import PdfWriter
        source = self.root / 'Outside'; source.mkdir()
        contents = []
        for name, width in [('Crystal', 72), ('Pressure', 144)]:
            directory = source / name; directory.mkdir()
            path = directory / (name + '.pdf')
            writer = PdfWriter(); writer.add_blank_page(width=width, height=72)
            with path.open('wb') as stream:
                writer.write(stream)
            contents.append(path.read_bytes())
        inventory = self.root / 'two-pdfs.json'
        data = build_inventory_from_folder(source, parse_pdfs=False)
        for record in data['files']:
            record.update(doi='10.1234/layout-fixture', title='The same fixture paper')
        inventory.write_text(json.dumps(data))
        for attempt in range(2):
            result = import_library_inventory(inventory, copy_mode='copy', preserve_folders=True,
                dedupe_by=('doi', 'arxiv', 'path'), dry_run=False, storage=self.storage,
                target_root=self.library_root)
            self.assertFalse(result['errors']); self.assertFalse(result['warnings'])
            papers = list(self.storage.conn.execute('SELECT paper_id FROM papers'))
            self.assertEqual(len(papers), 1)
            pid = papers[0][0]
            files = self.storage.list_paper_resources(pid)
            self.assertEqual(len(files), 2)
            self.assertEqual(sorted(Path(r['stored_path']).read_bytes() for r in files), sorted(contents))
            main = ui.canonical_file_path_for_paper(self.storage.get_paper(pid))
            secondary = next(r for r in files if Path(r['stored_path']) != main)
            self.assertTrue(Path(secondary['stored_path']).is_relative_to(self.associated_root))
            placements = list(self.storage.conn.execute('SELECT * FROM library_items WHERE paper_id=?', (pid,)))
            self.assertEqual(len(placements), 2)
            for placement in placements:
                path = ui.library_item_local_pdf_path(self.storage, dict(placement))
                if path != main:
                    self.assert_alias(path, main)
            if attempt == 0:
                ids = [r['id'] for r in files]
            else:
                self.assertEqual([r['id'] for r in files], ids)
        self.assertEqual(sorted(p.read_bytes() for p in source.rglob('*.pdf')), sorted(contents))

    def test_pending_alias_failure_is_repaired_on_next_startup(self):
        _, _, paths = self.fixture()
        migrate(self.storage)
        path = paths[0]
        path.unlink()
        with patch.object(aliases, 'create', side_effect=OSError('synthetic Finder failure')):
            with self.assertRaisesRegex(OSError, 'synthetic Finder failure'):
                reconcile(self.storage, 'work')
        result = migrate(self.storage)
        self.assertFalse(result['errors'])
        self.assert_alias(path, paths[1])
        self.assertFalse(json.loads(self.storage.get_paper('work')['raw_json'])['file_layout']['links_pending'])

    def test_external_linked_and_cross_paper_shared_originals_are_preserved(self):
        for kind in ('linked', 'shared'):
            with self.subTest(kind=kind):
                self.add_paper(kind)
                self.storage.add_library_item(paper_id=kind, folder_id=1)
                path = (self.root / 'Outside' if kind == 'linked' else self.library_root) / (kind + '.pdf')
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'%PDF original')
                file = self.storage.create_paper_resource(paper_id=kind, stored_path=str(path),
                    file_type='unknown', storage_mode='linked' if kind == 'linked' else 'managed')
                if kind == 'shared':
                    self.add_paper('second-owner')
                    self.storage.create_paper_resource(paper_id='second-owner', stored_path=str(path), file_type='unknown')
                reconcile(self.storage, kind)
                self.assertEqual(path.read_bytes(), b'%PDF original')
                self.assertEqual(self.storage.get_paper_resource(file['id'])['stored_path'], str(path))

    def test_default_fallback_skips_missing_invalid_and_explicit_secondary_files(self):
        self.add_paper('defaults')
        self.storage.add_library_item(paper_id='defaults', folder_id=1)
        for index, kind in enumerate(('invalid_file', 'supplementary_material', 'correction_notice', 'unknown', 'unknown')):
            path = self.library_root / f'{index}.pdf'; path.parent.mkdir(parents=True, exist_ok=True)
            if index != 3:
                path.write_bytes(b'%PDF fixture')
            file = self.storage.create_paper_resource(paper_id='defaults', stored_path=str(path), file_type=kind)
        self.assertEqual(self.storage.resolve_default_paper_resource('defaults')['id'], file['id'])
        reconcile(self.storage, 'defaults')
        self.assertEqual(self.storage.resolve_default_paper_resource('defaults')['id'], file['id'])
        self.assertFalse(self.storage.get_paper('defaults')['preferred_resource_manual'])

    def test_non_pdf_default_then_pdf_addition_and_manual_switch_preserve_one_copy(self):
        self.add_paper('mixed')
        self.storage.add_library_item(paper_id='mixed', folder_id=1)
        note = ui.attach_file_to_paper(self.storage, paper_id='mixed', filename='Notes.rtf',
            content=b'{\\rtf1 unique note}', file_type='unknown')
        self.assertIsNone(ui.canonical_pdf_path_for_paper(self.storage.get_paper('mixed')))
        self.assertEqual(ui.canonical_file_path_for_paper(self.storage.get_paper('mixed')).name, 'Notes.rtf')
        pdf = ui.attach_file_to_paper(self.storage, paper_id='mixed', filename='Paper.pdf',
            content=fixtures.PaperResourceStorageTests.valid_pdf_bytes(self, 'a paper'), file_type='published_version')
        self.assertEqual(self.storage.resolve_default_paper_resource('mixed')['id'], pdf['id'])
        note_path = Path(self.storage.get_paper_resource(note['id'])['stored_path'])
        self.assertTrue(note_path.is_relative_to(self.associated_root))
        self.assertEqual(note_path.read_bytes(), b'{\\rtf1 unique note}')
        self.assertEqual(len(list((self.root / 'data').rglob('*.rtf'))), 1)
        ui.set_preferred_paper_file(self.storage, 'mixed', note['id'])
        self.assertIsNone(ui.canonical_pdf_path_for_paper(self.storage.get_paper('mixed')))
        self.assertEqual(ui.canonical_file_path_for_paper(self.storage.get_paper('mixed')).read_bytes(), b'{\\rtf1 unique note}')
        self.assertTrue(Path(self.storage.get_paper_resource(pdf['id'])['stored_path']).is_relative_to(self.associated_root))


if __name__ == '__main__':
    unittest.main()
