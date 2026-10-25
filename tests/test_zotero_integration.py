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
