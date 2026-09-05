import os
import secrets
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_monitor import ui_server
from paper_monitor.storage import Storage


def block(start, end):
    return start + ui_server.INDEX_HTML.split(start, 1)[1].split(end, 1)[0]


class SourceCredentialRevealTests(unittest.TestCase):
    def test_explicit_reveal_reads_only_the_requested_source_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.sqlite"
            storage = Storage(path)
            values = {provider: secrets.token_hex(12) for provider in ("openalex", "semantic_scholar", "ads")}
            settings = {"openalex": ui_server.OPENALEX_API_KEY_SETTING,
                        "semantic_scholar": ui_server.SEMANTIC_SCHOLAR_API_KEY_SETTING,
                        "ads": ui_server.ADS_API_TOKEN_SETTING}
            try:
                for provider, value in values.items():
                    storage.set_setting(settings[provider], value)
                for provider, value in values.items():
                    handler = SimpleNamespace(configured_db_path=path, server=SimpleNamespace(server_port=8765),
                        headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "X-Gewu-Reveal": "1"},
                        send_json=Mock(), send_error_json=Mock())
                    ui_server.PaperMonitorUiHandler.handle_reveal_source_credential(handler, {"provider": provider})
                    handler.send_error_json.assert_not_called()
                    self.assertTrue(handler.send_json.call_args.args[0] == {"value": value})
                    self.assertTrue(storage.get_setting(settings[provider]) == value)
            finally:
                storage.close()

    def test_reveal_rejects_cross_origin_missing_intent_and_wrong_host_before_database_access(self):
        for host, origin, intent in (
            ("127.0.0.1:8765", "https://example.com", "1"),
            ("127.0.0.1:8765", "", "1"),
            ("127.0.0.1:8765", "http://127.0.0.1:8765", ""),
            ("example.com:8765", "http://example.com:8765", "1"),
            ("127.0.0.1:8766", "http://127.0.0.1:8766", "1"),
        ):
            handler = SimpleNamespace(server=SimpleNamespace(server_port=8765),
                headers={"Host": host, "Origin": origin, "X-Gewu-Reveal": intent},
                send_error_json=Mock())
            with patch.object(ui_server, "Storage") as storage:
                ui_server.PaperMonitorUiHandler.handle_reveal_source_credential(handler, {"provider": "openalex"})
            storage.assert_not_called()
            self.assertEqual(handler.send_error_json.call_args.args[0], 403)

    def test_environment_key_can_be_revealed_without_persisting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.sqlite"
            storage = Storage(path)
            storage.close()
            value = secrets.token_hex(12)
            handler = SimpleNamespace(configured_db_path=path, server=SimpleNamespace(server_port=8765),
                headers={"Host": "localhost:8765", "Origin": "http://localhost:8765", "X-Gewu-Reveal": "1"},
                send_json=Mock(), send_error_json=Mock())
            with patch.dict(os.environ, {"OPENALEX_API_KEY": value}):
                ui_server.PaperMonitorUiHandler.handle_reveal_source_credential(handler, {"provider": "openalex"})
            self.assertTrue(handler.send_json.call_args.args[0] == {"value": value})
            reopened = Storage(path)
            try:
                self.assertFalse(reopened.get_setting(ui_server.OPENALEX_API_KEY_SETTING, ""))
            finally:
                reopened.close()


