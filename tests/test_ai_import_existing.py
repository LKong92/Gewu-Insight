"""Import-only adoption of cached identities; all records and files are temporary."""
import io
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from paper_monitor import ai_uploads, ui_server as ui
from paper_monitor.download import paper_download_lock
from tests import test_ai_writes as write_fixture


class AIImportExistingTests(unittest.TestCase):
    def setUp(self):
        write_fixture.AIWriteTests.setUp(self)
        download_root = patch.object(ui, 'DEFAULT_PDF_DIR', self.path.parent / 'pdfs')
        download_root.start()
        self.patches.append(download_root)
    tearDown = write_fixture.AIWriteTests.tearDown
    request = write_fixture.AIWriteTests.request
    call = write_fixture.AIWriteTests.call
    enable_writes = write_fixture.AIWriteTests.enable_writes
    upload = write_fixture.AIWriteTests.upload
    metadata = write_fixture.AIWriteTests.metadata
    import_args = write_fixture.AIWriteTests.import_args

    def cached(self, paper_id='cached', *, source='crossref', arxiv=False):
        meta = self.metadata()
        if arxiv:
            meta.update(doi=None, arxiv_id='2601.01234')
        self.storage.upsert_paper(dict(paper_id=paper_id, title=meta['title'],
            doi=meta['doi'], journal=meta['journal'], source=source,
            raw={'authors': meta['authors'], 'arxiv_id': meta['arxiv_id']}))
        return self.storage.get_paper(paper_id), meta

    def monitor_pdf(self, paper, *, registered=True):
        path = ui.DEFAULT_PDF_DIR / paper['paper_id'] / 'downloaded.pdf'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.pdf_bytes)
        self.storage.update_download_status(paper['paper_id'], status='success',
            main_pdf_path=str(path), merged_pdf_path=str(path))
        resource = None
        if registered:
            resource = self.storage.create_paper_resource(paper_id=paper['paper_id'],
                stored_path=str(path), storage_mode='managed', file_type='preprint',
                added_via='download_initial', file_source='arxiv',sha256=hashlib.sha256(self.pdf_bytes).hexdigest())
            self.storage.conn.execute('UPDATE papers SET primary_resource_id=? WHERE paper_id=?',
                                      (resource['id'], paper['paper_id']))
            self.storage.conn.commit()
        return path, resource

    def do_import(self, meta, token, *, content=None, name='article.pdf'):
        upload = self.upload(token, name=name, content=content)
        args = self.import_args(upload)
        args['metadata'] = meta
        return self.call('import_paper', args, token=token), upload, args

    def assert_denied(self, paper, meta):
        token = self.enable_writes(selection={'kind':'papers', 'keys':[self.key]})
        before = dict(self.storage.get_paper(paper['paper_id']))
        (status, result, _), upload, _ = self.do_import(meta, token)
        self.assertEqual(status, 403, result)
        self.assertEqual(result['code'], 'import_access_required')
        self.assertNotIn(paper['storage_key'], json.dumps(result))
        self.assertEqual(self.storage.get_paper(paper['paper_id']), before)
        self.assertTrue(ai_uploads.path_for(self.storage, upload['upload_id']).exists())
        self.assertEqual(self.call('get_paper', {'gewu_key':paper['storage_key']}, token=token)[0], 404)

    def test_uncollected_provider_record_reuses_key_without_resolve_or_read_expansion(self):
        paper, meta = self.cached()
        token = self.enable_writes(selection={'kind':'papers', 'keys':[self.key]})
        self.assertEqual(self.call('get_paper', {'gewu_key':paper['storage_key']}, token=token)[0],404)
        with patch.object(ui, 'library_workspace_publication_from_query', side_effect=AssertionError('lookup')), \
             patch.object(ui, 'extract_identifier_from_pdf_or_title', side_effect=AssertionError('PDF scan')):
            (status, result, _), _, args = self.do_import(meta, token)
        self.assertEqual(status,200,result)
        self.assertEqual(result['gewu_key'],paper['storage_key'])
        self.assertTrue(result['reused_paper'])
        self.assertFalse(result['layout_pending'])
        self.assertEqual(self.call('get_paper',{'gewu_key':paper['storage_key']},token=token)[0],200)
        # Another connection's read-only selection did not change.
        self.assertEqual(self.call('get_paper',{'gewu_key':paper['storage_key']})[0],404)
        self.assertEqual(self.call('import_paper',args,token=token)[1]['file']['file_id'],result['file']['file_id'])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers WHERE doi=?',(meta['doi'],)).fetchone()[0],1)

    def test_arxiv_only_cache_can_be_imported_into_space(self):
        paper, meta = self.cached(source='arxiv', arxiv=True)
        token=self.enable_writes()
        space=self.call('create_space',{'name':'Topic','request_id':'new-space-001'},token=token)[1]
        upload=self.upload(token);args=self.import_args(upload)
        args.update(metadata=meta,folder_id=space['folder_id'])
        status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,200,result)
        self.assertEqual(result['gewu_key'],paper['storage_key'])
        self.assertEqual(Path(self.storage.get_paper_resource(result['file']['file_id'])['stored_path']).parent,ui.SPACES_LOCAL_COPY_ROOT/'Topic')

    def test_monitor_same_bytes_reuses_resource_and_archives_existing_default(self):
        paper,meta=self.cached();old,resource=self.monitor_pdf(paper)
        token=self.enable_writes()
        (status,result,_),_,_=self.do_import(meta,token)
        self.assertEqual(status,200,result)
        self.assertTrue(result['reused_file']);self.assertFalse(result['layout_pending'])
        self.assertEqual(result['file']['file_id'],resource['id'])
        self.assertEqual(result['file']['file_type'],'preprint')
        fresh=self.storage.get_paper_resource(resource['id'])
        self.assertEqual(Path(fresh['stored_path']).parent.resolve(),ui.LIBRARY_LOCAL_COPY_ROOT.resolve())
        self.assertEqual(Path(fresh['stored_path']).read_bytes(),self.pdf_bytes)
        self.assertFalse(old.exists())

    def test_legacy_monitor_pdf_is_registered_once_and_same_bytes_reused(self):
        paper,meta=self.cached();old,_=self.monitor_pdf(paper,registered=False)
        (status,result,_),_,_=self.do_import(meta,self.enable_writes())
        self.assertEqual(status,200,result)
        self.assertTrue(result['reused_file']);self.assertFalse(result['layout_pending'])
        self.assertEqual(len(self.storage.list_paper_resources(paper['paper_id'])),1)
        self.assertEqual(Path(self.storage.get_paper_resource(result['file']['file_id'])['stored_path']).parent.resolve(),ui.LIBRARY_LOCAL_COPY_ROOT.resolve())

    def test_monitor_different_pdf_retains_manual_default_and_both_bytes(self):
        paper,meta=self.cached();old,resource=self.monitor_pdf(paper)
        ui.set_preferred_paper_file(self.storage,paper['paper_id'],resource['id'])
        writer=PdfWriter();writer.add_blank_page(width=123,height=456);out=io.BytesIO();writer.write(out)
        (status,result,_),_,_=self.do_import(meta,self.enable_writes(),content=out.getvalue())
        self.assertEqual(status,200,result);self.assertFalse(result['reused_file'])
        self.assertEqual(self.storage.resolve_default_paper_resource(paper['paper_id'])['id'],resource['id'])
        default=self.storage.get_paper_resource(resource['id']);new=self.storage.get_paper_resource(result['file']['file_id'])
        self.assertEqual(Path(default['stored_path']).parent.resolve(),ui.LIBRARY_LOCAL_COPY_ROOT.resolve())
        self.assertTrue(Path(new['stored_path']).resolve().is_relative_to(ui.ASSOCIATED_FILES_ROOT.resolve()))
        self.assertEqual(Path(default['stored_path']).read_bytes(),self.pdf_bytes)
        self.assertEqual(Path(new['stored_path']).read_bytes(),out.getvalue())

    def test_monitor_new_published_pdf_uses_existing_automatic_priority(self):
        paper,meta=self.cached();_,resource=self.monitor_pdf(paper)
        writer=PdfWriter();writer.add_blank_page(width=321,height=654);out=io.BytesIO();writer.write(out)
        (status,result,_),_,_=self.do_import(meta,self.enable_writes(),content=out.getvalue())
        self.assertEqual(status,200,result)
        self.assertFalse(result['layout_pending'])
        new=self.storage.get_paper_resource(result['file']['file_id'])
        previous=self.storage.get_paper_resource(resource['id'])
        self.assertEqual(self.storage.resolve_default_paper_resource(paper['paper_id'])['id'],new['id'])
        self.assertEqual(Path(new['stored_path']).parent.resolve(),ui.LIBRARY_LOCAL_COPY_ROOT.resolve())
        self.assertTrue(Path(previous['stored_path']).resolve().is_relative_to(ui.ASSOCIATED_FILES_ROOT.resolve()))
        self.assertEqual(Path(previous['stored_path']).read_bytes(),self.pdf_bytes)
        self.assertEqual(Path(new['stored_path']).read_bytes(),out.getvalue())

    def test_private_placement_is_not_adopted(self):
        paper,meta=self.cached()
        folder=self.storage.create_library_root_folder(name='Private')
        self.storage.add_library_item(paper_id=paper['paper_id'],folder_id=folder['id'])
        self.assert_denied(paper,meta)

    def test_recycle_placement_is_not_resurrected(self):
        paper,meta=self.cached()
        folder=self.storage.create_library_folder(name='Recycle',parent_id=1)
        self.storage.add_library_item(paper_id=paper['paper_id'],folder_id=folder['id'])
        self.assert_denied(paper,meta)

    def test_unreadable_my_publication_is_not_adopted(self):
        paper,meta=self.cached()
        self.storage.add_my_publication(paper_id=paper['paper_id'])
        self.assert_denied(paper,meta)

    def test_legacy_analysis_path_is_not_adopted(self):
        paper,meta=self.cached()
        note=self.root/'private.md';note.write_text('# Private note')
        self.storage.conn.execute('UPDATE papers SET analysis_path=? WHERE paper_id=?',(str(note),paper['paper_id']));self.storage.conn.commit()
        self.assert_denied(paper,meta)

    def test_unsaved_private_attachment_is_not_adopted(self):
        paper,meta=self.cached()
        ui.attach_file_to_paper(self.storage,paper_id=paper['paper_id'],filename='private.md',content=b'# Private')
        self.assert_denied(paper,meta)

    def test_linked_monitor_file_is_not_adopted(self):
        paper,meta=self.cached();old,resource=self.monitor_pdf(paper)
        self.storage.conn.execute("UPDATE resources SET storage_mode='linked' WHERE id=?",(resource['id'],));self.storage.conn.commit()
        self.assert_denied(paper,meta)

    def test_annotated_monitor_file_is_not_adopted(self):
        paper,meta=self.cached();_,resource=self.monitor_pdf(paper)
        self.storage.conn.execute("UPDATE resources SET annotation_state='annotated',is_annotated=1 WHERE id=?",(resource['id'],));self.storage.conn.commit()
        self.assert_denied(paper,meta)

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_download_path_symlink_to_private_file_is_not_adopted(self):
        paper,meta=self.cached();old,_=self.monitor_pdf(paper)
        external=self.root/'private.pdf';old.rename(external);old.symlink_to(external)
        self.assert_denied(paper,meta)
        self.assertEqual(external.read_bytes(),self.pdf_bytes)

    def test_locally_edited_download_is_not_adopted_from_stale_annotation_flags(self):
        paper,meta=self.cached();old,_=self.monitor_pdf(paper)
        old.write_bytes(self.pdf_bytes+b'\n% local edit\n')
        self.assert_denied(paper,meta)
        self.assertTrue(old.read_bytes().endswith(b'% local edit\n'))

    def test_file_shared_with_another_work_is_not_adopted(self):
        paper,meta=self.cached();old,_=self.monitor_pdf(paper)
        self.storage.create_paper_resource(paper_id='outside',stored_path=str(old),file_type='preprint')
        self.assert_denied(paper,meta)
        self.assertEqual(old.read_bytes(),self.pdf_bytes)

    def test_cached_identity_does_not_bypass_destination_permission(self):
        paper,meta=self.cached();private=self.storage.create_library_root_folder(name='Private')
        token=self.enable_writes();upload=self.upload(token);args=self.import_args(upload)
        args.update(metadata=meta,folder_id=private['id'])
        status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,403,result);self.assertEqual(result['code'],'write_scope_required')
        self.assertEqual(self.storage.get_paper(paper['paper_id']),paper)
        self.assertTrue(ai_uploads.path_for(self.storage,upload['upload_id']).exists())

    def test_multiple_identifier_targets_remain_conflict(self):
        paper,meta=self.cached();other,_=self.cached('other_cache',source='arxiv',arxiv=True)
        meta['arxiv_id']='2601.01234'
        (status,result,_),_,_=self.do_import(meta,self.enable_writes())
        self.assertEqual(status,409,result);self.assertEqual(result['code'],'identity_conflict')
        self.assertEqual(self.storage.get_paper(paper['paper_id']),paper)
        self.assertEqual(self.storage.get_paper(other['paper_id']),other)

    def test_uncollected_user_import_is_not_treated_as_a_public_cache(self):
        paper,meta=self.cached()
        self.storage.conn.execute("UPDATE papers SET import_kind='pdf' WHERE paper_id=?",(paper['paper_id'],));self.storage.conn.commit()
        self.assert_denied(paper,meta)

    def test_reused_identity_and_membership_roll_back_when_file_copy_fails(self):
        paper,meta=self.cached();token=self.enable_writes()
        with patch('paper_monitor.ai_writes.shutil.copyfileobj',side_effect=OSError('disk full')):
            (status,result,_),upload,args=self.do_import(meta,token)
        self.assertNotEqual(status,200,result)
        self.assertEqual(self.storage.get_paper(paper['paper_id']),paper)
        self.assertEqual(self.storage.list_paper_resources(paper['paper_id']),[])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM library_items WHERE paper_id=?',(paper['paper_id'],)).fetchone()[0],0)
        self.assertTrue(ai_uploads.path_for(self.storage,upload['upload_id']).exists())
        self.assertEqual(self.call('import_paper',args,token=token)[0],200)

    def test_layout_failure_retains_files_and_exact_retry_finishes(self):
        paper,meta=self.cached();old,resource=self.monitor_pdf(paper);token=self.enable_writes()
        with patch.object(ui,'sync_all_pdf_aliases_for_paper',side_effect=OSError('busy volume')):
            (status,result,_),_,args=self.do_import(meta,token)
        self.assertEqual(status,200,result);self.assertTrue(result['layout_pending'])
        self.assertEqual(old.read_bytes(),self.pdf_bytes)
        status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,200,result);self.assertFalse(result['layout_pending'])
        self.assertEqual(result['file']['file_id'],resource['id'])

    def test_archive_move_failure_restores_original_then_retry_moves_it(self):
        paper,meta=self.cached();old,resource=self.monitor_pdf(paper);token=self.enable_writes()
        update=ui.update_paper_file_path_references
        def interrupted(*args,**kwargs):
            update(*args,**kwargs)
            raise OSError('synthetic interruption after move')
        with patch.object(ui,'update_paper_file_path_references',side_effect=interrupted):
            (status,result,_),_,args=self.do_import(meta,token)
        self.assertEqual(status,200,result);self.assertTrue(result['layout_pending'])
        self.assertEqual(old.read_bytes(),self.pdf_bytes)
        self.assertEqual(Path(self.storage.get_paper_resource(resource['id'])['stored_path']),old)
        status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,200,result);self.assertFalse(result['layout_pending'])
        self.assertFalse(old.exists())

    def test_active_monitor_download_returns_retry_without_importing(self):
        paper,meta=self.cached();token=self.enable_writes()
        # HTTP handler is a different thread; a busy download must not deadlock
        # by waiting for a lock while holding SQLite's writer transaction.
        with paper_download_lock(self.storage.db_path,paper['paper_id']):
            (status,result,_),upload,args=self.do_import(meta,token)
        self.assertEqual(status,409,result);self.assertEqual(result['code'],'paper_busy')
        self.assertTrue(ai_uploads.path_for(self.storage,upload['upload_id']).exists())
        self.assertEqual(self.call('import_paper',args,token=token)[0],200)

    def test_import_filename_preserves_pdf_extension(self):
        paper,meta=self.cached()
        (status,result,_),_,_=self.do_import(meta,self.enable_writes(),name='Long paper title '+('materials '*18)+'.pdf')
        self.assertEqual(status,200,result)
        self.assertTrue(result['file']['name'].endswith('.pdf'))
        self.assertEqual(result['file']['kind'],'pdf')
