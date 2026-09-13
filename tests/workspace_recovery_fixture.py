"""Minimal workspace gate fixture; no research database, jobs or external URLs."""
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import tempfile
import threading
from paper_monitor.local_access import WorkspaceAccess, LOCKED_WORKSPACE_HTML
with tempfile.TemporaryDirectory(prefix='gewu-recovery-') as tmp:
    root=Path(tmp)
    access=WorkspaceAccess(root/'data/test.sqlite')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            ok=access.accepts(self.headers)
            body=b'<p id="authenticated">Synthetic workspace</p>' if ok else LOCKED_WORKSPACE_HTML.encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html')
            if ok:self.send_header('Set-Cookie',access.cookie())
            self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        fixture=root/'fixture.json';fixture.write_text(json.dumps({'data':str(root/'data'),'url':f'http://127.0.0.1:{server.server_port}/'}))
        subprocess.run([sys.argv[1],str(fixture)],check=True,timeout=55)
    finally:
        server.shutdown();server.server_close();thread.join()
