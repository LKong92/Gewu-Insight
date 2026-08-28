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

        loading_page = source.split("- (void)showLoadingPage", 1)[1].split(
            "- (void)ensureServerThenLoad", 1
        )[0]
        self.assertIn("src='GewuInsightAppIcon.png'", loading_page)
        icon_shell_css = loading_page.split('".icon-shell{', 1)[1].split('}"', 1)[0]
        self.assertNotIn("border:", icon_shell_css)
        self.assertNotIn("background:", icon_shell_css)
        self.assertNotIn("box-shadow:", icon_shell_css)
        self.assertIn("Starting Gewu Insight", loading_page)
        self.assertIn("brand-art", loading_page)
        self.assertIn("src='GewuSealGlyphs.png'", loading_page)
        self.assertIn("width:460px", loading_page)
        self.assertIn("right:-28px;top:-66px;width:236px;height:236px", loading_page)
        self.assertNotIn("mix-blend-mode:multiply", loading_page)
        self.assertGreater(loading_page.index("class='brand-art'"), loading_page.index("class='card'"))
        self.assertNotIn("-webkit-mask", loading_page)
        self.assertNotIn("格物洞见", loading_page)
        self.assertNotIn("brand-seal", loading_page)
        self.assertIn("baseURL:[NSBundle mainBundle].resourceURL", loading_page)
        self.assertIn("self.startupWebView", loading_page)
        self.assertIn("[self.startupWebView loadHTMLString:html", loading_page)
        self.assertNotIn("[self.webView loadHTMLString:html", loading_page)
        self.assertNotIn("<div class='icon'>G</div>", loading_page)
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
        self.assertEqual(info["CFBundleVersion"], expected_build)
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
        self.assertIn('APP_ICON_BASENAME="GewuInsightAppIcon-$APP_ICON_BUILD_VERSION"', build_script)
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
        self.assertIn("const CGFloat height = 340.0", source)
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
        self.assertIn('addScriptMessageHandler:self name:@"printUserGuide"', source)
        self.assertIn('message.name isEqualToString:@"printUserGuide"', source)
        self.assertIn("printOperationWithPrintInfo", source)
        self.assertIn("runOperationModalForWindow:self.userGuideWindow", source)
        self.assertIn("userGuidePrintOperationDidRun:success:contextInfo:", source)
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

        self.assertTrue(readme.startswith("# Gewu Insight\n\n**Keep research objects visible"))
        self.assertIn("## Platform support", readme)
        self.assertIn("the current native desktop release", readme)
        self.assertIn("planned as an experimental desktop release", readme)
        self.assertIn("not yet a supported distribution", readme)
        self.assertIn("## Name and Chinese origin", readme)
        self.assertGreater(readme.index("格物洞见"), readme.index("## Name and Chinese origin"))

    def test_native_startup_overlay_persists_until_library_is_ready(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn("@property(nonatomic, strong) WKWebView *startupWebView;", source)
        self.assertIn('name:@"appReady"', source)
        self.assertIn('[message.name isEqualToString:@"appReady"]', source)
        self.assertIn("[self dismissStartupOverlay];", source)
        self.assertIn("[self.window.contentView addSubview:self.startupWebView", source)
        self.assertIn("overlay.animator.alphaValue = 0.0;", source)
        self.assertIn("[overlay removeFromSuperview];", source)
        self.assertIn("[self.webView loadRequest:[NSURLRequest requestWithURL:self.url]];", source)

        self.assertIn("function finishAppStartup()", INDEX_HTML)
        self.assertIn("window.webkit?.messageHandlers?.appReady", INDEX_HTML)
        self.assertIn('nativeReady.postMessage({status: "ready"});', INDEX_HTML)
        self.assertIn("requestAnimationFrame(() => requestAnimationFrame(finishAppStartup));", INDEX_HTML)

    def test_title_bar_double_click_requests_native_fill_toggle(self) -> None:
        drag_region = INDEX_HTML.split("function wireWindowDragRegion", 1)[1].split(
            '$("reportMode")', 1
        )[0]

        self.assertIn('region.addEventListener("dblclick"', drag_region)
        self.assertIn('post("toggleFill", event);', drag_region)

    def test_native_fill_toggle_restores_previous_frame(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn('[type isEqualToString:@"toggleFill"]', source)
        self.assertIn("self.windowRestoreFrame = currentFrame;", source)
        self.assertIn("NSRect visibleFrame = screen.visibleFrame;", source)
        self.assertIn("[self.window setFrame:targetFrame display:YES animate:YES];", source)
        self.assertNotIn("toggleFullScreen", source)

    def test_native_window_consumes_system_titlebar_double_click_action(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()

        self.assertIn("@interface GewuInsightWindow : NSWindow", source)
        self.assertIn('setObject:@"None" forKey:@"AppleActionOnDoubleClick"', source)
        self.assertIn("- (void)sendEvent:(NSEvent *)event", source)
        self.assertIn("event.clickCount == 2", source)
        self.assertIn("distanceFromTop <= 40.0", source)
        self.assertIn("- (void)performMiniaturize:(id)sender", source)
        self.assertIn("- (void)performZoom:(id)sender", source)
        self.assertIn("[self handleTitlebarDoubleClickAction]", source)
        self.assertIn("[strongSelf toggleMainWindowFill]", source)
        self.assertNotIn("GewuInsightTitlebarGestureView", source)
        self.assertNotIn("[self.webView addSubview:self.titlebarGestureView", source)
        self.assertIn("[self.window deminiaturize:nil]", source)
        self.assertIn("- (void)windowWillMiniaturize:(NSNotification *)notification", source)
        self.assertIn("- (void)windowDidMiniaturize:(NSNotification *)notification", source)
        self.assertIn("recoverTitlebarDoubleClickMiniaturize", source)
        self.assertIn("return;", source)

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
