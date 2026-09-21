const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "paper_monitor/markdown_preview_worker.js"), "utf8");
const parser = require(path.join(root, "paper_monitor/vendor/markdown-it/markdown-it.min.js"));
const yaml = require(path.join(root, "paper_monitor/vendor/js-yaml/js-yaml.min.js"));
const results = [];
let read = async () => { throw new Error("Current previews must not fetch from the worker"); };
const context = vm.createContext({
  markdownit: parser, jsyaml: yaml, importScripts() {}, URL, AbortController,
  fetch: (...args) => read(...args), self: {postMessage: data => results.push(data)},
});
vm.runInContext(source, context);
async function render(text, token = 1) {
  await context.self.onmessage({data: {token, path: "/tmp/note folder/分析.md", content: {text, truncated: false}}});
  return results.at(-1).html;
}
(async () => {
  let html = await render("# 标题\n\n**Bold** and *italic* and `code`\n\n1. First\n2. Second\n   - Nested\n\n> Quote\n\n```python\nprint('<x>')\n```\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n");
  for (const tag of ["h1", "strong", "em", "code", "ol", "ul", "blockquote", "pre", "table", "th", "td"]) {
    assert.match(html, new RegExp(`<${tag}[ >]`), tag);
  }
  assert.match(html, /&lt;x&gt;/);
  const provenance = '---\ngewu_ai: {"gewu_key":"gw_0123456789","source_sha256":"' + 'a'.repeat(64) + '","pages":[1,2,30]}\n---\n\n';
  const properties = '---\ntitle: "研究笔记"\nauthors: ["One Author", "另一作者"]\nread_date: 2026-09-22\ntags:\n  - AI\n  - chemistry\nsummary: |\n  First line\n  Second line\nempty: null\nflag: false\ncount: 0\nquoted: \'A \'\'quoted\'\' value\'\n---\n\n';
  html = await render(provenance + properties + '# 正文标题\n\nAn ordinary paragraph.');
  assert.equal((html.match(/<details /g) || []).length, 2);
  assert.match(html, /<summary>Source record<\/summary>/);
  assert.match(html, /class="library-markdown-properties" open><summary>Properties/);
  for (const value of ['One Author','另一作者','2026-09-22','First line\nSecond line','A \'quoted\' value']) assert.ok(html.includes(value), value);
  assert.match(html, /<dt>flag<\/dt><dd>false<\/dd>/);
  assert.match(html, /<dt>count<\/dt><dd>0<\/dd>/);
  assert.equal((html.match(/<h[1-6][ >]/g) || []).length, 1, 'metadata never becomes a heading');
  assert.match(html, /<h1>正文标题<\/h1>/);
  assert.match(await render('\uFEFF' + properties.replaceAll('\n','\r\n') + '# Body'), /<summary>Properties/);
  for (const indent of [' ', '  ', '   ']) {
    html = await render(indent + provenance + properties + '# Body');
    assert.equal((html.match(/<details /g) || []).length, 2, 'indented first separator retains both property blocks');
    assert.equal((html.match(/<h[1-6][ >]/g) || []).length, 1);
    assert.match(await render(properties.replace(/^---/gm, indent + '---') + '# Body'), /<summary>Properties/);
  }
  assert.doesNotMatch(await render('    ---\n    title: Code example\n    ---\n'), /<details/);
  assert.match(await render('---\ntitle: [broken\n---\n\n# Body'), /properties-source/);
  assert.match(await render('---\ntitle: [broken\n---\n\n# Body'), /<h1>Body<\/h1>/);
  assert.doesNotMatch(await render('---\nThis is prose\n---\n\n# Body'), /<details/);
  assert.doesNotMatch(await render('---\ntitle: Unclosed\n\n# Body'), /<details/);
  html = await render('# Body\n\nA regular heading\n---\n\n---\n\n```yaml\n---\ntitle: Example\n---\n```');
  assert.match(html, /<h2>A regular heading<\/h2>/); assert.match(html, /<hr>/); assert.doesNotMatch(html, /<details/);
  html = await render('---\nvalue: "<img src=x onerror=evil()>"\n---\n# Body');
  assert.doesNotMatch(html, /<img/); assert.match(html, /&lt;img/);
  html = await render('---\nloop: &cycle [*cycle]\n---\n# Body');
  assert.match(html, /Circular reference/); assert.ok(html.length < 1500);
  html = await render('---\nvalue: !!js/function "function(){evil()}"\n---\n# Body');
  assert.match(html, /properties-source/);
  html = await render('---\nvalue: ' + '['.repeat(100) + '1' + ']'.repeat(100) + '\n---\n# Body');
  assert.match(html, /properties-source/);
  assert.match(await render(properties.replace(/---\n\n$/, '...\n\n') + '# Body'), /<h1>Body<\/h1>/);
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
  // Transport cancellation and reuse are exercised by markdown_preview_flow_probe.
  await context.self.onmessage({data: {token: 20, path: "/tmp/broken.md"}});
  assert.ok(results.at(-1).error);
  await render('# Recovered', 21);
  assert.equal(results.at(-1).token, 21);
  assert.match(results.at(-1).html, /<h1>Recovered<\/h1>/);
  // Already-open older workspaces retain cancellation until their restart.
  let release;
  let firstSignal;
  read = async (url, options) => {
    if (url.includes("old.md")) {
      firstSignal = options.signal;
      return new Promise(resolve => { release = () => resolve({ok: true, json: async () => ({text: "# Old"})}); });
    }
    return {ok: true, json: async () => ({text: "# New"})};
  };
  const first = context.self.onmessage({data: {token: 30, path: "/tmp/old.md"}});
  await context.self.onmessage({data: {token: 31, path: "/tmp/new.md"}});
  assert.equal(firstSignal.aborted, true);
  release(); await first;
  assert.equal(results.at(-1).token, 31);
  assert.equal(results.some(result => result.token === 30), false);
  const pending = context.self.onmessage({data: {token: 32, path: "/tmp/old.md"}});
  await context.self.onmessage({data: {cancel: true}});
  assert.equal(firstSignal.aborted, true);
  release(); await pending;
  assert.equal(results.some(result => result.token === 32), false);
  // A large note remains bounded by the API; parsing happens in this worker.
  const start = performance.now();
  html = await render(("## Section\n\n- A **result** with `code`.\n\n").repeat(6000));
  assert.ok(html.length < 1500000);
  console.log(`Markdown worker checks passed; large-note parse ${(performance.now() - start).toFixed(1)} ms`);
})().catch(error => { console.error(error); process.exitCode = 1; });
