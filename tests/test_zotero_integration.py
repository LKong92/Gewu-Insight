"""Companion setup uses an existing database and never touches Zotero's profile."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from paper_monitor import zotero_integration as integration

ROOT = Path(__file__).resolve().parents[1]

class ZoteroIntegrationTests(unittest.TestCase):
    def test_plugin_detection_requires_registry_and_package_and_distinguishes_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "profiles.ini").write_text("[Profile0]\nPath=Profiles/default\nIsRelative=1\nDefault=1\n")
            profile = root / "Profiles/default"
            (profile / "extensions").mkdir(parents=True)
            registry = profile / "extensions.json"
            addon = {"id": integration.PLUGIN_ID, "version": "0.2.3"}
            registry.write_text(json.dumps({"addons": [addon]}))
            self.assertEqual(integration.installed_plugin(root)["state"], "not_installed")
            (profile / "extensions" / (integration.PLUGIN_ID + ".xpi")).write_bytes(b"fixture")
            self.assertEqual(integration.installed_plugin(root), {"state": "installed", "version": "0.2.3"})
            addon["userDisabled"] = True
            registry.write_text(json.dumps({"addons": [addon]}))
            self.assertEqual(integration.installed_plugin(root)["state"], "disabled")
            registry.write_text("incomplete")
            self.assertEqual(integration.installed_plugin(root)["state"], "unknown")

    def test_versions_compare_numerically_and_never_offer_downgrades(self):
        self.assertTrue(integration.newer_version("0.3.0", "0.2.3"))
        self.assertTrue(integration.newer_version("0.2.10", "0.2.9"))
        for bundled, installed in [("0.3.0", "0.3"), ("0.3.0", "0.4.0"), ("0.3.0", "unknown")]:
            self.assertFalse(integration.newer_version(bundled, installed))

    def test_presence_expires_after_crash_and_late_heartbeat_cannot_reopen_closed_tab(self):
        now = [100.0]
        sessions = integration.ZoteroSessions(clock=lambda: now[0])
        beat = {"action": "heartbeat", "session": "tab-123456", "handoff_request": "request-1234567890"}
        self.assertTrue(sessions.update(beat)["active"])
        self.assertEqual(sessions.status()["handoff_requests"], [beat["handoff_request"]])
        sessions.update({"action": "close", "session": beat["session"]})
        self.assertFalse(sessions.update(beat)["active"])
        beat["session"] = "tab-654321"
        sessions.update(beat)
        now[0] += 13
        self.assertFalse(sessions.status()["active"])
        self.assertEqual(sessions.status()["handoff_requests"], [])

    def test_presence_of_another_tab_survives_one_tab_closing(self):
        sessions = integration.ZoteroSessions()
        for name in ["session-1", "session-2"]:
            sessions.update({"action": "heartbeat", "session": name})
        self.assertTrue(sessions.update({"action": "close", "session": "session-1"})["active"])
        self.assertFalse(sessions.update({"action": "close", "session": "session-2"})["active"])

    def test_package_has_complete_host_and_no_machine_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "plugin.xpi"
            subprocess.run([sys.executable, str(ROOT / "scripts/build_zotero_plugin.py"), "--output", str(package)], check=True, capture_output=True)
            with ZipFile(package) as archive:
                names=set(archive.namelist())
                self.assertIn("workspace-source.js", names)
                self.assertIn("web-child.mjs", names)
                self.assertIn("pdf-preview.js", names)
                self.assertIn("pdf-resources.js", names)
                self.assertFalse(any("token" in n or "sqlite" in n or "test" in n for n in names))
                manifest=json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["name"], "Gewu Insight")
                self.assertEqual(manifest["applications"]["zotero"]["id"], integration.PLUGIN_ID)

    def test_setup_binds_existing_identity_without_copying_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            support=Path(directory)/"preferences"
            workspace=Path(directory)/"database"
            with patch("paper_monitor.workspace.database_identity", return_value="fixture-identity"), \
                patch.object(integration, "package_info", return_value=(Path(directory)/"companion.xpi", {"version":"0.2.0"})), \
                patch.object(integration.sys,"platform","darwin"), patch.object(integration.subprocess,"run") as run:
                result=integration.configure(workspace,"http://127.0.0.1:8878","open", support)
                config=json.loads((support/"zotero-connection.json").read_text())
                self.assertTrue(result["ok"])
                self.assertEqual(config["database_uuid"],"fixture-identity")
                self.assertEqual(config["workspace"],str(workspace.resolve()))
                self.assertNotIn("token",config)
                self.assertEqual((support/"zotero-connection.json").stat().st_mode & 0o777,0o600)
                self.assertEqual(run.call_args.args[0][1:3],["-a","/Applications/Zotero.app"])
                self.assertTrue(run.call_args.args[0][-1].startswith("zotero://gewu-insight/open?request="))
                self.assertFalse(workspace.exists())

    def test_missing_database_does_not_create_an_empty_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(integration.sys,"platform","darwin"), patch.object(integration.subprocess,"run") as run:
                with self.assertRaises(ValueError):
                    integration.configure(Path(directory)/"missing","http://127.0.0.1:8878","open",Path(directory)/"settings")
                run.assert_not_called()
                self.assertEqual(list(Path(directory).iterdir()),[])
