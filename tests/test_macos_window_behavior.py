from __future__ import annotations

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
        self.assertIn("src='PaperMonitor.png'", loading_page)
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

        self.assertIn('parsed.path == "/api/app-icon"', (ROOT / "paper_monitor" / "ui_server.py").read_text())
        self.assertIn('parsed.path == "/api/startup-brand-art"', (ROOT / "paper_monitor" / "ui_server.py").read_text())
        self.assertIn('class="app-startup-brand-art" src="/api/startup-brand-art"', INDEX_HTML)
        self.assertIn("width: 460px", INDEX_HTML)
        self.assertIn("right: -28px", INDEX_HTML)
        self.assertIn("width: 236px", INDEX_HTML)
        self.assertNotIn("mix-blend-mode: multiply", INDEX_HTML)
        self.assertGreater(INDEX_HTML.index('class="app-startup-brand-art"'), INDEX_HTML.index('class="app-startup-card"'))
        self.assertNotIn('-webkit-mask: url("/api/startup-brand-art")', INDEX_HTML)
        self.assertIn('class="app-startup-icon" src="/api/app-icon"', INDEX_HTML)
        self.assertNotIn('class="app-startup-chinese-name"', INDEX_HTML)
        self.assertNotIn('class="app-startup-brand-seal"', INDEX_HTML)
        self.assertNotIn('<div class="app-startup-icon">D</div>', INDEX_HTML)

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
