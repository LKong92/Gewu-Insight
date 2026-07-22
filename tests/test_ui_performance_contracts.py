from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from paper_monitor import ui_server


ROOT = Path(__file__).resolve().parents[1]


class UiPerformanceContractTests(unittest.TestCase):
    @staticmethod
    def js_function(name: str) -> str:
        marker = f"function {name}"
        start = ui_server.INDEX_HTML.index(marker)
        candidates = [
            position
            for position in (
                ui_server.INDEX_HTML.find("\n    function ", start + len(marker)),
                ui_server.INDEX_HTML.find("\n    async function ", start + len(marker)),
            )
            if position >= 0
        ]
        end = min(candidates) if candidates else len(ui_server.INDEX_HTML)
        return ui_server.INDEX_HTML[start:end]

    def test_launcher_uses_small_health_endpoint(self) -> None:
        route_source = inspect.getsource(ui_server.PaperMonitorUiHandler.do_GET)
        launcher_source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()
        helper_source = (ROOT / "Daiqo.app" / "Contents" / "MacOS" / "Paper Monitor Server").read_text()

        self.assertIn('parsed.path == "/api/health"', route_source)
        self.assertIn('@"api/health"', launcher_source)
        self.assertIn('HEALTH_URL="$URL/api/health"', helper_source)
        self.assertNotIn('curl -fsS "$URL"', helper_source)

    def test_navigation_refresh_does_not_replace_library_with_navigation_only_data(self) -> None:
        refresh = self.js_function("refreshLibrarySnapshotForNavigation")

        self.assertIn('/api/library/paper-locations', refresh)
        self.assertIn("applyLibraryNavigationSnapshot(data);", refresh)
        self.assertNotIn("applyLibrarySnapshot(data);", refresh)

    def test_common_library_mutations_request_incremental_responses(self) -> None:
        for function_name in (
            "commitLibraryEntryRename",
            "moveLibraryEntry",
            "deleteLibraryEntry",
            "recoverLibraryEntry",
        ):
            function_body = self.js_function(function_name)
            self.assertIn("snapshot: false", function_body, function_name)

    def test_import_completion_uses_bootstrap_refresh(self) -> None:
        for function_name in ("refreshLibraryAfterImportReady", "refreshLibraryAfterImportCompletion"):
            function_body = self.js_function(function_name)
            self.assertIn("refreshMainLibrarySnapshot", function_body, function_name)
            self.assertNotIn('fetch("/api/library")', function_body, function_name)
            self.assertNotIn("applyLibrarySnapshot", function_body, function_name)

    def test_my_publication_field_updates_return_one_publication(self) -> None:
        for handler_name in (
            "handle_star_my_publication",
            "handle_my_publication_head",
            "handle_my_publication_roles",
            "handle_my_publication_author_marks",
            "handle_my_publication_manual_metadata",
        ):
            source = inspect.getsource(getattr(ui_server.PaperMonitorUiHandler, handler_name))
            self.assertIn('"publication":', source, handler_name)
            self.assertNotIn("list_my_publications", source, handler_name)


if __name__ == "__main__":
    unittest.main()
