"""Exercise AI Access settings against an isolated product HTTP server."""
import json
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlparse

from paper_monitor import ui_server as ui
from paper_monitor.storage import Storage
from paper_monitor.ai_store import create_connection


with tempfile.TemporaryDirectory(prefix='gewu-ai-settings-') as temp, ExitStack() as patches:
    root = Path(temp)
    db = root / 'fixture.sqlite'
    storage = Storage(db)
    for name in ('LIBRARY_LOCAL_COPY_ROOT', 'SPACES_LOCAL_COPY_ROOT', 'MY_PUBLICATIONS_LOCAL_COPY_ROOT',
                 'DEFAULT_PDF_DIR', 'ASSOCIATED_FILES_ROOT'):
        patches.enter_context(patch.object(ui, name, root / name))
    parent = storage.create_library_folder(parent_id=1, name='Research Group')
    folder = storage.create_library_folder(parent_id=parent['id'], name='Quantum Notes')
    space = storage.create_library_root_folder(name='AI')
    storage.create_library_folder(parent_id=space['id'], name='Literature Project')
    create_connection(storage, {'name': 'Earlier folder grant', 'scopes': ['papers:read', 'folders:create'],
                               'write_folder_ids': [folder['id']]})
    storage.upsert_paper({'paper_id': 'fixture', 'title': 'Synthetic UI fixture', 'journal': 'Fixture'})
    storage.add_library_item(paper_id='fixture', folder_id=folder['id'])
    storage.add_library_item(paper_id='fixture', folder_id=1)
    patches.enter_context(patch.object(ui, 'request_with_retries', side_effect=AssertionError('No external requests')))

    class Handler(ui.PaperMonitorUiHandler):
        configured_db_path = db

        def log_message(self, *args):
            pass

        def do_GET(self):
            if urlparse(self.path).path in ('/api/arxiv-daily-refresh', '/api/author-monitor/summary',
                                           '/api/my-publications/work', '/api/my-publications/jobs'):
                self.send_json({})
                return
            super().do_GET()

        def do_POST(self):
            if urlparse(self.path).path != '/api/settings/ai-access':
                self.send_error(405)
                return
            super().do_POST()

    server = ui.FastLocalThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        fixture = root / 'fixture.json'
        fixture.write_text(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/',
                                      'token': server.workspace_access.token, 'folder': folder['id'], 'space': space['id']}))
        subprocess.run([sys.argv[1], 'tests/ai_access_ui_probe.cjs', str(fixture)], check=True, timeout=150)
        print('AI settings UI: opt-in, toggle, token preservation and existing controls passed with synthetic data.')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        storage.close()
