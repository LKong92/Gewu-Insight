// Windows PDFium preview: continuous pages, native scrolling, no extra toolbar.
(() => {
  let active = null, cacheBytes = 0;
  const cache = new Map();
  const live = a => active === a && a.body.isConnected;
  const pageUrl = (a, n, size) => '/api/pdf-thumb?' + new URLSearchParams({path:a.path, page:n, size, v:a.version});
  function remember(key, blob) {
    if (cache.has(key)) return cache.get(key).url;
    const value = {url:URL.createObjectURL(blob), bytes:blob.size};
    cache.set(key, value); cacheBytes += blob.size;
    while (cache.size > 16 || cacheBytes > 48 * 1024 * 1024) {
      const oldest = cache.keys().next().value, removed = cache.get(oldest);
      URL.revokeObjectURL(removed.url); cacheBytes -= removed.bytes; cache.delete(oldest);
    }
    return value.url;
  }
  function close() {
    const a = active; active = null;
    if (!a) return;
    a.controller.abort(); a.resize.disconnect(); cancelAnimationFrame(a.frame);
    clearTimeout(a.zoomTimer);
    for (const entry of a.pending.values()) entry.controller.abort();
    document.getElementById('libraryQuickLookThumbs')?.replaceChildren();
  }
  function schedule(a) {
    if (!live(a) || a.frame) return;
    a.frame = requestAnimationFrame(() => { a.frame = 0; refresh(a); });
  }
  function atOffset(a, y) {
    let lo = 0, hi = a.pages.length - 1;
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2), node = a.pages[mid].node;
      if (node.offsetTop + node.offsetHeight < y) lo = mid + 1; else hi = mid;
    }
    return lo;
  }
  function setActivePage(a, index) {
    const page = index + 1;
    if (a.page === page) return;
    a.page = page; a.changed(page, a.pages.length);
    a.status.textContent = `Page ${page} of ${a.pages.length}`;
  }
  function refresh(a) {
    if (!live(a) || !a.pages.length) return;
    const top = a.body.scrollTop - a.strip.offsetTop;
    const index = atOffset(a, top + Math.min(a.body.clientHeight * .35, 160));
    setActivePage(a, index);
    const first = atOffset(a, Math.max(0, top - 400));
    const last = atOffset(a, top + a.body.clientHeight + 400);
    const wanted = new Map();
    // Reading pages take priority over thumbnails. Only two renders run at once.
    const visible = a.pages.slice(first, last + 1).sort((x, y) => Math.abs(x.n - a.page) - Math.abs(y.n - a.page));
    for (const record of visible) wanted.set(record, pageUrl(a, record.n, a.quality));
    if (a.firstPageReady && a.thumbsRoot) {
      const start = a.thumbsRoot.scrollTop, end = start + a.thumbsRoot.clientHeight;
      for (const record of a.thumbnails) {
        const node = record.node;
        if (node.offsetTop + node.offsetHeight >= start - 80 && node.offsetTop <= end + 80)
          wanted.set(record, pageUrl(a, record.n, 240));
      }
    }
    a.wanted = wanted;
    for (const [record, pending] of a.pending) if (wanted.get(record) !== pending.key) pending.controller.abort();
    for (const record of a.loaded) if (!wanted.has(record)) {
      record.node.querySelector('img')?.remove(); record.key = ''; a.loaded.delete(record);
    }
    pump(a);
  }
  function pump(a) {
    if (!live(a)) return;
    for (const [record, key] of a.wanted) {
      if (a.pending.size >= 2) break;
      if (record.key === key || record.failed === key || a.pending.has(record)) continue;
      const pending = {controller:new AbortController(), key}; a.pending.set(record, pending);
      load(a, record, pending);
    }
  }
  async function load(a, record, pending) {
    const {key, controller} = pending;
    try {
      let src = cache.get(key)?.url;
      if (!src) {
        const response = await fetch(key, {signal:controller.signal, cache:'no-store'});
        if (!response.ok) throw Error('Page could not be read.');
        const blob = await response.blob();
        if (!live(a) || controller.signal.aborted || a.wanted.get(record) !== key) return;
        if (!blob.type.startsWith('image/')) throw Error('Invalid PDF page.');
        src = remember(key, blob);
      }
      const image = new Image(); image.src = src; image.alt = record.thumb ? '' : `PDF page ${record.n}`; image.draggable = false;
      await image.decode();
      if (!live(a) || controller.signal.aborted || a.wanted.get(record) !== key) return;
      record.node.querySelector('img')?.remove(); record.node.querySelector('.windows-pdf-retry')?.remove();
      (record.preview || record.node).prepend(image); record.key = key; record.node.removeAttribute('aria-busy'); a.loaded.add(record);
      if (!record.thumb && !a.firstPageReady) { a.firstPageReady = true; schedule(a); }
    } catch (error) {
      if (live(a) && !controller.signal.aborted && a.wanted.get(record) === key) {
        record.failed = key;
        if (!record.thumb) {
          const retry = document.createElement('button'); retry.className = 'windows-pdf-retry'; retry.textContent = 'Retry page';
          retry.onclick = () => { record.failed = ''; retry.remove(); pump(a); }; record.node.append(retry);
          a.status.textContent = error.message;
        }
      }
    } finally { a.pending.delete(record); pump(a); }
  }
  function thumbs() {
    const a = active, root = document.getElementById('libraryQuickLookThumbs');
    if (!a || !root || !a.pages.length) return;
    if (a.thumbsRoot === root && root.firstElementChild) { schedule(a); return; }
    a.thumbsRoot = root; root.replaceChildren(); root.style.position = 'relative';
    const fragment = document.createDocumentFragment();
    a.thumbnails = a.pages.map(({n, ratio}) => {
      const button = document.createElement('button'); button.type = 'button'; button.dataset.page = n;
      button.className = 'library-page-thumb' + (n === a.page ? ' active' : ''); button.title = `Page ${n}`;
      const preview = document.createElement('span'); preview.className = 'library-page-thumb-preview'; preview.style.aspectRatio = ratio;
      const label = document.createElement('span'); label.textContent = n; button.append(preview, label);
      button.onclick = () => show(n); fragment.append(button);
      return {n, node:button, preview, thumb:true, key:''};
    });
    root.append(fragment); root.onscroll = () => schedule(a); schedule(a);
  }
  function show(number) {
    const a = active; if (!a?.pages.length) return;
    const index = Math.max(0, Math.min(a.pages.length - 1, Math.trunc(Number(number) || 1) - 1));
    a.body.scrollTop = a.pages[index].node.offsetTop + a.strip.offsetTop;
    setActivePage(a, index); schedule(a);
  }
  function resize(a) {
    if (!live(a)) return;
    a.strip.style.width = `${Math.max(120, a.body.clientWidth - 24) * a.zoom}px`;
    schedule(a);
  }
  function zoom(a, factor, clientX, clientY) {
    if (!a.pages.length) return;
    const rect = a.body.getBoundingClientRect(), x = clientX ?? rect.left + rect.width / 2, y = clientY ?? rect.top + rect.height / 2;
    const record = a.pages[atOffset(a, a.body.scrollTop + y - rect.top - a.strip.offsetTop)];
    const before = record.node.getBoundingClientRect();
    const fx = (x - before.left) / before.width, fy = (y - before.top) / before.height;
    a.zoom = Math.max(.5, Math.min(4, a.zoom * factor)); resize(a);
    const after = record.node.getBoundingClientRect();
    a.body.scrollLeft += after.left + fx * after.width - x;
    a.body.scrollTop += after.top + fy * after.height - y;
    clearTimeout(a.zoomTimer);
    a.zoomTimer = setTimeout(() => { if (live(a)) { a.quality = a.zoom > 1.4 ? 2048 : 1600; schedule(a); } }, 150);
  }
  function render(root, path, changed) {
    if (active?.path === path && active.root === root && root.querySelector('.windows-pdf-reader')) return;
    close();
    root.innerHTML = '<div class="windows-pdf-reader"><div class="windows-pdf-status" role="status">Loading PDF…</div><div class="windows-pdf-body" tabindex="0" aria-label="PDF reading area"><div class="windows-pdf-strip"></div></div></div>';
    const a = active = {root, path, changed, controller:new AbortController(), page:0, pages:[], thumbnails:[], zoom:1, quality:1600,
      pending:new Map(), wanted:new Map(), loaded:new Set(), body:root.querySelector('.windows-pdf-body'), strip:root.querySelector('.windows-pdf-strip'), status:root.querySelector('[role=status]')};
    a.resize = new ResizeObserver(() => resize(a)); a.resize.observe(a.body);
    a.body.addEventListener('scroll', () => schedule(a), {passive:true});
    // Precision touchpad pinch arrives as Ctrl+wheel in Chromium. Consume only
    // that gesture; ordinary two-finger scrolling stays native and continuous.
    a.body.addEventListener('wheel', event => {
      if (!event.ctrlKey) return;
      event.preventDefault(); event.stopPropagation();
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? a.body.clientHeight : 1);
      zoom(a, Math.exp(-Math.max(-120, Math.min(120, delta)) * .01), event.clientX, event.clientY);
    }, {passive:false});
    // Coalesce selections made in the same event turn. Aborted previews must
    // not fill the local connection queue ahead of the current attachment.
    Promise.resolve().then(() => {
      if (!live(a) || a.controller.signal.aborted) return;
      return fetch('/api/pdf-info?' + new URLSearchParams({path, layout:1}), {signal:a.controller.signal, cache:'no-store'});
    })
      .then(async response => { if (!live(a)) return; const data = await response.json(); if (!response.ok) throw Error(data.error || 'PDF could not be read.'); return data; })
      .then(data => {
        if (!live(a)) return;
        if (!data.page_count || data.page_sizes?.length !== data.page_count) throw Error('PDF page layout is unavailable.');
        a.version = data.file_version;
        const fragment = document.createDocumentFragment();
        a.pages = data.page_sizes.map(([width, height], index) => {
          const node = document.createElement('div'), n = index + 1, ratio = width / height;
          node.className = 'windows-pdf-sheet'; node.dataset.page = n; node.style.aspectRatio = ratio;
          node.setAttribute('aria-label', `Page ${n}`); node.setAttribute('aria-busy', 'true'); fragment.append(node);
          return {n, ratio, node, key:''};
        });
        a.strip.append(fragment); a.status.classList.add('visually-hidden'); resize(a); thumbs(); refresh(a);
      })
      .catch(error => { if (live(a) && error.name !== 'AbortError') a.status.textContent = error.message; });
  }
  addEventListener('keydown', event => {
    const a = active;
    if (!a || event.altKey || event.target.closest?.('input,textarea,[contenteditable="true"]')) return;
    if ((event.ctrlKey || event.metaKey) && ['+', '=', '-', '0'].includes(event.key)) {
      event.preventDefault(); event.stopImmediatePropagation(); zoom(a, event.key === '0' ? 1 / a.zoom : event.key === '-' ? 1 / 1.15 : 1.15); return;
    }
    if (event.ctrlKey || event.metaKey || !['PageUp','PageDown','Home','End'].includes(event.key)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (event.key === 'Home' || event.key === 'End') show(event.key === 'Home' ? 1 : a.pages.length);
    else a.body.scrollBy({top:(event.key === 'PageDown' ? 1 : -1) * a.body.clientHeight * .9, behavior:'instant'});
  }, true);
  addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style'); style.textContent = `
      #libraryQuickLookPages:has(.windows-pdf-reader){position:relative;display:block;padding:0;overflow:hidden}
      .windows-pdf-reader{position:absolute;inset:0;background:#e6e8eb}
      .windows-pdf-body{position:absolute;inset:0;overflow:auto;overscroll-behavior:contain;padding:12px;box-sizing:border-box;outline:none}
      .windows-pdf-strip{position:relative;display:flex;flex-direction:column;gap:12px;margin:0 auto}
      .windows-pdf-sheet{position:relative;flex:none;width:100%;background:white;box-shadow:0 1px 5px #0003;overflow:hidden}
      .windows-pdf-sheet>img{display:block;width:100%;height:100%;object-fit:fill;max-width:none;user-select:none}
      .windows-pdf-status{position:absolute;top:12px;left:12px;z-index:1;font-size:13px;color:#475467}
      .windows-pdf-status.visually-hidden{clip-path:inset(50%);width:1px;height:1px;overflow:hidden;white-space:nowrap}
      .windows-pdf-retry{position:absolute;top:12px;left:12px}
    `; document.head.append(style);
  }, {once:true});
  window.gewuWindowsPdf = {render, page:show, thumbs, close};
})();
