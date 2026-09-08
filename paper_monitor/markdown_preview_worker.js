/* Markdown Quick Look runs on demand, off the workspace's UI thread. */
"use strict";
importScripts("/markdown-it.min.js");

const markdown = markdownit({html: false, linkify: false, typographer: false});
const escape = markdown.utils.escapeHtml;
let currentRead = null;
let revision = 0;

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
  const request = ++revision;
  currentRead?.abort();
  currentRead = null;
  if (data.cancel) return;
  const controller = new AbortController();
  currentRead = controller;
  try {
    const response = await fetch(`/api/markdown-preview?path=${encodeURIComponent(data.path)}`, {
      signal: controller.signal, cache: "no-store"
    });
    const content = await response.json();
    if (request !== revision) return;
    if (!response.ok) throw new Error(content.error || "Markdown preview failed.");
    let rendered = markdown.render(content.text, {path: data.path});
    // Bound DOM insertion as well as file reads. The original is never edited.
    let truncated = Boolean(content.truncated);
    if (rendered.length > 250000) {
      rendered = markdown.render(content.text.slice(0, 65536), {path: data.path});
      truncated = true;
    }
    if (rendered.length > 250000) rendered = `<pre>${escape(content.text.slice(0, 65536))}</pre>`;
    self.postMessage({token: data.token, path: data.path, html: rendered, truncated});
  } catch (error) {
    if (request !== revision || error.name === "AbortError") return;
    self.postMessage({token: data.token, path: data.path, error: error.message || "Markdown preview failed."});
  } finally {
    if (currentRead === controller) currentRead = null;
  }
};
