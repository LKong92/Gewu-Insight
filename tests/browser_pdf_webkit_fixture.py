"""Run the native PDF probe against generated localhost fixtures only."""
import base64
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import threading
import time
from reportlab.pdfgen import canvas

stream = BytesIO()
c = canvas.Canvas(stream)
c.drawString(72, 720, 'Gewu generated PDF download test')
c.save()
PDF = stream.getvalue()
counts = Counter()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        counts['GET ' + self.path] += 1
        if self.path == '/start':
            body = ("<!doctype html><title>PDF fixture</title><input id='draft' value='keep me'>"
                    "<a id='attachment' href='/attachment?download=true'>PDF download</a>"
                    "<a id='popup' target='_blank' href='/attachment?popup=true'>PDF popup</a>"
                    "<a id='slow' href='/slow'>Slow PDF</a>"
                    "<form action='/post' method='post'><input name='ticket' value='one-use'><button id='post'>POST PDF</button></form>"
                    "<script>window.fixtureBase64='" + base64.b64encode(PDF).decode() + "';</script>").encode()
            self.reply(body, 'text/html')
        elif self.path == '/other':
            self.reply(b'<!doctype html><title>Other fixture</title><input id="draft" value="working">', 'text/html')
        elif self.path == '/not-pdf':
            self.reply(b'<html>Sign in required</html>', 'application/pdf', True)
        elif self.path == '/slow':
            self.reply(PDF, 'application/pdf', True, slow=True)
        elif self.path == '/binary':
            self.reply(PDF, 'application/octet-stream', True)
        elif self.path == '/inline':
            self.reply(PDF, 'application/pdf')
        elif self.path.startswith('/attachment'):
            self.reply(PDF, 'application/pdf', True)
        else:
            self.send_error(404)

    def do_POST(self):
        counts['POST ' + self.path] += 1
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path == '/post' and body == b'ticket=one-use':
            self.reply(PDF, 'application/pdf', True)
        elif self.path == '/api/browser-capture-file':
            if body != PDF or self.headers.get('X-Gewu-Capture-Token') != 'synthetic-capture-token-0123456789abcdef':
                self.send_error(400)
            else:
                self.reply(b'{"ok":true}', 'application/json')
        else:
            self.send_error(400)

    def reply(self, body, mime, attachment=False, slow=False):
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        if attachment:
            self.send_header('Content-Disposition', 'attachment; filename="Generated.pdf"')
        self.end_headers()
        try:
            if slow:
                self.wfile.write(body[:20]); self.wfile.flush(); time.sleep(2)
                self.wfile.write(body[20:])
            else:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    result = subprocess.run([sys.argv[1], 'http://127.0.0.1:' + str(server.server_port)], timeout=150)
    server.shutdown()
    if result.returncode:
        raise SystemExit(result.returncode)
assert counts['POST /post'] == 1 and counts['GET /post'] == 0, counts
assert counts['POST /api/browser-capture-file'] == 1, counts
print('Fixture requests: POST performed exactly once; displayed PDF uploaded byte-for-byte; no live websites.')
