import json
import tempfile
import unittest
from pathlib import Path

from paper_monitor.storage import Storage
from paper_monitor.ui_server import (
    DEFAULT_STANDALONE_FIELDS,
    FIELD_STANDALONE_SETTING,
    INDEX_HTML,
    classify_discipline,
    classify_fields,
    field_settings_payload,
)


class FieldSettingsTests(unittest.TestCase):
    def test_default_standalone_fields_keep_specialized_physics_under_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                payload = field_settings_payload(storage)
            finally:
                storage.close()

        self.assertEqual(
            payload["standalone_fields"],
            ["physics", "quantum_information", "materials", "chemistry"],
        )
        self.assertEqual(tuple(payload["standalone_fields"]), DEFAULT_STANDALONE_FIELDS)
        self.assertNotIn("astronomy_astrophysics", payload["standalone_fields"])
        self.assertNotIn("particle_nuclear_physics", payload["standalone_fields"])
        self.assertEqual(payload["special_fields"][-2:], [
            {"code": "other", "label": "Other Fields"},
            {"code": "all", "label": "All Fields"},
        ])

    def test_saved_standalone_fields_follow_canonical_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.set_setting(
                    FIELD_STANDALONE_SETTING,
                    json.dumps(["computer_science", "physics", "astronomy_astrophysics"]),
                )
                payload = field_settings_payload(storage)
            finally:
                storage.close()

        self.assertEqual(
            payload["standalone_fields"],
            ["physics", "astronomy_astrophysics", "computer_science"],
        )

    def test_arxiv_categories_classify_specialized_fields_without_generic_physics(self):
        astronomy = {
            "title": "A stellar population in a nearby galaxy",
            "journal": "arXiv",
            "raw_json": json.dumps({"categories": ["astro-ph.GA"]}),
        }
        particle = {
            "title": "Neutrino scattering at a collider",
            "journal": "arXiv",
            "raw_json": json.dumps({"categories": ["hep-ph"]}),
        }
        quantum = {
            "title": "A quantum error correction protocol",
            "journal": "arXiv",
            "raw_json": json.dumps({"categories": ["quant-ph"]}),
        }

        self.assertEqual(classify_fields(astronomy), ["astronomy_astrophysics"])
        self.assertEqual(classify_fields(particle), ["particle_nuclear_physics"])
        self.assertIn("quantum_information", classify_fields(quantum))
        self.assertIn("physics", classify_fields(quantum))
        self.assertEqual(classify_discipline(astronomy), "physical")

    def test_field_settings_ui_and_native_bridge_are_present(self):
        self.assertIn('id="fieldSettingsBackdrop"', INDEX_HTML)
        self.assertIn('id="fieldSettingsOptions"', INDEX_HTML)
        self.assertIn('fetch("/api/settings/fields"', INDEX_HTML)
        self.assertIn('window.openFieldSettings = openFieldSettings;', INDEX_HTML)
        self.assertIn('.concat([["other", FIELD_LABELS.other], ["all", FIELD_LABELS.all]])', INDEX_HTML)

        native_source = (Path(__file__).resolve().parents[1] / "scripts" / "PaperMonitorApp.m").read_text(
            encoding="utf-8"
        )
        self.assertIn('@"Field Settings"', native_source)
        self.assertIn("openFieldSettings:", native_source)
        self.assertIn("window.openFieldSettings", native_source)

    def test_all_primary_surfaces_load_field_settings(self):
        for function_name in (
            "loadLibrary",
            "loadMyPublications",
            "openAuthorMonitor",
            "loadThemeMonth",
            "openThemeMonitor",
        ):
            body = INDEX_HTML.split(f"async function {function_name}", 1)[1].split("\n    }", 1)[0]
            self.assertIn("loadFieldSettings({render: false})", body, function_name)


if __name__ == "__main__":
    unittest.main()
