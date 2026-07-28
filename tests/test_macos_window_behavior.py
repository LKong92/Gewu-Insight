from __future__ import annotations

import unittest
from pathlib import Path

from paper_monitor.ui_server import INDEX_HTML


ROOT = Path(__file__).resolve().parents[1]


class MacosWindowBehaviorTests(unittest.TestCase):
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

        self.assertIn("@interface DaiqoWindow : NSWindow", source)
        self.assertIn('setObject:@"None" forKey:@"AppleActionOnDoubleClick"', source)
        self.assertIn("- (void)sendEvent:(NSEvent *)event", source)
        self.assertIn("event.clickCount == 2", source)
        self.assertIn("distanceFromTop <= 40.0", source)
        self.assertIn("- (void)performMiniaturize:(id)sender", source)
        self.assertIn("- (void)performZoom:(id)sender", source)
        self.assertIn("[self handleTitlebarDoubleClickAction]", source)
        self.assertIn("[strongSelf toggleMainWindowFill]", source)
        self.assertNotIn("DaiqoTitlebarGestureView", source)
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
