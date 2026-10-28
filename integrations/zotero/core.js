/* Pure mapping/validation, shared by the native plugin and its regression tests. */
var GewuZoteroCore = (() => {
  "use strict";
  const text = (value, limit = 20000) => typeof value === "string"
    ? value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "").trim().slice(0, limit) : "";

  function origin(value) {
    const url = new URL(value);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
      || url.username || url.password || url.search || url.hash || url.pathname !== "/") {
      throw new Error("Use a local Gewu address, for example http://127.0.0.1:8765.");
    }
    return url.origin;
  }

  function website(value) {
    try {
      const u = new URL(text(value));
      return ["https:", "http:"].includes(u.protocol) && !u.username && !u.password ? u.href : "";
    } catch (_) { return ""; }
  }

  function browserURL(value) {
    const address = website(value);
    if (!address || address.length > 8192) throw new Error("Use a public HTTP or HTTPS website.");
    const url = new URL(address), host = url.hostname.toLowerCase().replace(/\.$/, "");
    if (!host.includes(".") || host === "localhost" || /\.(localhost|local|internal)$/.test(host)
      || host.startsWith("[") || /^(0|10|127|169\.254|192\.168|172\.(1[6-9]|2[0-9]|3[01]))(?:\.|$)/.test(host)
      || /^(22[4-9]|2[3-5][0-9])\./.test(host)) throw new Error("Use a public HTTP or HTTPS website.");
    return address;
  }

  function doi(value) {
    const s = text(value, 500).replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i, "").toLowerCase();
    return /^10\.\d{4,9}\/\S+$/.test(s) ? s : "";
  }

  function arxiv(value) {
    const s = text(value, 200).replace(/^arxiv:\s*/i, "")
      .replace(/^https?:\/\/arxiv\.org\/(?:abs|pdf)\//i, "").replace(/\.pdf$/i, "").replace(/v\d+$/i, "");
    return /^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})$/i.test(s) ? s.toLowerCase() : "";
  }

  function marker(databaseID, paper) {
    const key = text(paper.storage_key || paper.paper_id, 200);
    if (!/^[a-zA-Z0-9_.:-]+$/.test(databaseID) || !/^[a-zA-Z0-9_.:/-]+$/.test(key)) {
      throw new Error("Gewu returned an invalid paper identity.");
    }
    return `Gewu: ${databaseID}/${key}`;
  }

  function fields(paper, databaseID) {
    const title = text(paper.title);
    if (!title) throw new Error("This paper has no title. Complete its metadata before saving.");
    const d = doi(paper.doi), a = arxiv(paper.preprint_id);
    const authors = Array.isArray(paper.full_authors) && paper.full_authors.length
      ? paper.full_authors : Array.isArray(paper.authors) ? paper.authors : [];
    const extra = [a ? `arXiv: ${a}` : "", marker(databaseID, paper)].filter(Boolean).join("\n");
    // Keep complete names instead of guessing family names, including institutional authors.
    return {
      itemType: a && (!d || d.startsWith("10.48550/arxiv.") || /^arxiv$/i.test(text(paper.journal))) ? "preprint" : "journalArticle",
      title, DOI: d, url: website(paper.url) || (d ? `https://doi.org/${d}` : a ? `https://arxiv.org/abs/${a}` : ""),
      abstractNote: text(paper.abstract, 100000), date: text(paper.publication_date, 100),
      publicationTitle: text(paper.journal, 1000),
      volume: text(paper.manual_metadata?.volume, 100), issue: text(paper.manual_metadata?.issue, 100),
      pages: text(paper.manual_metadata?.pages, 100), extra,
      creators: authors.map(name => text(name, 500)).filter(Boolean)
        .map(name => ({ creatorType: "author", lastName: name, fieldMode: 1 }))
    };
  }

  function extraHas(extra, line) {
    return String(extra || "").split(/\r?\n/).some(value => value.trim() === line);
  }

  function defaultPDF(payload) {
    const selected = Number(payload.default_resource_id || payload.resolved_resource_id || 0);
    const file = (Array.isArray(payload.files) ? payload.files : []).find(f => Number(f.id) === selected);
    if (!file || !file.exists || !text(file.local_path).toLowerCase().endsWith(".pdf")
      || file.file_type === "invalid_file") return null;
    return file;
  }

  return { text, origin, website, browserURL, doi, arxiv, marker, fields, extraHas, defaultPDF };
})();
if (typeof module !== "undefined") module.exports = GewuZoteroCore;
