from __future__ import annotations

import plistlib
import subprocess
import unittest
from pathlib import Path

from paper_monitor.ui_server import INDEX_HTML


ROOT = Path(__file__).resolve().parents[1]


class MacosWindowBehaviorTests(unittest.TestCase):
    def test_loading_pages_use_the_packaged_icon_and_subtle_brand_art(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        loading_view = source.split("@implementation GewuStartupView", 1)[1].split("@end", 1)[0]
        self.assertIn('URLForResource:@"GewuInsightAppIcon"', loading_view)
        self.assertIn('URLForResource:@"GewuSealGlyphs"', loading_view)
        self.assertIn("Starting Gewu Insight", loading_view)
        self.assertIn("NSRectFill(self.bounds)", loading_view)
        self.assertIn("drawRect:", loading_view)
        self.assertNotIn("WKWebView", loading_view)
        creation = source.split("- (void)createWindow", 1)[1].split("- (void)userContentController:", 1)[0]
        self.assertLess(creation.index("[self showLoadingPage]"), creation.index("makeKeyAndOrderFront"))
        loading_page = source.split("- (void)showLoadingPage", 1)[1].split("- (void)dismissStartupOverlay", 1)[0]
        self.assertIn("GewuStartupView alloc", loading_page)
        self.assertNotIn("loadHTMLString", loading_page)
        self.assertIn('objectForInfoDictionaryKey:@"CFBundleIconFile"', source)
        self.assertIn('URLForResource:applicationIconName', source)
        self.assertIn('withExtension:@"png"', source)
        self.assertIn("applicationIcon.template = NO;", source)
        self.assertIn("NSApp.applicationIconImage = applicationIcon;", source)

        self.assertIn('parsed.path == "/api/app-icon"', (ROOT / "paper_monitor" / "ui_server.py").read_text())
        self.assertIn('parsed.path == "/api/startup-brand-art"', (ROOT / "paper_monitor" / "ui_server.py").read_text())
        self.assertIn('class="app-startup-brand-art" src="/api/startup-brand-art"', INDEX_HTML)
        self.assertNotIn('class="app-runtime-watermark"', INDEX_HTML)
        self.assertIn(".runtime-branded-empty {", INDEX_HTML)
        self.assertIn(".runtime-empty-brand-crop {", INDEX_HTML)
        self.assertIn('function runtimeEmptyBrandArtMarkup(extraClass = "")', INDEX_HTML)
        self.assertIn('class="runtime-empty-brand-art" src="/api/startup-brand-art" alt=""', INDEX_HTML)
        self.assertIn("width: clamp(150px, 16vw, 210px);", INDEX_HTML)
        self.assertIn("opacity: .04;", INDEX_HTML)
        self.assertIn("--runtime-empty-brand-right: -23px;", INDEX_HTML)
        self.assertIn("--runtime-empty-brand-bottom: -15px;", INDEX_HTML)
        self.assertNotIn(".library-detail:has(> .library-folder-brand-art)", INDEX_HTML)
        self.assertIn("width: 460px", INDEX_HTML)
        self.assertIn("right: -28px", INDEX_HTML)
        self.assertIn("width: 236px", INDEX_HTML)
        self.assertNotIn("mix-blend-mode: multiply", INDEX_HTML)
        self.assertGreater(INDEX_HTML.index('class="app-startup-brand-art"'), INDEX_HTML.index('class="app-startup-card"'))
        self.assertNotIn('-webkit-mask: url("/api/startup-brand-art")', INDEX_HTML)
        self.assertIn('class="app-startup-icon" src="/api/app-icon"', INDEX_HTML)
        web_icon_shell_css = INDEX_HTML.split(".app-startup-icon-shell {", 1)[1].split("}", 1)[0]
        self.assertNotIn("border:", web_icon_shell_css)
        self.assertNotIn("background:", web_icon_shell_css)
        self.assertNotIn("box-shadow:", web_icon_shell_css)
        self.assertNotIn('class="app-startup-chinese-name"', INDEX_HTML)
        self.assertNotIn('class="app-startup-brand-seal"', INDEX_HTML)
        self.assertNotIn('<div class="app-startup-icon">D</div>', INDEX_HTML)

    def test_dock_and_startup_icons_use_the_current_versioned_asset(self) -> None:
        app = ROOT / "Gewu Insight.app"
        resources = app / "Contents" / "Resources"
        source_icon = ROOT / "assets" / "gewu-insight-app-icon.png"
        expected_build = subprocess.check_output(
            ["cksum", str(source_icon)], text=True
        ).split()[0]
        expected_name = f"GewuInsightAppIcon-{expected_build}"
        with (app / "Contents" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)

        self.assertEqual(info["CFBundleIconFile"], expected_name)
        from paper_monitor import __build__, __version__
        self.assertEqual(info["CFBundleVersion"], str(__build__))
        self.assertEqual(info["CFBundleShortVersionString"], __version__)
        self.assertTrue((resources / f"{expected_name}.icns").is_file())
        self.assertEqual(
            (resources / f"{expected_name}.png").read_bytes(),
            source_icon.read_bytes(),
        )
        self.assertEqual(
            (resources / "GewuInsightAppIcon.png").read_bytes(),
            source_icon.read_bytes(),
        )

        build_script = (ROOT / "scripts" / "build_macos_app.sh").read_text()
        self.assertIn('APP_ICON_BASENAME="GewuInsightAppIcon-$APP_ICON_CACHE_KEY"', build_script)
        self.assertIn('touch "$APP"', build_script)

    def test_native_about_panel_uses_bundle_identity_and_explicit_credits(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()
        build_script = (ROOT / "scripts" / "build_macos_app.sh").read_text()
        app = ROOT / "Gewu Insight.app"
        with (app / "Contents" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)

        self.assertIn('addItemWithTitle:@"About Gewu Insight"', source)
        self.assertIn("- (void)showAboutWindow", source)
        self.assertIn("NSApp.applicationIconImage", source)
        self.assertIn('objectForInfoDictionaryKey:@"CFBundleShortVersionString"', source)
        self.assertIn('objectForInfoDictionaryKey:@"CFBundleVersion"', source)
        self.assertIn('objectForInfoDictionaryKey:@"NSHumanReadableCopyright"', source)
        self.assertIn('withString:@".\\nAll Rights Reserved."', source)
        self.assertIn("copyrightDisplay", source)
        self.assertIn('@"格物洞见"', source)
        self.assertNotIn('aboutLabelWithString:@"格物洞见"', source)
        self.assertIn('URLForResource:@"GewuAboutCalligraphy"', source)
        self.assertIn("calligraphyImage.template = YES", source)
        self.assertIn("calligraphyView.contentTintColor = NSColor.secondaryLabelColor", source)
        self.assertIn('ABOUT_CALLIGRAPHY_SOURCE="$PROJECT_DIR/assets/branding/GewuAboutCalligraphy.png"', build_script)
        self.assertIn('cp "$ABOUT_CALLIGRAPHY_SOURCE" "$ABOUT_CALLIGRAPHY_DEST"', build_script)
        self.assertIn(
            '@"Your personal research workspace where papers,\\nevidence, and files stay connected over time."',
            source,
        )
        self.assertIn("taglineLabel.maximumNumberOfLines = 2", source)
        self.assertIn("const CGFloat width = 336.0", source)
        self.assertIn("const CGFloat height = 380.0", source)
        self.assertIn("self.aboutWindow.titleVisibility = NSWindowTitleVisible", source)
        self.assertIn("self.aboutWindow.titlebarAppearsTransparent = NO", source)
        self.assertIn("aboutLinkButtonWithTitle", source)
        self.assertIn("button.bordered = NO", source)
        self.assertIn("button.contentTintColor = NSColor.linkColor", source)
        self.assertNotIn(
            'aboutLabelWithString:@"SQLite is the source of truth.', source
        )
        self.assertIn("Designed and developed by Lingyuan Kong and Zhengran Wu,", source)
        self.assertIn("with coding assistance from OpenAI Codex.", source)
        self.assertNotIn("Developed with coding assistance from OpenAI Codex.", source)
        self.assertIn('aboutLinkButtonWithTitle:@"User Guide"', source)
        self.assertIn('aboutLinkButtonWithTitle:@"GitHub"', source)
        self.assertIn('addScriptMessageHandler:self name:@"openUserGuidePDF"', source)
        self.assertIn('message.name isEqualToString:@"openUserGuidePDF"', source)
        self.assertIn('URLForResource:@"Gewu Insight User Guide" withExtension:@"pdf"', source)
        self.assertIn('@"/System/Applications/Preview.app"', source)
        self.assertEqual(
            info["NSHumanReadableCopyright"],
            "Copyright © 2026 Lingyuan Kong and Zhengran Wu. All rights reserved.",
        )

        self.assertIn("NSHumanReadableCopyright", build_script)

    def test_repository_license_and_readme_match_about_attribution(self) -> None:
        license_text = (ROOT / "LICENSE").read_text()
        readme = (ROOT / "README.md").read_text()

        for document in [license_text, readme]:
            self.assertIn("Copyright © 2026 Lingyuan Kong and Zhengran Wu", document)
            self.assertIn("All rights reserved", document)
        normalized_license = " ".join(license_text.lower().split())
        self.assertIn("not offered under an open-source license", normalized_license)
        self.assertIn("Developed with coding assistance from **OpenAI Codex**", readme)
        self.assertIn("[LICENSE](LICENSE)", readme)
        self.assertNotIn("Licensed under the MIT License", readme)

        resources = ROOT / "Gewu Insight.app" / "Contents" / "Resources"
        self.assertEqual((resources / "LICENSE.txt").read_bytes(), (ROOT / "LICENSE").read_bytes())
        self.assertEqual(
            (resources / "THIRD_PARTY_NOTICES.md").read_bytes(),
            (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes(),
        )

        self.assertTrue(readme.startswith("# Gewu Insight\n"))
        self.assertIn("**Keep research objects visible", readme)
        self.assertIn("## Platform support", readme)
        self.assertIn("the current native desktop release", readme)
        self.assertIn("developed separately on the experimental Windows branch", readme)
        self.assertIn("do not establish Windows feature parity", readme)
        self.assertIn("## Name and Chinese origin", readme)
        self.assertGreater(readme.index("格物洞见"), readme.index("## Name and Chinese origin"))

    def test_native_startup_overlay_persists_until_library_is_ready(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn("@property(nonatomic, strong) GewuStartupView *startupView;", source)
        self.assertIn('name:@"appReady"', source)
        self.assertIn('[message.name isEqualToString:@"appReady"]', source)
        self.assertIn("[self dismissStartupOverlay];", source)
        self.assertIn("[self.window.contentView addSubview:self.startupView", source)
        self.assertIn("overlay.animator.alphaValue = 0.0;", source)
        self.assertIn("[overlay removeFromSuperview];", source)
        self.assertIn("[self.webView loadRequest:[self workspaceRequestForURL:self.url]];", source)

        self.assertIn("function finishAppStartup()", INDEX_HTML)
        self.assertIn("window.webkit?.messageHandlers?.appReady", INDEX_HTML)
        self.assertIn('nativeReady.postMessage({status: "ready"});', INDEX_HTML)
        self.assertIn("requestAnimationFrame(() => requestAnimationFrame(finishAppStartup));", INDEX_HTML)

    def test_native_launcher_allows_slow_first_run_database_migrations(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn("GewuInsightServerStartupTimeout = 120.0", source)
        self.assertIn(
            "self.serverStartupDeadline = [NSDate dateWithTimeIntervalSinceNow:GewuInsightServerStartupTimeout];",
            source,
        )
        self.assertIn("compare:self.serverStartupDeadline", source)
        self.assertNotIn("self.attempts >= 80", source)

    def test_native_launcher_recovers_an_unexpected_server_exit_before_alerting(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()
        termination_handler = source.split("task.terminationHandler", 1)[1].split(
            "NSError *error", 1
        )[0]
        recovery = source.split("- (void)recoverServerAfterUnexpectedExit", 1)[1].split(
            "- (void)checkServerWithCompletion", 1
        )[0]

        self.assertIn("self.applicationIsTerminating = YES;", source)
        self.assertIn("strongSelf.ownedServerTask = nil", termination_handler)
        self.assertIn("recoverServerAfterUnexpectedExit", termination_handler)
        self.assertNotIn("presentStartupFailure", termination_handler)
        self.assertIn("[self checkServerWithCompletion", recovery)
        self.assertIn("if ([self restartServerForCurrentOutageIfPossible])", recovery)
        self.assertIn("[self beginServerReadinessPolling]", recovery)
        self.assertIn("GewuInsightServerMaxRestartAttempts = 3", source)
        self.assertIn("Native launcher observed server", source)
        self.assertIn("if (self.applicationIsTerminating || self.startupFailurePresented) return;", source)

    def test_native_launcher_dismisses_stale_failure_after_server_recovers(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()
        failure = source.split("- (void)presentStartupFailure", 1)[1].split(
            "- (void)appendLauncherLogMessage", 1
        )[0]

        self.assertIn("beginSheetModalForWindow:self.window", failure)
        self.assertNotIn("[alert runModal]", failure)
        self.assertIn("recheckServerWhileStartupFailureIsVisible", failure)
        self.assertIn("[self dismissStartupFailureAlert];", source)
        self.assertIn("if (available)", failure)
        self.assertIn("[self loadApp];", failure)

    def test_non_pdf_library_preview_uses_macos_quick_look_without_replacing_pdf_preview(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()
        build_script = (ROOT / "scripts" / "build_macos_app.sh").read_text()

        self.assertIn("#import <Quartz/Quartz.h>", source)
        self.assertIn("QLPreviewPanelDataSource", source)
        self.assertIn('addScriptMessageHandler:self name:@"nativeQuickLook"', source)
        self.assertIn('message.name isEqualToString:@"nativeQuickLook"', source)
        self.assertIn("showNativeQuickLookForPath", source)
        self.assertIn("addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown", source)
        self.assertIn("handleGewuInsightNativeQuickLookKey", source)
        self.assertIn("dispatchNativeQuickLookKey", source)
        self.assertIn("nativeQuickLookKeyDispatchInFlight", source)
        self.assertIn("nativeQuickLookPendingKey", source)
        self.assertIn("scheduleNativeQuickLookReload", source)
        self.assertIn("restoreMainWindowFocusForNativeQuickLook", source)
        self.assertIn("panel.becomesKeyOnlyIfNeeded = YES", source)
        self.assertIn("numberOfPreviewItemsInPreviewPanel", source)
        self.assertIn("previewItemAtIndex", source)
        self.assertIn("window.closeGewuInsightNativeQuickLookFromNative", source)
        self.assertIn("-framework Quartz", build_script)

    def test_title_bar_double_click_requests_native_fill_toggle(self) -> None:
        drag_region = INDEX_HTML.split("function wireWindowDragRegion", 1)[1].split(
            '$("reportMode")', 1
        )[0]

        self.assertIn('region.addEventListener("dblclick"', drag_region)
        self.assertIn("event.target !== region", drag_region)
        self.assertIn('post("toggleFill", event);', drag_region)

    def test_native_fill_toggle_restores_previous_frame(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn('[type isEqualToString:@"toggleFill"]', source)
        self.assertIn("self.windowRestoreFrame = currentFrame;", source)
        self.assertIn("NSRect visibleFrame = screen.visibleFrame;", source)
        self.assertIn("[self.window setFrame:targetFrame display:YES animate:YES];", source)
        self.assertNotIn("toggleFullScreen", source)

    def test_native_window_leaves_titlebar_hit_testing_to_the_web_ui(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn("@interface GewuInsightWindow : NSWindow", source)
        self.assertIn('setObject:@"None" forKey:@"AppleActionOnDoubleClick"', source)
        event_dispatch = source.split("- (void)sendEvent:(NSEvent *)event", 1)[1].split("- (void)beginNativeWindowDrag", 1)[0]
        self.assertIn("[super sendEvent:event]", event_dispatch)
        self.assertNotIn("performWindowDragWithEvent", event_dispatch)
        self.assertNotIn("handleTitlebarDoubleClickAction", source)
        self.assertNotIn("titlebarDoubleClickHandler", source)
        self.assertNotIn("distanceFromTop <= 40.0", source)
        self.assertNotIn("GewuInsightTitlebarGestureView", source)
        self.assertNotIn("[self.webView addSubview:self.titlebarGestureView", source)
        self.assertIn("[self.window deminiaturize:nil]", source)

    def test_quicklook_uses_native_pdf_zoom_without_showing_webkit_hud(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn('name:@"pdfPreviewState"', source)
        self.assertIn('containsString:@"WKPDFHUDView"', source)
        self.assertIn("view.hidden = YES;", source)
        self.assertIn("- (void)magnifyWithEvent:(NSEvent *)event", source)
        self.assertIn('@"performPDFZoomIn"', source)
        self.assertIn('@"performPDFZoomOut"', source)
        self.assertIn('@"_performActionForControl:"', source)
        self.assertIn('@"plus.magnifyingglass"', source)
        self.assertIn('@"minus.magnifyingglass"', source)

    def test_quicklook_header_opens_the_original_pdf_in_preview(self) -> None:
        self.assertIn('id="openLibraryQuickLookInPreview"', INDEX_HTML)
        self.assertIn("async function openLibraryQuickLookInPreview()", INDEX_HTML)
        self.assertIn("await openLibraryPdfInPreview({merged_pdf_path: path});", INDEX_HTML)
        self.assertIn("setNativePdfQuickLookActive(true);", INDEX_HTML)
        self.assertIn("setNativePdfQuickLookActive(false);", INDEX_HTML)
        self.assertIn('<iframe class="library-pdf-frame"', INDEX_HTML)
        self.assertNotIn("pdfjsLib", INDEX_HTML)

    def test_command_w_closes_quicklook_before_the_main_window(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn("((GewuInsightWebView *)self.webView).pdfQuickLookActive", source)
        self.assertIn("window.closeGewuInsightPreviewFromNative", source)
        self.assertLess(
            source.index("window.closeGewuInsightPreviewFromNative"),
            source.index("[activeWindow performClose:sender];"),
        )
        self.assertIn("function handlePreviewCloseShortcut(event)", INDEX_HTML)
        self.assertIn("String(event.key || \"\").toLowerCase() !== \"w\"", INDEX_HTML)
        self.assertIn("closeLibraryQuickLook({restoreFocus: true})", INDEX_HTML)
        self.assertIn("captureLibraryQuickLookReturnFocus();", INDEX_HTML)
        self.assertIn("restoreLibraryQuickLookReturnFocus(returnFocus)", INDEX_HTML)
        self.assertIn("state.libraryQuickLookReturnFocus", INDEX_HTML)

    def test_native_publisher_download_accepts_science_supplements(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn('[path hasPrefix:@"/doi/suppl/"]', source)
        self.assertIn('rangeOfString:@"/suppl_file/"', source)
        self.assertIn("publisher_download_kind: browserFallback.kind", INDEX_HTML)
        self.assertIn("aaas-supplement-discovery", source)
        self.assertIn("document.querySelectorAll('a[href], iframe[src], embed[src]')", source)
        self.assertIn("/\\\\.pdf$/i.test(path)", source)
        self.assertIn("supplement_urls", INDEX_HTML)
        self.assertIn('payload[@"publisher_download_kind"] = @"aaas-supplement-pdf";', source)
        self.assertIn("supplement_attached", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
