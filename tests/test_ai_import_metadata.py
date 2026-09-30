"""Metadata-only paper imports over MCP/HTTP, using disposable records and files."""
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import ai_uploads, mcp_server, ui_server as ui
from paper_monitor.download import paper_download_lock
from tests import test_ai_import_existing as fixture


class AIMetadataImportTests(unittest.TestCase):
    setUp = fixture.AIImportExistingTests.setUp
    tearDown = fixture.AIImportExistingTests.tearDown
    request = fixture.AIImportExistingTests.request
    call = fixture.AIImportExistingTests.call
    enable_writes = fixture.AIImportExistingTests.enable_writes
    upload = fixture.AIImportExistingTests.upload
    metadata = fixture.AIImportExistingTests.metadata
    import_args = fixture.AIImportExistingTests.import_args
    cached = fixture.AIImportExistingTests.cached
    monitor_pdf = fixture.AIImportExistingTests.monitor_pdf

    def args(self, **extra):
        return dict(folder_id=1, metadata=self.metadata(), request_id='metadata-import-001', **extra)

    def test_new_paper_has_key_metadata_placement_and_no_fake_file_or_upload(self):
        token = self.enable_writes(scopes=['papers:read', 'papers:import', 'folders:read'])
        before = self.storage.conn.execute('SELECT count(*) FROM resources').fetchone()[0]
        with patch.object(ai_uploads, 'get_upload', side_effect=AssertionError('upload required')), \
             patch.object(ai_uploads, 'consume', side_effect=AssertionError('no upload to consume')), \
             patch.object(ui, 'library_workspace_publication_from_query', side_effect=AssertionError('network lookup')), \
             patch.object(ui, 'extract_identifier_from_pdf_or_title', side_effect=AssertionError('PDF scan')), \
             patch.object(ui, 'refresh_imported_doi_metadata', side_effect=AssertionError('enrichment')):
            status, result, _ = self.call('import_paper', self.args(), token=token)
        self.assertEqual(status, 200, result)
        self.assertTrue(result['gewu_key'].startswith('gw_'))
        self.assertIsNone(result['file']); self.assertNotIn('upload_id', result)
        self.assertEqual(result['item_kind'], 'paper'); self.assertFalse(result['layout_pending'])
        paper = self.storage.paper_for_key(result['gewu_key'])
        for field in ('title', 'journal', 'doi', 'abstract', 'publication_date'):
            self.assertEqual(paper[field], self.metadata()[field])
        self.assertEqual(json.loads(paper['raw_json'])['authors'], self.metadata()['authors'])
        for field in ('main_pdf_path', 'merged_pdf_path', 'primary_resource_id'):
            self.assertFalse(paper.get(field))
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM resources').fetchone()[0], before)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM ai_uploads').fetchone()[0], 0)
        detail = self.call('get_paper', {'gewu_key': result['gewu_key']}, token=token)
        self.assertEqual(detail[0], 200, detail[1]); self.assertEqual(detail[1]['files'], [])
        listing = self.call('list_folder_papers', {'folder_id': 1}, token=token)
        self.assertEqual(listing[0], 200, listing[1]); self.assertIn(result['gewu_key'], json.dumps(listing[1]))

    def test_mcp_schema_and_stdio_accept_paper_without_upload(self):
        client = mcp_server.GewuClient(f'http://127.0.0.1:{self.server.server_port}', self.enable_writes())
        messages = [dict(jsonrpc='2.0', id=1, method='initialize'),
                    dict(jsonrpc='2.0', id=2, method='tools/list'),
                    dict(jsonrpc='2.0', id=3, method='tools/call', params={'name':'import_paper', 'arguments':self.args()})]
        output = io.StringIO()
        try:
            mcp_server.serve(client, io.StringIO('\n'.join(json.dumps(m) for m in messages)+'\n'), output)
        finally:
            client.close()
        replies = [json.loads(line)['result'] for line in output.getvalue().splitlines()]
        tool = next(t for t in replies[1]['tools'] if t['name']=='import_paper')
        self.assertEqual(tool['inputSchema']['required'], ['folder_id', 'metadata', 'request_id'])
        self.assertIn('omit upload_id', replies[0]['instructions'])
        self.assertFalse(replies[2]['isError'], replies[2])
        self.assertIsNone(json.loads(replies[2]['content'][0]['text'])['file'])

    def test_exact_retry_and_new_request_reuse_key_and_membership(self):
        token = self.enable_writes(); args = self.args()
        first = self.call('import_paper', args, token=token)[1]
        for retry in (args, {**args, 'request_id':'metadata-import-002'}):
            status, result, _ = self.call('import_paper', retry, token=token)
            self.assertEqual(status, 200, result)
            self.assertEqual(result['gewu_key'], first['gewu_key'])
            self.assertEqual(result['membership_id'], first['membership_id'])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers WHERE doi=?', (args['metadata']['doi'],)).fetchone()[0], 1)
        changed = {**args, 'metadata':{**args['metadata'], 'title':'Changed'}}
        self.assertEqual(self.call('import_paper', changed, token=token)[1]['code'], 'request_conflict')

    def test_cached_failed_download_reuses_identity_without_read_grant_expansion(self):
        paper, meta = self.cached()
        self.storage.update_download_status(paper['paper_id'], status='failed', message='Temporary network restriction')
        token = self.enable_writes(selection={'kind':'papers', 'keys':[self.key]})
        self.assertEqual(self.call('get_paper', {'gewu_key':paper['storage_key']}, token=token)[0], 404)
        args = self.args(); args['metadata'] = meta
        status, result, _ = self.call('import_paper', args, token=token)
        self.assertEqual(status, 200, result); self.assertEqual(result['gewu_key'], paper['storage_key'])
        self.assertTrue(result['reused_paper'])
        self.assertEqual(self.storage.get_paper(paper['paper_id'])['download_status'], 'failed')
        self.assertEqual(self.call('get_paper', {'gewu_key':paper['storage_key']}, token=token)[0], 200)
        self.assertEqual(self.call('get_paper', {'gewu_key':paper['storage_key']})[0], 404)

    def test_arxiv_only_cache_imports_into_writable_space(self):
        paper, meta = self.cached(source='arxiv', arxiv=True); token = self.enable_writes()
        space = self.call('create_space', {'name':'Topic', 'request_id':'space-metadata-001'}, token=token)[1]
        args = self.args(); args.update(folder_id=space['folder_id'], metadata=meta)
        status, result, _ = self.call('import_paper', args, token=token)
        self.assertEqual(status, 200, result); self.assertEqual(result['gewu_key'], paper['storage_key'])
        self.assertEqual(self.storage.get_library_item(result['membership_id'])['folder_id'], space['folder_id'])

    def test_later_pdf_attachment_and_pdf_reimport_keep_the_key(self):
        token = self.enable_writes(); first = self.call('import_paper', self.args(), token=token)[1]
        upload = self.upload(token)
        status, attached, _ = self.call('add_paper_file', {'gewu_key':first['gewu_key'], 'upload_id':upload['upload_id'],
            'file_type':'published_version', 'request_id':'attach-later-001'}, token=token)
        self.assertEqual(status, 200, attached); self.assertEqual(attached['gewu_key'], first['gewu_key'])
        paper = self.storage.paper_for_key(first['gewu_key'])
        resource = self.storage.resolve_default_paper_resource(paper['paper_id'])
        self.assertEqual(resource['id'], attached['file']['file_id'])
        self.assertEqual(Path(resource['stored_path']).parent.resolve(), ui.LIBRARY_LOCAL_COPY_ROOT.resolve())
        self.assertEqual(Path(resource['stored_path']).read_bytes(), self.pdf_bytes)
        args = self.import_args(self.upload(token, request='later-pdf-upload-002'))
        status, again, _ = self.call('import_paper', args, token=token)
        self.assertEqual(status, 200, again); self.assertEqual(again['gewu_key'], first['gewu_key'])
        self.assertTrue(again['reused_file']); self.assertEqual(again['file']['file_id'], resource['id'])

    def test_metadata_reuse_preserves_existing_manual_default_and_files(self):
        paper, meta = self.cached(); _, resource = self.monitor_pdf(paper)
        ui.set_preferred_paper_file(self.storage, paper['paper_id'], resource['id'])
        token = self.enable_writes(); args = self.args(); args['metadata'] = {**meta, 'title':'Different supplied title'}
        status, result, _ = self.call('import_paper', args, token=token)
        self.assertEqual(status, 200, result); self.assertIsNone(result['file'])
        current = self.storage.resolve_default_paper_resource(paper['paper_id'])
        self.assertEqual(current['id'], resource['id']); self.assertEqual(current['file_type'], 'preprint')
        self.assertEqual(Path(current['stored_path']).read_bytes(), self.pdf_bytes)
        self.assertEqual(Path(current['stored_path']).parent.resolve(), ui.LIBRARY_LOCAL_COPY_ROOT.resolve())
        self.assertEqual(self.storage.get_paper(paper['paper_id'])['title'], paper['title'])

    def test_legacy_cached_pdf_registers_once_without_upload(self):
        paper, _ = self.cached(); self.monitor_pdf(paper, registered=False)
        token = self.enable_writes(); args = self.args()
        for _ in range(2):
            status, result, _ = self.call('import_paper', args, token=token)
            self.assertEqual(status, 200, result)
            self.assertEqual(len(self.storage.list_paper_resources(paper['paper_id'])), 1)

    def test_private_recycle_and_unknown_records_cannot_be_adopted_without_pdf(self):
        token = self.enable_writes(selection={'kind':'papers', 'keys':[self.key]})
        private = self.storage.create_library_root_folder(name='Private')
        recycle = self.storage.create_library_folder(name='Recycle', parent_id=1)
        for index, category in enumerate(('private', 'recycle', 'publication', 'analysis', 'unknown', 'annotated', 'linked', 'edited')):
            with self.subTest(category=category):
                paper, meta = self.cached('private-'+category, source='fixture' if category=='unknown' else 'crossref')
                meta['doi'] = '10.5555/private-'+category
                self.storage.conn.execute('UPDATE papers SET doi=? WHERE paper_id=?', (meta['doi'], paper['paper_id']))
                # Discard the fixture's original DOI identity, keeping a unique exact match.
                self.storage.conn.execute('DELETE FROM paper_identifiers WHERE paper_id=?', (paper['paper_id'],))
                from paper_monitor import paper_identity
                paper_identity.register(self.storage, self.storage.get_paper(paper['paper_id']))
                self.storage.conn.commit()
                if category in ('private', 'recycle'):
                    self.storage.add_library_item(paper_id=paper['paper_id'], folder_id=(private if category=='private' else recycle)['id'])
                elif category=='publication': self.storage.add_my_publication(paper_id=paper['paper_id'])
                elif category=='analysis':
                    self.storage.conn.execute("UPDATE papers SET analysis_path='private.md' WHERE paper_id=?", (paper['paper_id'],)); self.storage.conn.commit()
                elif category in ('annotated', 'linked', 'edited'):
                    path, resource = self.monitor_pdf(paper)
                    if category=='edited': path.write_bytes(self.pdf_bytes+b'\n% edit')
                    else:
                        assignment = "annotation_state='annotated'" if category=='annotated' else "storage_mode='linked'"
                        self.storage.conn.execute('UPDATE resources SET '+assignment+' WHERE id=?', (resource['id'],)); self.storage.conn.commit()
                before = self.storage.get_paper(paper['paper_id'])
                args = self.args(); args.update(metadata=meta, request_id=f'denied-metadata-{index}')
                status, result, _ = self.call('import_paper', args, token=token)
                self.assertEqual(status, 403, result); self.assertEqual(result['code'], 'import_access_required')
                self.assertNotIn(paper['storage_key'], json.dumps(result))
                self.assertEqual(self.storage.get_paper(paper['paper_id']), before)

    def test_operation_and_destination_permissions_still_required(self):
        for token in (self.token, self.enable_writes(roots=[])):
            status, result, _ = self.call('import_paper', self.args(), token=token)
            self.assertEqual(status, 403, result)
        private = self.storage.create_library_root_folder(name='Private')
        args = self.args(); args['folder_id'] = private['id']
        self.assertEqual(self.call('import_paper', args, token=self.enable_writes())[0], 403)

    def test_metadata_validation_and_invalid_upload_do_not_create_shell_as_fallback(self):
        token = self.enable_writes(); before = self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0]
        invalid = [self.args(), self.args(), self.args()]
        invalid[0]['metadata'].pop('authors'); invalid[1]['file_type']='published_version'; invalid[2]['metadata']['doi']='bad'
        for value in (None, '', 'upload_'+'0'*32): invalid.append({**self.args(), 'upload_id':value})
        for args in invalid:
            self.assertNotEqual(self.call('import_paper', args, token=token)[0], 200)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0], before)

    def test_conflicting_identifiers_preserve_both_records(self):
        paper, meta = self.cached(); other, _ = self.cached('other', source='arxiv', arxiv=True)
        args = self.args(); args['metadata'] = {**meta, 'arxiv_id':'2601.01234'}
        status, result, _ = self.call('import_paper', args, token=self.enable_writes())
        self.assertEqual(status, 409, result); self.assertEqual(result['code'], 'identity_conflict')
        self.assertEqual(self.storage.get_paper(paper['paper_id']), paper)
        self.assertEqual(self.storage.get_paper(other['paper_id']), other)

    def test_without_identifiers_only_exact_request_retry_reuses_paper(self):
        token = self.enable_writes(); args = self.args(); args['metadata'].update(doi=None, arxiv_id=None)
        first = self.call('import_paper', args, token=token)[1]
        again = self.call('import_paper', args, token=token)[1]
        self.assertEqual(first['gewu_key'], again['gewu_key'])
        args['request_id'] = 'unidentified-paper-002'
        separate = self.call('import_paper', args, token=token)[1]
        self.assertNotEqual(first['gewu_key'], separate['gewu_key'])

    def test_receipt_failure_rolls_back_new_paper_and_placement(self):
        token = self.enable_writes(); before = self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0]
        self.storage.conn.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON ai_write_requests BEGIN SELECT RAISE(ABORT,'fixture failure'); END"); self.storage.conn.commit()
        self.assertEqual(self.call('import_paper', self.args(), token=token)[0], 503)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0], before)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM library_items').fetchone()[0], 2)
        self.storage.conn.execute('DROP TRIGGER fail_receipt'); self.storage.conn.commit()
        self.assertEqual(self.call('import_paper', self.args(), token=token)[0], 200)

    def test_busy_paper_retries_without_partial_placement(self):
        paper, _ = self.cached(); token = self.enable_writes()
        with paper_download_lock(self.storage.db_path, paper['paper_id']):
            status, result, _ = self.call('import_paper', self.args(), token=token)
        self.assertEqual(status, 409, result); self.assertEqual(result['code'], 'paper_busy')
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM library_items WHERE paper_id=?', (paper['paper_id'],)).fetchone()[0], 0)
        self.assertEqual(self.call('import_paper', self.args(), token=token)[0], 200)

    def test_pending_layout_exact_retry_finishes_without_new_paper(self):
        paper, _ = self.cached(); old, resource = self.monitor_pdf(paper); token = self.enable_writes()
        with patch.object(ui, 'sync_all_pdf_aliases_for_paper', side_effect=OSError('busy volume')):
            status, result, _ = self.call('import_paper', self.args(), token=token)
        self.assertEqual(status, 200, result); self.assertTrue(result['layout_pending'])
        self.assertEqual(old.read_bytes(), self.pdf_bytes)
        status, result, _ = self.call('import_paper', self.args(), token=token)
        self.assertEqual(status, 200, result); self.assertFalse(result['layout_pending'])
        self.assertEqual(result['gewu_key'], paper['storage_key'])
        self.assertEqual(Path(self.storage.get_paper_resource(resource['id'])['stored_path']).read_bytes(), self.pdf_bytes)

    def test_removed_membership_is_not_restored_by_retry(self):
        token = self.enable_writes(); args = self.args()
        result = self.call('import_paper', args, token=token)[1]
        paper = self.storage.paper_for_key(result['gewu_key'])
        folder = self.storage.create_library_folder(name='Elsewhere', parent_id=1)
        self.storage.add_library_item(paper_id=paper['paper_id'], folder_id=folder['id'])
        self.storage.delete_library_item(item_id=result['membership_id'])
        status, result, _ = self.call('import_paper', args, token=token)
        self.assertEqual(status, 410, result); self.assertEqual(result['code'], 'import_removed')
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM library_items WHERE paper_id=? AND folder_id=1', (paper['paper_id'],)).fetchone()[0], 0)

    def test_notice_metadata_stays_an_event_on_its_original(self):
        token = self.enable_writes(); original = self.call('import_paper', self.args(), token=token)[1]
        args = self.args(); args.update(request_id='notice-metadata-001')
        args['metadata'].update(title='Correction: A supplied paper', doi='10.5555/correction',
            publication_notice={'kind':'correction_notice', 'related_dois':[self.metadata()['doi']], 'evidence_url':'https://example.org/correction'})
        status, result, _ = self.call('import_paper', args, token=token)
        self.assertEqual(status, 200, result); self.assertEqual(result['gewu_key'], original['gewu_key'])
        self.assertIsNone(result['file']); self.assertGreater(result['publication_notice_id'], 0)
        self.assertEqual(self.storage.conn.execute("SELECT count(*) FROM papers WHERE doi='10.5555/correction'").fetchone()[0], 0)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM publication_notice_files').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
