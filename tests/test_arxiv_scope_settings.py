import json
import tempfile
import unittest
from pathlib import Path

from paper_monitor.sources.arxiv import (
    DEFAULT_ARXIV_SCOPE_IDS,
    arxiv_categories_for_scopes,
    arxiv_scope_groups,
)
from paper_monitor.storage import Storage
from paper_monitor.ui_server import (
    ARXIV_PRIMARY_SUBJECT_SETTING,
    ARXIV_SCOPE_GROUPS_SETTING,
    ARXIV_SECONDARY_SUBJECT_SETTING,
    INDEX_HTML,
    arxiv_settings_payload,
    configured_arxiv_categories,
)


class ArxivScopeSettingsTests(unittest.TestCase):
    def test_default_scope_is_only_physics_condensed_matter(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                payload = arxiv_settings_payload(storage)
            finally:
                storage.close()

        self.assertEqual(payload["selected_scope_ids"], list(DEFAULT_ARXIV_SCOPE_IDS))
        self.assertEqual(payload["primary_subject"], "physics")
        self.assertEqual(payload["secondary_subject"], "cond-mat")
        self.assertIn("cond-mat.supr-con", payload["fetch_categories"])
        self.assertEqual(
            payload["display_default_categories"],
            ["cond-mat.mes-hall", "cond-mat.str-el", "cond-mat.supr-con"],
        )

    def test_hierarchy_exposes_groups_outside_physics(self):
        scopes = {scope["id"]: scope for scope in arxiv_scope_groups()}

        self.assertIn("physics/cond-mat", scopes)
        self.assertIn("computer_science/cs", scopes)
        self.assertIn("mathematics/math", scopes)
        self.assertIn("economics/econ", scopes)
        self.assertIn("eess/eess", scopes)
        self.assertIn("q_bio/q-bio", scopes)
        self.assertIn("q_fin/q-fin", scopes)
        self.assertIn("statistics/stat", scopes)
        self.assertIn("cs.AI", {item["code"] for item in scopes["computer_science/cs"]["categories"]})
        self.assertIn("math.AG", {item["code"] for item in scopes["mathematics/math"]["categories"]})

    def test_physics_archive_is_named_physics_and_keeps_all_leaf_categories(self):
        scopes = {scope["id"]: scope for scope in arxiv_scope_groups()}
        physics_scope = scopes["physics/physics"]
        category_codes = {item["code"] for item in physics_scope["categories"]}

        self.assertEqual(physics_scope["primary_label"], "Physics")
        self.assertEqual(physics_scope["group_label"], "Physics")
        self.assertEqual(len(category_codes), 21)
        self.assertIn("physics.acc-ph", category_codes)
        self.assertIn("physics.gen-ph", category_codes)
        self.assertIn("physics.optics", category_codes)

    def test_legacy_single_scope_is_read_without_mutating_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.set_setting(ARXIV_PRIMARY_SUBJECT_SETTING, "physics")
                storage.set_setting(ARXIV_SECONDARY_SUBJECT_SETTING, "astro-ph")
                payload = arxiv_settings_payload(storage)
                stored_multi_scope = storage.get_setting(ARXIV_SCOPE_GROUPS_SETTING, "")
            finally:
                storage.close()

        self.assertEqual(payload["selected_scope_ids"], ["physics/astro-ph"])
        self.assertIn("astro-ph.CO", payload["fetch_categories"])
        self.assertEqual(stored_multi_scope, "")

    def test_saved_scopes_combine_categories_across_primary_subjects(self):
        selected = ["physics/cond-mat", "computer_science/cs", "mathematics/math"]
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.set_setting(ARXIV_SCOPE_GROUPS_SETTING, json.dumps(selected))
                payload = arxiv_settings_payload(storage)
                categories = configured_arxiv_categories(storage)
            finally:
                storage.close()

        self.assertEqual(payload["selected_scope_ids"], selected)
        self.assertEqual(categories, arxiv_categories_for_scopes(selected))
        self.assertEqual(len(categories), len(set(categories)))
        self.assertIn("cond-mat.supr-con", categories)
        self.assertIn("cs.AI", categories)
        self.assertIn("math.AG", categories)

    def test_invalid_stored_multi_scope_falls_back_without_mutating_database(self):
        raw_value = json.dumps(["not-a-subject/not-a-group"])
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.set_setting(ARXIV_SCOPE_GROUPS_SETTING, raw_value)
                payload = arxiv_settings_payload(storage)
                stored_value = storage.get_setting(ARXIV_SCOPE_GROUPS_SETTING, "")
            finally:
                storage.close()

        self.assertEqual(payload["selected_scope_ids"], list(DEFAULT_ARXIV_SCOPE_IDS))
        self.assertEqual(stored_value, raw_value)

    def test_arxiv_scope_has_its_own_multi_select_settings_window(self):
        citation_markup = INDEX_HTML.split('id="citationSettingsBackdrop"', 1)[1].split(
            'id="arxivSettingsBackdrop"', 1
        )[0]

        self.assertNotIn("arXiv Discovery Scope", citation_markup)
        self.assertIn('id="arxivSettingsBackdrop"', INDEX_HTML)
        self.assertIn('id="arxivScopeOptions"', INDEX_HTML)
        self.assertIn('id="saveArxivSettings"', INDEX_HTML)
        self.assertIn('body: JSON.stringify({scope_ids: scopeIds})', INDEX_HTML)
        self.assertIn('window.openArxivSettings = openArxivSettings', INDEX_HTML)
        self.assertNotIn('id="arxivPrimarySubject"', INDEX_HTML)
        self.assertNotIn('id="arxivSecondarySubject"', INDEX_HTML)

    def test_native_settings_menu_opens_arxiv_scope_window(self):
        native_source = (Path(__file__).parents[1] / "scripts" / "PaperMonitorApp.m").read_text(encoding="utf-8")

        self.assertIn('@"arXiv Scope Settings"', native_source)
        self.assertIn("openArxivSettings:", native_source)
        self.assertIn("window.openArxivSettings && window.openArxivSettings()", native_source)


if __name__ == "__main__":
    unittest.main()
