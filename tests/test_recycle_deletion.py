import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from paper_monitor import finder_alias
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from paper_monitor import ui_server as ui
from paper_monitor.recycle import delete_recycle_selection, preview_recycle_selection
from paper_monitor.storage import Storage


class RecycleDeletionTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.storage = Storage(self.root / 'fixture.sqlite'); self.addCleanup(self.storage.close)
        for name in ('LIBRARY_LOCAL_COPY_ROOT', 'MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'SPACES_LOCAL_COPY_ROOT', 'ASSOCIATED_FILES_ROOT', 'DEFAULT_PDF_DIR', 'DEFAULT_LIBRARY_IMPORT_DIR'):
            target = self.root / name; target.mkdir()
            p = patch.object(ui, name, target); p.start(); self.addCleanup(p.stop)
        self.recycle = ui.ensure_library_special_folders(self.storage)['recycle']['id']
        self.directory = ui.local_copy_dir_for_library_folder(self.storage, self.recycle)
        self.directory.mkdir(parents=True)
        self.trash = self.root / 'Trash'; self.trash.mkdir()
        self.moves = []
        def move(path):
            target = self.trash / path.name
            self.assertFalse(os.path.lexists(target))
            shutil.move(path, target); self.moves.append((path, target)); return target
        p = patch.object(ui, 'move_path_to_macos_trash', side_effect=move)
        self.move = p.start(); self.addCleanup(p.stop)
        if __import__('sys').platform == 'win32':
            from paper_monitor import windows_recycle
            p = patch.object(windows_recycle, 'recycle_file', side_effect=lambda path: self.move(path))
            p.start(); self.addCleanup(p.stop)
            p = patch.object(windows_recycle, 'restore_shell_item', side_effect=lambda receipt, path: shutil.move(receipt, path))
            p.start(); self.addCleanup(p.stop)

    def folder(self, name, parent=None):
        f = self.storage.create_library_folder(parent_id=parent or self.recycle, name=name)
        path = ui.local_copy_dir_for_library_folder(self.storage, f['id']); path.mkdir(parents=True, exist_ok=True)
        return f['id'], path

    def paper(self, pid, folder, file=None):
        self.storage.upsert_paper({'paper_id':pid,'title':pid,'journal':'Fixture','source':'fixture'})
        item = self.storage.add_library_item(paper_id=pid, folder_id=folder)
        if file:
            file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(b'fixture '+pid.encode())
            r = self.storage.create_paper_resource(paper_id=pid, stored_path=str(file), file_type='preprint', annotation_state='annotated', file_source='author', display_name='Custom label')
            self.storage.conn.execute("UPDATE papers SET main_pdf_path=?,merged_pdf_path=?,primary_resource_id=?,preferred_resource_id=?,preferred_resource_manual=1 WHERE paper_id=?", (str(file),str(file),r['id'],r['id'],pid))
            self.storage.conn.commit()
        return item

    def delete(self, entries=None, empty=False):
        return delete_recycle_selection(self.storage, entries or [], recycle_id=self.recycle, empty=empty, confirmed=True)

    def rows(self):
        return {table:[tuple(r) for r in self.storage.conn.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in ('papers','resources','library_items','library_folders')}

    def tree(self, root):
        result = {}
        for directory, folders, files in os.walk(root, followlinks=False):
            for name in folders+files:
                p=Path(directory)/name
                result[str(p.relative_to(root))] = ('link',os.readlink(p)) if p.is_symlink() else ('dir',) if p.is_dir() else ('file',p.read_bytes())
        return result

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_folder_moves_intact_including_unregistered_files_empty_dirs_and_dangling_links(self):
        fid, folder = self.folder('Selected')
        self.paper('a',fid,folder/'sub'/'paper.pdf')
        (folder/'notes.txt').write_text('unregistered original note')
        (folder/'empty').mkdir(); (folder/'lost.pdf').symlink_to(self.root/'missing.pdf')
        before = self.tree(folder)
        result = self.delete([{'type':'folder','id':fid}])
        self.assertEqual(len(self.moves),1); self.assertEqual(self.moves[0][0],folder)
        self.assertEqual(self.tree(self.trash/'Selected'),before)
        self.assertFalse(folder.exists()); self.assertIsNone(self.storage.get_paper('a'))
        self.assertEqual(result['cleanup']['cleaned_papers'],['a'])
        self.assertEqual(list(self.storage.conn.execute('PRAGMA foreign_key_check')),[])

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_empty_clears_ui_and_every_disk_child_preserving_recycle_root(self):
        self.paper('a',self.recycle)
        fid, folder = self.folder('Registered'); self.paper('b',fid,folder/'file.pdf')
        (self.directory/'old-empty').mkdir()
        (self.directory/'.hidden').write_text('orphan')
        (self.directory/'orphan.bin').write_bytes(b'anything')
        (self.directory/'broken.pdf').symlink_to(self.root/'missing.pdf')
        before = self.tree(self.directory)
        result = self.delete(empty=True)
        self.assertEqual(list(self.directory.iterdir()),[])
        self.assertEqual(self.tree(self.trash),before)
        self.assertTrue(self.storage.get_library_folder(self.recycle))
        self.assertEqual(result['removed'],{'items':2,'folders':1})
        self.assertIsNone(self.storage.get_paper('a')); self.assertIsNone(self.storage.get_paper('b'))
        self.assertEqual(list(self.storage.conn.execute('PRAGMA foreign_key_check')),[])

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_surviving_library_reference_keeps_key_ids_classification_default_and_bytes(self):
        fid, folder = self.folder('Selected'); source = folder/'paper.pdf'
        self.paper('a',fid,source)
        survivor, outside = self.folder('Keep',1)
        self.storage.add_library_item(paper_id='a',folder_id=survivor)
        alias = outside/'paper.pdf'; alias.symlink_to(source)
        before = self.storage.get_paper('a'); resource = dict(self.storage.conn.execute('SELECT * FROM resources').fetchone())
        original = self.tree(folder)
        self.delete([{'type':'folder','id':fid}])
        after = self.storage.get_paper('a'); kept = Path(after['merged_pdf_path'])
        self.assertTrue(kept.is_file()); self.assertNotIn('Recycle',kept.parts)
        self.assertEqual(kept.read_bytes(),b'fixture a'); self.assertEqual(finder_alias.resolve(alias).read_bytes(),b'fixture a')
        self.assertEqual(self.tree(self.trash/'Selected'),original)
        for field in ('storage_key','primary_resource_id','preferred_resource_id','preferred_resource_manual'):
            self.assertEqual(after[field],before[field])
        registered = dict(self.storage.conn.execute('SELECT * FROM resources').fetchone())
        for field in resource:
            if field != 'stored_path':self.assertEqual(registered[field],resource[field],field)
        self.assertEqual(registered['stored_path'],str(kept))
        self.assertEqual(len(self.storage.conn.execute('SELECT * FROM library_items WHERE paper_id="a"').fetchall()),1)

    def test_my_publications_reference_retains_paper_when_recycle_is_emptied(self):
        source=self.directory/'p.pdf'; self.paper('a',self.recycle,source)
        self.storage.add_my_publication(paper_id='a')
        self.delete(empty=True)
        paper=self.storage.get_paper('a')
        self.assertTrue(paper); self.assertTrue(Path(paper['merged_pdf_path']).is_file())
        self.assertEqual(list(self.directory.iterdir()),[])
        self.assertEqual(len(self.storage.list_my_publications()),1)

    def test_another_recycle_placement_is_still_a_reference_for_selected_folder_delete(self):
        fid,folder=self.folder('Selected'); self.paper('a',fid,folder/'p.pdf')
        other,outside=self.folder('Keep'); self.storage.add_library_item(paper_id='a',folder_id=other)
        self.delete([{'type':'folder','id':fid}])
        paper=self.storage.get_paper('a'); self.assertTrue(Path(paper['merged_pdf_path']).is_file())
        self.assertEqual(Path(paper['merged_pdf_path']).parent,outside)
        self.assertTrue(self.storage.get_library_folder(other))

    def test_file_shared_with_another_paper_survives_intact_directory_delete(self):
        fid,folder=self.folder('Selected'); source=folder/'shared.pdf'
        self.paper('a',fid,source)
        self.storage.upsert_paper({'paper_id':'b','title':'b','journal':'Fixture','source':'fixture'})
        r=self.storage.create_paper_resource(paper_id='b',stored_path='',source_path=str(source),display_name='Shared')
        self.delete([{'type':'folder','id':fid}])
        self.assertIsNone(self.storage.get_paper('a'));self.assertIsNotNone(self.storage.get_paper('b'))
        saved=dict(self.storage.conn.execute('SELECT * FROM resources WHERE id=?',(r['id'],)).fetchone())
        self.assertEqual(Path(saved['source_path']).read_bytes(),b'fixture a')
        self.assertEqual((self.trash/'Selected'/'shared.pdf').read_bytes(),b'fixture a')

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_symlinks_never_delete_external_target_files_or_directories(self):
        outside=self.root/'outside';outside.mkdir();(outside/'original.txt').write_text('keep')
        (self.directory/'dir-link').symlink_to(outside,target_is_directory=True)
        (self.directory/'file-link').symlink_to(outside/'original.txt')
        (self.directory/'broken').symlink_to(outside/'missing')
        self.delete(empty=True)
        self.assertEqual((outside/'original.txt').read_text(),'keep')
        self.assertEqual(len(list(self.trash.iterdir())),3)
        self.assertTrue(all(p.is_symlink() for p in self.trash.iterdir()))

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_sql_failure_rolls_back_folder_and_surviving_references(self):
        fid,folder=self.folder('Selected');self.paper('a',fid,folder/'p.pdf')
        self.paper('b',fid,folder/'b.pdf')
        survivor,outside=self.folder('Keep',1);self.storage.add_library_item(paper_id='b',folder_id=survivor)
        (outside/'b.pdf').symlink_to(folder/'b.pdf')
        self.storage.conn.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON papers BEGIN SELECT RAISE(ABORT,'fixture SQL failure'); END")
        self.storage.conn.commit();before=self.rows();tree=self.tree(ui.LIBRARY_LOCAL_COPY_ROOT)
        with self.assertRaises(sqlite3.IntegrityError):self.delete([{'type':'folder','id':fid}])
        self.assertEqual(self.rows(),before);self.assertEqual(self.tree(ui.LIBRARY_LOCAL_COPY_ROOT),tree)
        self.assertEqual(list(self.trash.iterdir()),[])

    def test_later_trash_failure_rolls_back_all_earlier_moves_and_records(self):
        for name in ('A','B'):
            fid,folder=self.folder(name);self.paper(name,fid,folder/'p.pdf')
        before=self.rows();tree=self.tree(self.directory);real=self.move.side_effect
        def failing(path):
            if self.moves:raise PermissionError('fixture refusal')
            return real(path)
        self.move.side_effect=failing
        with self.assertRaises(PermissionError):self.delete(empty=True)
        self.assertEqual(self.rows(),before);self.assertEqual(self.tree(self.directory),tree)
        self.assertEqual(list(self.trash.iterdir()),[])

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_missing_historical_pdf_does_not_block_empty(self):
        self.paper('a',self.recycle,self.directory/'missing.pdf');(self.directory/'missing.pdf').unlink()
        (self.directory/'stale-link').symlink_to(self.directory/'missing.pdf')
        self.delete(empty=True)
        self.assertIsNone(self.storage.get_paper('a'));self.assertEqual(list(self.directory.iterdir()),[])

    def test_preview_covers_intact_folders_and_disk_only_entries(self):
        folder=self.directory/'unregistered';folder.mkdir();(folder/'notes.txt').write_text('notes')
        result=preview_recycle_selection(self.storage,[],recycle_id=self.recycle,empty=True)
        self.assertTrue(result['requires_confirmation']);self.assertEqual(result['folder_paths'],[str(folder)])
        self.assertEqual(result['local_copy_paths'],[])
        with self.assertRaises(ValueError):
            delete_recycle_selection(self.storage,[],recycle_id=self.recycle,empty=True)
        self.assertTrue(folder.is_dir());self.move.assert_not_called()

    def test_empty_menu_context_is_root_or_root_blank_only(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node unavailable')
        start=ui.INDEX_HTML.index('    function contextRecycleFolderId(')
        end=ui.INDEX_HTML.index('    function libraryFolderIsWithin(',start)
        js='const state={libraryActiveFolderId:893};function libraryRecycleFolderId(){return 893;}\n'+ui.INDEX_HTML[start:end]+'''
const cases=[[1,'folder',893,893],[893,'',0,893],[893,'folder',100,0],[893,'item',12,0],[100,'',0,0],[1,'',0,0],[100,'item',4,0]];
for(const [parent,type,id,expected] of cases) if(contextRecycleFolderId(parent,type,id)!==expected) throw Error(JSON.stringify([parent,type,id]));
'''
        subprocess.run([node,'-e',js],check=True,capture_output=True,text=True)
        self.assertIn('data-action="delete-recycle-all">Empty Recycle<',ui.INDEX_HTML)

    def test_space_reference_survives_empty_with_identical_file_ids(self):
        self.paper('a',self.recycle,self.directory/'a.pdf')
        space=self.storage.create_library_root_folder(name='Research Space')
        self.storage.add_library_item(paper_id='a',folder_id=space['id'])
        before=dict(self.storage.conn.execute('SELECT * FROM resources').fetchone())
        self.delete(empty=True)
        after=dict(self.storage.conn.execute('SELECT * FROM resources').fetchone())
        self.assertEqual(before['id'],after['id'])
        self.assertTrue(Path(after['stored_path']).is_file())
        self.assertTrue(str(Path(after['stored_path'])).startswith(str(ui.SPACES_LOCAL_COPY_ROOT)))

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_single_item_keeps_paper_used_by_another_recycle_item(self):
        fid,folder=self.folder('Other');source=folder/'a.pdf';self.paper('a',fid,source)
        item=self.storage.add_library_item(paper_id='a',folder_id=self.recycle)
        alias=self.directory/'a.pdf';alias.symlink_to(source)
        self.delete([{'type':'item','id':item['id']}])
        self.assertTrue(source.is_file());self.assertTrue(self.storage.get_paper('a'))
        self.assertTrue((self.trash/'a.pdf').is_symlink())
        self.assertFalse(alias.is_symlink())

    def test_empty_ui_keeps_entries_on_failure_and_refreshes_after_retry(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node unavailable')
        a=ui.INDEX_HTML.index('    async function deleteAllLibraryRecycle(')
        b=ui.INDEX_HTML.index('    function contextRecycleFolderId(',a)
        js='''const assert=require('node:assert/strict');const state={};let failed=true,cleared=0;
function libraryRecycleFolderId(){return 893;}async function previewRecycleDeletion(){return {requires_confirmation:true};}
async function confirmRecycleDeletion(){return true;}async function withLibraryActivityStatus(a,b,action){return action();}
async function fetch(url,options){assert.equal(url,'/api/library/special-folder/clear');assert.equal(JSON.parse(options.body).folder_id,893);return {ok:!failed,json:async()=>failed?{error:'fixture refusal'}:{removed:{items:2,folders:0}}};}
function applyPaperFilesPayloads(){}
function clearLibraryFolderContentsLocal(id){assert.equal(id,893);cleared++;}function clearLibraryRangeSelection(){}
function setLibraryColumnSelection(){}function parentFolderId(){return 1;}function renderLibrary(){}
'''+ui.INDEX_HTML[a:b]+'''
(async()=>{await assert.rejects(deleteAllLibraryRecycle(893),/fixture refusal/);assert.equal(cleared,0);failed=false;await deleteAllLibraryRecycle(893);assert.equal(cleared,1);assert.equal(state.libraryActiveFolderId,893);})().catch(e=>{console.error(e);process.exit(1)});
'''
        subprocess.run([node,'-e',js],check=True,capture_output=True,text=True)

    def handler(self):
        h=ui.PaperMonitorUiHandler.__new__(ui.PaperMonitorUiHandler)
        h.configured_db_path=self.storage.db_path
        h.responses=[];h.errors=[]
        h.send_json=lambda payload:h.responses.append(payload)
        h.send_error_json=lambda status,message:h.errors.append((int(status),message))
        return h

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_empty_api_commits_complete_cleanup_and_reports_retained_default(self):
        self.paper('a',self.recycle,self.directory/'a.pdf')
        keep,outside=self.folder('Keep',1);self.storage.add_library_item(paper_id='a',folder_id=keep)
        before=self.storage.get_paper('a');resource=dict(self.storage.conn.execute('SELECT * FROM resources').fetchone())
        (self.directory/'broken').symlink_to(self.root/'missing')
        h=self.handler();h.handle_clear_library_special_folder({'folder_id':self.recycle,'confirmed':True,'snapshot':False})
        self.assertEqual(h.errors,[]);self.assertEqual(len(h.responses),1)
        p=h.responses[0]['paper_files'][0]
        self.assertEqual(p['storage_key'],before['storage_key']);self.assertEqual(p['default_resource_id'],resource['id'])
        self.assertEqual(p['files'][0]['id'],resource['id'])
        registered=dict(self.storage.conn.execute('SELECT * FROM resources').fetchone())
        for field in resource:
            if field!='stored_path':self.assertEqual(registered[field],resource[field],field)
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_batch_api_rolls_back_first_folder_when_second_move_fails(self):
        entries=[]
        for name in ('A','B'):
            fid,folder=self.folder(name);self.paper(name,fid,folder/'a.pdf');entries.append({'type':'folder','id':fid})
        before=self.rows();tree=self.tree(self.directory);real=self.move.side_effect
        def failing(path):
            if self.moves:raise PermissionError('fixture refusal')
            return real(path)
        self.move.side_effect=failing
        h=self.handler();h.handle_delete_library_entries({'entries':entries,'confirmed':True,'snapshot':False})
        self.assertEqual(h.responses,[]);self.assertEqual(h.errors[0][0],403)
        self.assertEqual(self.rows(),before);self.assertEqual(self.tree(self.directory),tree)

    def test_sql_failure_is_returned_to_ui_with_records_and_files_restored(self):
        self.paper('a',self.recycle,self.directory/'a.pdf')
        self.storage.conn.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON papers BEGIN SELECT RAISE(ABORT,'fixture SQL failure'); END")
        self.storage.conn.commit();before=self.rows()
        h=self.handler();h.handle_clear_library_special_folder({'folder_id':self.recycle,'confirmed':True,'snapshot':False})
        self.assertEqual(h.responses,[]);self.assertIn('fixture SQL failure',h.errors[0][1])
        self.assertEqual(self.rows(),before);self.assertTrue((self.directory/'a.pdf').is_file())
