from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from bs4 import BeautifulSoup


class UserGuideNavigationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_topic_and_subsection_links_preserve_search_and_history(self) -> None:
        """Execute the shipped guide script against its real topic/anchor inventory."""
        source = Path(__file__).resolve().parents[1] / "paper_monitor/user_guide.html"
        soup = BeautifulSoup(source.read_text(), "html.parser")
        topics = soup.select(".help-topic")
        fixture = {
            "script": soup.find("script").string,
            "topics": [
                {"id": t["id"], "dataset": {
                    k.removeprefix("data-"): v for k, v in t.attrs.items()
                    if k.startswith("data-")
                }, "text": t.get_text(" ", strip=True)} for t in topics
            ],
            "anchors": {el["id"]: t["id"] for t in topics
                        for el in [t, *t.select("[id]")]},
            "links": [a["href"] for t in topics for a in t.select('a[href^="#"]')],
        }
        script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const data = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
function node(id = '') {
  const attrs = {}, classes = new Set(), children = {};
  return {id, dataset: {}, textContent: '', value: '', hidden: false, style: {}, events: {},
    classList: {toggle(k, yes) {yes ? classes.add(k) : classes.delete(k)},
                contains(k) {return classes.has(k)}},
    setAttribute(k, v) {attrs[k] = v}, removeAttribute(k) {delete attrs[k]},
    querySelector(k) {return children[k] ||= node()},
    addEventListener(k, fn) {this.events[k] = fn},
    scrollIntoView() {scrolls.push(this.id)}, focus() {}, select() {},
    closest() {return this.owner}, contains(other) {return other.owner === this}};
}
let scrolls = [];
const elements = {}, topics = data.topics.map(t => {
  const n = node(t.id); n.owner = n; n.dataset = t.dataset; n.textContent = t.text;
  return elements[t.id] = n;
});
for (const [id, owner] of Object.entries(data.anchors)) {
  const n = elements[id] ||= node(id); n.owner = elements[owner];
}
const links = topics.map(t => {const n = node(); n.dataset.topic = t.id; return n});
const internal = data.links.map(hash => {const n = node(); n.hash = hash; return n});
const controls = Object.fromEntries(['guideSearch', 'toolbar-group', 'toolbar-title',
  'print-topic', '.clear-search', '.no-results', '.pager-link.previous',
  '.pager-link.next'].map(k => [k, node(k)]));
const events = {}, frames = [];
let hash = '#monitor-publication-updates';
const location = {get hash() {return hash},
  set hash(value) {hash = value.startsWith('#') ? value : '#' + value}};
const document = {
  getElementById: id => elements[id] || controls[id],
  querySelector: q => controls[q], addEventListener() {},
  querySelectorAll: q => ({'.help-topic': topics, '.topic-link': links,
    '.help-topic a[href^="#"]': internal}[q] || [])
};
vm.runInNewContext(data.script, {document, location,
  requestAnimationFrame: fn => frames.push(fn),
  window: {matchMedia: () => ({matches: true}), scrollTo: () => scrolls.push('TOP'),
    addEventListener: (k, fn) => events[k] = fn}});
function active(id) {
  assert.deepEqual(topics.filter(t => t.classList.contains('active')).map(t => t.id), [id]);
  assert.equal(controls['toolbar-title'].textContent, elements[id].dataset.title);
}
// Cold deep links must survive the deferred initial layout callback.
frames.forEach(fn => fn()); active('journal-monitor');
assert.equal(scrolls.at(-1), 'monitor-publication-updates');
// Every real in-guide link opens its owning topic, including nested headings.
for (const a of internal) {
  let prevented = false; a.events.click({preventDefault() {prevented = true}});
  assert.ok(prevented); events.hashchange();
  const id = decodeURIComponent(a.hash.slice(1)); active(elements[id].owner.id);
  if (id !== elements[id].owner.id) assert.equal(scrolls.at(-1), id);
}
// Search can hide the destination. A related link clears that filter safely.
const search = controls.guideSearch;
search.value = 'zzzz-no-topic'; search.events.input();
assert.ok(links.every(n => n.hidden));
const notice = internal.find(a => a.hash === '#paper-publication-updates');
notice.events.click({preventDefault() {}}); events.hashchange();
assert.equal(search.value, ''); active('paper-details');
assert.ok(links.every(n => !n.hidden));
// Clicking an already-selected subsection and browser Back/Forward both work.
scrolls = []; notice.events.click({preventDefault() {}});
assert.equal(scrolls.at(-1), 'paper-publication-updates');
location.hash = '#monitor-unread'; events.hashchange(); active('journal-monitor');
location.hash = '#paper-publication-updates'; events.hashchange(); active('paper-details');
for (const hash of ['#missing-topic', '#%broken']) {
  location.hash = hash; events.hashchange(); active('welcome');
}
for (const query of ['Publication updates', 'Harvest', 'unread', 'mathematical Markdown']) {
  search.value = query; search.events.input(); assert.ok(links.some(n => !n.hidden), query);
}
console.log(`Verified ${topics.length} topics and ${internal.length} internal links.`);
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", script], input=json.dumps(fixture),
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
