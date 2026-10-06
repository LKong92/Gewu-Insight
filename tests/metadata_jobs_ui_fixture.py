"""Real product UI/API on temporary SQLite, with no external provider traffic."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlparse
from paper_monitor import ui_server as ui, metadata_refresh as work, metadata_jobs as jobs
from paper_monitor.storage import Storage


with tempfile.TemporaryDirectory(prefix='gewu-refresh-ui-') as temp:
    root = Path(temp)
    db = root / 'data/test.sqlite'
    storage = Storage(db)
    folder = storage.create_library_folder(parent_id=1, name='Refresh scope')['id']
    child = storage.create_library_folder(parent_id=folder, name='Nested')['id']
    recycle = storage.ensure_library_folder(parent_id=1, name='Recycle')['id']
    for pid, target in [('a', folder), ('b', child), ('missing', child), ('outside', 1), ('recycled', recycle)]:
        storage.upsert_paper({'paper_id':pid, 'title':'Synthetic paper ' + pid, 'journal':'Fixture',
                             'doi':'' if pid == 'missing' else '10.1234/' + pid})
        storage.add_library_item(paper_id=pid, folder_id=target)
    storage.add_library_item(paper_id='a', folder_id=child)
    placements = [tuple(r) for r in storage.conn.execute('SELECT * FROM library_items')]
    release, first = threading.Event(), threading.Event()
    calls = []

    def refresh(store, paper_id, **options):
        calls.append((paper_id, options['mode']))
        if not first.is_set():
            first.set()
            if not release.wait(15):
                raise RuntimeError('Fixture release timed out')
        paper = store.get_paper(paper_id)
        report = {'status':'unchanged', 'mode':options['mode'], 'changed_fields':[],
                  'sources':{'Crossref':'found'}, 'message':'No new metadata found.',
                  'checked_at':jobs.stamp()}
        store.update_paper_raw_json(paper_id, {'metadata_refresh': report})
        return {'paper':store.get_paper(paper_id), 'metadata_refresh':report}

    class Handler(ui.PaperMonitorUiHandler):
        configured_db_path = db
        def log_message(self, *args): pass
        def do_GET(self):
            if urlparse(self.path).path in ('/api/arxiv-daily-refresh','/api/author-monitor/summary','/api/my-publications/work','/api/my-publications/jobs'):
                self.send_json({}); return
            super().do_GET()
        def do_POST(self):
            path = urlparse(self.path).path
            if path == '/qa/release':
                release.set(); self.send_json({}); return
            if path.startswith('/api/library/metadata-refresh/'):
                super().do_POST(); return
            self.send_error(405)

    with patch.object(work, '_refresh', side_effect=refresh), patch.object(ui, 'request_with_retries', side_effect=AssertionError('No external provider traffic')):
        server = ui.FastLocalThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            fixture = root / 'fixture.json'
            fixture.write_text(json.dumps({'url':f'http://127.0.0.1:{server.server_port}/',
                'token':server.workspace_access.token, 'folder_id':folder, 'recycle_id':recycle}))
            subprocess.run([sys.argv[1], 'tests/metadata_jobs_ui_probe.cjs', str(fixture)], check=True, timeout=90)
            assert calls == [('a','quick'), ('b','quick')], calls
            assert placements == [tuple(r) for r in storage.conn.execute('SELECT * FROM library_items')]
            print('Synthetic API: scope, deduplication, pause/resume, cooldown and unchanged placements passed.')
        finally:
            release.set()
            server.shutdown(); server.server_close(); thread.join()
            storage.close()
