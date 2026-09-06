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
    def test_tabs_preserve_webkit_configuration_and_do_not_hook_password_delivery(self):
        source = (ROOT / "scripts/GewuBrowserController.m").read_text()
        popup = source.split('- (WKWebView *)webView:', 1)[1].split('- (void)webViewDidClose:', 1)[0]
        self.assertIn('configuration:configuration', popup)
        self.assertNotIn('loadRequest:', popup)
        self.assertIn('WebMenuItemTagOpenLinkInNewWindow', source)
        self.assertIn('Open Link in New Tab', source)
        switch = source.split('- (void)selectTab:', 1)[1].split('- (GewuBrowserTab *)addTabWithRequest:', 1)[0]
        self.assertNotIn('stopLoading', switch)
        self.assertNotIn('loadRequest:', switch)
        self.assertIn('self.webView == view', source)
        ui = (ROOT / 'paper_monitor/browser_ui.js').read_text()
        renderer = ui.split('function renderTabs()', 1)[1].split('function newTab(', 1)[0]
        self.assertIn('existing.get(tab.id)', renderer)
        self.assertNotIn('.focus(', renderer)

    def test_home_is_local_and_never_loads_a_google_document(self):
        source = (ROOT / 'scripts/GewuBrowserController.m').read_text()
        home = source.split('- (void)showHomeRecordingVisit:', 1)[1].split('- (void)openContentRequest:', 1)[0]
        self.assertNotIn('loadRequest:', home)
        self.assertNotIn('loadHTMLString:', home)
        self.assertIn('self.homePage.ready = YES', home)
        self.assertIn('self.homePage.view.hidden = YES', source)
        self.assertIn('@"home":@(home)', source)

    def test_local_home_does_not_modify_remote_page_styles_or_zoom(self):
        source = (ROOT / "scripts/GewuBrowserController.m").read_text()
        self.assertNotIn('fitHomeGeneration', source)
        self.assertNotIn('scheduleHomeFit', source)
        self.assertNotIn('pageZoom', source)
        self.assertNotIn('gewu-insight-home-surface', source)
        self.assertNotIn('GewuBrowserGoogleHome', source)
        ui = (ROOT / 'paper_monitor/browser_ui.js').read_text()
        self.assertIn('updateHome(event.home === true)', ui)
        self.assertIn('Home — Favorites', ui)

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
        self.assertIn("page.navigationRequestedDownload = action.shouldPerformDownload", policy)
        self.assertIn("GewuBrowserResponsePolicy(response.response, response.canShowMIMEType", source)
        self.assertIn("GewuBrowserHTTPSRecoveryURL(error, page.mainNavigationRequest", source)
        self.assertIn("NSURL *url = self.currentPage.failedURL ?: self.webView.URL", source)
        self.assertNotIn("NSURLSession", source)
        plist = plistlib.loads((ROOT / "Gewu Insight.app/Contents/Info.plist").read_bytes())
        ats = plist.get("NSAppTransportSecurity", {})
        self.assertFalse(ats.get("NSAllowsArbitraryLoads", False))
        self.assertFalse(ats.get("NSAllowsArbitraryLoadsInWebContent", False))

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("xcrun"), "macOS compiler required")
    def test_home_reuse_and_navigation_with_fake_surfaces(self):
        with tempfile.TemporaryDirectory(prefix="gewu-home-session-test-") as directory:
            executable = Path(directory) / "home-test"
            env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(Path(directory) / "modules"))
            build = subprocess.run([
                "xcrun", "clang", "-fobjc-arc", "-framework", "Cocoa", "-framework", "WebKit",
                "-framework", "ImageIO", "-framework", "UniformTypeIdentifiers", "-I", str(ROOT / "scripts"),
                str(ROOT / "tests/browser_home_session_probe.m"), str(ROOT / "scripts/GewuBrowserFavicons.m"),
                str(ROOT / "scripts/GewuBrowserAutoFill.m"),
                "-o", str(executable),
            ], capture_output=True, text=True, env=env, timeout=90)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("checks passed", result.stdout)

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
