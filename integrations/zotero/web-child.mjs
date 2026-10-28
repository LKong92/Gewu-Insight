/* Read-only page inspection. Remote pages never receive the workspace bridge. */
export class GewuWebChild extends JSWindowActorChild {
  handleEvent(event) {
    if (event.type === "DOMContentLoaded" && event.target === this.document)
      this.sendAsyncMessage("loaded", {title:this.document.title});
    if (event.type === "click" && event.isTrusted) {
      const link = event.target.closest?.("a[target='_blank'][href]");
      if (link) { event.preventDefault(); this.sendAsyncMessage("open", {url:link.href}); }
    }
  }
  receiveMessage({name, data}) {
    if (name === "find") return this.contentWindow.find(String(data.text || ""), false, !!data.backwards, true);
    if (name !== "snapshot") return null;
    const doc = this.document;
    const meta = key => [...doc.querySelectorAll("meta[name],meta[property]")]
      .filter(e => (e.getAttribute("name") || e.getAttribute("property") || "").toLowerCase() === key)
      .map(e => String(e.content || "").slice(0,2000));
    const absolute = value => { try { return new URL(value, doc.URL).href; } catch (_) { return ""; } };
    const pdfs = [...meta("citation_pdf_url"), ...[...doc.querySelectorAll("a[href],iframe[src],embed[src]")]
      .map(e => e.getAttribute("href") || e.getAttribute("src")).filter(v => /\.pdf(?:[?#]|$)/i.test(v || ""))]
      .map(absolute).filter(Boolean).slice(0,8);
    const isPDF = doc.contentType === "application/pdf" || /\.pdf(?:[?#]|$)/i.test(doc.URL);
    return {url:doc.URL, is_pdf:isPDF, pdf_urls:isPDF ? [doc.URL,...pdfs].slice(0,8) : pdfs,
      loaded_pdf_urls:isPDF ? [doc.URL] : [],
      metadata:{title:meta("citation_title")[0] || meta("dc.title")[0] || doc.title,
        doi:meta("citation_doi")[0] || meta("dc.identifier").find(v => /10\.\d{4,9}\//.test(v)) || "",
        arxiv:meta("citation_arxiv_id")[0] || "", authors:meta("citation_author").slice(0,100),
        journal:meta("citation_journal_title")[0] || "", date:meta("citation_publication_date")[0] || ""}};
  }
}
