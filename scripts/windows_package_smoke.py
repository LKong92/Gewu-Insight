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
                for endpoint in ("/", "/api/health", "/api/library/bootstrap", "/api/settings/website-links",
                                 "/user-guide", "/user-guide.pdf", "/browser-ui.js"):
                    with opener.open(base + endpoint, timeout=15) as response:
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
