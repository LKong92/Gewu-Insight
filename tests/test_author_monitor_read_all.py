import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from paper_monitor import ui_server
from paper_monitor.storage import Storage


def block(start, end):
    return start + ui_server.INDEX_HTML.split(start, 1)[1].split(end, 1)[0]


class AuthorMonitorReadAllTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "monitor.sqlite"
        self.storage = Storage(self.db)
        self.addCleanup(self.storage.close)
        self.ids = []
        for name in ("Alpha", "Beta"):
            author = self.storage.add_author_monitor({
                "user_id": name, "name": name,
                "url": f"https://scholar.google.com/citations?user={name}",
            })
            self.ids.append(int(author["id"]))
        for paper_id, scopes in (("shared", self.ids), ("alpha", self.ids[:1]), ("beta", self.ids[1:]), ("old", self.ids)):
            self.storage.upsert_paper({
                "paper_id": paper_id, "title": paper_id, "journal": "Example",
                "publication_date": "2026-09-01", "source": "google-scholar",
            })
            for author_id in scopes:
                self.storage.add_author_monitor_paper(author_monitor_id=author_id, paper_id=paper_id, unread=paper_id != "old")

    def request(self, payload):
        handler = SimpleNamespace(configured_db_path=self.db, send_json=Mock(), send_error_json=Mock())
        ui_server.PaperMonitorUiHandler.handle_mark_author_monitor_read(handler, payload)
        return handler

    def test_scoped_read_all_preserves_other_author_shared_papers_and_restart(self):
        ui_server.rebuild_author_monitor_card_cache(self.db)
        response = self.request({"author_id": self.ids[0], "read_all": True}).send_json.call_args.args[0]
        self.assertEqual(response["unreadByPaper"], {"beta": self.ids[1:], "shared": self.ids[1:]})
        self.assertEqual([author["unread_count"] for author in response["authors"]], [0, 2])
        again = self.request({"author_id": self.ids[0], "read_all": True}).send_json.call_args.args[0]
        self.assertEqual(response, again)
        self.assertEqual(self.storage.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0], 4)
        self.assertEqual(self.storage.conn.execute("SELECT COUNT(*) FROM author_monitor_papers").fetchone()[0], 6)
        self.assertFalse(self.storage.conn.execute("PRAGMA foreign_key_check").fetchall())
        reopened = Storage(self.db)
        try:
            self.assertEqual(reopened.author_monitor_unread_by_paper(), response["unreadByPaper"])
            for cards in (reopened.list_author_monitor_papers(), reopened.list_author_monitor_cached_cards()):
                shared = next(p for p in cards if p["paper_id"] == "shared")
                self.assertEqual(shared["author_unread_monitor_ids"], self.ids[1:])
            snapshot = ui_server.author_monitor_snapshot(reopened, author_monitor_id=self.ids[0])
            self.assertTrue(all(p["author_unread_monitor_ids"] == [] for p in snapshot["papers"]))
        finally:
            reopened.close()

    def test_all_authors_requires_explicit_read_all_and_is_idempotent(self):
        for payload in ({}, {"author_id": 0, "paper_ids": []}, {"read_all": "true"}):
            self.request(payload)
            self.assertEqual(len(self.storage.author_monitor_unread_by_paper()), 3)
        for _ in range(2):
            response = self.request({"author_id": 0, "read_all": True}).send_json.call_args.args[0]
            self.assertEqual(response["unreadByPaper"], {})
            self.assertTrue(all(author["unread_count"] == 0 for author in response["authors"]))
        self.assertEqual(len(self.storage.list_author_monitor_papers()), 4)

    def test_invalid_scope_cannot_expand_to_all_authors(self):
        for scope in (-1, "bad"):
            response = self.request({"author_id": scope, "read_all": True})
            response.send_error_json.assert_called_once()
            response.send_json.assert_not_called()
        self.assertEqual(len(self.storage.author_monitor_unread_by_paper()), 3)


