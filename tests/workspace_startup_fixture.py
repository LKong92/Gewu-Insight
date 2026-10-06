"""Read-only product startup on a new temporary database; no worker is started."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlparse
from paper_monitor import ui_server as ui
from paper_monitor.storage import Storage

with tempfile.TemporaryDirectory(prefix='gewu-startup-') as temp:
    root=Path(temp); db=root/'data/test.sqlite'
    storage=Storage(db)
    folder=storage.create_library_folder(parent_id=1,name='Nested fixture')
    storage.close()
    class Handler(ui.PaperMonitorUiHandler):
        configured_db_path=db
        def log_message(self,*args):pass
        def do_GET(self):
            path=urlparse(self.path).path
            if path in ('/api/arxiv-daily-refresh','/api/author-monitor/summary','/api/my-publications/work','/api/my-publications/jobs'):
                self.send_json({});return
            return super().do_GET()
        def do_POST(self):self.send_error(405)
    # No fixture may contact an external metadata provider.
    with patch.object(ui,'request_with_retries',side_effect=AssertionError('Startup must not contact external providers')):
        server=ui.FastLocalThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            fixture=root/'fixture.json'
            fixture.write_text(json.dumps({'url':f'http://127.0.0.1:{server.server_port}/','token':server.workspace_access.token,'folder_id':folder['id']}))
            subprocess.run([sys.argv[1],str(fixture)],check=True,timeout=45)
        finally:
            server.shutdown();server.server_close();thread.join()
