"""AI access uses temporary SQLite/files and real loopback HTTP only."""
import hashlib
import http.client
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from paper_monitor import ai_service, ui_server
from paper_monitor.ai_store import APIError, create_connection
from paper_monitor.local_access import WorkspaceAccess
from paper_monitor.mcp_server import GewuClient, serve
from paper_monitor.storage import Storage, STORAGE_SCHEMA_VERSION


class AIAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'data' / 'test.sqlite'
        self.storage = Storage(self.path)
        self.patches = [patch.object(ui_server, name, self.root / name) for name in (
            'LIBRARY_LOCAL_COPY_ROOT', 'SPACES_LOCAL_COPY_ROOT', 'MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'DEFAULT_PDF_DIR', 'ASSOCIATED_FILES_ROOT')]
        for active in self.patches:
            active.start()
        for paper_id in ('one', 'two', 'outside'):
            self.storage.upsert_paper({'paper_id': paper_id, 'title': 'Quantum ' + paper_id,
                                      'journal': 'Fixture Journal', 'source': 'fixture', 'raw': {}})
        self.storage.add_library_item(paper_id='one', folder_id=1)
        self.storage.add_library_item(paper_id='two', folder_id=1)
        self.key = self.storage.get_paper('one')['storage_key']
        self.other_key = self.storage.get_paper('two')['storage_key']
        writer = PdfWriter()
        for _ in range(3): writer.add_blank_page(width=612, height=792)
        output = io.BytesIO(); writer.write(output)
        self.pdf_bytes = output.getvalue()
        self.pdf = ui_server.attach_file_to_paper(self.storage, paper_id='one', filename='original.pdf',
            content=self.pdf_bytes, file_type='preprint')
        self.storage.set_setting('ai_access_enabled', 'true')
        created = create_connection(self.storage, {'name': 'Fixture assistant',
            'scopes': ['papers:read', 'files:read', 'analysis:write'], 'selection': {'kind': 'papers', 'keys': [self.key]}})
        self.token = created['token']; self.connection = created['connection']['id']
        path = self.path
        class Handler(ui_server.PaperMonitorUiHandler):
            configured_db_path = path
            def log_message(self, *_args): pass
        self.server = ui_server.FastLocalThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.storage.close()
        for active in reversed(self.patches): active.stop()
        self.temp.cleanup()

    def request(self, path, payload=None, *, token=None, workspace=False, headers=None):
        hdr = dict(headers or {})
        if workspace: hdr['X-Gewu-Workspace'] = self.server.workspace_access.token
        if token: hdr['Authorization'] = 'Bearer ' + token
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        connection.request('POST' if payload is not None else 'GET', path, None if payload is None else json.dumps(payload), hdr)
        response = connection.getresponse(); content = response.read(); response_headers = dict(response.getheaders()); connection.close()
        if response_headers.get('Content-Type', '').startswith('application/json'):
            content = json.loads(content)
        return response.status, content, response_headers

    def call(self, name, args=None, token=None):
        return self.request('/api/v1/tools/' + name, args or {}, token=token or self.token)

    def test_workspace_cookie_and_native_header_preserve_regular_ui(self):
        status, content, headers = self.request('/', workspace=True)
        self.assertEqual(status, 200); self.assertIn(b'libraryShell', content)
        self.assertIn('HttpOnly', headers['Set-Cookie']); self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        self.assertEqual(self.request('/api/paper?paper_id=one', headers={'Cookie': cookie})[0], 200)
        self.assertEqual(self.request('/api/settings/website-links', {'browser': 'builtin'}, workspace=True)[0], 200)
        for asset in ('/browser-ui.js', '/ai-access.js', '/ai-access.css'):
            self.assertEqual(self.request(asset, workspace=True)[0], 200)
        self.assertIn(b'Open Gewu Insight', self.request('/')[1])
        self.assertNotIn(b'libraryShell', self.request('/')[1])

    def test_ai_token_cannot_bypass_scope_through_internal_routes(self):
        for path in ('/api/paper?paper_id=one', '/api/paper-files?paper_id=one', '/api/native-file-preview?path=/etc/hosts',
                     '/files?path=/etc/hosts', '/api/markdown-preview?path=/etc/hosts', '/api/settings/ai-access'):
            for token in (None, self.token):
                self.assertEqual(self.request(path, token=token)[0], 401, (path, token is not None))
        for path in ('/api/library/delete', '/api/settings/ai-access', '/api/settings/citation/reveal', '/api/manual-pdf-path'):
            self.assertEqual(self.request(path, {}, token=self.token)[0], 401)
        cookie = self.server.workspace_access.cookie().split(';', 1)[0]
        self.assertEqual(self.request('/api/paper?paper_id=one', token=self.token, headers={'Cookie': cookie})[0], 401)
        self.assertEqual(self.request('/api/browser-capture-file', {}, token=self.token)[0], 400)

    def test_host_origin_checks_apply_even_with_valid_credentials(self):
        for headers in ({'Origin': 'https://example.org'}, {'Sec-Fetch-Site': 'cross-site'}, {'Host': 'attacker.example'}):
            self.assertEqual(self.request('/api/v1/capabilities', token=self.token, headers=headers)[0], 403)
            self.assertEqual(self.request('/api/settings/ai-access', workspace=True, headers=headers)[0], 403)

    def test_workspace_bootstrap_is_single_use_and_not_the_full_ui(self):
        ticket = self.server.workspace_access.bootstrap()
        status, _, headers = self.request('/api/workspace-session', {}, headers={'X-Gewu-Bootstrap': ticket})
        self.assertEqual(status, 200); self.assertIn('Set-Cookie', headers)
        self.assertEqual(self.request('/api/workspace-session', {}, headers={'X-Gewu-Bootstrap': ticket})[0], 401)
        self.assertEqual(self.request('/api/workspace-session', {}, headers={'X-Gewu-Bootstrap': self.token})[0], 401)
        self.assertEqual(WorkspaceAccess(self.path).token, self.server.workspace_access.token)
        self.assertEqual((self.path.parent / '.gewu-workspace-token').stat().st_mode & 0o777, 0o600)

    def test_credentials_hashes_only_disabled_expired_and_revoked(self):
        state = self.request('/api/settings/ai-access', workspace=True)[1]
        self.assertNotIn(self.token, json.dumps(state))
        row = self.storage.conn.execute('SELECT * FROM ai_connections WHERE id=?', (self.connection,)).fetchone()
        self.assertEqual(row['token_hash'], hashlib.sha256(self.token.encode()).hexdigest())
        self.assertEqual(self.request('/api/v1/capabilities')[0], 401)
        self.storage.set_setting('ai_access_enabled', 'false')
        self.assertEqual(self.call('get_paper', {'gewu_key': self.key})[0], 403)
        self.storage.set_setting('ai_access_enabled', 'true')
        self.storage.conn.execute("UPDATE ai_connections SET expires_at='2000-01-01' WHERE id=?", (self.connection,)); self.storage.conn.commit()
        self.assertEqual(self.call('get_paper', {'gewu_key': self.key})[0], 401)
        self.storage.conn.execute("UPDATE ai_connections SET expires_at='2999-01-01' WHERE id=?", (self.connection,)); self.storage.conn.commit()
        self.assertEqual(self.request('/api/settings/ai-access', {'action': 'revoke', 'connection_id': self.connection}, workspace=True)[0], 200)
        self.assertEqual(self.call('get_paper', {'gewu_key': self.key})[0], 401)

    def test_scoped_metadata_search_and_file_id_cannot_cross_papers(self):
        status, data, _ = self.call('search_papers', {'query': 'Quantum'})
        self.assertEqual(status, 200); self.assertEqual([p['gewu_key'] for p in data['papers']], [self.key])
        for q in ('%', "' OR 1=1 --"):
            self.assertEqual(self.call('search_papers', {'query': q})[1]['papers'], [])
        self.assertEqual(len(self.call('search_papers', {'query': self.key})[1]['papers']), 1)
        self.assertEqual(self.call('get_paper', {'gewu_key': self.other_key})[0], 404)
        data = self.call('get_paper', {'gewu_key': self.key})[1]
        self.assertEqual(data['default_file_id'], self.pdf['id'])
        for forbidden in ('stored_path', 'source_path', 'raw_json', 'token_hash', 'paper_id'):
            self.assertNotIn(forbidden, json.dumps(data))
        self.assertNotIn(str(self.root), json.dumps(data))
        foreign = ui_server.attach_file_to_paper(self.storage, paper_id='two', filename='private.txt', content=b'private')
        self.assertEqual(self.call('read_paper', {'gewu_key': self.key, 'file_id': foreign['id']})[0], 404)

    def test_metadata_keeps_preprint_identifier_and_all_authors(self):
        authors = [{'given': 'Researcher', 'family': str(i)} for i in range(12)]
        raw = {'arxiv_id': '2609.00001v2', 'author': authors}
        self.storage.conn.execute('UPDATE papers SET raw_json=? WHERE paper_id=?', (json.dumps(raw), 'one'))
        self.storage.conn.commit()
        status, result, _ = self.call('get_paper', {'gewu_key': self.key})
        self.assertEqual(status, 200)
        self.assertEqual(result['arxiv_id'], '2609.00001v2')
        self.assertEqual(len(result['authors']), 12)
        self.assertIn('Researcher 11', result['authors'])

    def test_default_connection_is_metadata_only(self):
        status, created, _ = self.request('/api/settings/ai-access', {'action': 'create', 'name': 'Reader'}, workspace=True)
        self.assertEqual(status, 200)
        token = created['token']; self.assertEqual(created['connection']['scopes'], ['papers:read'])
        self.assertEqual(self.call('get_paper', {'gewu_key': self.key}, token)[0], 200)
        self.assertEqual(self.call('read_paper', {'gewu_key': self.key}, token)[0], 403)
        self.assertEqual(self.request(f'/api/v1/papers/{self.key}/files/default/content', token=token)[0], 403)
        self.assertEqual(self.call('save_analysis', {'gewu_key': self.key, 'markdown': 'test', 'request_id': 'fixture-1'}, token)[0], 403)

    def test_folder_grant_follows_live_ancestry_without_exposing_siblings(self):
        parent = self.storage.create_library_folder(name='Allowed', parent_id=1)
        child = self.storage.create_library_folder(name='Child', parent_id=parent['id'])
        self.storage.conn.execute('UPDATE library_items SET folder_id=? WHERE paper_id=?', (child['id'], 'one')); self.storage.conn.commit()
        grant = create_connection(self.storage, {'name': 'Folder', 'selection': {'kind': 'folder', 'folder_id': parent['id']}})
        token = grant['token']
        self.assertEqual([p['gewu_key'] for p in self.call('search_papers', {}, token)[1]['papers']], [self.key])
        self.storage.conn.execute('UPDATE library_folders SET parent_id=1 WHERE id=?', (child['id'],)); self.storage.conn.commit()
        self.assertEqual(self.call('get_paper', {'gewu_key': self.key}, token)[0], 404)
        self.storage.conn.execute("UPDATE library_folders SET parent_id=?,trashed_at='now' WHERE id=?", (parent['id'], child['id'])); self.storage.conn.commit()
        self.assertEqual(self.call('search_papers', {}, token)[1]['papers'], [])

    def test_pdf_pages_text_and_raw_download_return_same_version(self):
        status, data, _ = self.call('read_paper', {'gewu_key': self.key, 'start_page': 2, 'page_count': 1})
        self.assertEqual(status, 200); self.assertEqual(data['pages'][0]['page'], 2)
        self.assertEqual(data['total_pages'], 3); self.assertTrue(data['ocr_needed'])
        self.assertEqual(data['sha256'], hashlib.sha256(self.pdf_bytes).hexdigest())
        status, content, headers = self.request(f'/api/v1/papers/{self.key}/files/default/content', token=self.token)
        self.assertEqual(status, 200); self.assertEqual(content, self.pdf_bytes)
        self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertEqual(self.call('read_paper', {'gewu_key': self.key, 'page_count': 11})[0], 400)

    def test_save_analysis_is_append_only_idempotent_and_survives_restart(self):
        before = self.storage.get_paper('one')
        args = {'gewu_key': self.key, 'markdown': '# 分析\n\nThis is research content.', 'request_id': 'analysis-fixture-1',
                'source_file_id': self.pdf['id'], 'source_sha256': hashlib.sha256(self.pdf_bytes).hexdigest(), 'pages': [1, 2]}
        status, result, _ = self.call('save_analysis', args)
        self.assertEqual(status, 200); file_id = result['file']['file_id']
        resource = self.storage.get_paper_resource(file_id)
        text = Path(resource['stored_path']).read_text()
        self.assertIn(self.key, text); self.assertIn('Fixture assistant', text); self.assertIn(args['markdown'], text)
        self.assertEqual(resource['added_via'], 'ai_analysis')
        self.assertEqual(self.call('save_analysis', args)[1]['file']['file_id'], file_id)
        reopened = Storage(self.path)
        self.assertEqual(ai_service.execute(reopened, 'Bearer ' + self.token, 'save_analysis', args)['file']['file_id'], file_id)
        reopened.close()
        self.assertEqual(self.call('save_analysis', {**args, 'markdown': 'Changed'})[0], 409)
        self.assertEqual(len(self.storage.list_paper_resources('one')), 2)
        after = self.storage.get_paper('one')
        for field in ('storage_key', 'main_pdf_path', 'merged_pdf_path', 'primary_resource_id', 'preferred_resource_id', 'preferred_resource_manual'):
            self.assertEqual(before[field], after[field], field)
        self.assertEqual(Path(before['main_pdf_path']).read_bytes(), self.pdf_bytes)
        self.assertIn(args['markdown'], self.call('read_paper', {'gewu_key': self.key, 'file_id': file_id})[1]['text'])
        log = json.dumps(self.request('/api/settings/ai-access', workspace=True)[1]['activity'])
        self.assertNotIn(self.token, log); self.assertNotIn(args['markdown'], log)

    def test_changed_source_and_removed_analysis_do_not_silently_recreate(self):
        args = {'gewu_key': self.key, 'markdown': 'A note', 'request_id': 'analysis-fixture-2',
                'source_file_id': self.pdf['id'], 'source_sha256': '0' * 64}
        self.assertEqual(self.call('save_analysis', args)[0], 409)
        args.pop('source_file_id'); args.pop('source_sha256')
        result = self.call('save_analysis', args)[1]
        self.storage.conn.execute('DELETE FROM resources WHERE id=?', (result['file']['file_id'],)); self.storage.conn.commit()
        self.assertEqual(self.call('save_analysis', args)[0], 410)

    def test_completed_retry_survives_later_source_edit(self):
        args = {'gewu_key': self.key, 'markdown': 'Original analysis', 'request_id': 'analysis-fixture-retry',
                'source_file_id': self.pdf['id'], 'source_sha256': hashlib.sha256(self.pdf_bytes).hexdigest()}
        status, first, _ = self.call('save_analysis', args)
        self.assertEqual(status, 200)
        Path(self.storage.get_paper('one')['main_pdf_path']).write_bytes(b'New source version')
        status, repeated, _ = self.call('save_analysis', args)
        self.assertEqual(status, 200)
        self.assertEqual(first['file']['file_id'], repeated['file']['file_id'])
        self.assertTrue(repeated['reused'])
        self.assertEqual(self.call('save_analysis', {**args, 'request_id': 'new-analysis-fixture'})[0], 409)

    def test_failed_receipt_update_recovers_same_attachment_on_retry(self):
        self.storage.conn.execute("CREATE TRIGGER fail_ai_receipt BEFORE UPDATE ON ai_analyses BEGIN SELECT RAISE(FAIL, 'fixture'); END")
        self.storage.conn.commit()
        args = {'gewu_key': self.key, 'markdown': 'One recoverable note', 'request_id': 'analysis-fixture-3'}
        self.assertEqual(self.call('save_analysis', args)[0], 503)
        files = self.storage.list_paper_resources('one'); self.assertEqual(len(files), 2)
        self.storage.conn.execute('DROP TRIGGER fail_ai_receipt'); self.storage.conn.commit()
        self.assertEqual(self.call('save_analysis', args)[0], 200)
        self.assertEqual(len(self.storage.list_paper_resources('one')), 2)

    def test_revocation_during_pdf_read_prevents_content_return(self):
        def read_and_revoke(*_args):
            db = sqlite3.connect(self.path)
            db.execute("UPDATE ai_connections SET revoked_at='now' WHERE id=?", (self.connection,)); db.commit(); db.close()
            return {'private': 'must not be returned'}
        with patch.object(ai_service, 'read_paper', side_effect=read_and_revoke):
            status, data, _ = self.call('read_paper', {'gewu_key': self.key})
        self.assertEqual(status, 401); self.assertNotIn('private', data)

    def test_real_mcp_stdio_adapter_uses_only_scoped_http(self):
        url = f'http://127.0.0.1:{self.server.server_port}'
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'fixture', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'get_paper', 'arguments': {'gewu_key': self.key}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'get_paper', 'arguments': {'gewu_key': self.other_key}}},
        ]
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'gewu_mcp.py'
        proc = subprocess.run([sys.executable, str(script)], input='\n'.join(json.dumps(m) for m in messages) + '\n',
            text=True, capture_output=True, timeout=30, env={**os.environ, 'GEWU_API_URL': url, 'GEWU_API_TOKEN': self.token})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        results = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(results), 4)
        self.assertEqual(results[0]['result']['protocolVersion'], '2025-11-25')
        self.assertEqual(len(results[1]['result']['tools']), 4)
        self.assertFalse(results[2]['result']['isError']); self.assertTrue(results[3]['result']['isError'])
        self.assertNotIn(self.token, proc.stdout + proc.stderr)
        for bad in ('https://example.org', 'http://127.0.0.1:8765/evil', 'http://user:pass@localhost:8765'):
            with self.assertRaises(ValueError): GewuClient(bad, self.token)

    def test_schema_upgrade_preserves_papers_and_files_without_backfill(self):
        before = [dict(r) for r in self.storage.conn.execute('SELECT * FROM papers ORDER BY paper_id')]
        self.storage.conn.execute('PRAGMA user_version=17'); self.storage.conn.commit()
        with patch.object(Storage, '_backfill_paper_source_observations', side_effect=AssertionError('No backfill')):
            upgraded = Storage(self.path)
        self.assertEqual(upgraded.conn.execute('PRAGMA user_version').fetchone()[0], STORAGE_SCHEMA_VERSION)
        self.assertEqual(before, [dict(r) for r in upgraded.conn.execute('SELECT * FROM papers ORDER BY paper_id')])
        self.assertEqual(upgraded.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        upgraded.close()


if __name__ == '__main__':
    unittest.main()
