/* Zotero-only Quick Look adapter. Shared Gewu/App preview code stays untouched. */
(() => {
  "use strict";
  const root = document.getElementById("libraryQuickLookPages");
  const overlay = document.getElementById("libraryQuickLook");
  if (!root || !overlay || typeof renderLibraryQuickLookPages !== "function"
      || typeof updateLibraryPdfFramePage !== "function") return;
  const request = window.GewuZoteroHost.request;
  const urls = [];
  let enginePromise, current, resizeTimer;
  const blobURL = text => {
    const url = URL.createObjectURL(new Blob([text], {type:"text/javascript"}));
    urls.push(url); return url;
  };
  async function engine() {
    if (!enginePromise) enginePromise = request("pdf-engine").then(async sources => {
      const pdf = await import(blobURL(sources.module));
      pdf.GlobalWorkerOptions.workerSrc = blobURL(sources.worker);
      return pdf;
    }).catch(error => { enginePromise = null; throw error; });
    return enginePromise;
  }
  class BinaryDataFactory {
    async fetch({kind, filename}) {
      const encoded = await request("pdf-asset", {kind, filename});
      return Uint8Array.from(atob(encoded), character => character.charCodeAt(0));
    }
  }
  const style = document.createElement("style");
  style.textContent = `
    #libraryQuickLookPages.gewu-pdf-pages{display:block;position:relative;background:#eef1f5;overflow-anchor:none;padding:10px;box-sizing:border-box}
    .gewu-pdf-page{position:relative;margin:0 auto 10px;background:white;box-shadow:0 1px 4px #0002;overflow:hidden;box-sizing:content-box}
    .gewu-pdf-page canvas{display:block;width:100%;height:100%}
    .gewu-pdf-page .textLayer{position:absolute;inset:0;overflow:hidden;line-height:1;text-size-adjust:none;forced-color-adjust:none;transform-origin:0 0;user-select:text;--min-font-size:1;--text-scale-factor:calc(var(--total-scale-factor) * var(--min-font-size));--min-font-size-inv:calc(1 / var(--min-font-size))}
    .gewu-pdf-page .textLayer :is(span,br){color:transparent;position:absolute;white-space:pre;transform-origin:0 0;cursor:text}
    .gewu-pdf-page .textLayer > :not(.markedContent),.gewu-pdf-page .textLayer .markedContent span:not(.markedContent){z-index:1;--font-height:0;font-size:calc(var(--text-scale-factor) * var(--font-height));--scale-x:1;--rotate:0deg;transform:rotate(var(--rotate)) scaleX(var(--scale-x)) scale(var(--min-font-size-inv))}
    .gewu-pdf-page .markedContent{display:contents}
    .gewu-pdf-page .textLayer ::selection{background:#87b9ee80}
    .gewu-pdf-page .textLayer br::selection{background:transparent}
    .gewu-pdf-message{padding:24px;color:var(--muted);font:inherit;text-align:center}
    .gewu-pdf-message button{margin-left:8px}
  `;
  document.head.append(style);
  function dispose() {
    const old = current; current = null;
    if (!old) return;
    old.abort.abort(); old.observer?.disconnect();
    for (const slot of old.slots) release(slot);
    old.loading?.destroy().catch(() => {});
    root.classList.remove("gewu-pdf-pages");
    root.onscroll = null;
  }
  function live(session) {
    return current === session && state.libraryQuickLookOpen
      && state.libraryQuickLookKind === "pdf" && state.libraryQuickLookPath === session.path;
  }
  function release(slot) {
    slot.render?.cancel(); slot.text?.cancel();
    slot.render = null; slot.text = null; slot.renderedWidth = 0;
    delete slot.element.dataset.rendered;
    for (const canvas of slot.element.querySelectorAll("canvas")) canvas.width = canvas.height = 0;
    slot.element.replaceChildren();
  }
  function message(text, retry) {
    const element = document.createElement("div"); element.className = "gewu-pdf-message";
    element.setAttribute("role", "status"); element.textContent = text;
    if (retry) {
      const button = document.createElement("button"); button.className = "smallbtn";
      button.type = "button"; button.textContent = "Retry"; button.onclick = retry; element.append(button);
    }
    root.replaceChildren(element);
  }
  function pageWidth() { return Math.max(100, root.clientWidth - 20); }
  async function renderPage(session, slot) {
    if (!live(session) || slot.busy || slot.renderedWidth === pageWidth()) return;
    slot.busy = true;
    let failed = false;
    try {
      const page = await session.pdf.getPage(slot.number);
      if (!live(session) || !session.visible.has(slot)) return;
      release(slot);
      const base = page.getViewport({scale:1}), width = pageWidth();
      const viewport = page.getViewport({scale:width / base.width});
      slot.ratio = base.height / base.width;
      slot.element.style.height = `${viewport.height}px`;
      slot.element.style.setProperty("--total-scale-factor", viewport.scale);
      const canvas = document.createElement("canvas");
      canvas.setAttribute("aria-label", `PDF page ${slot.number}`);
      // Bound backing storage even for unusually large pages on Retina screens.
      const ratio = Math.min(devicePixelRatio || 1, 2, Math.sqrt(16000000 / (width * viewport.height)));
      canvas.width = Math.max(1, Math.floor(width * ratio));
      canvas.height = Math.max(1, Math.floor(viewport.height * ratio));
      slot.element.append(canvas);
      slot.render = page.render({canvasContext:canvas.getContext("2d"), viewport,
        transform:[ratio, 0, 0, ratio, 0, 0]});
      await slot.render.promise;
      if (!live(session) || !session.visible.has(slot)) return;
      const text = document.createElement("div"); text.className = "textLayer";
      slot.element.append(text);
      slot.text = new session.engine.TextLayer({textContentSource:page.streamTextContent(), container:text, viewport});
      await slot.text.render();
      slot.renderedWidth = width;
      slot.element.dataset.rendered = "true";
    } catch (error) {
      if (live(session) && session.visible.has(slot) && !/cancel|abort|destroy/i.test(String(error))) {
        failed = true;
        slot.element.textContent = `Page ${slot.number} could not be displayed. Use Open in Preview.`;
        slot.element.dataset.error = "true";
      }
    } finally {
      slot.busy = false;
      if (!failed && live(session) && session.visible.has(slot)
          && slot.renderedWidth !== pageWidth()) void renderPage(session, slot);
    }
  }
  function visiblePage(session) {
    const top = root.getBoundingClientRect().top + 32;
    const slot = session.slots.find(item => item.element.getBoundingClientRect().bottom > top);
    if (slot && slot.number !== state.libraryQuickLookPage) updateLibraryQuickLookActivePage(slot.number);
  }
  function resize() {
    const session = current;
    if (!session?.pdf || !live(session)) return;
    const width = pageWidth();
    if (width === session.width) return;
    session.width = width;
    const page = state.libraryQuickLookPage;
    for (const slot of session.slots) {
      slot.element.style.width = `${width}px`;
      slot.element.style.height = `${width * slot.ratio}px`;
    }
    for (const slot of session.visible) if (!slot.busy) void renderPage(session, slot);
    jump(page);
  }
  function jump(page) {
    const session = current;
    if (!session?.pdf) return;
    const slot = session.slots[Math.max(0, Math.min(session.slots.length - 1, Number(page) - 1))];
    if (slot) root.scrollTop += slot.element.getBoundingClientRect().top - root.getBoundingClientRect().top - 10;
  }
  async function open(session, url) {
    try {
      const target = new URL(url, location.href);
      if (target.origin !== location.origin || target.pathname !== "/files" || target.username || target.password) {
        throw new Error("The PDF is not in this Gewu workspace.");
      }
      target.hash = "";
      const [pdfEngine, response] = await Promise.all([engine(), fetch(target.href, {
        credentials:"same-origin", redirect:"error", signal:session.abort.signal
      })]);
      if (!response.ok) throw new Error("The PDF could not be read.");
      const data = new Uint8Array(await response.arrayBuffer());
      if (!live(session)) return;
      session.engine = pdfEngine;
      session.loading = pdfEngine.getDocument({data, BinaryDataFactory, useWorkerFetch:false,
        isEvalSupported:false, enableXfa:false});
      session.pdf = await session.loading.promise;
      if (!live(session)) return;
      const firstPage = await session.pdf.getPage(1);
      if (!live(session)) return;
      const viewport = firstPage.getViewport({scale:1});
      session.width = pageWidth();
      const fragment = document.createDocumentFragment();
      for (let number = 1; number <= session.pdf.numPages; number++) {
        const element = document.createElement("div"); element.className = "gewu-pdf-page";
        element.dataset.previewPage = number;
        element.style.width = `${session.width}px`;
        element.style.height = `${session.width * viewport.height / viewport.width}px`;
        session.slots.push({number, element, ratio:viewport.height / viewport.width});
        fragment.append(element);
      }
      root.replaceChildren(fragment);
      session.observer = new IntersectionObserver(entries => {
        for (const entry of entries) {
          const slot = session.slots[Number(entry.target.dataset.previewPage) - 1];
          if (entry.isIntersecting) { session.visible.add(slot); void renderPage(session, slot); }
          else { session.visible.delete(slot); release(slot); delete slot.element.dataset.rendered; }
        }
      }, {root, rootMargin:"500px 0px"});
      for (const slot of session.slots) session.observer.observe(slot.element);
      root.onscroll = () => visiblePage(session);
      state.libraryQuickLookPageCount = session.pdf.numPages;
      scheduleLibraryQuickLookThumbs(session.path, session.pdf.numPages);
      jump(state.libraryQuickLookPage);
    } catch (error) {
      if (!live(session) || session.abort.signal.aborted) return;
      message(`PDF preview could not open. ${error.message || error}`, () => {
        dispose(); renderLibraryQuickLookPages();
      });
    }
  }
  // Replace only these two PDF browser hooks, in this plugin-owned page/realm.
  // Never create a raw PDF iframe: Gecko would hand it to its download handler.
  renderLibraryQuickLookPages = function () {
    if (current?.path === state.libraryQuickLookPath && root.childElementCount) return;
    dispose();
    if (!state.libraryQuickLookUrl) { root.replaceChildren(); return; }
    current = {path:state.libraryQuickLookPath, abort:new AbortController(), slots:[], visible:new Set()};
    root.classList.add("gewu-pdf-pages"); root.scrollTop = 0;
    message("Loading PDF…");
    void open(current, state.libraryQuickLookUrl);
  };
  updateLibraryPdfFramePage = jump;
  const observer = new MutationObserver(() => {
    if (current && (!overlay.classList.contains("open") || state.libraryQuickLookKind !== "pdf")) dispose();
  });
  observer.observe(overlay, {attributes:true, attributeFilter:["class"]});
  const sizing = new ResizeObserver(() => {
    clearTimeout(resizeTimer); resizeTimer = setTimeout(resize, 120);
  });
  sizing.observe(root);
  window.addEventListener("pagehide", () => {
    dispose(); observer.disconnect(); sizing.disconnect(); clearTimeout(resizeTimer);
    for (const url of urls) URL.revokeObjectURL(url);
  }, {once:true});
})();
