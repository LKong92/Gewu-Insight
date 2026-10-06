"""Notice identity, provenance and scoped import regressions on temporary data."""
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from paper_monitor import publication_notices as notices, ui_server as ui, ai_uploads
from paper_monitor.storage import legacy_paper_file_type
import test_ai_access as access_fixture
import test_ai_writes as write_fixture
import test_browser_capture as browser_fixture
import test_inventory_importer as inventory_fixture


class PublicationNoticeTests(unittest.TestCase):
    setUp = access_fixture.AIAccessTests.setUp
    tearDown = access_fixture.AIAccessTests.tearDown
    call = access_fixture.AIAccessTests.call
    request = access_fixture.AIAccessTests.request
    enable_writes = write_fixture.AIWriteTests.enable_writes
    upload = write_fixture.AIWriteTests.upload
    metadata = write_fixture.AIWriteTests.metadata

    def args(self, *, kind='correction_notice', relation=True):
        self.storage.conn.execute("UPDATE papers SET doi='10.5555/original' WHERE paper_id='one'")
        self.storage.conn.commit()
        token=self.enable_writes()
        writer=PdfWriter();writer.add_blank_page(width=231,height=456)
        out=io.BytesIO();writer.write(out)
        upload=self.upload(token,name='notice.pdf',content=out.getvalue())
        meta=self.metadata()
        meta.update(title='Author Correction: A supplied paper',doi='10.5555/notice')
        if relation:
            meta['publication_notice']={'kind':kind,'related_dois':['10.5555/original'],'evidence_url':'https://example.org/notice'}
        return token,upload,dict(folder_id=1,upload_id=upload['upload_id'],metadata=meta,
                                file_type='published_version',request_id='notice-import-001')

    def test_notice_titles_do_not_capture_research_or_retracted_originals(self):
        for title in ('Quantum error correction','Correction of optical aberrations',
                      'RETRACTED: Original research','Reply to: Some research','Corrected version of a paper'):
            self.assertIsNone(notices.describe({'title':title}),title)
        for title,kind in [('Author Correction: Research','correction_notice'),('Erratum: Research','correction_notice'),
                           ('Retraction Note: Research','retraction_notice'),('Expression of Concern: Research','expression_of_concern')]:
            self.assertEqual(notices.describe({'title':title})['kind'],kind)
        self.assertIsNone(notices.describe({'title':'Research','raw':{'is_retracted':True,'update-by':[{'type':'retraction','DOI':'10.5555/notice'}]}}))
        self.assertEqual(legacy_paper_file_type('publication_version','version_of_record',display_name='Quantum error correction.pdf'),'published_version')

    def test_crossmark_direction_and_central_storage_barrier(self):
        paper={'paper_id':'bad','doi':'10.5555/notice','title':'Unlabelled notice','raw':{'crossref':{'update-to':[{'type':'retraction','DOI':'10.5555/original'}]}}}
        self.assertFalse(self.storage.upsert_paper(paper))
        self.assertIsNone(self.storage.get_paper('bad'))
        row=dict(self.storage.conn.execute('SELECT * FROM publication_notices').fetchone())
        self.assertEqual(row['status'],'needs_relation')
        self.assertIsNone(row['paper_id'])
        self.assertFalse(self.storage.upsert_paper(paper))
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM publication_notices').fetchone()[0],1)

    def test_corrected_full_article_is_not_a_standalone_notice(self):
        for title, footer in (
            ('Autonomous biomedical research with an artificial intelligence agent',
             'CORRECTED 21 AUGUST 2026; SEE LAST PAGE'),
            ('AI in scientific publishing: Slower, worse, and more expensive',
             'CORRECTED 4 AUGUST 2026; SEE FULL TEXT'),
        ):
            self.assertIsNone(notices.from_front_matter(title, title+'\n'+footer))
            self.assertIsNone(notices.describe({'title':title,'type':'journal-article',
                'raw':{'crossref':{'update-by':[{'type':'correction','DOI':'10.5555/notice'}]}}}))

    def test_regular_mcp_article_import_keeps_the_existing_scope_boundary(self):
        token, _, args = self.args()
        args['metadata'].pop('publication_notice')
        args['metadata'].update(title='Autonomous biomedical research with an artificial intelligence agent',
                                doi='10.5555/regular')
        status, result, _ = self.call('import_paper',args,token=token)
        self.assertEqual(status,200,result)
        self.assertEqual(result['file']['file_type'],'published_version')
        self.assertNotIn('publication_notice_id',result)
        # An existing monitor-only record outside the grant still cannot be
        # pulled into scope by this notice fix.
        self.storage.conn.execute("UPDATE papers SET doi='10.5555/hidden' WHERE paper_id='outside'")
        self.storage.conn.commit()
        args['metadata']['doi']='10.5555/hidden'
        args['request_id']='notice-scope-check-002'
        args['upload_id']=self.upload(token,name='regular.pdf',content=self.pdf_bytes,
                                     request='notice-scope-upload-002')['upload_id']
        self.assertIn(self.call('import_paper',args,token=token)[0],(403,404))

    def test_missing_relation_preserves_upload_without_resolve(self):
        token,upload,args=self.args(relation=False)
        with patch.object(ui,'library_workspace_publication_from_query',side_effect=AssertionError('network')),patch.object(ui,'extract_identifier_from_pdf_or_title',side_effect=AssertionError('PDF scan')):
            status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,400,result);self.assertEqual(result['code'],'notice_relation_required')
        self.assertTrue(ai_uploads.path_for(self.storage,upload['upload_id']).exists())
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],3)

    def test_notice_import_uses_original_and_preserves_metadata_default_and_bytes(self):
        token,upload,args=self.args()
        before=self.storage.get_paper('one');default=self.storage.resolve_default_paper_resource('one')['id']
        original=Path(self.pdf['stored_path']).read_bytes()
        with patch.object(ui,'library_workspace_publication_from_query',side_effect=AssertionError('network')),patch.object(ui,'extract_identifier_from_pdf_or_title',side_effect=AssertionError('PDF scan')):
            status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,200,result)
        self.assertEqual(result['gewu_key'],self.key)
        self.assertEqual(result['file']['file_type'],'correction_notice')
        self.assertFalse(result['file']['is_default'])
        self.assertEqual(self.storage.resolve_default_paper_resource('one')['id'],default)
        after=self.storage.get_paper('one')
        for field in ('doi','title','journal','publication_date','storage_key'): self.assertEqual(before[field],after[field])
        self.assertEqual(Path(self.pdf['stored_path']).read_bytes(),original)
        event=notices.for_paper(self.storage,'one')[0]
        self.assertEqual(event['doi'],'10.5555/notice')
        self.assertEqual(event['file_ids'],[result['file']['file_id']])
        self.assertIn(str(ui.ASSOCIATED_FILES_ROOT),self.storage.get_paper_resource(result['file']['file_id'])['stored_path'])
        self.assertEqual(self.call('import_paper',args,token=token)[1]['file']['file_id'],result['file']['file_id'])
        self.assertEqual(len(notices.for_paper(self.storage,'one')),1)
        self.assertEqual(self.call('get_paper',{'gewu_key':self.key},token=token)[1]['publication_notices'][0]['doi'],'10.5555/notice')

    def test_absent_multiple_self_and_unauthorized_targets_are_not_guessed(self):
        token,upload,args=self.args()
        for related in (['10.5555/missing'],['10.5555/original','10.5555/second'],['10.5555/notice']):
            args['metadata']['publication_notice']['related_dois']=related
            status,result,_=self.call('import_paper',args,token=token)
            self.assertEqual(status,409,result);self.assertEqual(result['code'],'notice_target_required')
        self.storage.conn.execute("UPDATE papers SET doi='10.5555/hidden' WHERE paper_id='outside'");self.storage.conn.commit()
        args['metadata']['publication_notice']['related_dois']=['10.5555/hidden']
        self.assertIn(self.call('import_paper',args,token=token)[0],(403,404))
        self.assertTrue(ai_uploads.path_for(self.storage,upload['upload_id']).exists())

    def test_notice_only_work_has_no_automatic_default(self):
        token,upload,args=self.args(kind='retraction_notice')
        self.storage.conn.execute("UPDATE papers SET doi='10.5555/second' WHERE paper_id='two'");self.storage.conn.commit()
        args['metadata']['publication_notice']['related_dois']=['10.5555/second']
        status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,200,result)
        self.assertIsNone(self.storage.resolve_default_paper_resource('two'))
        self.assertFalse(self.storage.get_paper('two')['main_pdf_path'])
        self.assertEqual(notices.for_paper(self.storage,'two')[0]['kind'],'retraction_notice')

    def test_identical_article_bytes_cannot_be_reclassified_as_notice(self):
        token,_,args=self.args()
        upload=self.upload(token,name='notice.pdf',content=self.pdf_bytes,request='notice-duplicate-002')
        args['upload_id']=upload['upload_id']
        status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,409,result)
        self.assertEqual(self.storage.get_paper_resource(self.pdf['id'])['file_type'],'preprint')
        self.assertEqual(notices.for_paper(self.storage,'one'),[])

    def test_legacy_repair_preserves_file_ids_bytes_notes_and_old_key(self):
        self.storage.conn.execute("UPDATE papers SET doi='10.5555/original' WHERE paper_id='one'")
        old_key=self.other_key
        self.storage.conn.execute("UPDATE papers SET title='Author Correction: Research',doi='10.5555/notice' WHERE paper_id='two'")
        self.storage.conn.commit()
        pdf=ui.attach_file_to_paper(self.storage,paper_id='two',filename='old.pdf',content=self.pdf_bytes,file_type='published_version')
        note=ui.attach_file_to_paper(self.storage,paper_id='two',filename='note.md',content=old_key.encode(),file_type='analysis')
        before={r['id']:Path(r['stored_path']).read_bytes() for r in (pdf,note)}
        notice=notices.describe({'title':'Author Correction: Research','doi':'10.5555/notice','publication_notice':{'kind':'correction_notice','related_dois':['10.5555/original'],'evidence_url':'https://example.org/correction'}})
        result=notices.rehome_legacy(self.storage,'two','one',notice,[pdf['id']])
        self.assertEqual(self.storage.paper_for_key(old_key)['storage_key'],self.key)
        self.assertEqual(set(result['file_ids']),{pdf['id'],note['id']})
        for fid,content in before.items(): self.assertEqual(Path(self.storage.get_paper_resource(fid)['stored_path']).read_bytes(),content)
        self.assertEqual(self.storage.get_paper('one')['doi'],'10.5555/original')
        self.assertEqual(self.storage.resolve_default_paper_resource('one')['id'],self.pdf['id'])
        self.assertEqual(self.storage.get_paper_resource(pdf['id'])['file_type'],'correction_notice')
        self.assertEqual(self.storage.get_paper_resource(note['id'])['file_type'],'analysis')
        self.assertFalse(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall())


