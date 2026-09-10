"""Installed service acceptance on disposable data, without a developer Python path."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--install", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
install = args.install.resolve()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
result = {"service": "embedded CPython", "runs": []}
with tempfile.TemporaryDirectory(prefix="gewu-installed-check-", dir=output) as temporary:
    workspace = Path(temporary)
    env = os.environ.copy()
    env.update(GEWU_WORKSPACE_ROOT=str(workspace), GEWU_DATA_ROOT=str(workspace / "data"),
               GEWU_DOCUMENTATION_MODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8", TEMP=str(workspace), TMP=str(workspace))
    for key in ("PYTHONPATH", "PYTHONHOME", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"):
        env.pop(key, None)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    service = install / "service"
    seed = '''
import io, os
from pathlib import Path
from pypdf import PdfWriter
from paper_monitor.storage import Storage
from paper_monitor import ui_server as ui
storage = Storage(Path(os.environ['GEWU_DATA_ROOT']) / 'paper_monitor.sqlite')
ui.ensure_library_special_folders(storage)
storage.upsert_paper({'paper_id':'package-fixture','title':'Packaged MCP fixture','journal':'Fixture','source':'fixture','raw':{}})
storage.add_library_item(paper_id='package-fixture', folder_id=1)
writer=PdfWriter(); writer.add_blank_page(width=612,height=792)
content=io.BytesIO(); writer.write(content)
ui.attach_file_to_paper(storage,paper_id='package-fixture',filename='Fixture.pdf',content=content.getvalue(),file_type='preprint')
storage.close()
'''
    subprocess.run([str(service / 'python.exe'), '-c', seed], cwd=install, env=env,
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    ai_config = None
    note_id = None
    for cycle in range(2):
        with socket.socket() as socket_:
            socket_.bind(("127.0.0.1", 0))
            port = socket_.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        with (output / f"service-{cycle}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([str(service / "python.exe"), "-B", str(service / "service_entry.py"),
                                        "ui", "--host", "127.0.0.1", "--port", str(port)],
                                       cwd=install, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Installed service stopped; see service log")
                    try:
                        opener.open(base + "/api/health", timeout=1).close()
                        break
                    except OSError:
                        time.sleep(0.2)
                else:
                    raise TimeoutError("Installed service was not ready")
                checks = {}
                token = (workspace / 'data' / '.gewu-workspace-token').read_text(encoding='utf-8').strip()
                for endpoint in ("/", "/api/health", "/api/library/bootstrap", "/api/settings/website-links",
                                 "/user-guide", "/user-guide.pdf", "/browser-ui.js"):
                    request = urllib.request.Request(base + endpoint, headers={'X-Gewu-Workspace': token})
                    with opener.open(request, timeout=15) as response:
                        body = response.read()
                        assert body, endpoint
                        checks[endpoint] = response.status
                request = urllib.request.Request(base + "/api/library/bootstrap", headers={"Origin": "https://example.com", "Sec-Fetch-Site": "cross-site"})
                try:
                    opener.open(request, timeout=5).close()
                    raise AssertionError("Cross-site Library access was accepted")
                except urllib.error.HTTPError as error:
                    assert error.code == 403, error.code
                    checks["cross_site_api_blocked"] = True
                def admin(payload):
                    request = urllib.request.Request(base + '/api/settings/ai-access',
                        headers={'X-Gewu-Workspace': token, 'Content-Type':'application/json'},
                        data=json.dumps(payload).encode())
                    with opener.open(request, timeout=15) as response:
                        return json.load(response)
                if ai_config is None:
                    admin({'action':'enable','enabled':True})
                    created = admin({'action':'create','name':'Packaged fixture','selection':{'kind':'saved'},
                        'scopes':['papers:read','files:read','analysis:write']})
                    ai_config = created['mcp_config']['mcpServers']['gewu-insight']
                    assert Path(ai_config['command']).resolve() == (service/'python.exe').resolve()
                    assert Path(ai_config['args'][0]).is_file()
                with closing(sqlite3.connect(workspace/'data/paper_monitor.sqlite')) as connection:
                    key = connection.execute("SELECT storage_key FROM papers WHERE paper_id='package-fixture'").fetchone()[0]
                messages = [
                    {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},
                    {'jsonrpc':'2.0','method':'notifications/initialized'},
                    {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                    {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'read_paper','arguments':{'gewu_key':key,'page_count':1}}},
                    {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'save_analysis','arguments':{'gewu_key':key,'markdown':'# 隔离验证\n\n这是安装包的合成分析。','request_id':'package-fixture-note'}}},
                    {'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':'get_paper_file','arguments':{'gewu_key':key}}},
                    {'jsonrpc':'2.0','id':6,'method':'tools/call','params':{'name':'get_paper_file','arguments':{'gewu_key':key}}},
                ]
                # Reuse the original config after the port changes in cycle 2.
                completed = subprocess.run([ai_config['command'], *ai_config['args']], input='\n'.join(json.dumps(m) for m in messages)+'\n',
                    text=True, encoding='utf-8', capture_output=True, timeout=45, cwd=workspace,
                    env={**env, **ai_config['env']}, creationflags=subprocess.CREATE_NO_WINDOW)
                assert completed.returncode == 0, 'Packaged MCP adapter failed'
                replies = [json.loads(line) for line in completed.stdout.splitlines()]
                assert len(replies) == 6 and len(replies[1]['result']['tools']) == 5
                assert not replies[2]['result']['isError'] and not replies[3]['result']['isError'], 'Packaged read/save failed'
                assert 'get_paper_file' in {tool['name'] for tool in replies[1]['result']['tools']}
                assert all(not reply['result']['isError'] for reply in replies[4:6]), 'Packaged original-file/repeat delivery failed'
                copies = [json.loads(reply['result']['content'][0]['text']) for reply in replies[4:6]]
                assert copies[0]['sha256'] == copies[1]['sha256']
                assert copies[0]['delivery']['local_path'] == copies[1]['delivery']['local_path']
                assert not Path(copies[0]['delivery']['local_path']).exists(), 'MCP exit left delivered file behind'
                checks['original_pdf_delivery_repeat_and_exit_cleanup'] = True
                with closing(sqlite3.connect(workspace/'data/paper_monitor.sqlite')) as connection:
                    notes = connection.execute("SELECT id,stored_path FROM resources WHERE added_via='ai_analysis'").fetchall()
                    assert len(notes) == 1
                    if note_id is not None: assert note_id == notes[0][0]
                    note_id = notes[0][0]
                    assert '这是安装包的合成分析。' in Path(notes[0][1]).read_text(encoding='utf-8')
                    assert connection.execute('PRAGMA user_version').fetchone()[0] == 18
                checks['packaged_mcp_read_chinese_save_retry'] = True
                checks['original_mcp_config_after_restart'] = cycle == 1
                result["runs"].append(checks)
            finally:
                process.terminate()
                process.wait(timeout=15)
        with closing(sqlite3.connect(workspace / "data" / "paper_monitor.sqlite")) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    result["database_restart_integrity"] = "passed"
    result["isolated_workspace_removed"] = True
(output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
