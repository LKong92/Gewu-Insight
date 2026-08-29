from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from paper_monitor import ui_server
from paper_monitor.storage import Storage


ROOT = Path(__file__).resolve().parents[1]


class FontSizeSettingsTests(unittest.TestCase):
    def test_default_and_supported_scales(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "settings.sqlite")
            try:
                payload = ui_server.font_size_settings_payload(storage)
            finally:
                storage.close()

        self.assertEqual(ui_server.DEFAULT_FONT_SIZE_SCALE, 100)
        self.assertEqual(payload["scale"], 100)
        self.assertEqual(payload["default_scale"], 100)
        self.assertEqual(payload["scales"], [90, 100, 110, 120, 130])

    def test_saved_scale_round_trips_and_unknown_values_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "settings.sqlite")
            try:
                for scale in ui_server.FONT_SIZE_SCALES:
                    storage.set_setting(ui_server.FONT_SIZE_SCALE_SETTING, str(scale))
                    self.assertEqual(
                        ui_server.font_size_settings_payload(storage)["scale"],
                        scale,
                    )
                storage.set_setting(ui_server.FONT_SIZE_SCALE_SETTING, "175")
                self.assertEqual(
                    ui_server.font_size_settings_payload(storage)["scale"],
                    ui_server.DEFAULT_FONT_SIZE_SCALE,
                )
                storage.set_setting(ui_server.FONT_SIZE_SCALE_SETTING, "not-a-size")
                self.assertEqual(
                    ui_server.font_size_settings_payload(storage)["scale"],
                    ui_server.DEFAULT_FONT_SIZE_SCALE,
                )
            finally:
                storage.close()

    def test_ui_previews_restores_and_persists_font_size(self) -> None:
        html = ui_server.INDEX_HTML
        self.assertIn('id="fontSizeSettingsBackdrop"', html)
        for scale in (90, 100, 110, 120, 130):
            self.assertIn(f'value="{scale}"', html)
        self.assertIn('fetchJson("/api/settings/font-size")', html)
        self.assertIn('fetch("/api/settings/font-size"', html)
        self.assertIn("function applyFontSizeScale(value)", html)
        self.assertIn("function previewFontSizeSetting(value)", html)
        self.assertIn("applyFontSizeScale(state.fontSizeOriginalScale)", html)
        self.assertIn("window.openFontSizeSettings = openFontSizeSettings", html)

    def test_native_setting_menu_uses_monitor_cache_wording_and_font_size(self) -> None:
        source = (ROOT / "scripts" / "PaperMonitorApp.m").read_text()
        clear_index = source.index('addItemWithTitle:@"Clear Monitor Cache"')
        font_index = source.index('addItemWithTitle:@"Font Size"')
        self.assertLess(clear_index, font_index)
        self.assertNotIn('addItemWithTitle:@"Clear Web Cache"', source)
        self.assertIn('@selector(openFontSizeSettings:)', source)
        self.assertIn("window.openFontSizeSettings", source)
        self.assertIn('@"Monitor cache cleared"', source)


if __name__ == "__main__":
    unittest.main()
