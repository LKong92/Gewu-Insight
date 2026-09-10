import unittest
from tests import test_ai_access as fixtures


class FileReassignmentApiTests(unittest.TestCase):
    setUp=fixtures.AIAccessTests.setUp
    tearDown=fixtures.AIAccessTests.tearDown
    request=fixtures.AIAccessTests.request
    call=fixtures.AIAccessTests.call

    def test_ui_move_preserves_file_id_and_enforces_mcp_boundaries(self):
        for query in ('Quantum two', self.other_key):
            from urllib.parse import quote
            status, found, _ = self.request('/api/library/search?q=' + quote(query), workspace=True)
            self.assertEqual(status, 200)
            self.assertIn(self.other_key, [r['item']['paper']['storage_key'] for r in found['results']])
        args={'paper_id':'one','resource_id':self.pdf['id'],'target_key':self.other_key}
        self.assertEqual(self.request('/api/paper-files/reassign',args,token=self.token)[0],401)
        self.assertEqual(self.call('reassign',args)[0],404)
        status,body,_=self.request('/api/paper-files/reassign',args,workspace=True)
        self.assertEqual(status,200,body)
        self.assertEqual(body['reassignment']['resource_id'],self.pdf['id'])
        self.assertEqual(body['reassignment']['target_gewu_key'],self.other_key)
        self.assertEqual(self.storage.get_paper_resource(self.pdf['id'])['paper_id'],'two')
        self.assertEqual(self.call('get_paper',{'gewu_key':self.key})[1]['files'],[])
        self.assertEqual(self.call('read_paper',{'gewu_key':self.key,'file_id':self.pdf['id']})[0],404)
        self.assertEqual(self.request('/api/paper-files/reassign',args,workspace=True)[0],400)

    def test_moved_analysis_receipt_cannot_expose_out_of_scope_file(self):
        args={'gewu_key':self.key,'markdown':'# Fixture note','request_id':'note-before-moving'}
        status,saved,_=self.call('save_analysis',args)
        self.assertEqual(status,200)
        status,_,_=self.request('/api/paper-files/reassign',{'paper_id':'one','resource_id':saved['file']['file_id'],
            'target_key':self.other_key},workspace=True)
        self.assertEqual(status,200)
        status,error,_=self.call('save_analysis',args)
        self.assertEqual(status,410,error)
        self.assertNotIn('file',error)
