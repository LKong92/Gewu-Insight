"""Exact duplicate prevention and repair in disposable libraries only."""
import json
from pathlib import Path
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch

from paper_monitor import ui_server as ui
from paper_monitor.importers.inventory import build_inventory_from_folder, import_library_inventory
from paper_monitor.resource_dedup_migration import migrate, SETTING
from tests import test_paper_resources as fixtures


class ResourceDedupTests(unittest.TestCase):
    setUp = fixtures.PaperResourceStorageTests.setUp
    tearDown = fixtures.PaperResourceStorageTests.tearDown
    add_paper = fixtures.PaperResourceStorageTests.add_paper
    write_pdf = fixtures.PaperResourceStorageTests.write_pdf
    valid_pdf_bytes = fixtures.PaperResourceStorageTests.valid_pdf_bytes
    def load(self, source, content, name='paper.pdf'):
        source.mkdir(parents=True, exist_ok=True)
        (source / name).write_bytes(content)
        inventory = self.root / 'inventory.json'
        data = build_inventory_from_folder(source, parse_pdfs=False)
        for row in data['files']:
            row.update(doi='10.1234/exact-dedup-fixture', title='Exact duplicate fixture')
        inventory.write_text(json.dumps(data))
        result = import_library_inventory(inventory, copy_mode='copy', preserve_folders=True,
            dedupe_by=('doi', 'arxiv', 'path'), dry_run=False, storage=self.storage, target_root=self.library_root)
        self.assertFalse(result['errors'])
        return result

    def test_changed_source_and_filename_reuses_bytes_and_preserves_sources(self):
        content = self.valid_pdf_bytes('one')
        self.load(self.root / 'Outside A', content)
        paper = dict(self.storage.conn.execute('SELECT * FROM papers').fetchone())
        rid = self.storage.conn.execute('SELECT id FROM resources').fetchone()[0]
        self.storage.set_preferred_paper_resource(paper['paper_id'], rid)
        for name in ('Outside B', 'Outside C', 'Outside B'):
            result = self.load(self.root / name, content, 'renamed.pdf')
            self.assertEqual(result['reused_existing_files'], 1)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resources').fetchone()[0], 1)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resource_import_sources').fetchone()[0], 3)
        self.assertEqual(self.storage.get_paper(paper['paper_id'])['preferred_resource_id'], rid)

    def test_same_size_changed_bytes_are_a_separate_version(self):
        first, second = self.valid_pdf_bytes('one'), self.valid_pdf_bytes('two')
        self.assertEqual(len(first), len(second))
        self.load(self.root / 'Outside', first)
        self.load(self.root / 'Outside', second)
        self.load(self.root / 'Outside', second)
        rows = list(self.storage.conn.execute('SELECT stored_path FROM resources'))
        self.assertEqual(len(rows), 2)
        self.assertEqual({Path(r[0]).read_bytes() for r in rows}, {first, second})

    def test_direct_registration_and_sql_guard_prevent_same_path(self):
        self.add_paper('work'); path = self.write_pdf('same.pdf')
        first = self.storage.create_paper_resource(paper_id='work', stored_path=str(path))
        second = self.storage.create_paper_resource(paper_id='work', stored_path=str(path.parent / '.' / path.name))
        self.assertEqual(first['id'], second['id'])
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'Duplicate Paper File path'):
            self.storage.conn.execute('''INSERT INTO resources(paper_id,stored_path,created_at,updated_at)
                VALUES('work',?,'now','now')''', (str(path),))
        self.storage.conn.rollback()

    def duplicate_fixture(self):
        self.add_paper('work')
        self.storage.add_library_item(paper_id='work', folder_id=1)
        content = self.valid_pdf_bytes('same')
        paths, resources = [], []
        for name in ('one.pdf', 'two.pdf'):
            path = self.library_root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
            resource = self.storage.create_paper_resource(paper_id='work', stored_path=str(path),
                source_path=str(self.root / 'Outside' / name), added_via='inventory', file_type='unknown')
            paths.append(path); resources.append(resource)
        self.storage.conn.execute('UPDATE papers SET main_pdf_path=?,merged_pdf_path=?,primary_resource_id=? WHERE paper_id=?',
            (str(paths[0]),str(paths[0]),resources[0]['id'],'work'))
        self.storage.conn.commit()
        return paths, resources

    def test_migration_preserves_manual_default_metadata_and_quarantines_bytes(self):
        paths, resources = self.duplicate_fixture()
        self.storage.set_preferred_paper_resource('work', resources[1]['id'])
        self.storage.conn.execute("UPDATE resources SET annotation_override=1,annotation_state='annotated',is_annotated=1 WHERE id=?", (resources[0]['id'],))
        self.storage.conn.commit()
        result = migrate(self.storage)
        self.assertEqual(len(result['merged']), 1); self.assertFalse(result['deferred'])
        paper = self.storage.get_paper('work')
        self.assertEqual(paper['preferred_resource_id'], resources[1]['id'])
        self.assertEqual(paper['primary_resource_id'], resources[1]['id'])
        self.assertEqual(paper['main_pdf_path'], str(paths[1]))
        keep = self.storage.get_paper_resource(resources[1]['id'])
        self.assertEqual(keep['annotation_override'], 1)
        self.assertFalse(paths[0].exists()); self.assertTrue(paths[1].exists())
        directory = Path(result['backup_directory'])
        self.assertTrue((directory/'before.sqlite').exists())
        backups = list((directory/'files').rglob('*.pdf'))
        self.assertEqual(len(backups), 1); self.assertEqual(backups[0].read_bytes(), paths[1].read_bytes())
        self.assertEqual(migrate(self.storage)['skipped'], 'already checked')
        self.assertFalse(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_migration_retains_different_annotations_and_conflicting_classifications(self):
        paths, resources = self.duplicate_fixture()
        paths[1].write_bytes(self.valid_pdf_bytes('different'))
        self.assertEqual(migrate(self.storage)['merged'], [])
        self.storage.set_setting(SETTING, '')
        paths[1].write_bytes(paths[0].read_bytes())
        for resource, kind in zip(resources, ('preprint','published_version')):
            self.storage.conn.execute('UPDATE resources SET file_type=?,file_type_override=1 WHERE id=?', (kind,resource['id']))
        self.storage.conn.commit()
        result=migrate(self.storage)
        self.assertEqual(len(result['deferred']), 1)
        self.assertTrue(all(p.exists() for p in paths))

    def test_failed_backup_preserves_records_and_originals(self):
        paths, resources = self.duplicate_fixture()
        with patch('paper_monitor.resource_dedup_migration.shutil.copy2', side_effect=OSError('fixture failure')):
            result = migrate(self.storage)
        self.assertEqual(len(result['deferred']), 1)
        self.assertTrue(all(self.storage.get_paper_resource(r['id']) for r in resources))
        self.assertTrue(all(p.exists() for p in paths))

    def test_interrupted_cleanup_resumes_only_after_database_commit(self):
        paths, resources = self.duplicate_fixture()
        from paper_monitor.resource_dedup_migration import finish_files
        with patch('paper_monitor.resource_dedup_migration.finish_files', side_effect=OSError('interrupted')):
            result = migrate(self.storage)
        self.assertEqual(len(result['deferred']), 1)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resources').fetchone()[0], 1)
        self.assertTrue(all(p.exists() for p in paths))
        migrate(self.storage)
        self.assertTrue(paths[0].exists()); self.assertFalse(paths[1].exists())

    def test_concurrent_registrations_reuse_resource_and_remove_only_the_new_copy(self):
        from paper_monitor.storage import Storage
        from paper_monitor.importers.inventory import copy_record, upsert_resource, normalize_record
        self.add_paper('work')
        barrier = threading.Barrier(2)
        content = self.valid_pdf_bytes('same')
        records = []
        for index in range(2):
            source = self.root / f'Outside{index}'; source.mkdir()
            (source/'paper.pdf').write_bytes(content)
            records.append(normalize_record(build_inventory_from_folder(source, parse_pdfs=False)['files'][0]))
        def register(record):
            storage = Storage(self.db_path)
            try:
                copied = copy_record(record, target_root=self.library_root)
                barrier.wait(timeout=5)
                upsert_resource(storage, record, batch_id='fixture', paper_id='work', stored_path=copied)
            finally:
                storage.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(register, records))
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resources').fetchone()[0], 1)
        self.assertEqual(len(list(self.library_root.rglob('*.pdf'))), 1)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resource_import_sources').fetchone()[0], 2)

    def test_same_path_legacy_rows_repair_without_removing_the_file(self):
        paths, resources = self.duplicate_fixture()
        self.storage.conn.execute('DROP TRIGGER resource_path_unique_update')
        self.storage.conn.execute('UPDATE resources SET stored_path=? WHERE id=?', (str(paths[0]),resources[1]['id']))
        self.storage.conn.commit()
        result = migrate(self.storage)
        self.assertEqual(len(result['merged']), 1)
        self.assertTrue(paths[0].exists())
        self.assertEqual(result['merged'][0]['files'], [])

    def test_uncommitted_merge_restores_records_and_keeps_originals(self):
        paths, resources = self.duplicate_fixture()
        with patch('paper_monitor.resource_dedup_migration.remember_source', side_effect=RuntimeError('SQL failure')):
            result=migrate(self.storage)
        self.assertEqual(len(result['deferred']), 1)
        self.assertTrue(all(p.exists() for p in paths))
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resources').fetchone()[0], 2)
        migrate(self.storage)
        self.assertTrue(all(p.exists() for p in paths))

    def test_external_original_survives_duplicate_record_merge(self):
        paths, resources = self.duplicate_fixture()
        outside = self.root/'external.pdf';outside.write_bytes(paths[1].read_bytes())
        self.storage.conn.execute("UPDATE resources SET stored_path=?,storage_mode='linked' WHERE id=?", (str(outside),resources[1]['id']))
        self.storage.conn.commit()
        result=migrate(self.storage)
        self.assertEqual(len(result['merged']), 1)
        self.assertTrue(outside.exists())

    def test_schema19_upgrade_preserves_resources_and_adds_guards(self):
        from paper_monitor.storage import Storage
        paths, resources = self.duplicate_fixture()
        self.storage.conn.execute('PRAGMA user_version=19')
        self.storage.conn.execute('DROP TABLE resource_import_sources')
        self.storage.conn.execute('DROP TABLE resource_duplicate_archive')
        self.storage.conn.commit()
        upgraded=Storage(self.db_path)
        try:
            self.assertEqual(upgraded.conn.execute('PRAGMA user_version').fetchone()[0],20)
            self.assertEqual([r['id'] for r in upgraded.list_paper_resources('work')], [r['id'] for r in resources])
            self.assertTrue(all(p.exists() for p in paths))
        finally:
            upgraded.close()
