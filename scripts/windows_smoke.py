"""Run the portable entry point in a disposable, complete workspace.

This is a product smoke check, not a desktop/installer acceptance test. No
personal database, subjects, credentials, bookmarks or research files are copied.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
CORE_TESTS = (
    "test_browser_bookmarks.py", "test_browser_capture.py",
    "test_inventory_importer.py", "test_paper_files_vnext.py",
    "test_paper_source_observations.py", "test_pdf_ingress.py",
    "test_resource_fingerprint.py", "test_timezone_portability.py",
)


def run(output: Path, *, tests: bool, test_patterns: list[str] | None = None) -> int:
    output.mkdir(parents=True, exist_ok=True)
    result = {"platform": platform.platform(), "python": sys.version,
              "desktop_verified": False, "tests": {}}
    with tempfile.TemporaryDirectory(prefix="gewu-windows-smoke-") as temporary:
        workspace = Path(temporary)
        for name in ("paper_monitor", "tests", "scripts", "assets"):
            shutil.copytree(ROOT / name, workspace / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "README.md", workspace / "README.md")
        (workspace / "config").mkdir()
        shutil.copy2(ROOT / "config" / "journals.json", workspace / "config" / "journals.json")
        scratch = workspace / "scratch"
        scratch.mkdir()
        env = os.environ.copy()
        env.update(GEWU_DATA_ROOT=str(workspace / "data"), GEWU_WORKSPACE_ROOT=str(workspace),
                   GEWU_DOCUMENTATION_MODE="1", TEMP=str(scratch), TMP=str(scratch),
                   PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        for key in ("PYTHONPATH", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"):
            env.pop(key, None)
        # Source-relative reports/config are isolated by the complete code copy.
        # Documentation mode suppresses automatic monitors and WebKit cleanup.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with (output / "server.log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "paper_monitor", "ui", "--port", str(port)],
                cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError(f"UI exited with code {server.returncode}; see server.log")
                    try:
                        with opener.open(base + "/api/health", timeout=1) as response:
                            result["health"] = json.load(response)
                        break
                    except OSError:
                        time.sleep(0.15)
                else:
                    raise TimeoutError("UI did not become healthy in 30 seconds")
                with opener.open(base, timeout=5) as response:
                    page = response.read().decode("utf-8")
                result["ui"] = {label: label in page for label in (
                    "Library", "My Publications", "Journal Monitor", "Subject Monitor",
                    "Author Monitor", "Browser", "Paper Files")}
                if not all(result["ui"].values()):
                    raise AssertionError("The served page is missing a product area")
                result["entry_point"] = "passed (automatic monitors disabled)"
            except Exception as error:
                result["entry_point"] = str(error)
            finally:
                server.terminate()
                server.wait(timeout=15)
        if tests or test_patterns:
            for filename in test_patterns or CORE_TESTS:
                with (output / (filename + ".log")).open("w", encoding="utf-8") as log:
                    completed = subprocess.run(
                        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", filename, "-v"],
                        cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT,
                        timeout=120)
                result["tests"][filename] = completed.returncode
                print(f"{filename}: exit {completed.returncode}", flush=True)
    (output / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(not str(result.get("entry_point", "")).startswith("passed")
               or any(result["tests"].values()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Diagnostic output directory (keep out of Git).")
    parser.add_argument("--tests", action="store_true", help="Also run the bounded portable product suite.")
    parser.add_argument("--test-pattern", action="append", help="Run an additional scoped unittest file pattern instead of the default suite.")
    args = parser.parse_args()
    raise SystemExit(run(args.output.resolve(), tests=args.tests, test_patterns=args.test_pattern))
