"""Synthetic-only external write -> bounded workspace snapshot regressions."""
import unittest
from unittest.mock import patch
from paper_monitor import library_live, ui_server
from tests import test_ai_writes as fixture


class LibraryLiveTests(unittest.TestCase):
    setUp = fixture.AIWriteTests.setUp
    tearDown = fixture.AIWriteTests.tearDown
    request = fixture.AIWriteTests.request
    call = fixture.AIWriteTests.call
    enable_writes = fixture.AIWriteTests.enable_writes
    upload = fixture.AIWriteTests.upload
    metadata = fixture.AIWriteTests.metadata
    import_args = fixture.AIWriteTests.import_args

    def poll(self, **kwargs):
        return library_live.changes(self.storage, **kwargs)

    def test_import_and_analysis_appear_without_reopening_or_global_papers(self):
        cursor = self.poll(folder_ids=[1])['cursor']
        token = self.enable_writes()
        status, space, _ = self.call('create_space', {'name':'Live space','request_id':'live-space-001'}, token)
        self.assertEqual(status,200,space)
        status, folder, _ = self.call('create_folder', {'parent_id':space['folder_id'],'name':'Readout','request_id':'live-folder-001'}, token)
        self.assertEqual(status,200,folder)
        update = self.poll(since=cursor,folder_ids=[space['folder_id']])
        self.assertTrue(update['changed'])
        self.assertTrue(any(t['root_folder_id']==space['folder_id'] for t in update['workspace_tabs']))
        self.assertEqual(update['children'][0]['folders'][0]['name'],'Readout')
        cursor = update['cursor']
        args = self.import_args(self.upload(token));args['folder_id']=folder['folder_id']
        status, paper, _ = self.call('import_paper',args,token)
        self.assertEqual(status,200,paper)
        pid=self.storage.paper_for_key(paper['gewu_key'])['paper_id']
        with patch.object(self.storage,'list_library_items',side_effect=AssertionError('No global paper reload')):
            update=self.poll(since=cursor,folder_ids=[folder['folder_id']],paper_id=pid)
        self.assertEqual(update['children'][0]['items'][0]['paper_id'],pid)
        cursor=update['cursor']
        # Separate existing analysis permission; the write connection is not broadened.
        status,note,_=self.call('save_analysis',{'gewu_key':self.key,'title':'Fresh note','markdown':'# Analysis','request_id':'live-note-001'})
        self.assertEqual(status,200,note)
        update=self.poll(since=cursor,folder_ids=[1],paper_id='one')
        self.assertIn(note['file']['file_id'],[f['id'] for f in update['paper_files'][0]['files']])

    def test_no_change_reads_denials_and_uploads_do_not_reload(self):
        cursor=self.poll()['cursor']
        self.call('get_paper',{'gewu_key':self.key})
        self.call('save_analysis',{'gewu_key':self.other_key,'title':'Denied','markdown':'x','request_id':'live-deny-001'})
        with patch.object(ui_server,'library_navigation_snapshot',side_effect=AssertionError('No snapshot for reads')):
            result=self.poll(since=cursor,folder_ids=[1])
            self.assertFalse(result['changed'])
            self.assertEqual(set(result),{'cursor','changed'})
            self.assertFalse(self.poll(since=result['cursor'])['changed'])

    def test_cursor_gap_reset_and_bad_input(self):
        initial=self.poll()['cursor']
        for i in range(3): self.call('get_paper',{'gewu_key':self.key})
        self.storage.conn.execute('DELETE FROM ai_audit WHERE id < (SELECT MAX(id) FROM ai_audit)');self.storage.conn.commit()
        self.assertTrue(self.poll(since=initial)['changed'])
        self.assertTrue(self.poll(since='9223372036854775806')['changed'])
        for args in ({'since':'-1'}, {'since':'not-an-id'}, {'folder_ids':range(65)}, {'folder_ids':['../secret']}, {'paper_id':'x'*301}):
            with self.assertRaises(ValueError): self.poll(**args)

    def test_endpoint_requires_workspace_not_mcp_grant_and_validates_bounds(self):
        url='/api/library/changes?folder_id=1&paper_id=one'
        for token in (None,self.token): self.assertEqual(self.request(url,token=token)[0],401)
        self.assertEqual(self.request(url,workspace=True)[0],200)
        self.assertEqual(self.request('/api/library/changes?since=bad',workspace=True)[0],400)
