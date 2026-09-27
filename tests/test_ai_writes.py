"""Temporary-only MCP write workflows, including transfer lifecycle and identity reuse."""
import hashlib
import io
import json
import sqlite3
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from paper_monitor import ai_store, ai_uploads, ai_service, ui_server, mcp_server
from paper_monitor.ai_contract import WRITE_SCOPES
from tests import test_ai_access as access_fixture


class AIWriteTests(unittest.TestCase):
    setUp=access_fixture.AIAccessTests.setUp
    tearDown=access_fixture.AIAccessTests.tearDown
    request=access_fixture.AIAccessTests.request
    call=access_fixture.AIAccessTests.call

    def enable_writes(self, roots=None, scopes=None, selection=None):
        created=ai_store.create_connection(self.storage, {'name':'Writer','scopes':scopes or ['papers:read','files:read','folders:read',*set(WRITE_SCOPES.values())],
            'selection':selection or {'kind':'saved'},'write_folder_ids':[1] if roots is None else roots})
        return created['token']

    def upload(self, token, name='article.pdf', content=None, request='upload-test-001'):
        content=self.pdf_bytes if content is None else content
        return ai_uploads.receive(self.storage,'Bearer '+token,io.BytesIO(content),name=name,length=len(content),digest=hashlib.sha256(content).hexdigest(),retry_id=request)

    def metadata(self, **extra):
        return dict(title='A supplied paper',authors=['Example Author'],journal='Example Journal',publication_type='journal_article',publication_date='2026-09-21',doi='10.5555/ai-example',arxiv_id=None,source_url='https://example.org/article',abstract='Supplied abstract',**extra)

    def import_args(self, upload, **extra):
        return dict(folder_id=1,upload_id=upload['upload_id'],metadata=self.metadata(),file_type='published_version',request_id='import-test-001',**extra)

    def test_full_import_uses_supplied_metadata_and_releases_staging(self):
        token=self.enable_writes();upload=self.upload(token)
        args=self.import_args(upload)
        with patch.object(ui_server,'library_workspace_publication_from_query',side_effect=AssertionError('network during import')), patch.object(ui_server,'extract_identifier_from_pdf_or_title',side_effect=AssertionError('PDF identifier scan')),patch.object(ui_server,'refresh_imported_doi_metadata',side_effect=AssertionError('enrichment queue')),patch('paper_monitor.resource_fingerprint.pdf_content_fingerprint',side_effect=AssertionError('whole-document decompression')):
            status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,200,result)
        paper=self.storage.paper_for_key(result['gewu_key'])
        self.assertEqual(paper['doi'],args['metadata']['doi']);self.assertEqual(paper['journal'],'Example Journal')
        self.assertEqual(paper['publication_date'],'2026-09-21');self.assertEqual(json.loads(paper['raw_json'])['authors'],['Example Author'])
        path=Path(self.storage.get_paper_resource(result['file']['file_id'])['stored_path'])
        self.assertEqual(path.parent,ui_server.LIBRARY_LOCAL_COPY_ROOT)
        self.assertEqual(path.read_bytes(),self.pdf_bytes)
        self.assertFalse(ai_uploads.path_for(self.storage,upload['upload_id']).exists())
        self.assertEqual(self.call('get_upload_status',token=token)[1]['quota']['used_bytes'],0)
        repeat=self.call('import_paper',args,token=token)
        self.assertEqual(repeat[0],200,repeat[1]);self.assertEqual(repeat[1]['file']['file_id'],result['file']['file_id'])

    def test_standalone_resolve_completes_and_same_request_does_not_lookup_twice(self):
        self.storage.conn.execute("UPDATE papers SET doi='10.5555/resolve-example' WHERE paper_id='one'");self.storage.conn.commit()
        token=self.enable_writes();args={'gewu_key':self.key,'purpose':'standalone','request_id':'resolve-success-001'}
        found={'title':'Quantum one','doi':'10.5555/resolve-example','abstract':'Fetched abstract','raw':{'authors':['Fixture Author']}}
        with patch.object(ui_server,'library_workspace_publication_from_query',return_value=found) as lookup:
            self.assertEqual(self.call('resolve_paper',{**args,'purpose':'import'},token=token)[0],400)
            self.assertEqual(self.call('resolve_paper',args,token=token)[0],200)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                status,result,_=self.call('get_resolve_status',{'request_id':args['request_id']},token=token)
                if result.get('status') in ('completed','failed'): break
                time.sleep(.02)
            self.assertEqual(result['status'],'completed',result)
            self.assertEqual(self.call('resolve_paper',args,token=token)[1]['status'],'completed')
            lookup.assert_called_once_with('10.5555/resolve-example')
        self.assertEqual(self.storage.get_paper('one')['abstract'],'Fetched abstract')
        self.assertEqual(self.storage.resolve_default_paper_resource('one')['id'],self.pdf['id'])

    def test_oversized_mcp_json_is_drained_without_ending_connection(self):
        source=io.StringIO('x'*(1024*1024+50)+'\n'+json.dumps({'jsonrpc':'2.0','id':8,'method':'ping'})+'\n')
        output=io.StringIO()
        self.assertEqual(mcp_server.serve(None,source,output),0)
        messages=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertIn('error',messages[0]);self.assertEqual(messages[1],{'jsonrpc':'2.0','id':8,'result':{}})

    def test_expired_and_interrupted_uploads_reclaim_only_inactive_staging(self):
        token=self.enable_writes();grant=ai_store.authenticate(self.storage,'Bearer '+token)
        first=self.upload(token,name='first.md',content=b'first')
        second=self.upload(token,name='second.md',content=b'second',request='upload-expiry-002')
        self.storage.conn.execute("UPDATE ai_uploads SET created_at='2000-01-01T00:00:00.000000+00:00'");self.storage.conn.commit()
        active=(str(self.storage.db_path.resolve()),second['upload_id'])
        ai_uploads.ACTIVE.add(active)
        try:
            with ai_uploads.LOCK: ai_uploads.prune(self.storage)
            self.assertFalse(ai_uploads.path_for(self.storage,first['upload_id']).exists())
            self.assertTrue(ai_uploads.path_for(self.storage,second['upload_id']).exists())
            self.assertEqual(ai_uploads.quota(self.storage,grant)['used_files'],1)
        finally: ai_uploads.ACTIVE.discard(active)
        self.storage.conn.execute("UPDATE ai_uploads SET status='uploading' WHERE upload_id=?",(second['upload_id'],));self.storage.conn.commit()
        with ai_uploads.LOCK: ai_uploads.prune(self.storage)
        self.assertEqual(ai_uploads.quota(self.storage,grant)['used_files'],0)

    def test_linked_external_default_is_preserved_when_appending(self):
        token=self.enable_writes();external=self.root/'linked-original.pdf';external.write_bytes(self.pdf_bytes)
        self.storage.conn.execute("UPDATE resources SET stored_path=?,storage_mode='linked' WHERE id=?",(str(external),self.pdf['id']))
        self.storage.conn.execute("UPDATE papers SET main_pdf_path=?,merged_pdf_path=? WHERE paper_id='one'",(str(external),str(external)));self.storage.conn.commit()
        upload=self.upload(token,name='support.csv',content=b'a,b\n1,2')
        result=self.call('add_paper_file',{'gewu_key':self.key,'upload_id':upload['upload_id'],'request_id':'linked-attachment-001'},token=token)
        self.assertEqual(result[0],200,result[1])
        self.assertEqual(external.read_bytes(),self.pdf_bytes)
        self.assertEqual(self.storage.get_paper_resource(self.pdf['id'])['stored_path'],str(external))
        self.assertIn(str(ui_server.ASSOCIATED_FILES_ROOT),self.storage.get_paper_resource(result[1]['file']['file_id'])['stored_path'])

    def test_missing_metadata_rejects_without_creating_or_resolving(self):
        token=self.enable_writes();upload=self.upload(token)
        before=self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0]
        args=self.import_args(upload);args['metadata'].pop('authors')
        status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,400,result);self.assertEqual(result['code'],'metadata_required')
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],before)
        self.assertTrue(ai_uploads.path_for(self.storage,upload['upload_id']).exists())
        args=self.import_args(upload);args['resolve']=True
        self.assertEqual(self.call('import_paper',args,token=token)[0],400)

    def test_same_identity_adds_placement_and_different_pdf_without_changing_manual_default(self):
        token=self.enable_writes();first=self.call('import_paper',self.import_args(self.upload(token)),token=token)[1]
        paper=self.storage.paper_for_key(first['gewu_key']);default=self.storage.resolve_default_paper_resource(paper['paper_id'])
        ui_server.set_preferred_paper_file(self.storage,paper['paper_id'],default['id'])
        original=Path(default['stored_path']).read_bytes()
        folder=self.call('create_folder',{'parent_id':1,'name':'New topic','request_id':'folder-test-001'},token=token)[1]
        writer=PdfWriter();writer.add_blank_page(width=321,height=456);out=io.BytesIO();writer.write(out)
        new=self.upload(token,content=out.getvalue(),request='upload-test-002')
        args=self.import_args(new);args.update(folder_id=folder['folder_id'],request_id='import-test-002')
        status,result,_=self.call('import_paper',args,token=token)
        self.assertEqual(status,200,result);self.assertEqual(result['gewu_key'],first['gewu_key']);self.assertTrue(result['reused_paper'])
        resource=self.storage.get_paper_resource(result['file']['file_id'])
        self.assertIn(str(ui_server.ASSOCIATED_FILES_ROOT),resource['stored_path'])
        self.assertEqual(resource['file_type'],'published_version')
        self.assertEqual(self.storage.resolve_default_paper_resource(paper['paper_id'])['id'],default['id'])
        self.assertEqual(Path(default['stored_path']).read_bytes(),original)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM library_items WHERE paper_id=?',(paper['paper_id'],)).fetchone()[0],2)
        self.assertEqual(Path(resource['stored_path']).read_bytes(),out.getvalue())

    def test_new_space_read_scope_and_standalone_file(self):
        token=self.enable_writes(roots=[],selection={'kind':'papers','keys':[self.key]})
        args={'name':'My direction','request_id':'space-test-001'}
        status,space,_=self.call('create_space',args,token=token);self.assertEqual(status,200,space)
        self.assertEqual(self.call('create_space',args,token=token)[1]['folder_id'],space['folder_id'])
        listing=self.call('list_folders',token=token);self.assertEqual(listing[0],200,listing[1])
        self.assertIn(space['folder_id'],[f['folder_id'] for f in listing[1]['folders']])
        upload=self.upload(token,name='Overview.md',content=b'# A direction overview')
        status,result,_=self.call('import_file',{'folder_id':space['folder_id'],'upload_id':upload['upload_id'],'request_id':'file-test-001'},token=token)
        self.assertEqual(status,200,result)
        paper=self.storage.paper_for_key(result['gewu_key']);self.assertEqual(paper['import_kind'],'md')
        resource=self.storage.get_paper_resource(result['file']['file_id'])
        self.assertEqual(Path(resource['stored_path']).parent,ui_server.SPACES_LOCAL_COPY_ROOT/'My direction')
        self.assertEqual(self.call('get_paper',{'gewu_key':result['gewu_key']},token=token)[0],200)

    def test_old_permissions_and_separate_resolve(self):
        self.assertEqual(self.call('create_space',{'name':'No','request_id':'space-denied-001'})[0],403)
        token=self.enable_writes(scopes=['papers:read','papers:import'])
        status,result,_=self.call('resolve_paper',{'gewu_key':self.key,'purpose':'standalone','request_id':'resolve-test-001'},token=token)
        self.assertEqual(status,403,result)
        self.assertFalse(mcp_server.tool_allowed('resolve_paper',['papers:read','papers:import']))

    def test_many_batches_recycle_upload_quota(self):
        token=self.enable_writes()
        with patch.object(ai_uploads,'MAX_STAGED_BYTES',30),patch.object(ai_uploads,'MAX_STAGED_FILES',1):
            for index in range(10):
                upload=self.upload(token,name=f'notes-{index}.md',content=b'0123456789'*2,request=f'upload-batch-{index}')
                args={'folder_id':1,'upload_id':upload['upload_id'],'request_id':f'import-batch-{index}'}
                status,result,_=self.call('import_file',args,token=token);self.assertEqual(status,200,result)
                self.assertEqual(self.call('get_upload_status',token=token)[1]['quota']['used_files'],0)
        self.assertEqual(list((self.path.parent/'.ai-uploads').glob('*.bin')),[])

    def test_upload_failure_cross_connection_and_release(self):
        token=self.enable_writes();upload=self.upload(token,name='data.xyz',content=b'unknown format')
        other=self.enable_writes()
        status,result,_=self.call('import_file',{'folder_id':1,'upload_id':upload['upload_id'],'request_id':'wrong-owner-001'},token=other)
        self.assertEqual(status,404,result)
        self.assertFalse(self.call('release_upload',{'upload_id':upload['upload_id']},token=other)[1]['released'])
        self.assertTrue(self.call('release_upload',{'upload_id':upload['upload_id']},token=token)[1]['released'])
        self.assertFalse(self.call('release_upload',{'upload_id':upload['upload_id']},token=token)[1]['released'])
        with self.assertRaises(ai_store.APIError):
            ai_uploads.receive(self.storage,'Bearer '+token,io.BytesIO(b'a'),name='broken.pdf',length=12,digest='0'*64,retry_id='broken-upload-001')
        self.assertEqual(ai_uploads.quota(self.storage,ai_store.authenticate(self.storage,'Bearer '+token))['used_bytes'],0)

    def test_binary_http_upload_and_exact_retry(self):
        token=self.enable_writes();client=mcp_server.GewuClient(f'http://127.0.0.1:{self.server.server_port}',token)
        source=self.root/'中文报告.xyz';source.write_bytes(b'binary data\0\xff')
        upload=client.upload_file({'local_path':str(source),'request_id':'http-upload-001'})
        repeat=client.upload_file({'local_path':str(source),'request_id':'http-upload-001'})
        self.assertEqual(upload['upload_id'],repeat['upload_id'])
        self.assertEqual(upload['name'],source.name)
        client.close()

    def test_database_failure_preserves_source_and_no_partial_paper(self):
        token=self.enable_writes();upload=self.upload(token)
        before=self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0]
        self.storage.conn.execute("CREATE TRIGGER fixture_fail_ai BEFORE INSERT ON resources BEGIN SELECT RAISE(ABORT,'fixture failure'); END");self.storage.conn.commit()
        self.assertEqual(self.call('import_paper',self.import_args(upload),token=token)[0],503)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],before)
        self.assertTrue(ai_uploads.path_for(self.storage,upload['upload_id']).exists())
        self.assertFalse((ui_server.LIBRARY_LOCAL_COPY_ROOT/'article.pdf').exists())

    def test_outside_identity_never_becomes_accessible_by_import(self):
        self.storage.conn.execute("UPDATE papers SET doi='10.5555/ai-example' WHERE paper_id='outside'");self.storage.conn.commit()
        token=self.enable_writes(selection={'kind':'papers','keys':[self.key]})
        result=self.call('import_paper',self.import_args(self.upload(token)),token=token)
        self.assertEqual(result[0],404,result[1])
        self.assertEqual(self.storage.conn.execute("SELECT count(*) FROM library_items WHERE paper_id='outside'").fetchone()[0],0)

    def test_identity_evidence_is_retained_and_identical_bytes_reuse_resource(self):
        token=self.enable_writes()
        first=self.call('import_paper',self.import_args(self.upload(token)),token=token)[1]
        args=self.import_args(self.upload(token,request='upload-identity-2'))
        args['request_id']='import-identity-2';args['metadata']['arxiv_id']='2601.01234v2'
        args['metadata']['title']='A different title supplied later'
        second=self.call('import_paper',args,token=token)
        self.assertEqual(second[0],200,second[1]);self.assertTrue(second[1]['reused_file'])
        args=self.import_args(self.upload(token,request='upload-identity-3'))
        args['request_id']='import-identity-3';args['metadata'].update(doi=None,arxiv_id='2601.01234')
        third=self.call('import_paper',args,token=token)
        self.assertEqual(third[0],200,third[1]);self.assertEqual(third[1]['gewu_key'],first['gewu_key'])
        details=self.call('get_paper',{'gewu_key':first['gewu_key']},token=token)[1]
        self.assertEqual(details['title'],'A supplied paper');self.assertEqual(details['authors'],['Example Author'])
        self.assertEqual(len(details['files']),1)

    def test_conflicting_identity_never_merges_two_keys(self):
        from paper_monitor import paper_identity
        self.storage.conn.execute("UPDATE papers SET doi='10.5555/ai-example' WHERE paper_id='one'")
        self.storage.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id='two'",(json.dumps({'arxiv_id':'2601.01234'}),))
        for pid in ('one','two'): paper_identity.register(self.storage,self.storage.get_paper(pid))
        self.storage.conn.commit()
        token=self.enable_writes();upload=self.upload(token);args=self.import_args(upload)
        args['metadata']['arxiv_id']='2601.01234'
        result=self.call('import_paper',args,token=token)
        self.assertEqual(result[0],409,result[1]);self.assertEqual(result[1]['code'],'identity_conflict')
        self.assertEqual(self.storage.get_paper('one')['storage_key'],self.key)
        self.assertEqual(self.storage.get_paper('two')['storage_key'],self.other_key)
        self.assertTrue(ai_uploads.path_for(self.storage,upload['upload_id']).exists())

    def test_append_any_format_and_manual_default_stays_unchanged(self):
        token=self.enable_writes()
        upload=self.upload(token,name='result.custom',content=b'\x00\xffarbitrary bytes')
        result=self.call('add_paper_file',{'gewu_key':self.key,'upload_id':upload['upload_id'],
            'file_type':'source_data','request_id':'attachment-test-001'},token=token)
        self.assertEqual(result[0],200,result[1])
        resource=self.storage.get_paper_resource(result[1]['file']['file_id'])
        self.assertEqual(Path(resource['stored_path']).read_bytes(),b'\x00\xffarbitrary bytes')
        self.assertIn(str(ui_server.ASSOCIATED_FILES_ROOT),resource['stored_path'])
        self.assertEqual(self.storage.resolve_default_paper_resource('one')['id'],self.pdf['id'])
        # A human can still explicitly choose an imported attachment as Default.
        self.storage.set_preferred_paper_resource('one',resource['id'])
        self.assertEqual(self.storage.resolve_default_paper_resource('one')['id'],resource['id'])

    def test_pdf_cannot_bypass_metadata_via_ordinary_file_import(self):
        token=self.enable_writes();upload=self.upload(token)
        result=self.call('import_file',{'folder_id':1,'upload_id':upload['upload_id'],'request_id':'bypass-test-001'},token=token)
        self.assertEqual(result[0],400,result[1]);self.assertEqual(result[1]['code'],'metadata_required')

    def test_rollback_never_deletes_external_file_that_wins_name_race(self):
        from paper_monitor import ai_writes
        token=self.enable_writes();upload=self.upload(token)
        destination=ui_server.LIBRARY_LOCAL_COPY_ROOT/'article.pdf'
        def collide(_source, target):
            Path(target).write_bytes(b'unrelated external file')
            raise FileExistsError('fixture name race')
        with patch.object(ai_writes.os,'link',side_effect=collide):
            result=self.call('import_paper',self.import_args(upload),token=token)
        self.assertEqual(result[0],503,result[1])
        self.assertEqual(destination.read_bytes(),b'unrelated external file')
        self.assertEqual(list(destination.parent.glob('.gewu-ai-*')),[])
        self.assertEqual(self.call('import_paper',self.import_args(upload),token=token)[0],200)
        self.assertEqual(destination.read_bytes(),b'unrelated external file')

    def test_fill_metadata_preserves_existing_values_and_files(self):
        token=self.enable_writes()
        result=self.call('update_paper_metadata',{'gewu_key':self.key,'metadata':{
            'title':'Conflicting title','abstract':'New abstract','source_url':'https://example.org/source'},'request_id':'metadata-test-001'},token=token)
        self.assertEqual(result[0],200,result[1]);self.assertEqual(result[1]['preserved_conflicts'],['title'])
        self.assertEqual(self.storage.get_paper('one')['title'],'Quantum one')
        self.assertEqual(self.storage.get_paper('one')['abstract'],'New abstract')
        self.assertEqual(self.storage.resolve_default_paper_resource('one')['id'],self.pdf['id'])

    def test_write_settings_keep_token_read_permissions_and_old_grants(self):
        before=self.storage.conn.execute('SELECT * FROM ai_connections WHERE id=?',(self.connection,)).fetchone()
        result=self.request('/api/settings/ai-access',{'action':'write_access','connection_id':self.connection,
            'scopes':['spaces:create','folders:create'],'write_folder_ids':[1]},workspace=True)
        self.assertEqual(result[0],200,result[1])
        after=self.storage.conn.execute('SELECT * FROM ai_connections WHERE id=?',(self.connection,)).fetchone()
        for field in ('token_hash','selection_json','expires_at'): self.assertEqual(before[field],after[field])
        self.assertEqual(set(json.loads(after['scopes_json']))-set(json.loads(before['scopes_json'])),{'spaces:create','folders:create'})
        self.assertEqual(self.call('create_space',{'name':'Authorized','request_id':'authorized-space'},token=self.token)[0],200)
        denied=self.request('/api/settings/ai-access',{'action':'write_access','connection_id':self.connection,
            'scopes':['papers:resolve'],'write_folder_ids':[1]},token=self.token)
        self.assertIn(denied[0],(401,403))

    def test_schema_upgrade_does_not_expand_existing_connections(self):
        from paper_monitor.storage import Storage, STORAGE_SCHEMA_VERSION
        before=dict(self.storage.conn.execute('SELECT * FROM ai_connections WHERE id=?',(self.connection,)).fetchone())
        self.storage.conn.execute('DROP TABLE ai_uploads');self.storage.conn.execute('DROP TABLE ai_write_requests')
        self.storage.conn.execute('ALTER TABLE ai_connections DROP COLUMN write_roots_json')
        self.storage.conn.execute('PRAGMA user_version=20');self.storage.conn.commit()
        upgraded=Storage(self.path)
        try:
            self.assertEqual(upgraded.conn.execute('PRAGMA user_version').fetchone()[0],STORAGE_SCHEMA_VERSION)
            after=dict(upgraded.conn.execute('SELECT * FROM ai_connections WHERE id=?',(self.connection,)).fetchone())
            self.assertEqual(before,after)
            self.assertEqual(upgraded.conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally: upgraded.close()

    def test_quota_full_is_recoverable_without_reconnect(self):
        token=self.enable_writes()
        with patch.object(ai_uploads,'MAX_STAGED_FILES',1):
            first=self.upload(token,name='first.md',content=b'first')
            with self.assertRaises(ai_store.APIError) as error:
                self.upload(token,name='second.md',content=b'second',request='upload-second-001')
            self.assertEqual(error.exception.code,'upload_capacity')
            self.call('release_upload',{'upload_id':first['upload_id']},token=token)
            second=self.upload(token,name='second.md',content=b'second',request='upload-second-001')
            self.assertEqual(second['status'],'ready')

    def test_stdio_error_then_import_then_ping_keeps_session_alive(self):
        token=self.enable_writes();upload=self.upload(token)
        client=mcp_server.GewuClient(f'http://127.0.0.1:{self.server.server_port}',token)
        requests=[('initialize',{}),('tools/call',{'name':'upload_file','arguments':{'local_path':'missing','request_id':'bad'}}),
                  ('tools/call',{'name':'import_paper','arguments':self.import_args(upload)}),('ping',{})]
        source=io.StringIO(''.join(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params})+'\n' for i,(method,params) in enumerate(requests)))
        output=io.StringIO()
        try: self.assertEqual(mcp_server.serve(client,source,output),0)
        finally: client.close()
        messages=[json.loads(line)['result'] for line in output.getvalue().splitlines()]
        self.assertTrue(messages[1]['isError']);self.assertFalse(messages[2]['isError']);self.assertEqual(messages[3],{})

    def test_standalone_resolve_runs_independently_and_revocation_prevents_write(self):
        from paper_monitor import ai_resolve
        self.storage.conn.execute("UPDATE papers SET doi='10.5555/resolve-example' WHERE paper_id='one'");self.storage.conn.commit()
        token=self.enable_writes();grant=ai_store.authenticate(self.storage,'Bearer '+token)
        entered=threading.Event();release=threading.Event()
        def slow_lookup(_identifier):
            entered.set();release.wait(5)
            return {'title':'Quantum one','doi':'10.5555/resolve-example','abstract':'Fetched abstract','journal':'Fixture Journal','raw':{'authors':['Fixture Author']}}
        job={'gewu_key':self.key,'purpose':'standalone','request_id':'resolve-job-001'}
        with patch.object(ui_server,'library_workspace_publication_from_query',side_effect=slow_lookup):
            try:
                response=self.call('resolve_paper',job,token=token)
                self.assertEqual(response[0],200,response[1]);self.assertTrue(entered.wait(3))
                writer=self.enable_writes()
                upload=self.upload(writer,name='during-resolve.md',content=b'no waiting for resolve')
                response=self.call('import_file',{'folder_id':1,'upload_id':upload['upload_id'],'request_id':'during-resolve-001'},token=writer)
                self.assertEqual(response[0],200,response[1])
                self.storage.conn.execute('UPDATE ai_connections SET revoked_at=? WHERE id=?',(ai_store.utc_now(),grant['id']));self.storage.conn.commit()
            finally: release.set()
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                row=self.storage.conn.execute('SELECT result_json FROM ai_write_requests WHERE connection_id=? AND request_id=?',(grant['id'],job['request_id'])).fetchone()
                if row and json.loads(row[0])['status']=='failed': break
                time.sleep(.02)
            self.assertEqual(json.loads(row[0])['status'],'failed')
        self.assertFalse(self.storage.get_paper('one')['abstract'])
        self.assertEqual(self.storage.resolve_default_paper_resource('one')['id'],self.pdf['id'])

if __name__=='__main__': unittest.main()
