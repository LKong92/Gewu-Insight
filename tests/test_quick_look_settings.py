from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from paper_monitor import ui_server
from paper_monitor.storage import Storage


ROOT = Path(__file__).resolve().parents[1]


class QuickLookSettingsTests(unittest.TestCase):
    def test_default_keeps_every_preview_inside_gewu_insight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "settings.sqlite")
            try:
                payload = ui_server.quick_look_settings_payload(storage)
            finally:
                storage.close()

        self.assertEqual(ui_server.DEFAULT_QUICK_LOOK_MODE, "builtin_all")
        self.assertEqual(payload["mode"], "builtin_all")
        self.assertEqual(payload["default_mode"], "builtin_all")
        self.assertEqual(
            set(payload["modes"]),
            {"builtin_all", "hybrid", "native_all"},
        )

    def test_saved_modes_round_trip_and_unknown_values_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "settings.sqlite")
            try:
                for mode in ("hybrid", "native_all", "builtin_all"):
                    storage.set_setting(ui_server.QUICK_LOOK_MODE_SETTING, mode)
                    self.assertEqual(
                        ui_server.quick_look_settings_payload(storage)["mode"],
                        mode,
                    )
                storage.set_setting(ui_server.QUICK_LOOK_MODE_SETTING, "unexpected")
                self.assertEqual(
                    ui_server.quick_look_settings_payload(storage)["mode"],
                    "builtin_all",
                )
            finally:
                storage.close()

    def test_ui_exposes_all_three_modes_and_refreshes_an_open_preview(self) -> None:
        html = ui_server.INDEX_HTML
        self.assertIn('id="quickLookSettingsBackdrop"', html)
        self.assertIn('value="builtin_all"', html)
        self.assertIn('value="hybrid"', html)
        self.assertIn('value="native_all"', html)
        self.assertIn('fetchJson("/api/settings/quick-look")', html)
        self.assertIn('fetch("/api/settings/quick-look"', html)
        self.assertIn('quickLookUsesNativeForPaper(paper)', html)
        self.assertIn('refreshLibraryQuickLookForSelection({force: true})', html)
        self.assertIn('window.openQuickLookSettings = openQuickLookSettings', html)

    def test_native_menu_opens_the_quick_look_settings_panel(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()
        self.assertIn('addItemWithTitle:@"Quick Look Settings"', source)
        self.assertIn('@selector(openQuickLookSettings:)', source)
        self.assertIn('window.openQuickLookSettings', source)


if __name__ == "__main__":
    unittest.main()