@unittest.skipUnless(shutil.which("node"), "Node.js required")
class OpenSourceSettingsUiTests(unittest.TestCase):
    def run_js(self, assertions):
        script = r'''
const assert = require('node:assert/strict');
const nodes = {};
function $(id) {
  if (!nodes[id]) {
    const classes = new Set();
    nodes[id] = {value: '', type: 'password', placeholder: id + ' API key', dataset: {}, disabled: false,
      textContent: '', attrs: {}, setAttribute(key, value) {this.attrs[key] = value;},
      classList: {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x),
        toggle(x, on) { if (on) classes.add(x); else classes.delete(x); }}};
  }
  return nodes[id];
}
function focusDialogSurface() {}
let calls = [], configured = true, fail = false, releaseReveal;
const syntheticValue = 'unit-test-only-value';
async function fetch(url, options = {}) {
  calls.push({url, options});
  if (url.endsWith('/reveal')) {
    assert.equal(options.headers['X-Gewu-Reveal'], '1');
    if (releaseReveal) await new Promise(resolve => {releaseReveal = resolve;});
    return {ok: !fail, json: async () => ({value: syntheticValue})};
  }
  const body = JSON.parse(options.body || '{}');
  if (body.action === 'clear') configured = false;
  return {ok: true, json: async () => ({ads: {configured}, openalex: {configured, ok: true}, semantic_scholar: {configured}})};
}
'''
        script += block("function updateSourceCredentialInput", "async function openArxivSettings")
        script += block("function updateCitationSettingsUi", "function escapeHtml")
        script += "\n(async () => {" + assertions + "})().catch(error => {console.error(error); process.exitCode = 1;});"
        result = subprocess.run([shutil.which("node"), "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_masks_do_not_fetch_keys_or_submit_the_dots(self):
        self.run_js(r'''
await openCitationSettings();
assert.deepEqual(calls.map(call => call.url), ['/api/settings/citation']);
for (const id of ['openalexKeyInput', 'semanticScholarKeyInput', 'adsTokenInput']) {
  assert.equal($(id).value, '');
  assert.equal($(id).placeholder, '••••••••');
  assert.equal($(id).type, 'password');
}
assert.ok($('citationSettingsStatus').textContent.includes('saved locally'));
await saveCitationOpenalexKey();
assert.equal(calls.length, 1);
await testCitationOpenalexKey();
assert.equal(JSON.parse(calls.at(-1).options.body).openalex_key, '');
await clearCitationOpenalexKey();
assert.ok(!$('openalexKeyInput').placeholder.includes('•'));
assert.equal($('openalexKeyInput').value, '');
assert.equal($('openalexKeyInputReveal').disabled, true);
''')

    def test_show_hide_for_each_source_and_close_clear_plaintext(self):
        self.run_js(r'''
await openCitationSettings();
for (const [id, provider] of [['openalexKeyInput', 'openalex'], ['semanticScholarKeyInput', 'semantic_scholar'], ['adsTokenInput', 'ads']]) {
  const status = $('citationSettingsStatus').textContent;
  await toggleSourceCredentialVisibility(id, provider);
  assert.equal($(id).value, syntheticValue);
  assert.equal($(id).type, 'text');
  assert.equal($(id + 'Reveal').textContent, 'Hide');
  assert.equal($('citationSettingsStatus').textContent, status);
  await toggleSourceCredentialVisibility(id, provider);
  assert.equal($(id).value, '');
  assert.equal($(id).placeholder, '••••••••');
  assert.equal($(id).type, 'password');
}
await toggleSourceCredentialVisibility('adsTokenInput', 'ads');
closeCitationSettings();
assert.equal($('adsTokenInput').value, '');
assert.equal($('adsTokenInput').type, 'password');
await openCitationSettings();
assert.equal($('adsTokenInput').value, '');
''')

    def test_closing_or_clearing_while_reveal_is_pending_cannot_restore_plaintext(self):
        self.run_js(r'''
await openCitationSettings();
releaseReveal = true;
let pending = toggleSourceCredentialVisibility('openalexKeyInput', 'openalex');
closeCitationSettings();
releaseReveal();
await pending;
assert.equal($('openalexKeyInput').value, '');
assert.equal($('openalexKeyInput').type, 'password');
releaseReveal = null;
await openCitationSettings();
releaseReveal = true;
pending = toggleSourceCredentialVisibility('openalexKeyInput', 'openalex');
await clearCitationOpenalexKey();
releaseReveal();
await pending;
assert.equal($('openalexKeyInput').value, '');
assert.equal($('openalexKeyInput').type, 'password');
''')

    def test_draft_show_does_not_fetch_and_failed_reveal_stays_hidden(self):
        self.run_js(r'''
await openCitationSettings();
$('adsTokenInput').value = 'new-test-draft';
await toggleSourceCredentialVisibility('adsTokenInput', 'ads');
assert.equal(calls.length, 1);
assert.equal($('adsTokenInput').type, 'text');
await toggleSourceCredentialVisibility('adsTokenInput', 'ads');
assert.equal($('adsTokenInput').value, 'new-test-draft');
assert.equal($('adsTokenInput').type, 'password');
fail = true;
await toggleSourceCredentialVisibility('openalexKeyInput', 'openalex');
assert.equal($('openalexKeyInput').value, '');
assert.equal($('openalexKeyInput').type, 'password');
assert.ok($('openalexCitationSettingsStatus').textContent.includes('Could not show'));
''')

    def test_visible_name_and_reveal_controls_match_the_native_menu(self):
        mask_css = ui_server.INDEX_HTML.split("input.saved-credential:placeholder-shown::placeholder {", 1)[1].split("}", 1)[0]
        self.assertIn("font-size: 13px", mask_css)
        self.assertIn("letter-spacing: 1px", mask_css)
        self.assertIn('<h2 id="citationSettingsTitle">Open Source Settings</h2>', ui_server.INDEX_HTML)
        native = (Path(__file__).resolve().parents[1] / "scripts" / "PaperMonitorApp.m").read_text()
        self.assertIn('addItemWithTitle:@"Open Source Settings"', native)
        self.assertNotIn('addItemWithTitle:@"Citation Settings"', native)
        for source in ("openalexKeyInput", "semanticScholarKeyInput", "adsTokenInput"):
            self.assertIn(f'data-credential-input="{source}"', ui_server.INDEX_HTML)
