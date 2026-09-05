"""Executable native policy regression tests; no user data or network requests."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BrowserNativeNavigationTests(unittest.TestCase):
    def test_context_menu_keeps_system_insertion_target_in_remote_webview(self):
        native = (ROOT / "scripts/GewuBrowserController.m").read_text()
        view = native.split("@implementation GewuBrowserWebView", 1)[1].split("@end", 1)[0]
        self.assertLess(view.index("makeFirstResponder:self"), view.index("[super willOpenMenu:"))
        self.assertIn("!self.hidden", view)
        self.assertNotIn("insertText", view)
        self.assertNotIn("evaluateJavaScript", view)
        self.assertNotIn("SecItemCopyMatching", native)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("xcrun"), "macOS compiler required")
    def test_compiled_response_recovery_and_redacted_error_policies(self):
        with tempfile.TemporaryDirectory(prefix="gewu-browser-native-test-") as directory:
            executable = Path(directory) / "navigation-test"
            env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(Path(directory) / "modules"))
            build = subprocess.run([
                "xcrun", "clang", "-fobjc-arc", "-framework", "Foundation", "-framework", "WebKit",
                "-I", str(ROOT / "scripts"), str(ROOT / "tests/browser_navigation_probe.m"),
                "-o", str(executable),
            ], capture_output=True, text=True, env=env, timeout=90)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("checks passed", result.stdout)

    def test_navigation_waits_for_mime_without_weakening_transport_security(self):
        source = (ROOT / "scripts/GewuBrowserController.m").read_text()
        policy = source.split("decidePolicyForNavigationAction:", 1)[1].split("createWebViewWithConfiguration:", 1)[0]
        self.assertNotIn("WKNavigationActionPolicyDownload", policy)
        self.assertIn("self.navigationRequestedDownload = action.shouldPerformDownload", policy)
        self.assertIn("GewuBrowserResponsePolicy(response.response, response.canShowMIMEType", source)
        self.assertIn("GewuBrowserHTTPSRecoveryURL(error, self.mainNavigationRequest", source)
        self.assertIn("NSURL *url = self.failedURL ?: self.webView.URL", source)
        self.assertNotIn("NSURLSession", source)
        plist = plistlib.loads((ROOT / "Gewu Insight.app/Contents/Info.plist").read_bytes())
        ats = plist.get("NSAppTransportSecurity", {})
        self.assertFalse(ats.get("NSAllowsArbitraryLoads", False))
        self.assertFalse(ats.get("NSAllowsArbitraryLoadsInWebContent", False))

    def test_favicons_are_bounded_private_and_passwords_remain_system_owned(self):
        source = (ROOT / "scripts/GewuBrowserFavicons.m").read_text()
        for contract in ["self.tasks.count >= 2", "self.pending.count >= 64", "HTTPCookieStorage = nil", "URLCredentialStorage = nil", "HTTPShouldHandleCookies = NO", "524288", "65536", "kCGImageSourceThumbnailMaxPixelSize", "NSURLSessionAuthChallengePerformDefaultHandling"]:
            self.assertIn(contract, source)
        for service in ["google.com/s2", "duckduckgo.com", "icon.horse"]:
            self.assertNotIn(service, source)
        native = (ROOT / "scripts/GewuBrowserController.m").read_text()
        self.assertIn('URLForApplicationWithBundleIdentifier:@"com.apple.Passwords"', native)
        self.assertNotIn("SecItemCopyMatching", native)
        self.assertNotIn("ASPasswordCredential", native)
        ui = (ROOT / "paper_monitor/browser_ui.js").read_text()
        self.assertIn("new IntersectionObserver", ui)
        self.assertIn('id="browserImportBookmarks"', ui)
        self.assertIn('id="browserExportBookmarks"', ui)


if __name__ == "__main__":
    unittest.main()