class NoticeBrowserTests(unittest.TestCase):
    setUp=browser_fixture.BrowserCaptureTests.setUp
    clean=browser_fixture.BrowserCaptureTests.clean
    begin=browser_fixture.BrowserCaptureTests.begin
    paper=browser_fixture.BrowserCaptureTests.paper
    save=browser_fixture.BrowserCaptureTests.save
    pdf=browser_fixture.BrowserCaptureTests.pdf
    upload=browser_fixture.BrowserCaptureTests.upload

    def test_browser_routes_verified_notice_and_blocks_missing_relation(self):
        original=self.paper()
        capture=self.begin(doi='10.1234/notice')
        self.upload(capture,title='Author Correction: Research')
        capture.paper={'paper_id':'notice','title':'Author Correction: Research','doi':'10.1234/notice'}
        with self.assertRaises(notices.NoticeReviewRequired): self.save(capture,include_pdf=True)
        self.assertIsNone(self.storage.get_paper('notice'))
        capture.paper['raw']={'crossref':{'update-to':[{'type':'correction','DOI':'10.1234/first'}]}}
        result=self.save(capture,include_pdf=True,file_type='published_version')
        self.assertEqual(result['paper_id'],original['paper_id'])
        resources=self.storage.list_paper_resources(original['paper_id'])
        self.assertEqual(len(resources),1)
        self.assertEqual(resources[0]['file_type'],'correction_notice')
        self.assertIsNone(self.storage.resolve_default_paper_resource(original['paper_id']))


