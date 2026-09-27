// Real offline worker/parser, synthetic notes only; no application data.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const root = path.resolve(__dirname, '..', 'paper_monitor');
const outputs = [], loads = [];
let failEngine = false;
const resources = {
  '/markdown-it.min.js': 'vendor/markdown-it/markdown-it.min.js',
  '/js-yaml.min.js': 'vendor/js-yaml/js-yaml.min.js',
  '/katex.min.js': 'vendor/katex/katex.min.js',
};
const context = vm.createContext({URL, AbortController, console, atob, postMessage: result => outputs.push(result),
  importScripts(...urls) {
    for (const url of urls) {
      assert.ok(resources[url], 'only local bundled resources');
      loads.push(url);
      if (url === '/katex.min.js' && failEngine) throw Error('Engine unavailable');
      vm.runInContext(fs.readFileSync(path.join(root, resources[url]), 'utf8'), context);
    }
  },
});
vm.runInContext('self = globalThis', context);
vm.runInContext(fs.readFileSync(path.join(root, 'markdown_preview_worker.js'), 'utf8'), context);
let count = 0;
async function result(text) {
  await context.self.onmessage({data: {token: ++count, path: '/tmp/math.md', content: {text}}});
  return outputs.at(-1);
}
async function render(text) {
  const data = await result(text);
  assert.equal(data.error, undefined, text.slice(0, 100));
  return data.html;
}
const mathCount = html => (html.match(/<math[ >]/g) || []).length;
(async () => {
  const literal = String.raw`Plain **text**, prices $5 and $10, $1,000.00 and $20.50; US$30.

\$5 and \$10; 5$ and 10$; escaped \(not math without a close.`;
  assert.equal(mathCount(await render(literal)), 0);
  assert.equal(loads.includes('/katex.min.js'), false, 'non-math notes never load the engine');
  let html = await render(String.raw`$w$ and $\mu$, \(c_{2j+1}\), $\lvert x\rvert$ and $\operatorname{Pf}(A)$; $\frac{a}{b}$ and $x\!\,y$.`);
  assert.equal(mathCount(html), 7);
  for (const text of ['<mi>μ</mi>', '<msub>', '<mfrac>', '>Pf<', 'x\\!\\,y']) assert.ok(html.includes(text), text);
  assert.equal(loads.filter(url => url === '/katex.min.js').length, 1);
  assert.equal(mathCount(await render('$w$\n\n$w$')), 2);
  assert.equal(mathCount(await render(String.raw`$\text{测量}$`)), 1);
  assert.equal(loads.filter(url => url === '/katex.min.js').length, 1, 'engine reused between notes');
  for (const delimiter of [['$$','$$'], ['\\[','\\]']]) {
    for (const sep of ['', '\n']) {
      html = await render(delimiter[0] + sep + String.raw`H=iw\sum_{j=1}^{L-1}c_{2j}c_{2j+1}.` + sep + delimiter[1]);
      assert.equal(mathCount(html), 1);
      assert.match(html, /display="block"/); assert.match(html, /<munderover>/);
    }
  }
  html = await render(String.raw`$$
\operatorname{Pf}(A)^2=\det A,\quad A=\begin{pmatrix}0 & a \\ -a & 0\end{pmatrix}
$$`);
  assert.match(html, /<mtable/); assert.equal((html.match(/<mtr>/g)||[]).length, 2);
  for (const note of ['- $$\n  x_1\n  $$', '> \\[\n> \\frac{1}{2}\n> \\]', 'Paragraph\n$$x^2$$\n\nAfter']) {
    assert.equal(mathCount(await render(note)), 1, note);
  }
  html = await render('| Value | Formula |\n| --- | --- |\n| Absolute | $\\lvert x_1\\rvert$ |');
  assert.match(html, /<table>/); assert.equal((html.match(/<td>/g)||[]).length, 2); assert.equal(mathCount(html), 1);
  for (const note of [
    '`$x$ \\(x\\) $$x$$`', '`` $x$ ` \\(x\\) ``',
    '```tex\n$$\nx_1\\!\\,y\n$$\n```', '~~~md\n$x$\n~~~',
    '    $$\n    x_1\n    $$', '    \\[x_1\\]',
    '---\ntitle: "$x$"\n---\n# Body',
    '[$x$](https://example.org/$y$)', // only link label is math, destination is untouched
  ]) {
    html = await render(note);
    assert.equal(mathCount(html), note.startsWith('[') ? 1 : 0, note);
  }
  html = await render(String.raw`Prices $5, $10, and $20; $5.00 USD, $10.00 USD; math $w$ and $2+3$; dollar $\text{\$5}$; \$x\$.`);
  assert.equal(mathCount(html), 3); assert.ok(html.includes('Prices $5, $10, and $20; $5.00 USD, $10.00 USD;'));
  assert.ok(html.includes('$x$.'));
  assert.equal(mathCount(await render(String.raw`$ x $ and $x $ and $ x$ and $$$x$$$`)), 0);
  html = await render(String.raw`$\frac{a}{$

# Still here

$\badcommand{<img src=x onerror=evil()>}$ and $w$`);
  assert.equal(mathCount(html), 1); assert.equal((html.match(/library-markdown-math-error/g)||[]).length, 2);
  assert.match(html, /<h1>Still here<\/h1>/); assert.match(html, /&lt;img/); assert.doesNotMatch(html, /<img/);
  html = await render('$$\nUnclosed\n\n# Not swallowed\n\n$w$');
  assert.match(html, /<h1>Not swallowed/); assert.equal(mathCount(html), 1);
  for (const tex of [
    String.raw`\href{javascript:alert(1)}{x}`, String.raw`\href{/api/open-url}{x}`,
    String.raw`\includegraphics{https://example.org/leak.png}`,
    String.raw`\htmlStyle{position:fixed;inset:0}{x}`, String.raw`\htmlId{libraryQuickLook}{x}`,
    String.raw`\url{https://example.org/private}`, String.raw`\def\a{\a}\a`,
  ]) {
    html = await render('$' + tex + '$\n\n# After');
    assert.doesNotMatch(html, /<a[ >]|<img[ >]|<script[ >]|position:fixed;inset:0"|id="libraryQuickLook"/);
    assert.match(html, /<h1>After<\/h1>/);
  }
  await render(String.raw`$\gdef\secret{42}\secret$`);
  html = await render(String.raw`$\secret$`); assert.match(html, /library-markdown-math-error/, 'macros cannot leak between documents');
  html = await render(String.raw`$\rule{999999em}{999999em}$`);
  assert.doesNotMatch(html, /(?:width|height)="999999em"/);
  const start = performance.now();
  const large = await result(('$x_1+\\mu$\n\n').repeat(600));
  assert.ok(large.html.length <= 250000); assert.equal(large.truncated, false);
  assert.match(large.html, /<math[ >]/); assert.match(large.html, /library-markdown-math-error/);
  console.log(`Math-rich note: ${large.html.length} HTML chars in ${(performance.now()-start).toFixed(1)} ms`);
  html = await render('$' + 'x'.repeat(9000) + '$\n\n# After'); assert.match(html, /<h1>After/);
  html = await render(String.raw`\(x`.repeat(20000) + '\n\n# After'); assert.match(html, /<h1>After/);
  vm.runInContext('katex = undefined', context); failEngine = true;
  assert.match((await result('$w$')).error, /Engine unavailable/);
  failEngine = false; assert.equal(mathCount(await render('$w$')), 1, 'engine failure can be retried');
  console.log(`Markdown math checks passed (${count} synthetic notes): offline rendering, literal code/currency, safe fallback, bounded output and retry.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
