"""Website preference persistence and OS dispatch without launching a browser."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from paper_monitor import ui_server
from paper_monitor.storage import Storage

ROOT = Path(__file__).resolve().parents[1]


class WebsiteLinkSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "settings.sqlite"
        storage = Storage(self.path)
        self.version = storage.conn.execute("PRAGMA user_version").fetchone()[0]
        storage.close()
        self.handler = object.__new__(ui_server.PaperMonitorUiHandler)
        self.handler.configured_db_path = self.path
        self.handler.send_json = Mock()
        self.handler.send_error_json = Mock()

    def tearDown(self):
        self.temp.cleanup()

    def test_default_save_reopen_reset_and_invalid_preference(self):
        self.handler.handle_get_website_link_settings()
        self.handler.send_json.assert_called_with({"browser": "builtin"})
        for browser in ("system", "builtin", "system"):
            self.handler.handle_set_website_link_settings({"browser": browser})
            self.handler.send_json.assert_called_with({"browser": browser})
            storage = Storage(self.path)
            try:
                self.assertEqual(ui_server.website_link_settings_payload(storage), {"browser": browser})
                self.assertIn(f'websiteLinkBrowser: "{browser}",', ui_server.workspace_html(storage))
                self.assertEqual(storage.conn.execute("PRAGMA user_version").fetchone()[0], self.version)
                self.assertEqual(storage.conn.execute("SELECT count(*) FROM browser_history").fetchone()[0], 0)
                self.assertEqual(storage.conn.execute("SELECT count(*) FROM papers").fetchone()[0], 0)
            finally:
                storage.close()
        for payload in ({}, {"browser": "safari"}, {"browser": []}, {"browser": "<script>"}):
            self.handler.handle_set_website_link_settings(payload)
            self.assertEqual(self.handler.send_error_json.call_args.args[0], 400)
            self.handler.handle_get_website_link_settings()
            self.handler.send_json.assert_called_with({"browser": "system"})
        storage = Storage(self.path)
        try:
            storage.set_setting(ui_server.WEBSITE_LINK_BROWSER_SETTING, '</script><script>alert(1)</script>')
            self.assertEqual(ui_server.website_link_settings_payload(storage), {"browser": "builtin"})
            self.assertEqual(ui_server.workspace_html(storage), ui_server.INDEX_HTML)
        finally:
            storage.close()

    def test_system_launch_uses_macos_default_and_reports_failure(self):
        with patch.object(ui_server.sys, "platform", "darwin"), patch.object(ui_server.subprocess, "run") as run, patch.object(ui_server.webbrowser, "open") as browser:
            self.handler.handle_open_url({"url": "https://example.org/paper?q=quantum#figure", "app": "default"})
            run.assert_called_once_with(["open", "https://example.org/paper?q=quantum#figure"], check=True, timeout=15)
            browser.assert_not_called()
            self.handler.send_json.assert_called_with({"status": "opened", "url": "https://example.org/paper?q=quantum#figure"})
            self.handler.send_json.reset_mock()
            for error in (OSError("unavailable"), subprocess.CalledProcessError(1, ["open"]), subprocess.TimeoutExpired(["open"], 15)):
                run.side_effect = error
                self.handler.handle_open_url({"url": "https://example.org/", "app": "default"})
                self.assertEqual(self.handler.send_error_json.call_args.args[0], 500)
                self.handler.send_json.assert_not_called()

    def test_invalid_destinations_never_launch_an_application(self):
        with patch.object(ui_server.subprocess, "run") as run, patch.object(ui_server.webbrowser, "open") as browser:
            for url in ["", "javascript:alert(1)", "file:///tmp/a.pdf", "https://u:p@example.org/", "http://127.0.0.1/", "http://localhost/", "http://192.168.1.1/", "http://127.1/", "https://example.org/\ncommand", "https://example.org/" + "x" * 8192]:
                self.handler.handle_open_url({"url": url, "app": "default"})
                self.assertEqual(self.handler.send_error_json.call_args.args[0], 400)
            run.assert_not_called()
            browser.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_real_router_save_cancel_failure_and_destination_status(self):
        html = ui_server.INDEX_HTML
        router = "function openWebsite(" + html.split("function openWebsite(", 1)[1].split("function wireWorkspaceWebsiteLinks(", 1)[0]
        settings = "function applyWebsiteLinkSettings(" + html.split("function applyWebsiteLinkSettings(", 1)[1].split("function renderFontSizeSettingsSelection(", 1)[0]
        library = "async function openLibraryWebsiteURL(" + html.split("async function openLibraryWebsiteURL(", 1)[1].split("async function copyLibraryBibtex(", 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const state={websiteLinkBrowser:'builtin',websiteLinkSettingsBusy:false,mode:'library',selection:17};
const calls=[],messages=[],inputs=[{value:'builtin',checked:true},{value:'system',checked:false}];
const elements={},$=id=>elements[id] ||= {textContent:'',className:'',classList:{add(){},remove(){}},setAttribute(){},querySelectorAll:()=>inputs};
const document={querySelectorAll:()=>inputs,querySelector:()=>inputs.find(i=>i.checked)};
const window={gewuBrowser:{openURL:url=>{calls.push(['builtin',url]);return 'Browser';}}};
const showMonitorStatusMessage=m=>messages.push(m),focusDialogSurface=()=>{};
let saved='builtin', fail=false, pending;
const fetchJson=async()=>({browser:saved});
const fetch=async(url,options)=>{
  const body=JSON.parse(options.body);calls.push([url,body]);
  if(pending) await pending;
  if(fail) return {ok:false,json:async()=>({error:'Synthetic failure'})};
  if(url.includes('settings')) saved=body.browser;
  return {ok:true,json:async()=>({browser:saved,status:'opened'})};
};
''' + router + settings + library + r'''
(async()=>{
  await openWebsiteLinkSettings();
  inputs[0].checked=false;inputs[1].checked=true;
  closeWebsiteLinkSettings();
  assert.equal(openWebsite('https://example.org/cancel'),'Browser');
  assert.equal(state.websiteLinkBrowser,'builtin','unsaved selection does not apply');
  await openWebsiteLinkSettings();
  assert.ok(inputs[0].checked,'reopening discards unsaved choice');
  inputs[0].checked=false;inputs[1].checked=true;
  fail=true;await saveWebsiteLinkSettings();
  assert.equal(state.websiteLinkBrowser,'builtin');assert.equal(saved,'builtin');
  fail=false;await saveWebsiteLinkSettings();
  assert.equal(state.websiteLinkBrowser,'system');assert.equal(saved,'system');
  for(const mode of ['library','my-publications','report','theme','author']) {
    state.mode=mode;const before={...state};calls.length=0;
    assert.equal(await openWebsite('https://example.org/'+mode),'system default browser');
    assert.deepEqual(calls,[['/api/open-url',{url:'https://example.org/'+mode,app:'default'}]]);
    assert.deepEqual(state,before,'external route leaves workspace untouched');
  }
  let finish;pending=new Promise(resolve=>finish=resolve);
  const result=openLibraryWebsiteURL('https://example.org/pdf');
  assert.equal($('libraryDetailStatus').textContent,'Opening website...');
  finish();await result;pending=null;
  assert.equal($('libraryDetailStatus').textContent,'Opening in system default browser...');
  fail=true;await openLibraryWebsiteURL('https://example.org/fail');
  assert.equal($('libraryDetailStatus').className,'library-detail-status err');
  assert.equal(messages.at(-1),'Synthetic failure');
  fail=false;await saveWebsiteLinkSettings('builtin');
  assert.equal(state.websiteLinkBrowser,'builtin');assert.equal(saved,'builtin');
  assert.equal(openWebsite('https://example.org/default'),'Browser');
  console.log('Website routing, saved preference, cancel, reset and failures passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run([shutil.which("node"), "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_setting_menu_and_dialog_entry(self):
        native = (ROOT / "scripts/PaperMonitorApp.m").read_text()
        self.assertIn('addItemWithTitle:@"Website Links"', native)
        self.assertIn('window.openWebsiteLinkSettings', native)
        self.assertIn('window.openWebsiteLinkSettings = openWebsiteLinkSettings', ui_server.INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