class NoticeLoaderTests(unittest.TestCase):
    setUp=inventory_fixture.InventoryImporterDryRunTests.setUp
    tearDown=inventory_fixture.InventoryImporterDryRunTests.tearDown
    write_inventory=inventory_fixture.InventoryImporterDryRunTests.write_inventory
    pdf_record=inventory_fixture.InventoryImporterDryRunTests.pdf_record
    write_text_pdf=inventory_fixture.InventoryImporterDryRunTests.write_text_pdf

    def test_pending_notice_is_retained_and_repeated_import_does_not_create_a_paper(self):
        from paper_monitor.importers.inventory import import_library_inventory
        path=self.write_text_pdf('notice.pdf','Author Correction: Research')
        record=self.pdf_record(path,title='Author Correction: Research',doi='10.5555/notice')
        inv=self.write_inventory([record])
        kwargs=dict(storage=self.storage,dry_run=False,preserve_folders=True,target_root=self.root/'copied')
        first=import_library_inventory(inv,**kwargs)
        self.assertFalse(first['errors'],first)
        self.assertEqual(first['created_papers'],0)
        self.assertEqual(first['publication_notices'][0]['status'],'needs_relation')
        files=[dict(r) for r in self.storage.conn.execute('SELECT * FROM resources')]
        self.assertEqual(len(files),1);self.assertIsNone(files[0]['paper_id'])
        self.assertEqual(Path(files[0]['stored_path']).read_bytes(),path.read_bytes())
        second=import_library_inventory(inv,**kwargs)
        self.assertFalse(second['errors'],second)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resources').fetchone()[0],1)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],0)

    def test_front_matter_original_doi_is_not_the_notice_identity(self):
        from paper_monitor.importers.inventory import pdf_metadata
        path=self.write_text_pdf('notice.pdf','Author Correction: Research. Correction to: Nature https://doi.org/10.5555/original')
        result=pdf_metadata(path)
        self.assertEqual(result['publication_notice']['related_dois'],['10.5555/original'])
        self.assertNotEqual(result['doi'],'10.5555/original')
