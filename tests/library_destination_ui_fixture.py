"""Full product page and endpoints backed only by temporary synthetic data."""
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

with tempfile.TemporaryDirectory(prefix='gewu-destination-ui-') as temp, ExitStack() as patches:
    root=Path(temp); db=root/'fixture.sqlite'; store=Storage(db)
    for name in ('LIBRARY_LOCAL_COPY_ROOT','SPACES_LOCAL_COPY_ROOT','MY_PUBLICATIONS_LOCAL_COPY_ROOT','DEFAULT_PDF_DIR','ASSOCIATED_FILES_ROOT'):
        patches.enter_context(patch.object(ui,name,root/name))
    parent=store.create_library_folder(parent_id=1,name='Reading')
    inbox=store.create_library_folder(parent_id=parent['id'],name='Inbox')
    long_folder=store.create_library_folder(parent_id=parent['id'],name='Long folder name for testing destination layout and independent folder selection')
    space=store.create_library_root_folder(name='Project Space')
    store.set_setting("library_workspace_tabs",json.dumps([{'root_folder_id':space['id'],'label':'Project Space'}]))
    recycle=ui.ensure_library_special_folders(store)['recycle']
    for key in ('journal','subject','author'):
        store.upsert_paper({'paper_id':key,'title':'Synthetic '+key+' paper','journal':'Fixture'})
    class Handler(ui.PaperMonitorUiHandler):
        configured_db_path=db
        def log_message(self,*args): pass
        def do_GET(self):
            if urlparse(self.path).path in ('/api/arxiv-daily-refresh','/api/author-monitor/summary','/api/my-publications/work','/api/my-publications/jobs'):
                self.send_json({});return
            super().do_GET()
        def do_POST(self):
            if urlparse(self.path).path not in ('/api/settings/add-to-library','/api/library/items'):
                self.send_error(405);return
            super().do_POST()
    patches.enter_context(patch.object(ui,'request_with_retries',side_effect=AssertionError('No external traffic')))
    server=ui.FastLocalThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        fixture=root/'fixture.json'
        fixture.write_text(json.dumps({'url':f'http://127.0.0.1:{server.server_port}/','token':server.workspace_access.token,
            'parent_id':parent['id'],'inbox_id':inbox['id'],'space_id':space['id'],'recycle_id':recycle['id'],'long_id':long_folder['id']}))
        subprocess.run([sys.argv[1],'tests/library_destination_ui_probe.cjs',str(fixture)],check=True,timeout=150)
        rows=list(store.conn.execute('SELECT paper_id,folder_id FROM library_items ORDER BY paper_id'))
        assert [(r['paper_id'],r['folder_id']) for r in rows]==[(key,space['id']) for key in ('author','journal','subject')]
        assert store.conn.execute('SELECT count(*) FROM resources').fetchone()[0]==0
        print('Synthetic settings/Monitor API: selected destinations persisted; no Paper Files created or changed.')
    finally:
        server.shutdown();server.server_close();thread.join();store.close()
