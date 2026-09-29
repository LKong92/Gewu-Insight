"""Run the native parity regression on a separate hidden desktop and scratch DB."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import win32con
import win32event
import win32job
import win32process
import win32service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--dotnet", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--publisher-only", action="store_true", help="Run only publisher and download integration checks")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(repo / "tmp"):
        parser.error("Native probe output must be inside this repository's tmp directory.")
    workspace = output / ("native-" + uuid.uuid4().hex)
    workspace.mkdir(parents=True)
    desktop_name = "GewuParity_" + uuid.uuid4().hex
    desktop = win32service.CreateDesktop(desktop_name, 0, win32con.GENERIC_ALL, None)
    job = win32job.CreateJobObject(None, "GewuParityJob_" + uuid.uuid4().hex)
    limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
    environment = os.environ.copy()
    environment.update(
        GEWU_DOCUMENTATION_MODE="1", PYTHONUNBUFFERED="1", PYTHONUTF8="1",
        GEWU_WORKSPACE_ROOT=str(workspace), GEWU_DATA_ROOT=str(workspace / "data"),
        TEMP=str(workspace), TMP=str(workspace), DOTNET_ROOT=str(args.dotnet.resolve()),
    )
    for name in ("PYTHONPATH", "PYTHONHOME", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"):
        environment.pop(name, None)
    startup = win32process.STARTUPINFO()
    startup.lpDesktop = "WinSta0\\" + desktop_name
    startup.dwFlags = win32con.STARTF_USESHOWWINDOW
    startup.wShowWindow = win32con.SW_HIDE
    executable = args.app.resolve()
    command = subprocess.list2cmdline([
        str(executable), "--workspace", str(workspace), "--source", str(repo),
        "--python", str(args.python.resolve()),
    ] + (["--publisher-only"] if args.publisher_only else []))
    process = thread = None
    result = {"success": False, "workspace": str(workspace)}
    print(json.dumps({"workspace": str(workspace), "hidden_desktop": True}), flush=True)
    try:
        process, thread, pid, _ = win32process.CreateProcess(
            str(executable), command, None, None, False,
            win32con.CREATE_SUSPENDED | win32con.CREATE_UNICODE_ENVIRONMENT,
            environment, str(repo), startup,
        )
        try:
            win32job.AssignProcessToJobObject(job, process)
        except Exception:
            win32process.TerminateProcess(process, 1)
            raise
        win32process.ResumeThread(thread)
        deadline = time.monotonic() + 210
        report = workspace / "native-results.json"
        while time.monotonic() < deadline:
            if report.exists():
                result.update(json.loads(report.read_text(encoding="utf-8")))
                break
            code = win32process.GetExitCodeProcess(process)
            if code != win32con.STILL_ACTIVE:
                result["process_exit_code"] = code
                break
            time.sleep(0.2)
        else:
            result["error"] = "Native probe exceeded its deadline"
    finally:
        job.Close()
        if process:
            win32event.WaitForSingleObject(process, 5000)
            process.Close()
        if thread:
            thread.Close()
        desktop.CloseDesktop()
        result["test_process_tree_closed"] = True
        (output / "latest-native-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
