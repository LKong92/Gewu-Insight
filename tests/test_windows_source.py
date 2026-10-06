"""Real Windows workspace exclusion and source-service authentication checks."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from unittest.mock import patch

from scripts.windows_source import ROOT as SOURCE_ROOT, WorkspaceLock, desktop_executable, desktop_launch, workspace_path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "win32", "Windows workspace lock")
class WindowsSourceTests(unittest.TestCase):
    def test_missing_saved_library_never_creates_a_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            selection = home / ".gewu-insight/preview-workspace.txt"
            selection.parent.mkdir()
            missing = home / "missing"
            selection.write_text(str(missing), encoding="utf-8")
            with patch("pathlib.Path.home", return_value=home):
                with self.assertRaisesRegex(ValueError, "Selected Library is unavailable"):
                    workspace_path(None)
            self.assertFalse(missing.exists())

    def test_new_workspace_does_not_reuse_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "keep.txt").write_text("keep")
            with self.assertRaisesRegex(ValueError, "empty directory"):
                workspace_path(workspace, create=True)
            self.assertEqual((workspace / "keep.txt").read_text(), "keep")

    def test_service_authentication_duplicate_launch_and_restart(self):
        import win32con
        import win32event
        import win32job
        import win32process

        with tempfile.TemporaryDirectory(prefix="gewu-source-test-") as temporary:
            workspace = Path(temporary)
            env = os.environ.copy()
            env.update(GEWU_DOCUMENTATION_MODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            command = [sys.executable, "-B", str(ROOT / "scripts/windows_source.py"),
                       "--workspace", str(workspace), "--web", "--no-open"]
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            # The log must stay outside the explicitly empty new workspace.
            # The venv redirector can create a child interpreter. Own the whole
            # disposable process tree so termination cannot leave a service alive.
            with tempfile.TemporaryFile() as log:
                job = win32job.CreateJobObject(None, "GewuSourceTest_" + uuid.uuid4().hex)
                limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
                limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
                process, thread, _, _ = win32process.CreateProcess(
                    None, subprocess.list2cmdline(command + ["--new-workspace"]),
                    None, None, False, win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW,
                    env, str(ROOT), win32process.STARTUPINFO())
                try:
                    win32job.AssignProcessToJobObject(job, process)
                    win32process.ResumeThread(thread)
                    deadline = time.monotonic() + 30
                    base = None
                    endpoint = workspace / "data/.gewu-api-url"
                    while time.monotonic() < deadline:
                        if win32process.GetExitCodeProcess(process) != win32con.STILL_ACTIVE:
                            self.fail("Source launcher exited before becoming ready")
                        if endpoint.exists():
                            try:
                                base = endpoint.read_text().strip()
                                with opener.open(base + "/api/health", timeout=1) as response:
                                    self.assertEqual(response.status, 200)
                                break
                            except OSError:
                                pass
                        time.sleep(.1)
                    else:
                        self.fail("Source service did not start")
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        opener.open(base + "/api/library/bootstrap", timeout=5)
                    self.assertEqual(denied.exception.code, 401)
                    token = (workspace / "data/.gewu-workspace-token").read_text().strip()
                    request = urllib.request.Request(base + "/api/library/bootstrap",
                                                     headers={"X-Gewu-Workspace": token})
                    with opener.open(request, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                    second = subprocess.run(command, env=env, cwd=ROOT, capture_output=True,
                                            text=True, encoding="utf-8", timeout=10,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(second.returncode, 1)
                    self.assertIn("already open", second.stderr)
                finally:
                    win32job.TerminateJobObject(job, 0)
                    self.assertEqual(win32event.WaitForSingleObject(process, 10000), win32con.WAIT_OBJECT_0)
                    thread.Close()
                    process.Close()
                    job.Close()
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with WorkspaceLock(workspace):
                            break
                    except RuntimeError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.05)
            # A stale lock file must not prevent reopening after process exit.
            with WorkspaceLock(workspace):
                with self.assertRaisesRegex(RuntimeError, "already open"):
                    with WorkspaceLock(workspace):
                        self.fail("Duplicate lock was accepted")

    def test_desktop_refuses_busy_workspace_before_spawning(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with WorkspaceLock(workspace), patch("subprocess.Popen") as launch, \
                    patch("scripts.windows_source.desktop_executable", return_value=Path(sys.executable)):
                with self.assertRaisesRegex(RuntimeError, "already open"):
                    desktop_launch(workspace, Path(sys.executable))
            launch.assert_not_called()

    def test_desktop_imports_source_and_keeps_help_paths(self):
        with tempfile.TemporaryDirectory() as temporary, patch("subprocess.Popen") as launch, \
                patch("scripts.windows_source.desktop_executable", return_value=Path(sys.executable)):
            workspace = Path(temporary)
            launch.return_value.pid = 123
            with patch.dict(os.environ, {"PYTHONHOME": "unrelated", "PYTHONPATH": "unrelated"}):
                self.assertEqual(desktop_launch(workspace, Path(sys.executable)), 0)
            command = launch.call_args.args[0]
            self.assertEqual(command[command.index("--source") + 1], str(SOURCE_ROOT / "windows"))
            self.assertEqual(command[command.index("--workspace") + 1], str(workspace))
            environment = launch.call_args.kwargs["env"]
            self.assertEqual(environment["PYTHONPATH"], str(SOURCE_ROOT))
            self.assertNotIn("PYTHONHOME", environment)
            self.assertTrue((Path(command[command.index("--source") + 1]) / "Windows_Preview_Guide.html").is_file())

    def test_desktop_missing_shell_does_not_fall_back_to_browser(self):
        with tempfile.TemporaryDirectory() as temporary, patch("subprocess.Popen") as launch:
            workspace = Path(temporary)
            with self.assertRaisesRegex(FileNotFoundError, "desktop shell was not found"):
                desktop_launch(workspace, workspace / "missing.exe")
            launch.assert_not_called()

    def test_older_shell_cannot_silently_claim_current_source_parity(self):
        with patch("win32api.GetFileVersionInfo", return_value={"FileVersionMS": 1, "FileVersionLS": 19 << 16}):
            with self.assertRaisesRegex(RuntimeError, "0.1.21 or later; found 0.1.19"):
                desktop_executable(Path(sys.executable))


if __name__ == "__main__":
    unittest.main()
