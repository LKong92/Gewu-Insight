"""Copy-only migration: synthetic Zotero sources, isolated Gewu SQLite/files."""
import copy
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from paper_monitor import ui_server as ui
from paper_monitor.storage import Storage
from paper_monitor.zotero_import import archives, files, http, importer, store


class ZoteroImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'Zotero'
        self.source.mkdir()
        self.original_db = self.source / 'zotero.sqlite'
        conn = sqlite3.connect(self.original_db)
        conn.execute('CREATE TABLE originals(id INTEGER, note TEXT)')
        conn.execute("INSERT INTO originals VALUES(1,'keep source annotation')")
        conn.commit(); conn.close()
        self.database_hash = files.digest_file(self.original_db)
        self.destination = self.root / 'Gewu' / 'data'
        self.storage = Storage(self.destination / 'paper_monitor.sqlite')
        store.initialize(self.storage)
        self.patches = [patch.object(ui, name, self.destination / name) for name in (
            'LIBRARY_LOCAL_COPY_ROOT', 'SPACES_LOCAL_COPY_ROOT', 'MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'DEFAULT_PDF_DIR', 'ASSOCIATED_FILES_ROOT')]
        for p in self.patches: p.start()
        self.job = store.create(self.storage)
        store.update(self.storage, self.job['id'], state='running', generation='generation',
                     config={'source_id':'zotero:local:test', 'target_id':1, 'library_id':1, 'root_name':'Imported Zotero',
                             'collection_keys':[], 'collections':[{'key':'COLLECT1','name':'Quantum','parent':''}, {'key':'COLLECT2','name':'Reading','parent':'COLLECT1'}]},
                     catalog={'protected_roots':[str(self.source)],'libraries':[]})
        self.job = store.get(self.storage, self.job['id'])
        writer=PdfWriter();writer.add_blank_page(width=612,height=792)
        output=io.BytesIO();writer.write(output);self.pdf=output.getvalue()
        path=self.source/'storage'/'ATTACH01'/'original.pdf';path.parent.mkdir(parents=True);path.write_bytes(self.pdf)
        self.entry={'data':{'key':'PAPER001','itemType':'journalArticle','title':'Synthetic migration paper','DOI':'10.5555/migration.fixture',
                           'publicationTitle':'Fixture Journal','date':'2026','creators':[{'creatorType':'author','firstName':'Jane','lastName':'Smith'}],
                           'collections':['COLLECT1','COLLECT2'],'tags':[{'tag':'Keep me','type':0}],'citationKey':'Smith2026'},
                    'attachments':[{'key':'ATTACH01','path':str(path),'filename':'original.pdf','contentType':'application/pdf',
                                    'size':len(self.pdf),'mtime':path.stat().st_mtime*1000}],
                    'notes':[{'key':'NOTE0001','title':'Reading note','html':'<h1>Insight</h1><p>Keep this text.</p>','images':[]}], 'warnings':[]}

    def tearDown(self):
        self.assertEqual(files.digest_file(self.original_db),self.database_hash)
        self.storage.close()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def run_import(self, entry=None, exports=None):
        return importer.import_entry(self.storage,self.job,entry or self.entry,exports or {})

    def test_original_database_and_files_unchanged_multiple_collections_share_paper(self):
        original=Path(self.entry['attachments'][0]['path']);before=original.stat()
        result=self.run_import();self.assertEqual(result['issues'],[])
        self.assertEqual(original.read_bytes(),self.pdf)
        self.assertEqual(files.fingerprint(original.stat()),files.fingerprint(before))
        members=self.storage.conn.execute('SELECT * FROM library_items WHERE paper_id=?',(result['paper_id'],)).fetchall()
        self.assertEqual(len(members),2)
        resources=self.storage.list_paper_resources(result['paper_id'],ensure_primary=False)
        self.assertEqual(len(resources),4)
        for resource in resources:
            self.assertTrue(Path(resource['stored_path']).is_file())
            self.assertFalse(Path(resource['stored_path']).is_relative_to(self.source))
        pdf=next(r for r in resources if r['kind']=='pdf')
        self.assertEqual(Path(pdf['stored_path']).read_bytes(),self.pdf)
        self.assertNotEqual(Path(pdf['stored_path']).stat().st_ino,original.stat().st_ino)
        text='\n'.join(Path(r['stored_path']).read_text() for r in resources if r['kind']=='md')
        self.assertIn('Keep me',text);self.assertIn('Smith2026',text);self.assertIn('Keep this text.',text)

    def test_connect_handoff_is_private_and_does_not_steal_the_import_window(self):
        support=self.root/'support'
        with patch.object(http.subprocess,'run') as launch:
            http.launch(self.storage,self.job,'http://127.0.0.1:8879',support=support)
        config=support/'zotero-import-connection.json'
        self.assertEqual(config.stat().st_mode & 0o777,0o600)
        value=json.loads(config.read_text());self.assertNotIn('token',value)
        self.assertEqual(value['job_id'],self.job['id']);self.assertEqual(len(value['generation']),48)
        self.assertEqual(launch.call_args.args[0][:4],['/usr/bin/open','-g','-a','/Applications/Zotero.app'])

    def test_retry_and_changed_external_filename_reuse_identity_and_files(self):
        first=self.run_import();second=self.run_import()
        self.assertEqual(first['gewu_key'],second['gewu_key']);self.assertEqual(first['files'],second['files'])
        moved=copy.deepcopy(self.entry);original=Path(moved['attachments'][0]['path']);new=original.with_name('renamed.pdf')
        original.rename(new);moved['attachments'][0].update(path=str(new),filename=new.name,mtime=new.stat().st_mtime*1000)
        third=self.run_import(moved)
        self.assertEqual(first['files'],third['files']);self.assertEqual(third['issues'],[])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)

    def test_existing_manual_metadata_and_default_retained(self):
        first=self.run_import();pid=first['paper_id']
        default=self.storage.resolve_default_paper_resource(pid)
        self.storage.set_preferred_paper_resource(pid,default['id'])
        self.storage.conn.execute("UPDATE papers SET title='My edited title' WHERE paper_id=?",(pid,));self.storage.conn.commit()
        entry=copy.deepcopy(self.entry);extra=self.source/'linked.pdf';extra.write_bytes(self.pdf+b'\n% distinct bytes')
        entry['attachments'].append({'key':'ATTACH02','path':str(extra),'filename':'second.pdf','size':extra.stat().st_size})
        second=self.run_import(entry)
        self.assertEqual(second['issues'],[])
        self.assertEqual(self.storage.get_paper(pid)['title'],'My edited title')
        self.assertEqual(self.storage.resolve_default_paper_resource(pid)['id'],default['id'])
        self.assertTrue(extra.exists())

    def test_unrelated_existing_identity_conflict_does_not_attach(self):
        self.storage.upsert_paper({'paper_id':'existing','doi':self.entry['data']['DOI'],'title':'Completely different experimental subject',
                                  'journal':'Unrelated Journal','raw':{'authors':['Some Other Person']}})
        with self.assertRaises(ValueError):self.run_import()
        self.assertEqual(self.storage.list_paper_resources('existing',ensure_primary=False),[])

    def test_missing_file_keeps_metadata_and_explains_incomplete_copy(self):
        entry=copy.deepcopy(self.entry);entry['attachments'][0].update(path='',missing='Attachment is not downloaded.')
        result=self.run_import(entry)
        self.assertIn('Attachment is not downloaded.',result['issues'])
        self.assertEqual(self.storage.get_paper(result['paper_id'])['title'],self.entry['data']['title'])

    def test_changed_source_is_not_imported_or_overwritten(self):
        path=Path(self.entry['attachments'][0]['path']);path.write_bytes(b'changed bytes')
        result=self.run_import()
        self.assertTrue(any('changed after preview' in m for m in result['issues']))
        self.assertEqual(path.read_bytes(),b'changed bytes')
        self.assertFalse(any(r['kind']=='pdf' for r in self.storage.list_paper_resources(result['paper_id'],ensure_primary=False)))

    def test_pausing_mid_copy_cleans_only_new_copy(self):
        path=self.source/'large.bin';path.write_bytes(b'a'*3*1024*1024);digest=files.digest_file(path)
        directory=self.destination/'copies';directory.mkdir();sentinel=directory/'sentinel.bin';sentinel.write_bytes(b'keep')
        calls=[0]
        def stop():
            calls[0]+=1
            if calls[0]==2:raise files.Paused()
        with self.assertRaises(files.Paused):files.copy_verified(self.storage,self.job['id'],path,directory,check=stop)
        self.assertEqual(list(directory.iterdir()),[sentinel]);self.assertEqual(files.digest_file(path),digest)

    def test_changed_during_copy_not_registered(self):
        path=self.source/'large.bin';path.write_bytes(b'a'*3*1024*1024)
        calls=[0]
        def mutate():
            calls[0]+=1
            if calls[0]==1:
                with path.open('ab') as stream:stream.write(b'new data')
        with self.assertRaises(ValueError):files.copy_verified(self.storage,self.job['id'],path,self.destination/'copies',check=mutate)
        self.assertTrue(path.read_bytes().endswith(b'new data'))

    def test_same_filename_never_overwrites_existing_destination(self):
        folder=self.destination/'collision';folder.mkdir();sentinel=folder/'original.pdf';sentinel.write_bytes(b'keep')
        result=files.copy_verified(self.storage,self.job['id'],self.entry['attachments'][0]['path'],folder)
        self.assertEqual(sentinel.read_bytes(),b'keep');self.assertNotEqual(result['path'],sentinel)
        files.discard(self.storage,result)

    def test_recovery_retains_registered_file_and_replacement_inode(self):
        folder=self.destination/'recovery'
        result=files.copy_verified(self.storage,self.job['id'],self.entry['attachments'][0]['path'],folder)
        target=result['path'];target.unlink();target.write_bytes(b'unrelated replacement')
        files.recover(self.storage,self.job['id']);self.assertEqual(target.read_bytes(),b'unrelated replacement')
        first=self.run_import();resource=self.storage.get_paper_resource(first['files'][0]);path=Path(resource['stored_path']);st=path.stat()
        self.storage.conn.execute('INSERT INTO zotero_import_copies VALUES(?,?,?,?,?,?,?,?)',('test',self.job['id'],str(path),st.st_dev,st.st_ino,'',resource['id'],0));self.storage.conn.commit()
        files.recover(self.storage,self.job['id']);self.assertTrue(path.exists())

    def test_destination_inside_zotero_rejected(self):
        with patch.object(ui,'LIBRARY_LOCAL_COPY_ROOT',self.source/'forbidden'):
            result=self.run_import()
        self.assertTrue(result['issues']);self.assertFalse((self.source/'forbidden').exists())

    def test_metadata_only_and_standalone_note_need_no_fake_doi(self):
        entry={'data':{'key':'NOTE0002','itemType':'note','note':'<p>Standalone note</p>'},'attachments':[],
               'notes':[{'key':'NOTE0002','title':'Standalone note','html':'<p>Original thought</p>','images':[]}]}
        result=self.run_import(entry);self.assertEqual(result['issues'],[])
        self.assertFalse(self.storage.get_paper(result['paper_id'])['doi'])
        self.assertEqual(len(result['files']),3)

    def test_removed_imported_file_is_not_resurrected_on_retry(self):
        result=self.run_import();resource=next(r for r in self.storage.list_paper_resources(result['paper_id']) if r['kind']=='pdf')
        Path(resource['stored_path']).unlink()
        repeated=self.run_import()
        self.assertTrue(any('not be restored automatically' in m for m in repeated['issues']))

    def test_annotated_export_and_original_remain_separate_files(self):
        path=self.destination/'annotations.pdf';path.write_bytes(self.pdf+b'\n% annotation copy')
        exports={'attachments':[{'key':'ATTACH01:annotated','path':str(path),'filename':'Annotated.pdf','annotated':True,'annotation_count':2}]}
        result=self.run_import(exports=exports)
        resources=self.storage.list_paper_resources(result['paper_id'],ensure_primary=False)
        self.assertEqual(len([r for r in resources if r['kind']=='pdf']),2)
        self.assertEqual(Path(self.entry['attachments'][0]['path']).read_bytes(),self.pdf)

    def test_annotation_export_random_ids_do_not_duplicate_unchanged_annotations(self):
        path=self.destination/'annotations.pdf';path.write_bytes(self.pdf+b'\n% export ID1')
        exports={'attachments':[{'key':'ATTACH01:annotated','path':str(path),'filename':'Annotated.pdf','annotated':True}]}
        first=self.run_import(exports=exports)
        path.write_bytes(self.pdf+b'\n% export ID2')
        repeated=self.run_import(exports=exports)
        self.assertEqual(first['files'],repeated['files']);self.assertEqual(repeated['issues'],[])
        changed=copy.deepcopy(self.entry);changed['attachments'][0]['annotations']=[{'comment':'A new annotation'}]
        updated=self.run_import(changed,exports)
        self.assertEqual(len(updated['files']),len(first['files'])+1)
        self.assertEqual(len(self.storage.list_paper_resources(first['paper_id'])),len(first['files'])+2) # old annotated copy retained

    def test_same_size_source_revision_is_preserved_as_a_new_file(self):
        first=self.run_import();path=Path(self.entry['attachments'][0]['path'])
        path.write_bytes(self.pdf.replace(b'PDF-',b'pdf-',1))
        changed=copy.deepcopy(self.entry);changed['attachments'][0]['mtime']=path.stat().st_mtime*1000
        result=self.run_import(changed)
        self.assertEqual(result['issues'],[]);self.assertEqual(len(result['files']),len(first['files']))
        self.assertEqual(len(self.storage.list_paper_resources(first['paper_id'])),len(first['files'])+1)

    def test_snapshot_archive_is_deterministic_and_rejects_escape_paths(self):
        item=dict(self.entry['attachments'][0],relative='nested/original.pdf')
        source={'snapshot_files':[item]}
        first=archives.snapshot(self.destination,source,lambda:None);second=archives.snapshot(self.destination,source,lambda:None)
        self.assertEqual(files.digest_file(first),files.digest_file(second))
        item['relative']='../escape.pdf'
        with self.assertRaises(ValueError):archives.snapshot(self.destination,source,lambda:None)

    def test_changed_note_image_not_silently_accepted(self):
        image=self.source/'image.png';image.write_bytes(b'image before')
        note={'html':'<p>Keep the original</p>','images':[{'path':str(image),'size':12,'contentType':'image/png','mtime':image.stat().st_mtime*1000}]}
        image.write_bytes(b'changed image')
        with self.assertRaises(ValueError):importer.readable_note(note)

    def test_layout_never_moves_another_items_linked_source(self):
        first=self.run_import();original=self.root/'external-source.pdf';original.write_bytes(self.pdf+b' other source')
        resource=self.storage.create_paper_resource(paper_id=first['paper_id'],stored_path=str(original),source_path=str(original),storage_mode='managed',file_type='unknown')
        self.storage.conn.execute('INSERT INTO zotero_import_sources VALUES(?,?)',(self.job['id'],str(original.resolve())));self.storage.conn.commit()
        result=self.run_import()
        self.assertTrue(original.is_file());self.assertEqual(self.storage.resource_local_path(self.storage.get_paper_resource(resource['id'])),str(original))
        self.assertTrue(any('location was preserved' in issue for issue in result['issues']))

    def test_existing_external_link_is_kept_but_migration_gets_independent_copy(self):
        incoming=importer.payload(self.entry);self.storage.upsert_paper(incoming)
        original=Path(self.entry['attachments'][0]['path'])
        linked=self.storage.create_paper_resource(paper_id=incoming['paper_id'],stored_path=str(original),storage_mode='linked')
        result=self.run_import();self.assertEqual(result['issues'],[])
        resources=self.storage.list_paper_resources(incoming['paper_id'])
        copies=[r for r in resources if r['kind']=='pdf' and r['id']!=linked['id']]
        self.assertEqual(len(copies),1);self.assertEqual(Path(copies[0]['stored_path']).read_bytes(),self.pdf)
        self.assertTrue(original.exists());self.assertEqual(self.storage.get_paper_resource(linked['id'])['storage_mode'],'linked')


class MigrationHTTPTests(unittest.TestCase):
    def setUp(self):
        from tests.test_ai_access import AIAccessTests
        AIAccessTests.setUp(self)
    def tearDown(self):
        from tests.test_ai_access import AIAccessTests
        AIAccessTests.tearDown(self)
    def request(self,*args,**kwargs):
        from tests.test_ai_access import AIAccessTests
        return AIAccessTests.request(self,*args,**kwargs)

    def test_page_cannot_inject_source_paths_and_mcp_cannot_use_import(self):
        self.assertEqual(self.request('/api/zotero-import',{'action':'connect'},token=self.token)[0],401)
        cookie=self.server.workspace_access.cookie().split(';',1)[0]
        code,_,_=self.request('/api/zotero-import/host',{'action':'entries','entries':[]},headers={'Cookie':cookie})
        self.assertEqual(code,403)
        self.assertEqual(self.request('/zotero-import.js',workspace=True)[0],200)

    def test_preview_is_non_importing_and_pause_is_resumable(self):
        with patch.object(http,'launch',lambda storage,job,origin:store.update(storage,job['id'],generation='generation')):
            code,job,_=self.request('/api/zotero-import',{'action':'connect'},workspace=True)
        self.assertEqual(code,200,job);job_id=job['id']
        catalog={'protocol':1,'protected_roots':[],'libraries':[{'id':1,'source_id':'zotero:test','name':'Test library','collections':[]}]}
        def host(action,**extra):return self.request('/api/zotero-import/host',{'action':action,'id':job_id,'generation':'generation',**extra},workspace=True)
        self.assertEqual(host('hello',catalog=catalog)[0],200)
        self.assertEqual(self.request('/api/zotero-import',{'action':'scan','id':job_id,'source_id':'zotero:test','target_id':1},workspace=True)[0],200)
        self.assertEqual(host('next')[1]['command'],'scan')
        before=self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0]
        entry={'data':{'key':'ITEM0001','title':'Metadata only','itemType':'journalArticle'},'attachments':[],'notes':[]}
        self.assertEqual(host('entries',entries=[entry])[0],200)
        self.assertEqual(host('scanned')[0],200)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],before)
        self.assertEqual(self.request('/api/zotero-import',{'action':'start','id':job_id},workspace=True)[0],200)
        command=host('next')[1];self.assertEqual(command['command'],'export')
        self.assertEqual(self.request('/api/zotero-import',{'action':'pause','id':job_id},workspace=True)[1]['state'],'paused')
        self.assertTrue(host('apply',key='ITEM0001',lease=command['lease'],exports={})[1]['stop'])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],before)
        self.assertEqual(self.request('/api/zotero-import',{'action':'start','id':job_id},workspace=True)[0],200)
        fresh=host('next')[1];self.assertNotEqual(fresh['lease'],command['lease'])
        self.assertTrue(host('apply',key='ITEM0001',lease=command['lease'],exports={})[1]['stop'])
        command=fresh
        self.assertEqual(host('apply',key='ITEM0001',lease=command['lease'],exports={})[1]['state'],'done')
        self.assertEqual(host('next')[1]['state'],'complete')
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],before+1)

    def test_empty_collection_preserved_and_disconnected_start_is_blocked(self):
        store.initialize(self.storage);job=store.create(self.storage)
        store.update(self.storage,job['id'],state='ready',config={'source_id':'zotero:test','library_id':1,'target_id':1,'root_name':'Empty import','collections':[{'key':'EMPTY001','name':'Empty folder','parent':''}]})
        self.assertEqual(self.request('/api/zotero-import',{'action':'start','id':job['id']},workspace=True)[0],400)
        store.update(self.storage,job['id'],adapter_seen=time.time())
        self.assertEqual(self.request('/api/zotero-import',{'action':'start','id':job['id']},workspace=True)[0],200)
        self.assertTrue(self.storage.conn.execute("SELECT 1 FROM library_folders WHERE name='Empty folder'").fetchone())


if __name__=='__main__':unittest.main()
