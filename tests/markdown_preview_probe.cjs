const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "paper_monitor/markdown_preview_worker.js"), "utf8");
const parser = require(path.join(root, "paper_monitor/vendor/markdown-it/markdown-it.min.js"));
const results = [];
let read = async () => ({ok: true, json: async () => ({text: "", truncated: false})});
const context = vm.createContext({
  markdownit: parser, importScripts() {}, URL, AbortController,
  fetch: (...args) => read(...args), self: {postMessage: data => results.push(data)},
});
vm.runInContext(source, context);
async function render(text, token = 1) {
  read = async () => ({ok: true, json: async () => ({text, truncated: false})});
  await context.self.onmessage({data: {token, path: "/tmp/note folder/分析.md"}});
  return results.at(-1).html;
}
(async () => {
  let html = await render("# 标题\n\n**Bold** and *italic* and `code`\n\n1. First\n2. Second\n   - Nested\n\n> Quote\n\n```python\nprint('<x>')\n```\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n");
  for (const tag of ["h1", "strong", "em", "code", "ol", "ul", "blockquote", "pre", "table", "th", "td"]) {
    assert.match(html, new RegExp(`<${tag}[ >]`), tag);
  }
  assert.match(html, /&lt;x&gt;/);
  html = await render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[x](javascript:alert%281%29)\n\n[x](/api/open-url)\n\n[Website](https://example.org/paper)\n\n![Plot](figures/a.png)\n\n![Remote](https://example.org/a.png)\n\n![Escape](../secret.png)');
  assert.doesNotMatch(html, /<script|<img src=x|href="javascript:|href="\/api\//);
  assert.match(html, /data-markdown-url="https:\/\/example.org\/paper"/);
  assert.match(html, /<img src="\/api\/native-file-preview\?path=%2Ftmp%2Fnote%20folder%2Ffigures%2Fa.png"/);
  assert.doesNotMatch(html, /<img src="https:|path=[^"]*secret/);
  for (const value of ['[x](data:text/html,evil)', '[x](vbscript:evil)', '<svg onload="evil()">']) {
    assert.doesNotMatch(await render(value), /href="(?:data|vbscript):|<svg/);
  }
  html = await render('[![Badge](https://example.org/badge.png)](https://example.org/project)');
  assert.equal((html.match(/<a /g) || []).length, 1, 'image badges must not create nested links');
  assert.match(html, /data-markdown-url="https:\/\/example.org\/project"/);
  let release;
  let firstSignal;
  read = async (url, options) => {
    if (url.includes("old.md")) {
      firstSignal = options.signal;
      return new Promise(resolve => { release = () => resolve({ok: true, json: async () => ({text: "# Old"})}); });
    }
    return {ok: true, json: async () => ({text: "# New"})};
  };
  const first = context.self.onmessage({data: {token: 20, path: "/tmp/old.md"}});
  await context.self.onmessage({data: {token: 21, path: "/tmp/new.md"}});
  assert.equal(firstSignal.aborted, true);
  release(); await first;
  assert.equal(results.at(-1).token, 21);
  assert.equal(results.some(result => result.token === 20), false);
  const pending = context.self.onmessage({data: {token: 22, path: "/tmp/old.md"}});
  await context.self.onmessage({data: {cancel: true}});
  assert.equal(firstSignal.aborted, true);
  release(); await pending;
  assert.equal(results.some(result => result.token === 22), false);
  // A large note remains bounded by the API; parsing happens in this worker.
  const start = performance.now();
  html = await render(("## Section\n\n- A **result** with `code`.\n\n").repeat(6000));
  assert.ok(html.length < 1500000);
  console.log(`Markdown worker checks passed; large-note parse ${(performance.now() - start).toFixed(1)} ms`);
})().catch(error => { console.error(error); process.exitCode = 1; });
