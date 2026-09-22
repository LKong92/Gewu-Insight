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
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from paper_monitor import ai_service, ui_server
from paper_monitor.ai_store import APIError, create_connection
from paper_monitor.local_access import WorkspaceAccess
from paper_monitor.mcp_server import GewuClient, serve
from paper_monitor.storage import Storage, STORAGE_SCHEMA_VERSION


class AIAccessTests(unittest.TestCase):
    def test_merged_key_keeps_grant_and_completed_analysis_retry(self):
        from paper_monitor import paper_identity
        request = {'gewu_key': self.key, 'markdown': 'Synthetic saved note',
                   'request_id': 'identity-retry-001', 'title': 'Identity note'}
        status, first, _ = self.call('save_analysis', request)
        self.assertEqual(status, 200)
        resource_id = first['file']['file_id']
        with paper_identity.transaction(self.storage):
            paper_identity.merge(self.storage,'two','one',reason='synthetic_verified_duplicate')
        status, repeated, _ = self.call('save_analysis', request)
        self.assertEqual(status,200)
        self.assertTrue(repeated['reused'])
        self.assertEqual(repeated['file']['file_id'],resource_id)
        self.assertEqual(self.call('get_paper',{'gewu_key':self.key})[0],200)
        self.assertEqual(self.call('get_paper',{'gewu_key':self.other_key})[0],200)
        outside=self.storage.get_paper('outside')['storage_key']
        self.assertEqual(self.call('get_paper',{'gewu_key':outside})[0],404)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM ai_analyses').fetchone()[0],1)
        duplicate=ui_server.attach_file_to_paper(self.storage,paper_id='one',filename='same.pdf',
            content=self.pdf_bytes,refresh_existing=False)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(duplicate['id'],self.pdf['id'])

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

    def test_markdown_revalidation_keeps_the_workspace_boundary(self):
        note = self.root / 'preview.md'
        note.write_text('# Current')
        from urllib.parse import urlencode
        route = '/api/markdown-preview?' + urlencode({'path': str(note)})
        status, content, headers = self.request(route, workspace=True)
        self.assertEqual(status, 200)
        self.assertEqual(content['text'], '# Current')
        validation = {'If-None-Match': headers['ETag']}
        status, content, _ = self.request(route, workspace=True, headers=validation)
        self.assertEqual((status, content), (304, b''))
        for token in (None, self.token):
            self.assertEqual(self.request(route, token=token, headers=validation)[0], 401)
        note.write_text('# Edited')
        status, content, _ = self.request(route, workspace=True, headers=validation)
        self.assertEqual(status, 200)
        self.assertEqual(content['text'], '# Edited')
        note.unlink()
        self.assertEqual(self.request(route, workspace=True, headers=validation)[0], 404)
        for asset in ('/markdown-preview-worker.js', '/markdown-it.min.js', '/js-yaml.min.js'):
            self.assertEqual(self.request(asset, workspace=True)[0], 200)

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
        for field, value in {'file_type': 'other', 'file_role': 'note', 'file_source': 'other',
                             'annotation_state': 'unannotated', 'source_detail': 'AI analysis · Fixture assistant',
                             'kind': 'md'}.items():
            self.assertEqual(resource[field], value, field)
            self.assertEqual(result['file'][field], value, field)
        self.assertEqual(result['file']['mime_type'], 'text/markdown')
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
        self.assertEqual({t['name'] for t in results[1]['result']['tools']},
                         {'search_papers', 'get_paper', 'read_paper', 'get_paper_file',
                          'save_analysis', 'get_file_delivery_status', 'release_paper_file'})
        self.assertFalse(results[2]['result']['isError']); self.assertTrue(results[3]['result']['isError'])
        self.assertNotIn(self.token, proc.stdout + proc.stderr)
        for bad in ('https://example.org', 'http://127.0.0.1:8765/evil', 'http://user:pass@localhost:8765'):
            with self.assertRaises(ValueError): GewuClient(bad, self.token)

    def file_client(self, token=None):
        client = GewuClient(f'http://127.0.0.1:{self.server.server_port}', token or self.token)
        self.addCleanup(client.close)
        return client

    def test_directory_tools_require_explicit_workspace_opt_in_and_work_over_stdio(self):
        from paper_monitor.mcp_server import TOOLS
        self.assertEqual(self.call('list_folders')[0], 403)
        payload = {'action': 'folder_access', 'connection_id': self.connection, 'allowed': True}
        self.assertEqual(self.request('/api/settings/ai-access', payload, token=self.token)[0], 401)
        before = dict(self.storage.conn.execute('SELECT * FROM ai_connections WHERE id=?', (self.connection,)).fetchone())
        status, settings, _ = self.request('/api/settings/ai-access', payload, workspace=True)
        self.assertEqual(status, 200)
        self.assertNotIn('token', settings)
        self.assertNotIn('mcp_config', settings)
        current = dict(self.storage.conn.execute('SELECT * FROM ai_connections WHERE id=?', (self.connection,)).fetchone())
        self.assertEqual(current['token_hash'], before['token_hash'])
        self.assertEqual(current['selection_json'], before['selection_json'])
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'list_folders', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'list_folder_papers', 'arguments': {'folder_id': 1, 'recursive': True, 'limit': 1}}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {'name': 'get_paper', 'arguments': {'gewu_key': self.key}}},
        ]
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'gewu_mcp.py'
        proc = subprocess.run([sys.executable, str(script)], input='\n'.join(json.dumps(m) for m in messages) + '\n',
            text=True, capture_output=True, timeout=30,
            env={**os.environ, 'GEWU_API_URL': f'http://127.0.0.1:{self.server.server_port}', 'GEWU_API_TOKEN': self.token})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        results = [json.loads(line)['result'] for line in proc.stdout.splitlines()]
        from paper_monitor.mcp_server import tool_allowed
        scopes=['papers:read','files:read','analysis:write','folders:read']
        self.assertEqual({t['name'] for t in results[1]['tools']}, {t['name'] for t in TOOLS if tool_allowed(t['name'],scopes)})
        self.assertEqual(results[0]['serverInfo']['version'], '1.5.0')
        for result in results[2:]:
            self.assertFalse(result['isError'])
        roots = json.loads(results[2]['content'][0]['text'])
        self.assertEqual([f['folder_id'] for f in roots['folders']], [1])
        entries = json.loads(results[3]['content'][0]['text'])['memberships']
        self.assertEqual([e['gewu_key'] for e in entries], [self.key])
        self.assertNotIn(self.other_key, proc.stdout)
        self.assertNotIn(self.token, proc.stdout + proc.stderr)
        payload['allowed'] = False
        self.assertEqual(self.request('/api/settings/ai-access', payload, workspace=True)[0], 200)
        self.assertEqual(self.call('list_folder_papers', {'folder_id': 1})[0], 403)
        self.assertEqual(self.call('get_paper', {'gewu_key': self.key})[0], 200)

    def test_directory_admin_rejects_invalid_permissions_and_openapi_is_current(self):
        for allowed in ('true', 1, None):
            self.assertEqual(self.request('/api/settings/ai-access', {'action': 'folder_access',
                'connection_id': self.connection, 'allowed': allowed}, workspace=True)[0], 400)
        self.assertEqual(self.request('/api/settings/ai-access', {'action': 'folder_access',
            'connection_id': 999999, 'allowed': True}, workspace=True)[0], 404)
        status, schema, _ = self.request('/api/v1/openapi.json', token=self.token)
        self.assertEqual(status, 200)
        for name in ('list_folders', 'list_folder_papers'):
            self.assertIn('/api/v1/tools/' + name, schema['paths'])

    def test_original_delivery_is_read_only_complete_and_client_readable(self):
        client = self.file_client()
        before_paper = self.storage.get_paper('one')
        before_files = [dict(r) for r in self.storage.conn.execute('SELECT * FROM resources ORDER BY id')]
        with patch.object(ai_service.subprocess, 'run', side_effect=AssertionError('No PDF processing in Gewu')):
            result = client.get_paper_file({'gewu_key': self.key})
        local = Path(result['delivery']['local_path'])
        self.assertEqual(local.read_bytes(), self.pdf_bytes)
        self.assertEqual(len(PdfReader(local).pages), 3)  # Processing happens in the receiving client.
        self.assertEqual(result['sha256'], hashlib.sha256(local.read_bytes()).hexdigest())
        self.assertEqual(result['file']['file_id'], self.pdf['id'])
        self.assertEqual(result['paper']['title'], 'Quantum one')
        self.assertEqual(result['paper']['journal'], 'Fixture Journal')
        self.assertIn('authors', result['paper']); self.assertIn('doi', result['paper'])
        self.assertNotEqual(local, Path(before_paper['main_pdf_path']))
        self.assertEqual(local.stat().st_mode & 0o222, 0)
        self.assertEqual(local.parent.stat().st_mode & 0o077, 0)
        with self.assertRaises(PermissionError): local.write_bytes(b'overwrite')
        self.assertEqual(client.get_paper_file({'gewu_key': self.key})['delivery']['local_path'], str(local))
        self.assertEqual(self.storage.get_paper('one'), before_paper)
        self.assertEqual([dict(r) for r in self.storage.conn.execute('SELECT * FROM resources ORDER BY id')], before_files)
        self.assertNotIn(self.token, json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        client.close(); self.assertFalse(local.exists())

    def test_delivery_requires_file_permission_and_exact_attachment_ownership(self):
        token = create_connection(self.storage, {'name': 'Metadata only'})['token']
        client = self.file_client(token)
        with self.assertRaisesRegex(ValueError, 'files:read'):
            client.get_paper_file({'gewu_key': self.key})
        source = io.StringIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'}) + '\n' +
                             json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}) + '\n')
        output = io.StringIO(); serve(client, source, output)
        tools = json.loads(output.getvalue().splitlines()[1])['result']['tools']
        self.assertNotIn('get_paper_file', [t['name'] for t in tools])
        foreign = ui_server.attach_file_to_paper(self.storage, paper_id='two', filename='private.txt', content=b'private')
        with self.assertRaises(ValueError): self.file_client().get_paper_file({'gewu_key': self.key, 'file_id': foreign['id']})
        with self.assertRaises(ValueError): self.file_client().get_paper_file({'gewu_key': self.other_key})
        for args in ({'gewu_key': '../private'}, {'gewu_key': self.key, 'file_id': True},
                     {'gewu_key': self.key, 'file_id': '../private'}, {'gewu_key': self.key, 'path': '/tmp/output.pdf'}):
            with self.assertRaises(ValueError): self.file_client().get_paper_file(args)

    def test_delivery_of_nondefault_file_and_null_default(self):
        note = ui_server.attach_file_to_paper(self.storage, paper_id='one', filename='note.md', content=b'# note', file_role='note')
        client = self.file_client()
        request = client.request
        def without_default(operation, args=None):
            result = request(operation, args)
            if operation == 'get_paper': result['default_file_id'] = None
            return result
        with patch.object(client, 'request', side_effect=without_default):
            with self.assertRaisesRegex(ValueError, 'no Default'):
                client.get_paper_file({'gewu_key': self.key})
            result = client.get_paper_file({'gewu_key': self.key, 'file_id': note['id']})
        self.assertEqual(Path(result['delivery']['local_path']).read_bytes(), b'# note')

    def test_delivery_revoked_during_transfer_exposes_no_copy(self):
        original_read = ai_service.read_bytes
        def revoke_after_read(*args, **kwargs):
            content = original_read(*args, **kwargs)
            db = sqlite3.connect(self.path)
            db.execute("UPDATE ai_connections SET revoked_at='now' WHERE id=?", (self.connection,)); db.commit(); db.close()
            return content
        client = self.file_client()
        with patch.object(ai_service, 'read_bytes', side_effect=revoke_after_read):
            with self.assertRaises(ValueError): client.get_paper_file({'gewu_key': self.key})
        self.assertFalse(client._deliveries)

    def test_delivery_rechecks_grant_after_receiving_and_cleans_partial(self):
        client = self.file_client(); request = client.request; checks = 0
        def revoke_on_final_check(operation, args=None):
            nonlocal checks
            if operation == 'capabilities':
                checks += 1
                if checks == 2:
                    self.storage.conn.execute("UPDATE ai_connections SET revoked_at='now' WHERE id=?", (self.connection,))
                    self.storage.conn.commit()
            return request(operation, args)
        with patch.object(client, 'request', side_effect=revoke_on_final_check):
            with self.assertRaises(ValueError): client.get_paper_file({'gewu_key': self.key})
        self.assertEqual(list(Path(client._delivery_dir.name).iterdir()), [])

    def test_delivery_checks_current_grant_even_when_copy_already_exists(self):
        client = self.file_client(); result = client.get_paper_file({'gewu_key': self.key})
        local = Path(result['delivery']['local_path'])
        self.storage.set_setting('ai_access_enabled', 'false')
        with self.assertRaises(ValueError): client.get_paper_file({'gewu_key': self.key})
        self.storage.set_setting('ai_access_enabled', 'true')
        self.storage.conn.execute("UPDATE ai_connections SET expires_at='2000-01-01' WHERE id=?", (self.connection,)); self.storage.conn.commit()
        with self.assertRaises(ValueError): client.get_paper_file({'gewu_key': self.key})
        self.assertEqual(local.read_bytes(), self.pdf_bytes)  # Previously delivered content cannot be recalled.

    def test_large_delivery_bypasses_json_limit_and_reports_actual_version(self):
        data = self.pdf_bytes + b'\n%' + b'x' * (34 * 1024 * 1024)
        Path(self.storage.get_paper('one')['main_pdf_path']).write_bytes(data)
        client = self.file_client()
        result = client.get_paper_file({'gewu_key': self.key})
        self.assertEqual(result['file']['size_bytes'], len(data))
        self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(Path(result['delivery']['local_path']).read_bytes(), data)
        self.assertLess(len(json.dumps(result)), 8192)

    def test_delivery_size_limits_clean_up_without_evicting_existing_copies(self):
        from paper_monitor import mcp_server
        client = self.file_client(); first = client.get_paper_file({'gewu_key': self.key})
        with patch.object(mcp_server, 'MAX_FILE_BYTES', 10):
            with self.assertRaises(ValueError): client.get_paper_file({'gewu_key': self.key})
        with patch.object(mcp_server, 'MAX_DELIVERY_BYTES', 10):
            with self.assertRaisesRegex(ValueError, 'session is full'): client.get_paper_file({'gewu_key': self.key})
        self.assertEqual(list(Path(client._delivery_dir.name).glob('*.part')), [])
        self.assertEqual(Path(first['delivery']['local_path']).read_bytes(), self.pdf_bytes)

    def test_incomplete_delivery_removes_partial_file(self):
        client = self.file_client(); original_open = client.opener.open
        def incomplete(request, **kwargs):
            if request.full_url.endswith('/content'):
                response = io.BytesIO(self.pdf_bytes[:-1])
                response.headers = {'Content-Length': str(len(self.pdf_bytes))}
                return response
            return original_open(request, **kwargs)
        with patch.object(client.opener, 'open', side_effect=incomplete):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                client.get_paper_file({'gewu_key': self.key})
        self.assertEqual(list(Path(client._delivery_dir.name).iterdir()), [])

    def test_release_restores_byte_and_file_quota_for_continued_reading(self):
        from paper_monitor import mcp_server
        note = ui_server.attach_file_to_paper(self.storage, paper_id='one', filename='second.txt', content=b'second')
        client = self.file_client()
        for limits in ({'MAX_DELIVERY_FILES': 1}, {'MAX_DELIVERY_BYTES': len(self.pdf_bytes)}):
            with patch.multiple(mcp_server, **limits):
                for _ in range(3):
                    first = client.get_paper_file({'gewu_key': self.key})
                    quota = first['quota']
                    self.assertEqual(quota['used_bytes'], len(self.pdf_bytes))
                    self.assertEqual(quota['remaining_bytes'], mcp_server.MAX_DELIVERY_BYTES - len(self.pdf_bytes))
                    self.assertEqual(quota['used_files'], 1)
                    self.assertEqual(quota['remaining_files'], mcp_server.MAX_DELIVERY_FILES - 1)
                    with self.assertRaisesRegex(ValueError, 'release_paper_file'):
                        client.get_paper_file({'gewu_key': self.key, 'file_id': note['id']})
                    self.assertTrue(Path(first['delivery']['local_path']).exists())
                    self.assertEqual(list(Path(client._delivery_dir.name).glob('*.part')), [])
                    released = client.release_paper_file({'delivery_id': first['delivery']['delivery_id']})
                    self.assertEqual(released['freed_bytes'], len(self.pdf_bytes))
                    self.assertEqual(released['quota']['used_bytes'], 0)
                    self.assertEqual(released['quota']['used_files'], 0)
                    second = client.get_paper_file({'gewu_key': self.key, 'file_id': note['id']})
                    self.assertEqual(Path(second['delivery']['local_path']).read_bytes(), b'second')
                    client.release_paper_file({'delivery_id': second['delivery']['delivery_id']})
        self.assertEqual(Path(self.storage.get_paper('one')['main_pdf_path']).read_bytes(), self.pdf_bytes)

    def test_active_redelivery_shares_quota_and_stale_release_cannot_delete_new_copy(self):
        client = self.file_client()
        first = client.get_paper_file({'gewu_key': self.key})
        repeated = client.get_paper_file({'gewu_key': self.key})
        self.assertEqual(first['delivery'], repeated['delivery'])
        self.assertEqual(repeated['quota']['used_files'], 1)
        release_args = {'delivery_id': first['delivery']['delivery_id']}
        client.release_paper_file(release_args)
        fresh = client.get_paper_file({'gewu_key': self.key})
        self.assertNotEqual(first['delivery']['delivery_id'], fresh['delivery']['delivery_id'])
        result = client.release_paper_file(release_args)
        self.assertFalse(result['released'])
        self.assertEqual(result['freed_bytes'], 0)
        self.assertEqual(result['quota']['used_files'], 1)
        self.assertEqual(Path(fresh['delivery']['local_path']).read_bytes(), self.pdf_bytes)

    def test_release_is_scoped_to_connection_handles_and_never_accepts_paths(self):
        client, other = self.file_client(), self.file_client()
        first = client.get_paper_file({'gewu_key': self.key})
        local = Path(first['delivery']['local_path'])
        delivery_id = first['delivery']['delivery_id']
        self.assertFalse(other.release_paper_file({'delivery_id': delivery_id})['released'])
        for args in ({}, {'delivery_id': str(local)}, {'delivery_id': '../original.pdf'},
                     {'delivery_id': True}, {'delivery_id': []},
                     {'delivery_id': delivery_id, 'path': str(local)}, {'gewu_key': self.key}):
            with self.assertRaises(ValueError): client.release_paper_file(args)
        self.assertTrue(local.exists())
        with self.assertRaises(ValueError): client.get_file_delivery_status({'path': str(local)})
        status = client.get_file_delivery_status({})
        self.assertEqual(status['deliveries'], [{'delivery_id': delivery_id, 'gewu_key': self.key,
                                               'file_id': self.pdf['id'], 'size_bytes': len(self.pdf_bytes)}])
        self.assertNotIn(str(self.root), json.dumps(status))
        self.assertNotIn(self.token, json.dumps(status))

    def test_changed_file_versions_have_independent_release_handles(self):
        client = self.file_client()
        first = client.get_paper_file({'gewu_key': self.key})
        original = Path(self.storage.get_paper('one')['main_pdf_path'])
        changed = self.pdf_bytes + b'\n% changed'
        original.write_bytes(changed)
        second = client.get_paper_file({'gewu_key': self.key})
        self.assertEqual(second['quota']['used_files'], 2)
        self.assertNotEqual(first['delivery']['delivery_id'], second['delivery']['delivery_id'])
        result = client.release_paper_file({'delivery_id': first['delivery']['delivery_id']})
        self.assertEqual(result['quota']['used_bytes'], len(changed))
        self.assertEqual(Path(second['delivery']['local_path']).read_bytes(), changed)
        self.assertEqual(original.read_bytes(), changed)

    def test_release_failure_preserves_accounting_and_missing_copy_can_be_released(self):
        client = self.file_client()
        first = client.get_paper_file({'gewu_key': self.key})
        args = {'delivery_id': first['delivery']['delivery_id']}
        with patch('paper_monitor.mcp_server.os.unlink', side_effect=PermissionError('busy')):
            with self.assertRaisesRegex(ValueError, 'quota is still reserved'):
                client.release_paper_file(args)
        self.assertEqual(client.delivery_quota()['used_files'], 1)
        local = Path(first['delivery']['local_path'])
        self.assertTrue(local.exists())
        local.unlink()
        self.assertTrue(client.release_paper_file(args)['released'])
        self.assertEqual(client.delivery_quota()['used_files'], 0)
        self.assertEqual(client.get_file_delivery_status({})['deliveries'], [])

    def test_release_unlinks_only_temp_symlink_not_original_target(self):
        client = self.file_client()
        first = client.get_paper_file({'gewu_key': self.key})
        original = Path(self.storage.get_paper('one')['main_pdf_path'])
        local = Path(first['delivery']['local_path'])
        local.unlink(); local.symlink_to(original)
        client.release_paper_file({'delivery_id': first['delivery']['delivery_id']})
        self.assertFalse(local.is_symlink())
        self.assertEqual(original.read_bytes(), self.pdf_bytes)

    def test_release_rejects_replaced_session_directory(self):
        client = self.file_client()
        first = client.get_paper_file({'gewu_key': self.key})
        directory = Path(client._delivery_dir.name)
        moved = directory.with_name(directory.name + '-moved')
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError, 'quota is still reserved'):
                client.release_paper_file({'delivery_id': first['delivery']['delivery_id']})
            self.assertEqual(client.delivery_quota()['used_files'], 1)
            self.assertTrue((moved / Path(first['delivery']['local_path']).name).exists())
        finally:
            directory.unlink(); moved.rename(directory)

    def test_local_status_and_release_work_over_rpc_after_revocation_or_offline(self):
        from paper_monitor.mcp_server import LOCAL_DELIVERY_TOOLS
        client = self.file_client()
        first = client.get_paper_file({'gewu_key': self.key})
        self.storage.conn.execute("UPDATE ai_connections SET revoked_at='now' WHERE id=?", (self.connection,))
        self.storage.conn.commit()
        messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                    {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'get_file_delivery_status'}},
                    {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'release_paper_file',
                        'arguments': {'delivery_id': first['delivery']['delivery_id']}}},
                    {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {'name': 'get_paper_file',
                        'arguments': {'gewu_key': self.key}}}]
        for offline in (False, True):
            output = io.StringIO()
            source = io.StringIO('\n'.join(json.dumps(m) for m in messages) + '\n')
            if offline:
                with patch.object(client, 'request', side_effect=ValueError('offline')): serve(client, source, output)
            else:
                serve(client, source, output)
            results = [json.loads(line)['result'] for line in output.getvalue().splitlines()]
            self.assertEqual({t['name'] for t in results[1]['tools']}, LOCAL_DELIVERY_TOOLS)
            self.assertFalse(results[2]['isError'])
            self.assertFalse(results[3]['isError'])
            self.assertTrue(results[4]['isError'])
            self.assertEqual(json.loads(results[3]['content'][0]['text'])['quota']['used_bytes'], 0)
        self.assertFalse(Path(first['delivery']['local_path']).exists())

    def test_stdio_client_can_read_delivered_file_and_append_analysis(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'gewu_mcp.py'
        process = subprocess.Popen([sys.executable, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env={**os.environ, 'GEWU_API_URL': f'http://127.0.0.1:{self.server.server_port}',
                                                   'GEWU_API_TOKEN': self.token})
        local = None
        try:
            def rpc(identifier, method, params):
                process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params}) + '\n')
                process.stdin.flush()
                return json.loads(process.stdout.readline())['result']
            rpc(1, 'initialize', {'protocolVersion': '2025-11-25'})
            delivered = rpc(2, 'tools/call', {'name': 'get_paper_file', 'arguments': {'gewu_key': self.key}})
            self.assertFalse(delivered['isError'])
            data = json.loads(delivered['content'][0]['text'])
            local = Path(data['delivery']['local_path'])
            self.assertEqual(local.read_bytes(), self.pdf_bytes)
            self.assertEqual(len(PdfReader(local).pages), 3)
            released = rpc(20, 'tools/call', {'name': 'release_paper_file',
                'arguments': {'delivery_id': data['delivery']['delivery_id']}})
            self.assertFalse(released['isError'])
            self.assertFalse(local.exists())
            status = rpc(21, 'tools/call', {'name': 'get_file_delivery_status'})
            self.assertEqual(json.loads(status['content'][0]['text'])['quota']['used_files'], 0)
            saved = rpc(3, 'tools/call', {'name': 'save_analysis', 'arguments': {'gewu_key': self.key,
                'markdown': '# Client-generated fixture note', 'request_id': 'stdio-delivery-analysis',
                'source_file_id': data['file']['file_id'], 'source_sha256': data['sha256'], 'pages': [1, 2, 3]}})
            self.assertFalse(saved['isError'])
            note = json.loads(saved['content'][0]['text'])['file']
            self.assertEqual(note['mime_type'], 'text/markdown')
            self.assertEqual(note['file_source'], 'other')
            self.assertNotIn(self.token, json.dumps([delivered, saved]))
        finally:
            process.stdin.close()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            process.stdout.close(); process.stderr.close()
        self.assertEqual(process.returncode, 0)
        self.assertIsNotNone(local); self.assertFalse(local.exists())

    def test_regular_ui_remains_available_while_original_transfer_waits(self):
        entered, release = threading.Event(), threading.Event()
        original_read = ai_service.read_bytes
        def paused_read(*args, **kwargs):
            entered.set(); release.wait(5)
            return original_read(*args, **kwargs)
        results = []
        client = self.file_client()
        def receive():
            try: results.append(client.get_paper_file({'gewu_key': self.key}))
            except Exception as exc: results.append(exc)
        with patch.object(ai_service, 'read_bytes', side_effect=paused_read):
            worker = threading.Thread(target=receive); worker.start()
            try:
                self.assertTrue(entered.wait(5))
                start = time.monotonic()
                self.assertEqual(self.request('/api/paper?paper_id=one', workspace=True)[0], 200)
                self.assertLess(time.monotonic() - start, 2)
                self.assertTrue(worker.is_alive())
            finally:
                release.set(); worker.join(10)
        self.assertIsInstance(results[0], dict)

    def test_save_with_delivered_hash_is_append_only_and_cannot_override_categories(self):
        delivered = self.file_client().get_paper_file({'gewu_key': self.key})
        before = [dict(r) for r in self.storage.conn.execute('SELECT * FROM resources ORDER BY id')]
        args = {'gewu_key': self.key, 'markdown': '# Client analysis', 'title': 'original', 'request_id': 'client-read-analysis',
                'source_file_id': delivered['file']['file_id'], 'source_sha256': delivered['sha256'], 'pages': [1]}
        with patch.object(ui_server, 'refresh_paper_resource_fingerprints', side_effect=AssertionError('No edits or rescans of existing files')):
            status, saved, _ = self.call('save_analysis', args)
        self.assertEqual(status, 200)
        self.assertNotEqual(saved['file']['file_id'], self.pdf['id'])
        self.assertFalse(saved['file']['is_default'])
        for old in before:
            self.assertEqual(dict(self.storage.conn.execute('SELECT * FROM resources WHERE id=?', (old['id'],)).fetchone()), old)
        for override in ({'file_id': self.pdf['id']}, {'file_type': 'published_version'}, {'file_source': 'publisher'}, {'overwrite': True}):
            self.assertEqual(self.call('save_analysis', {**args, **override})[0], 400)
        for operation in ('delete_file', 'update_file', 'overwrite_file', 'set_default'):
            self.assertEqual(self.call(operation, {'gewu_key': self.key, 'file_id': self.pdf['id']})[0], 404)
        changed = {**args, 'request_id': 'client-read-analysis-new', 'markdown': '# A new analysis'}
        second = self.call('save_analysis', changed)[1]
        self.assertNotEqual(second['file']['file_id'], saved['file']['file_id'])
        self.assertEqual(Path(self.storage.get_paper('one')['main_pdf_path']).read_bytes(), self.pdf_bytes)

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