@unittest.skipUnless(shutil.which("node"), "Node.js required")
class AuthorMonitorReadAllUiTests(unittest.TestCase):
    def run_js(self, assertions):
        script = r'''
const assert = require('node:assert/strict');
const state = {mode: 'author', authorMonitorSelectedId: 1, authorMonitorReadVersion: 0,
  authorMonitorReadPending: null, authorMonitorUnreadOnly: true, authorMonitorPaperCache: new Map(),
  authorMonitorPapers: [{paper_id: 'shared', author_monitor_ids: [1, 2], author_unread_monitor_ids: [1, 2], author_unread: true}],
  authorMonitors: [{id: 1, name: 'Alpha', unread_count: 1}, {id: 2, name: 'Beta', unread_count: 1}]};
const cached = structuredClone(state.authorMonitorPapers);
state.authorMonitorPaperCache.set(2, {papers: cached});
let renderCount = 0, status = '', body, fail = false;
let result = {ok: true, unreadByPaper: {shared: [2]}, authors: [{id: 1, unread_count: 0}, {id: 2, unread_count: 1}]};
const document = {querySelectorAll: () => []};
function invalidateAuthorMonitorViewCache() { state.authorMonitorViewCache = null; }
function renderAuthorMonitorRail() {}
function updateAuthorMonitorTopDot() {}
function renderAuthorMonitor() { renderCount++; }
function updateAuthorMonitorActivityStatus(text) { status = text; }
async function fetch(url, options) {
  assert.equal(url, '/api/author-monitor/read');
  body = JSON.parse(options.body);
  return {ok: !fail, json: async () => fail ? {error: 'Write failed'} : result};
}
'''
        script += block("function authorMonitorPaperIsUnread", "function setAuthorMonitorSort")
        script += "\n(async () => {" + assertions + "})().catch(error => { console.error(error); process.exitCode = 1; });"
        completed = subprocess.run([shutil.which("node"), "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_read_all_updates_scope_and_cached_rows_only_after_success(self):
        self.run_js(r'''
await readAllAuthorMonitorPapers(1);
assert.deepEqual(body, {author_id: 1, read_all: true});
assert.equal(authorMonitorPaperIsUnread(state.authorMonitorPapers[0], 1), false);
assert.equal(authorMonitorPaperIsUnread(cached[0], 2), true);
assert.equal(authorMonitorPaperIsUnread(cached[0], 0), true);
assert.equal(state.authorMonitorUnreadOnly, true);
assert.equal(state.authorMonitorSelectedId, 1);
assert.equal(renderCount, 1);
fail = true;
await readAllAuthorMonitorPapers(0);
assert.equal(authorMonitorPaperIsUnread(cached[0], 2), true);
assert.equal(status, 'Write failed');
assert.equal(renderCount, 1);
fail = false;
result = {ok: true, unreadByPaper: {}, authors: [{id: 1, unread_count: 0}, {id: 2, unread_count: 0}]};
await readAllAuthorMonitorPapers(0);
assert.deepEqual(body, {author_id: 0, read_all: true});
assert.equal(authorMonitorPaperIsUnread(cached[0], 0), false);
assert.equal(state.authorMonitorReadPending, null);
''')

    def test_inflight_snapshot_is_refetched_after_read_state_changes(self):
        self.run_js(r'''
let calls = 0;
global.fetchJson = async () => {
  calls++;
  if (calls === 1) { await persistAuthorMonitorRead({author_id: 1, read_all: true}); return 'stale'; }
  return 'fresh';
};
assert.equal(await fetchAuthorMonitorReadSafeJson('/api/author-monitor?index=1'), 'fresh');
assert.equal(calls, 2);
''')

    def test_context_menu_captures_scope_and_does_not_toggle_new_filter(self):
        self.assertIn('addEventListener("contextmenu", showAuthorMonitorNewContextMenu)', ui_server.INDEX_HTML)
        self.run_js(r'''
const listeners = {};
const button = {addEventListener: (name, action) => {listeners[name] = action;}};
const menu = {style: {}, setAttribute() {}, addEventListener() {}, querySelector: () => button};
document.createElement = () => menu;
document.body = {appendChild() {}};
global.window = {innerWidth: 900, innerHeight: 700};
global.hideThemeContextMenu = () => {};
global.escapeAttr = value => value;
let stopped = 0;
showAuthorMonitorNewContextMenu({clientX: 50, clientY: 50, preventDefault() {stopped++;}, stopPropagation() {stopped++;}});
assert.ok(menu.innerHTML.includes('Read All'));
assert.equal(stopped, 2);
state.authorMonitorSelectedId = 2;
listeners.click();
await state.authorMonitorReadPending;
assert.equal(body.author_id, 1);
assert.equal(state.authorMonitorUnreadOnly, true);
''')
