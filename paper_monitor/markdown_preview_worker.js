/* Markdown Quick Look runs on demand, off the workspace's UI thread. */
"use strict";
importScripts("/markdown-it.min.js", "/js-yaml.min.js");

const markdown = markdownit({html: false, linkify: false, typographer: false});
const escape = markdown.utils.escapeHtml;
let revision = 0;
let currentRead = null;

// Only leading YAML mappings are properties. Later rules, Setext headings and
// fenced examples stay in the Markdown body. Older saved analyses may contain
// a Gewu provenance mapping followed by the author's own front matter.
function renderProperties(raw, value) {
  const provenance = value && Object.keys(value).length === 1
    && value.gewu_ai && typeof value.gewu_ai === "object" && !Array.isArray(value.gewu_ai);
  const title = provenance ? "Source record" : "Properties";
  const seen = new Set();
  let remaining = 3000;
  function renderValue(item, depth = 0) {
    if (--remaining < 0 || depth > 12) throw new Error("Properties exceed the structured preview limit");
    if (item === null || item === "") return '<span class="library-markdown-property-empty">—</span>';
    if (typeof item !== "object") return escape(String(item));
    if (seen.has(item)) return '<span class="library-markdown-property-empty">[Circular reference]</span>';
    seen.add(item);
    let html;
    if (Array.isArray(item)) {
      html = '<ul class="library-markdown-property-list">' + item.map(entry => `<li>${renderValue(entry, depth + 1)}</li>`).join("") + '</ul>';
    } else {
      html = '<dl class="library-markdown-properties-grid">' + Object.entries(item).map(([key, entry]) =>
        `<dt>${escape(key)}</dt><dd>${renderValue(entry, depth + 1)}</dd>`).join("") + '</dl>';
    }
    seen.delete(item);
    return html;
  }
  let html;
  try {
    html = value ? renderValue(provenance ? value.gewu_ai : value) : '';
  } catch (_) { /* Keep unusual YAML readable without expanding aliases. */ }
  if (!html) html = `<pre class="library-markdown-properties-source">${escape(raw)}</pre>`;
  return `<details class="library-markdown-properties"${provenance ? '' : ' open'}><summary>${title}</summary>${html}</details>`;
}

function renderDocument(text, path) {
  let body = String(text || '').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  let properties = '';
  for (let blocks = 0; blocks < 8; blocks++) {
    // Markdown permits up to three spaces before a rule. Imported notes can
    // retain that indentation on their YAML delimiters too (four means code).
    const opening = /^(?:[ \t]*\n)* {0,3}---[ \t]*\n/.exec(body);
    if (!opening) break;
    const ending = /^ {0,3}(?:---|\.\.\.)[ \t]*(?:\n|$)/gm;
    ending.lastIndex = opening[0].length;
    const closing = ending.exec(body);
    if (!closing) break;
    const raw = body.slice(opening[0].length, closing.index);
    let value;
    try {
      value = jsyaml.load(raw, {schema: jsyaml.CORE_SCHEMA, maxDepth: 32});
      if (!value || typeof value !== 'object' || Array.isArray(value)) break;
    } catch (_) {
      // A clearly marked but malformed properties block is shown verbatim,
      // not silently removed or converted into an enormous Setext heading.
      const first = raw.split('\n').find(line => line.trim() && !line.trimStart().startsWith('#')) || '';
      if (!/^[^\s:#][^\n:]*:(?:\s|$)/.test(first)) break;
    }
    properties += renderProperties(raw, value);
    body = body.slice(ending.lastIndex);
  }
  return properties + markdown.render(body, {path});
}

markdown.renderer.rules.table_open = () => '<div class="library-markdown-table" role="region" aria-label="Table" tabindex="0"><table>\n';
markdown.renderer.rules.table_close = () => '</table></div>\n';

function websiteURL(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_) {
    return "";
  }
}

// Route explicit website clicks through the existing Website Links setting.
// Relative links must not navigate the trusted workspace or call its APIs.
markdown.renderer.rules.link_open = (tokens, index, options, env) => {
  env.linkDepth = (env.linkDepth || 0) + 1;
  const url = websiteURL(tokens[index].attrGet("href") || "");
  return url ? `<a href="#" data-markdown-url="${escape(url)}">` : "<a>";
};
markdown.renderer.rules.link_close = (tokens, index, options, env) => {
  env.linkDepth = Math.max(0, (env.linkDepth || 0) - 1);
  return "</a>";
};
markdown.renderer.rules.image = (tokens, index, options, env) => {
  const token = tokens[index];
  const source = token.attrGet("src") || "";
  const label = escape(token.content || "Image");
  // Nearby images work offline. Remote images are explicit links, so merely
  // previewing an imported note does not start third-party requests.
  const remote = websiteURL(source);
  if (remote) return env.linkDepth ? `[Image: ${label}]` : `<a href="#" data-markdown-url="${escape(remote)}">[Image: ${label}]</a>`;
  try {
    const base = new URL("file://" + env.path.split("/").map(encodeURIComponent).join("/"));
    const directory = new URL(".", base);
    const image = new URL(source, directory);
    const path = decodeURIComponent(image.pathname);
    if (image.protocol === "file:" && !image.host
        && path.startsWith(decodeURIComponent(directory.pathname))
        && /\.(png|jpe?g|gif|webp|avif|bmp|tiff?|svg)$/i.test(path)) {
      return `<img src="/api/native-file-preview?path=${encodeURIComponent(path)}" alt="${label}" loading="lazy" decoding="async">`;
    }
  } catch (_) { /* Keep an unavailable image's description readable. */ }
  return `[Image: ${label}]`;
};

self.onmessage = async ({data}) => {
  // The workspace reads the file while this worker starts, and owns cancellation
  // and validated reuse. Keep parsing off the UI thread without a serial fetch.
  const request = ++revision;
  currentRead?.abort();
  currentRead = null;
  if (data.cancel) return;
  try {
    let content = data.content;
    if (!content) {
      // A workspace already open during a source update still uses the older
      // path-only messages until its normal restart. Keep that session usable.
      currentRead = new AbortController();
      const response = await fetch(`/api/markdown-preview?path=${encodeURIComponent(data.path)}`, {
        signal: currentRead.signal, cache: "no-store"
      });
      content = await response.json();
      if (request !== revision) return;
      if (!response.ok) throw new Error(content.error || "Markdown preview failed.");
    }
    let rendered = renderDocument(content.text, data.path);
    // Bound DOM insertion as well as file reads. The original is never edited.
    let truncated = Boolean(content.truncated);
    if (rendered.length > 250000) {
      rendered = renderDocument(content.text.slice(0, 65536), data.path);
      truncated = true;
    }
    if (rendered.length > 250000) rendered = `<pre>${escape(content.text.slice(0, 65536))}</pre>`;
    self.postMessage({token: data.token, path: data.path, html: rendered, truncated});
  } catch (error) {
    if (request !== revision || error.name === "AbortError") return;
    self.postMessage({token: data.token, path: data.path, error: error.message || "Markdown preview failed."});
  } finally {
    if (request === revision) currentRead = null;
  }
};
