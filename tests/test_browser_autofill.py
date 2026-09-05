"""Credential-free regression contracts for the conservative login trigger."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrowserAutoFillTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("xcrun"), "macOS compiler required")
    def test_only_the_system_autofill_menu_password_item_is_eligible(self):
        with tempfile.TemporaryDirectory(prefix="gewu-autofill-menu-test-") as directory:
            output = Path(directory) / "menu-test"
            build = subprocess.run(["xcrun", "clang", "-fobjc-arc", "-framework", "Cocoa", "-framework", "WebKit",
                                    "-I", str(ROOT / "scripts"), str(ROOT / "tests/browser_autofill_policy_probe.m"), "-o", str(output)],
                                   env=dict(os.environ, CLANG_MODULE_CACHE_PATH=str(Path(directory)/"modules")),
                                   text=True, capture_output=True, timeout=90)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(output)], text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("8 native menu-boundary checks passed", result.stdout)
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_login_semantics_and_races_without_reading_values(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/browser_login_probe.cjs")],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checks passed", result.stdout)

    def test_trigger_does_not_manage_credentials_or_change_focus(self):
        source = (ROOT / "scripts/GewuBrowserAutoFill.m").read_text()
        for forbidden in ("SecItem", "ASPasswordCredential", "insertText", "makeFirstResponder", "NSPasteboard",
                          "AXUIElement", "AXIsProcessTrusted", "NSSelectorFromString", "setInterval", "setTimeout"):
            self.assertNotIn(forbidden, source)
        for contract in ("NSEventTypeLeftMouseUp", "event.clickCount != 1", "isKeyWindow", "GewuBrowserPublicURL",
                         "worldWithName:", "self.attempted.count >= 128", "@\"confirm\"", "view == self.pendingView",
                         "view != self.pendingView", "accessibilityPerformPress", "cancelTrackingWithoutAnimation"):
            self.assertIn(contract, source)

    def test_bundle_contains_the_exact_probe_and_no_page_bridge_is_added(self):
        source = ROOT / "scripts/GewuBrowserLoginProbe.js"
        bundled = ROOT / "Gewu Insight.app/Contents/Resources/GewuBrowserLoginProbe.js"
        self.assertEqual(source.read_bytes(), bundled.read_bytes())
        native = (ROOT / "scripts/GewuBrowserController.m").read_text()
        self.assertNotIn("addScriptMessageHandler", native)
        self.assertNotIn("addUserScript", native)
        self.assertIn("NSEventMaskLeftMouseDragged", native)
        self.assertIn("[self.loginTrigger cancelPending]", native)
