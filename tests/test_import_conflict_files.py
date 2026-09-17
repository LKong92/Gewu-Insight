from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import ui_server
from paper_monitor.file_reassignment import reassign_paper_file
from paper_monitor.importers import inventory
from paper_monitor.storage import Storage
from paper_monitor.text import make_paper_id
from tests import test_inventory_importer as fixtures


class ImportConflictFileTests(unittest.TestCase):
    def setUp(self):
        fixtures.InventoryImporterDryRunTests.setUp(self)
        for name, directory in (("LIBRARY_LOCAL_COPY_ROOT", "copied"), ("SPACES_LOCAL_COPY_ROOT", "Spaces"),
                ("MY_PUBLICATIONS_LOCAL_COPY_ROOT", "My Publications"), ("ASSOCIATED_FILES_ROOT", "Associated Files"),
                ("DEFAULT_PDF_DIR", "pdfs")):
            active = patch.object(ui_server, name, self.root / directory)
            active.start()
            self.addCleanup(active.stop)
    tearDown = fixtures.InventoryImporterDryRunTests.tearDown
    write_inventory = fixtures.InventoryImporterDryRunTests.write_inventory
    write_text_pdf = fixtures.InventoryImporterDryRunTests.write_text_pdf
    pdf_record = fixtures.InventoryImporterDryRunTests.pdf_record

    def run_import(self, records):
        return inventory.import_library_inventory(self.write_inventory(records), storage=self.storage,
            dry_run=False, copy_mode='copy', preserve_folders=True, library_item_name='filename',
            report_path=self.root/'report.json', target_root=self.root/'copied')

    def seed_collision(self, doi='10.1234/incoming'):
        paper_id=make_paper_id(doi,'','Imported Library','')
        self.storage.upsert_paper({'paper_id':paper_id,'doi':'10.1234/existing','title':'Existing unrelated work',
            'journal':'Fixture Journal','publication_date':'2020-01-01','url':'https://doi.org/10.1234/existing','source':'fixture'})
        return paper_id

    def test_conflict_keeps_all_files_placements_and_existing_metadata(self):
        paper_id=self.seed_collision()
        before=self.storage.get_paper(paper_id)
        files=[self.write_text_pdf(f'{folder}/version.pdf',f'fixture {folder}') for folder in ('one','two')]
        later=self.write_text_pdf('three/later.pdf','independent paper')
        report=self.run_import([*[self.pdf_record(p,doi='10.1234/incoming') for p in files],self.pdf_record(later,doi='10.1234/later')])
        self.assertEqual(report['errors'],[])
        self.assertEqual(len(report['identity_conflicts']),2)
        self.assertEqual(report['library_items_created'],3)
        self.assertEqual(self.storage.get_paper(paper_id),before)
        resources=self.storage.list_paper_resources(paper_id,ensure_primary=False)
        self.assertEqual(len(resources),2)
        self.assertEqual({Path(r['stored_path']).read_bytes() for r in resources},{p.read_bytes() for p in files})
        self.assertTrue(all(p.exists() for p in files))
        self.assertEqual(self.storage.conn.execute('SELECT status FROM inventory_import_batches').fetchone()[0],'completed')
        self.assertEqual(self.storage.conn.execute('SELECT status FROM paper_identity_conflicts').fetchone()[0],'attached')
        again=self.run_import([self.pdf_record(p,doi='10.1234/incoming') for p in files])
        self.assertFalse(again['errors'])
        self.assertEqual(len(self.storage.list_paper_resources(paper_id,ensure_primary=False)),2)

    def test_same_doi_different_bytes_are_two_paper_files(self):
        files=[self.write_text_pdf(f'{n}.pdf',str(n)) for n in (1,2)]
        report=self.run_import([self.pdf_record(p,doi='10.1234/shared') for p in files])
        self.assertFalse(report['errors'])
        self.assertEqual(report['created_papers'],1)
        self.assertEqual(report['existing_papers'],1)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resources').fetchone()[0],2)
        self.assertEqual(report['library_items_created'],1)

    def test_pnas_prefix_is_not_an_identifier(self):
        self.assertEqual(inventory.doi_from_text('https://doi.org/10.1073/pnas.\n2206481119'),'10.1073/pnas.2206481119')
        self.assertEqual(inventory.doi_from_text('doi:10.1073/pnas'),'')
        self.assertEqual(inventory.doi_from_filename('6.pnas.2206481119.pdf'),'10.1073/pnas.2206481119')
        self.assertEqual(inventory.doi_from_text('10.1073/pnas.\n Text DOI:10.1234/valid'),'10.1234/valid')
        self.assertEqual(inventory.doi_from_text('10.5555/word'),'10.5555/word')

    def test_batch_rollback_preserves_reassigned_file_and_destination(self):
        import shutil
        for create_new in (True, False):
            with self.subTest(create_new=create_new):
                first=self.write_text_pdf(f'{create_new}/a.pdf','first fixture')
                second=self.write_text_pdf(f'{create_new}/b.pdf','second fixture')
                result=self.run_import([self.pdf_record(first,doi=f'10.1234/a{create_new}'),
                                        self.pdf_record(second,doi=f'10.1234/b{create_new}')])
                one=self.storage.conn.execute('SELECT * FROM resources WHERE source_path=?',(str(first),)).fetchone()
                two=self.storage.conn.execute('SELECT * FROM resources WHERE source_path=?',(str(second),)).fetchone()
                destination=self.storage.get_paper(two['paper_id'])
                args={'new_title':'Separated file'} if create_new else {'target_key':destination['storage_key']}
                moved=reassign_paper_file(self.storage,one['paper_id'],one['id'],**args)
                moved_path=Path(self.storage.get_paper_resource(one['id'])['stored_path'])
                original=moved_path.read_bytes()
                trashed=[]
                def fake_trash(path):
                    trashed.append(str(path))
                    if Path(path).is_dir(): shutil.rmtree(path)
                    else: Path(path).unlink()
                job={'status':'completed','result':result}
                with patch.object(ui_server,'ROOT',self.root),patch.object(ui_server,'DEFAULT_LIBRARY_DIR',self.root/'copied'), \
                     patch.object(ui_server,'get_library_import_job',return_value=job), \
                     patch.object(ui_server,'move_path_to_macos_trash',side_effect=fake_trash):
                    ui_server.delete_library_import_job_data(self.storage,'fixture-deletion')
                target=self.storage.get_paper(moved['target_paper_id'])
                self.assertIsNotNone(target)
                self.assertIsNone(target['import_batch_id'])
                self.assertEqual(moved_path.read_bytes(),original)
                self.assertEqual(self.storage.get_paper_resource(one['id'])['paper_id'],target['paper_id'])
                self.assertNotIn(str(self.root/'copied'),trashed)
                self.assertEqual([r['id'] for r in self.storage.list_paper_resources(target['paper_id'])],[one['id']])
                self.assertEqual(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_folder_loader_and_drop_share_conflict_policy(self):
        for preserve in (False,True):
            with self.subTest(finder_drop=preserve):
                root=self.root/str(preserve); root.mkdir()
                source=self.write_text_pdf(f'{preserve}/paper.pdf','DOI: 10.1234/incoming')
                self.seed_collision()
                job=ui_server.create_library_import_job(folder_path=root,copy_mode='copy',preserve_top_level=preserve,metadata_mode='skip')
                with patch.object(ui_server,'ROOT',self.root),patch.object(ui_server,'refresh_imported_doi_metadata',return_value=0):
                    ui_server.run_library_import_job(job_id=job,folder_path=root,db_path=self.db_path,copy_mode='copy',
                        preserve_top_level=preserve,metadata_mode='skip',copy_plan={'copy_target_root':str(self.root/'loader-copies')})
                result=ui_server.get_library_import_job(job)
                self.assertEqual(result['status'],'completed',result.get('error'))
                self.assertTrue(result['library_ready'])
                self.assertEqual(len(result['result']['identity_conflicts']),1)
                self.assertTrue(source.exists())

    def test_reassign_preserves_bytes_ids_default_and_retry_ownership(self):
        old=self.seed_collision()
        pdf=self.write_text_pdf('misplaced.pdf','wrong DOI fixture')
        self.run_import([self.pdf_record(pdf,doi='10.1234/incoming')])
        r=self.storage.list_paper_resources(old,ensure_primary=False)[0]
        moved=reassign_paper_file(self.storage,old,r['id'],new_title='Independent paper')
        new=self.storage.get_paper(moved['target_paper_id'])
        self.assertEqual(new['doi'],'')
        self.assertNotEqual(new['storage_key'],self.storage.get_paper(old)['storage_key'])
        after=self.storage.get_paper_resource(r['id'])
        self.assertNotEqual(after['stored_path'],r['stored_path'])
        self.assertFalse(Path(r['stored_path']).exists())
        self.assertEqual(Path(after['stored_path']).read_bytes(),pdf.read_bytes())
        self.assertEqual(after['status'],'reassigned')
        self.assertIsNone(after['import_batch_id'])
        self.assertEqual(self.storage.resolve_default_paper_resource(new['paper_id'])['id'],r['id'])
        self.run_import([self.pdf_record(pdf,doi='10.1234/incoming')])
        self.assertEqual(self.storage.get_paper_resource(r['id'])['paper_id'],new['paper_id'])
        self.assertEqual(self.storage.list_paper_resources(old),[])

    def test_reassign_primary_and_sql_failure_are_atomic(self):
        first=self.write_text_pdf('one.pdf','first');second=self.write_text_pdf('two.pdf','second')
        self.run_import([self.pdf_record(p,doi='10.1234/shared') for p in (first,second)])
        source=self.storage.conn.execute('SELECT paper_id FROM papers').fetchone()[0]
        resources=self.storage.list_paper_resources(source)
        current=self.storage.get_paper(source)
        primary=next(r for r in resources if r['id']==current['primary_resource_id'])
        before=[dict(r) for r in self.storage.conn.execute('SELECT * FROM resources')]
        with patch.object(self.storage,'_select_default_paper_resource',side_effect=RuntimeError('fixture')):
            with self.assertRaisesRegex(RuntimeError,'fixture'):
                reassign_paper_file(self.storage,source,primary['id'],new_title='Rollback candidate')
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)
        self.assertEqual([dict(r) for r in self.storage.conn.execute('SELECT * FROM resources')],before)
        reassign_paper_file(self.storage,source,primary['id'],new_title='Separated')
        self.assertNotEqual(self.storage.get_paper(source)['primary_resource_id'],primary['id'])
        self.assertTrue(self.storage.get_paper(source)['main_pdf_path'])
        self.assertEqual(len(self.storage.list_paper_resources(source)),1)
        self.assertEqual(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_move_to_existing_preserves_destination_metadata(self):
        old=self.seed_collision();pdf=self.write_text_pdf('move.pdf','fixture')
        self.run_import([self.pdf_record(pdf,doi='10.1234/incoming')])
        r=self.storage.list_paper_resources(old,ensure_primary=False)[0]
        self.storage.upsert_paper({'paper_id':'target','title':'Target title','doi':'10.1234/target','journal':'Fixture Journal','source':'fixture'})
        target=self.storage.get_paper('target')
        reassign_paper_file(self.storage,old,r['id'],target_key=target['storage_key'])
        after=self.storage.get_paper('target')
        for key in ('title','doi','primary_resource_id','preferred_resource_id','preferred_resource_manual'):
            self.assertEqual(after[key],target[key])
        with self.assertRaisesRegex(ValueError,'no longer belongs'):
            reassign_paper_file(self.storage,old,r['id'],target_key=target['storage_key'])

    def test_conflict_cannot_take_automatic_default(self):
        paper_id=self.seed_collision()
        original=self.write_text_pdf('default.pdf','existing PDF')
        main=self.storage.create_paper_resource(paper_id=paper_id,stored_path=str(original),file_type='preprint')
        self.storage.conn.execute('UPDATE papers SET primary_resource_id=?,main_pdf_path=?,merged_pdf_path=? WHERE paper_id=?',
            (main['id'],str(original),str(original),paper_id));self.storage.conn.commit()
        incoming=self.write_text_pdf('new.pdf','mismatched PDF')
        report=self.run_import([self.pdf_record(incoming,doi='10.1234/incoming',arxiv_id='2203.08250')])
        self.assertFalse(report['errors'])
        self.assertEqual(self.storage.resolve_default_paper_resource(paper_id)['id'],main['id'])
        attached=[r for r in self.storage.list_paper_resources(paper_id) if r['id']!=main['id']][0]
        self.assertEqual(attached['added_via'],'inventory_conflict')
        self.storage.set_preferred_paper_resource(paper_id,attached['id'])
        self.assertEqual(self.storage.resolve_default_paper_resource(paper_id)['id'],attached['id'])
        self.storage.set_preferred_paper_resource(paper_id,main['id'])
        reassign_paper_file(self.storage,paper_id,main['id'],new_title='Main file moved explicitly')
        self.assertIsNone(self.storage.resolve_default_paper_resource(paper_id))
        self.assertEqual(self.storage.get_paper(paper_id)['merged_pdf_path'],'')

    def test_late_identity_conflict_still_keeps_file(self):
        paper_id=self.seed_collision()
        source=self.write_text_pdf('late.pdf','late conflict')
        with patch.object(inventory,'matched_import_paper',return_value=''):
            result=self.run_import([self.pdf_record(source,doi='10.1234/incoming')])
        self.assertFalse(result['errors'])
        self.assertEqual(result['created_papers'],0)
        self.assertEqual(result['existing_papers'],1)
        self.assertEqual(len(self.storage.list_paper_resources(paper_id,ensure_primary=False)),1)
