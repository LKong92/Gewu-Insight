// Run once, in an isolated content world, only after Save to Gewu is clicked.
// Read publication metadata and bounded PDF links, never forms or page text.
(() => {
  const clean = (v, max = 1000) => String(v || "").replace(/\s+/g, " ").trim().slice(0, max);
  const tags = Array.from(document.querySelectorAll("meta[name],meta[property]")).slice(0, 400);
  const values = names => tags.filter(m => names.includes((m.name || m.getAttribute("property") || "").toLowerCase())).map(m => clean(m.content)).filter(Boolean);
  const first = names => values(names)[0] || "";
  let article = {};
  for (const node of Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, 12)) {
    if (node.textContent.length > 262144) continue;
    try {
      const data = JSON.parse(node.textContent);
      const items = (Array.isArray(data) ? data : [data, ...(Array.isArray(data?.["@graph"]) ? data["@graph"] : [])]).slice(0, 100);
      const found = items.find(x => x && [x["@type"]].flat().some(t => ["ScholarlyArticle", "MedicalScholarlyArticle", "Article"].includes(t)));
      if (found) { article = found; break; }
    } catch (_) {}
  }
  const metadata = {
    title: first(["citation_title", "dc.title", "dcterms.title"]) || clean(article.headline || article.name),
    doi: first(["citation_doi", "dc.identifier.doi", "prism.doi"]),
    arxiv: first(["citation_arxiv_id"]),
    journal: first(["citation_journal_title", "prism.publicationname"]),
    date: first(["citation_publication_date", "citation_date", "dc.date", "prism.publicationdate"]) || clean(article.datePublished, 40),
    authors: values(["citation_author", "dc.creator"]).slice(0, 100)
  };
  if (!metadata.authors.length) metadata.authors = (Array.isArray(article.author) ? article.author : [article.author]).filter(Boolean).map(a => clean(typeof a === "string" ? a : a.name, 200)).filter(Boolean).slice(0, 100);
  if (!metadata.doi) {
    const ids = [article.identifier, ...values(["dc.identifier", "dc.identifier.uri", "dcterms.identifier"])].flat().filter(Boolean);
    metadata.doi = clean(ids.map(x => typeof x === "string" ? x : x.value || "").find(x => /10\.\d{4,9}\//.test(x)), 512);
  }
  const pdfs = values(["citation_pdf_url"]);
  for (const a of Array.from(document.querySelectorAll('a[href],link[type="application/pdf"]')).slice(0, 600)) {
    if (pdfs.length >= 8) break;
    if (a.type === "application/pdf" || /\.pdf(?:$|[?#])/i.test(a.href) || /^\s*(?:download\s+)?pdf\s*$/i.test(a.textContent || "")) pdfs.push(a.href);
  }
  const pdf_urls = [...new Set(pdfs.map(x => { try { return new URL(x, document.baseURI).href; } catch (_) { return ""; } }).filter(x => /^https?:\/\//i.test(x)))].slice(0, 8);
  return {metadata, pdf_urls, is_pdf: document.contentType === "application/pdf"};
})()
