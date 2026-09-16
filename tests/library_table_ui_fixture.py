"""Exercise the product UI with temporary papers, folders and intercepted metadata."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from contextlib import ExitStack
from unittest.mock import patch
from urllib.parse import urlparse
from paper_monitor import ui_server as ui
from paper_monitor.storage import Storage

with tempfile.TemporaryDirectory(prefix='gewu-table-ui-') as temp, ExitStack() as patches:
    root = Path(temp)
    store = Storage(root / 'fixture.sqlite')
    for name in ('LIBRARY_LOCAL_COPY_ROOT', 'SPACES_LOCAL_COPY_ROOT', 'MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'DEFAULT_PDF_DIR', 'ASSOCIATED_FILES_ROOT'):
        patches.enter_context(patch.object(ui, name, root / name))
    parent = store.create_library_folder(parent_id=1, name='Reading')
    space = ui.add_library_workspace_tab(store, name='Interferometry')
    shortcut = ui.add_library_shortcut_tab(store, folder_id=parent['id'])
    nested = store.create_library_folder(parent_id=space['root_folder_id'], name='Experiments')
    nested_library = store.create_library_folder(parent_id=parent['id'], name='Experiments')
    recycle = ui.ensure_library_special_folders(store)['recycle']
    roots = [parent['id'], nested_library['id'], space['root_folder_id'], nested['id']]
    for pid, title, authors, date, journal in [
        ('alpha', 'Alpha wave', ['Zoe Lee'], '2026-01-01', 'Nature'),
        ('beta', 'Beta interference', ['Alice Zhang'], '2022-03-01', 'Science'),
        ('gamma', 'Gamma phase', ['Bob Wu'], '2024-02-01', 'Applied Physics'),
        ('unknown', 'Unknown metadata', [], '', ''),
    ]:
        store.upsert_paper({'paper_id':pid, 'title':title, 'raw':{'author':[{'given':a.split()[0], 'family':a.split()[1]} for a in authors]}, 'publication_date':date, 'journal':journal})
        for folder_id in roots:
            store.add_library_item(paper_id=pid, folder_id=folder_id)
    patches.enter_context(patch.object(ui, 'library_workspace_publication_from_query', side_effect=lambda q: {'paper_id':'added-'+q, 'title':'Added '+q, 'journal':'Test Journal', 'authors':['New Author']}))
    for name in ('refresh_pubmed_if_possible','refresh_semantic_scholar_if_possible','refresh_ads_if_possible'):
        patches.enter_context(patch.object(ui, name, return_value=None))
    patches.enter_context(patch.object(ui, 'request_with_retries', side_effect=AssertionError('No external traffic')))
    class Handler(ui.PaperMonitorUiHandler):
        configured_db_path = root / 'fixture.sqlite'
        def log_message(self, *args): pass
        def do_GET(self):
            if urlparse(self.path).path in ('/api/arxiv-daily-refresh','/api/author-monitor/summary','/api/my-publications/work','/api/my-publications/jobs'):
                self.send_json({}); return
            super().do_GET()
        def do_POST(self):
            if urlparse(self.path).path not in ('/api/library/add-paper','/api/library/navigation-tabs/add-paper','/api/library/workspace-tabs/rename','/api/library/shortcut-tabs/rename','/api/library/workspace-tabs/move-to-library'):
                self.send_error(405); return
            super().do_POST()
    server = ui.FastLocalThreadingHTTPServer(('127.0.0.1',0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        fixture = root / 'fixture.json'
        fixture.write_text(json.dumps({'url':f'http://127.0.0.1:{server.server_port}/', 'token':server.workspace_access.token,
            'parent_id':parent['id'], 'space_id':space['root_folder_id'], 'nested_id':nested['id'],
            'nested_library_id':nested_library['id'], 'recycle_id':recycle['id']}))
        subprocess.run([sys.argv[1], 'tests/library_table_ui_probe.cjs', str(fixture)], check=True, timeout=150)
        assert store.conn.execute('SELECT count(*) FROM resources').fetchone()[0] == 0
        print('Temporary API fixtures only; zero Paper Files changed.')
    finally:
        server.shutdown(); server.server_close(); thread.join(); store.close()
