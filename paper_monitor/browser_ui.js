/* Browser chrome lives in the trusted workspace; remote content lives in a
 * separate native WKWebView. Never embed a remote page under the local origin. */
(function (global) {
  "use strict";
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function address(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (/^[a-z][a-z\d+.-]*:/i.test(text) && !/^https?:/i.test(text)) throw new Error("Use an HTTP or HTTPS website address.");
    if (/^https?:\/\//i.test(text)) return new URL(text).href;
    if (!/\s/.test(text) && /^[^/]+\.[^/]+/.test(text)) return new URL("https://" + text).href;
    return "https://www.google.com/search?q=" + encodeURIComponent(text);
  }
  function folderChoices(nodes, excludedId = null) {
    const result = [], seen = new Set();
    const walk = (parent, prefix) => {
      for (const node of nodes.filter(n => n.parent_id === parent && n.kind === "folder")) {
        if (node.id === excludedId || seen.has(node.id)) continue;
        seen.add(node.id);
        const title = prefix ? prefix + " / " + node.title : node.title;
        result.push({id: node.id, title}); walk(node.id, title);
      }
    };
    walk(null, ""); return result;
  }
  function bookmarkTree(nodes, expanded, query = "") {
    const result = [], seen = new Set(), needle = query.trim().toLocaleLowerCase();
    if (needle) return nodes.filter(n => `${n.title} ${n.url || ""}`.toLocaleLowerCase().includes(needle)).map(n => ({...n, depth: 0}));
    const walk = (parent, depth) => {
      for (const node of nodes.filter(n => n.parent_id === parent)) {
        if (seen.has(node.id)) continue;
        seen.add(node.id); result.push({...node, depth});
        if (node.kind === "folder" && expanded.has(node.id)) walk(node.id, depth + 1);
      }
    };
    walk(null, 0); return result;
  }
  function dayLabel(value, today = new Date()) {
    const date = new Date(value), yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (date.toDateString() === today.toDateString()) return "Today";
    if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
    return date.toLocaleDateString(undefined, {year:"numeric", month:"short", day:"numeric"});
  }
  function droppedURL(value) {
    const line = String(value || "").split(/\r?\n/).find(text => text.trim() && !text.startsWith("#"))?.trim();
    if (!/^https?:\/\//i.test(line || "")) throw new Error("Drag an HTTP or HTTPS website link to Bookmarks.");
    return new URL(line).href;
  }
  function microtaskScheduler(callback) {
    let pending = false;
    return () => {
      if (pending) return;
      pending = true;
      queueMicrotask(() => { pending = false; callback(); });
    };
  }
  function favoritesFolder(nodes) {
    const folders = nodes.filter(node => node.kind === "folder");
    // Home is fixed to Favorites, never an old arbitrary folder preference or
    // a browser's unrelated toolbar folder. Prefer the canonical English name.
    for (const name of ["favorites", "favourites", "个人收藏", "收藏夹"]) {
      const matches = folders.filter(node => node.title.trim().toLocaleLowerCase() === name);
      if (matches.length) return matches.find(node => node.parent_id == null) || matches[0];
    }
    return null;
  }
  function inlineCompletion(typed, url) {
    if (!typed || /\s/.test(typed)) return null;
    const candidates = [url, url.replace(/^https?:\/\//i, ""), url.replace(/^https?:\/\/(www\.)?/i, "")];
    const match = candidates.find(value => value.toLocaleLowerCase().startsWith(typed.toLocaleLowerCase()) && value.length > typed.length);
    return match ? typed + match.slice(typed.length) : null;
  }
  function favoriteContents(nodes, folder, requested) {
    if (!folder) return {folder:null, trail:[], items:[]};
    const trail = [], seen = new Set();
    let current = nodes.find(node => node.id === requested && node.kind === "folder") || folder;
    while (current && !seen.has(current.id)) {
      seen.add(current.id); trail.unshift(current);
      if (current.id === folder.id) return {folder:trail[trail.length - 1], trail, items:nodes.filter(node => node.parent_id === trail[trail.length - 1].id)};
      current = nodes.find(node => node.id === current.parent_id && node.kind === "folder");
    }
    return {folder, trail:[folder], items:nodes.filter(node => node.parent_id === folder.id)};
  }
  // Match the tile metrics in browser_ui.css. Favorites owns the entire local
  // Home; overflow is paged, never clipped or vertically scrolled.
  function homeLayout(width, height, count, nested = false) {
    const columns = Math.max(1, Math.floor((Math.min(1100, width) - 48 + 12) / 100));
    const overhead = 48 + (nested ? 30 : 0);
    const budget = Math.max(140 + overhead, height);
    const needed = Math.max(1, Math.ceil(count / columns));
    let rows = Math.max(1, Math.min(needed, Math.floor((budget - overhead) / 106)));
    if (rows < needed) rows = Math.max(1, Math.floor((budget - overhead - 26) / 106));
    const capacity = rows * columns, pages = Math.max(1, Math.ceil(count / capacity));
    return {columns, capacity, pages, height:rows * 106 + overhead + (pages > 1 ? 26 : 0)};
  }
  const model = {address, droppedURL, bookmarkTree, folderChoices, dayLabel, escape, microtaskScheduler, favoritesFolder, favoriteContents, inlineCompletion, homeLayout};
  if (typeof module !== "undefined" && module.exports) module.exports = model;
  if (typeof document === "undefined") return;

  const $ = id => document.getElementById(id);
  const bridge = () => global.webkit?.messageHandlers?.browser;
  const native = payload => { if (bridge()) bridge().postMessage(payload); };
  const data = {active:false, opened:false, loaded:false, tab:"bookmarks", bookmarks:[], history:[], more:false,
    preferences:{}, expanded:new Set(), width:250, hidden:false, url:"", title:"", loading:false,
    query:"", selected:null, favoritePath:null, favoritePage:0, favoriteLayout:"", home:false, fetching:0, layout:"", editor:null, confirm:null, searchTimer:null, persistTimer:null,
    addressQuery:"", suggestions:[], suggestionIndex:-1, suggestionGeneration:0, addressTimer:null, composing:false,
    browserTabs:[], browserTab:"", tabsSignature:"", tabChrome:new Map(), workspaceReturn:null};
  const icons = {
    back:'<path d="m14 5-7 7 7 7"/>', forward:'<path d="m10 5 7 7-7 7"/>',
    reload:'<path d="M19 8a8 8 0 1 0 1 7M19 3v6h-6"/>', stop:'<path d="m6 6 12 12M18 6 6 18"/>',
    home:'<path d="m3 11 9-8 9 8M6 9v11h5v-6h3v6h4V9"/>',
    sidebar:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    bookmark:'<path d="M6 4h12v17l-6-4-6 4V4Z"/>',
    share:'<path d="M8 8H5v13h14V8h-3M12 14V2m-4 4 4-4 4 4"/>',
    globe:'<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
    folder:'<path d="M3 7V5h7l2 3h9v12H3V7Z"/>', plus:'<path d="M12 4v16M4 12h16"/>',
    down:'<path d="m6 9 6 6 6-6"/>', right:'<path d="m9 6 6 6-6 6"/>',
    download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    external:'<path d="M14 3h7v7m0-7L10 14M11 5H4v16h16v-7"/>',
    key:'<circle cx="8" cy="9" r="5"/><path d="m12 13 8 8m-3-3 3-3m-6 0 3-3"/>'
  };
  const icon = key => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[key] || icons.globe}</svg>`;
  const button = (id, title, glyph) => `<button type="button" id="${id}" title="${title}" aria-label="${title}">${icon(glyph)}</button>`;
  const root = document.createElement("section");
  root.id = "gewuBrowser"; root.hidden = true; root.setAttribute("aria-label", "Browser");
  root.innerHTML = `
    <div class="browser-toolbar">
      ${button("browserSidebarToggle", "Show or hide sidebar", "sidebar")}
      ${button("browserBack", "Back", "back")}${button("browserForward", "Forward", "forward")}
      ${button("browserReload", "Reload", "reload")}${button("browserHome", "Home — Favorites", "home")}
      <form id="browserAddressForm" class="browser-address-form">
        <a id="browserSiteIcon" href="#" draggable="true" title="Drag this page into a bookmark folder" aria-label="Drag page to bookmarks">${icon("globe")}</a>
        <input id="browserAddress" type="text" placeholder="Search Google or enter a website" aria-label="Search Google or enter a website" aria-autocomplete="both" aria-expanded="false" autocomplete="off" autocapitalize="off" spellcheck="false">
        <div id="browserProgress" class="browser-progress"></div>
      </form>
      <button type="button" id="browserSaveGewu" class="browser-save-gewu" title="Save this article or PDF to Library" disabled>Save to Gewu</button>
      ${button("browserAddBookmark", "Add Bookmark (⌘D)", "bookmark")}
      ${button("browserPasswords", "Open Passwords", "key")}
      ${button("browserShare", "Share and page actions", "share")}
      ${button("browserNewTab", "New Tab (⌘T)", "plus")}
    </div>
    <div class="browser-body">
      <aside id="browserSidebar" class="browser-sidebar" aria-label="Browser sidebar">
        <div class="browser-sidebar-tabs" role="tablist" aria-label="Browser collections">
          <button id="browserBookmarksTab" role="tab" aria-selected="true" title="Bookmarks · Drop here to move to the root folder">Bookmarks</button>
          <button id="browserHistoryTab" role="tab" aria-selected="false">History</button>
        </div>
        <div id="browserCollection" class="browser-collection" tabindex="0" role="tabpanel" aria-label="Bookmarks"></div>
        <div class="browser-sidebar-footer">
          <div id="browserBookmarkTransfer"><button id="browserBookmarkMenu" title="Bookmarks menu: Import, Export, Sync" aria-label="Bookmarks menu" aria-haspopup="menu" aria-expanded="false">B</button></div>
          <button id="browserNewFolder" title="New Folder" aria-label="New Folder">${icon("plus")}</button>
          <button id="browserClearHistory" hidden>Clear History</button>
          <input id="browserSidebarSearch" class="browser-sidebar-search" type="search" placeholder="Search bookmarks" aria-label="Search bookmarks">
        </div>
        <div id="browserResize" class="browser-sidebar-resize" role="separator" tabindex="0" aria-label="Resize browser sidebar" aria-orientation="vertical"></div>
      </aside>
      <div class="browser-page-column">
        <div id="browserTabs" class="browser-tabs" role="tablist" aria-label="Webpage tabs"></div>
        <div id="browserFindBar" class="browser-find" hidden><input id="browserFindInput" placeholder="Find on page" aria-label="Find on page"><button id="browserFindPrevious" title="Previous match">↑</button><button id="browserFindNext" title="Next match">↓</button><span id="browserFindResult"></span><button id="browserFindClose" aria-label="Close find">×</button></div>
        <div id="browserMessage" class="browser-message" role="status" hidden><span id="browserMessageText"></span><button id="browserMessageAction" hidden></button><button id="browserMessageDismiss" aria-label="Dismiss message">×</button></div>
        <div id="browserViewport" class="browser-viewport"><div class="browser-native-placeholder">${icon("globe")}<strong>Browser</strong><span id="browserNativeHint">Opening the native web browser.</span></div></div>
        <section id="browserFavorites" class="browser-favorites" aria-label="Favorites start page" hidden>
          <div class="browser-favorites-inner">
            <nav id="browserFavoritesTrail" class="browser-favorites-trail" aria-label="Favorite folders" hidden></nav>
            <div id="browserFavoritesGrid" class="browser-favorites-grid"></div>
            <nav id="browserFavoritesPages" class="browser-favorites-pages" aria-label="Favorites pages" hidden>${button("browserFavoritesPrevious", "Previous favorites", "back")}<span id="browserFavoritesPage" aria-live="polite"></span>${button("browserFavoritesNext", "Next favorites", "forward")}</nav>
          </div>
        </section>
        <div class="browser-page-footer"><span title="Uses the system network. Actual DIRECT or proxy routing is determined by your network and Clash configuration.">System network</span><span id="browserPageTitle"></span>${button("browserDownload", "Save Download", "download")}${button("browserExternal", "Open in Safari", "external")}</div>
      </div>
    </div><div id="browserContext" class="browser-context" hidden></div>`;
  document.body.append(root);

  const siteIcons = new Map();
  const faviconObserver = new IntersectionObserver(entries => {
    if (!data.active || data.hidden || data.tab !== "bookmarks") return;
    for (const entry of entries) if (entry.isIntersecting && !siteIcons.has(entry.target.dataset.iconHost)) {
      native({action:"favicon", url:entry.target.dataset.iconUrl});
    }
  }, {root:$("browserCollection"), rootMargin:"32px"});
  const favoritesIconObserver = new IntersectionObserver(entries => {
    if (!data.active || !data.home) return;
    for (const entry of entries) if (entry.isIntersecting && !siteIcons.has(entry.target.dataset.iconHost)) {
      native({action:"favicon", url:entry.target.dataset.iconUrl});
    }
  }, {root:$("browserFavorites"), rootMargin:"32px"});
  function bookmarkIcon(node, tile = false) {
    if (node.kind === "folder") return icon("folder");
    const host = new URL(node.url).hostname.toLowerCase(), saved = siteIcons.get(host);
    return `<span class="browser-site-image" data-icon-host="${escape(host)}" data-icon-url="${escape(node.url)}">${saved ? `<img alt="" src="${escape(saved)}">` : tile ? `<span class="browser-monogram">${escape(Array.from(node.title.trim() || host)[0].toLocaleUpperCase())}</span>` : icon("globe")}</span>`;
  }
  function renderFavorites() {
    favoritesIconObserver.disconnect();
    const folder = favoritesFolder(data.bookmarks);
    const contents = favoriteContents(data.bookmarks, folder, data.favoritePath);
    if (data.favoritePath !== (contents.folder?.id || null)) data.favoritePage = 0;
    data.favoritePath = contents.folder?.id || null;
    const column = root.querySelector(".browser-page-column");
    const available = column.clientHeight - $("browserTabs").offsetHeight - root.querySelector(".browser-page-footer").offsetHeight - $("browserFindBar").offsetHeight - $("browserMessage").offsetHeight;
    const fit = homeLayout(column.clientWidth, available, contents.items.length + 1, contents.trail.length > 1);
    data.favoriteLayout = `${column.clientWidth}:${available}`;
    data.favoritePage = Math.max(0, Math.min(data.favoritePage, fit.pages - 1));
    root.style.setProperty("--browser-favorites-columns", fit.columns);
    $("browserFavoritesPages").hidden = fit.pages === 1;
    $("browserFavoritesPage").textContent = `${data.favoritePage + 1} / ${fit.pages}`;
    $("browserFavoritesPrevious").disabled = data.favoritePage === 0;
    $("browserFavoritesNext").disabled = data.favoritePage === fit.pages - 1;
    $("browserFavoritesTrail").hidden = contents.trail.length < 2;
    $("browserFavoritesTrail").innerHTML = contents.trail.map((item, index) => `${index ? '<span aria-hidden="true">/</span>' : ''}<button data-favorite-folder="${item.id}" ${index === contents.trail.length - 1 ? 'aria-current="page"' : ''}>${escape(item.title)}</button>`).join("");
    const tiles = contents.items.map(node => `<button class="browser-favorite-tile" data-favorite-id="${node.id}" title="${escape(node.url || node.title)}"><span class="browser-favorite-icon ${node.kind}" aria-hidden="true">${bookmarkIcon(node, true)}</span><span class="browser-favorite-title">${escape(node.title)}</span></button>`);
    tiles.push(folder ? `<button class="browser-favorite-tile browser-favorite-add" id="browserAddFavorite" title="Add a bookmark to this folder"><span class="browser-favorite-icon">${icon("plus")}</span><span class="browser-favorite-title">Add Favorite</span></button>` : '<div class="browser-favorites-empty">Websites in your Favorites folder appear here.<button id="browserCreateFavorites">Create Favorites Folder</button></div>');
    $("browserFavoritesGrid").innerHTML = tiles.slice(data.favoritePage * fit.capacity, (data.favoritePage + 1) * fit.capacity).join("");
    $("browserAddFavorite")?.addEventListener("click", () => edit({title:"New Favorite",url:"https://"}, "bookmark", contents.folder.id).catch(fail));
    $("browserCreateFavorites")?.addEventListener("click", async () => {
      try {
        const result = await api("save_bookmark", {kind:"folder", title:"Favorites", parent_id:null});
        data.favoritePath = null; await refresh();
      } catch (error) { fail(error); }
    });
    $("browserFavoritesGrid").querySelectorAll('[data-icon-host]').forEach(element => favoritesIconObserver.observe(element));
  }
  function updateHome(home = false) {
    if (data.home === home) return;
    data.home = home;
    root.classList.toggle("browser-at-home", home);
    $("browserFavorites").hidden = !home;
    if (home) renderFavorites();
    scheduleLayout();
  }

  function renderTabs() {
    const signature = JSON.stringify([data.browserTab, data.browserTabs]);
    if (signature === data.tabsSignature) return;
    data.tabsSignature = signature;
    const list = $("browserTabs");
    const existing = new Map([...list.children].map(element => [element.dataset.browserTab, element]));
    data.browserTabs.forEach((tab, index) => {
      const selected = tab.id === data.browserTab;
      let host = ""; try { host = new URL(tab.url).hostname; } catch (_) {}
      const saved = siteIcons.get(host);
      let element = existing.get(tab.id);
      if (!element) {
        element = document.createElement('div'); element.dataset.browserTab = tab.id;
        element.setAttribute('role','tab');
        element.innerHTML = '<button class="browser-tab-close" title="Close Tab (⌘W)">×</button><span class="browser-tab-icon" aria-hidden="true"></span><span class="browser-tab-title"></span>';
      }
      element.className = 'browser-web-tab' + (selected ? ' selected' : '');
      element.tabIndex = selected ? 0 : -1; element.setAttribute('aria-selected', String(selected));
      element.setAttribute('aria-label',tab.title || 'New Tab'); element.title = (tab.title || 'New Tab') + (tab.url ? '\n'+tab.url : '');
      const glyph = element.querySelector('.browser-tab-icon');
      glyph.classList.toggle('loading', Boolean(tab.loading));
      const markup = tab.loading ? icon('reload') : saved ? `<img alt="" src="${escape(saved)}">` : icon(tab.home ? 'home' : 'globe');
      if (glyph.innerHTML !== markup) glyph.innerHTML = markup;
      element.querySelector('.browser-tab-title').textContent = tab.title || 'New Tab';
      const close = element.querySelector('.browser-tab-close'); close.dataset.closeTab = tab.id;
      close.tabIndex = selected ? 0 : -1; close.setAttribute('aria-label','Close '+(tab.title || 'tab'));
      if (list.children[index] !== element) list.insertBefore(element, list.children[index] || null);
      existing.delete(tab.id);
    });
    for (const element of existing.values()) element.remove();
    // Keep stable tab nodes, never focus() in a background title/icon callback.
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({block:"nearest", inline:"nearest"});
  }

  function newTab(url) { closeContext(); closeSuggestions(); native({action:"new-tab", ...(url ? {url} : {})}); }

  function message(text, error = false, action = null) {
    $("browserMessageText").textContent = text || "";
    $("browserMessage").hidden = !text;
    $("browserMessage").classList.toggle("error", error);
    const button = $("browserMessageAction");
    button.hidden = !action; button.disabled = false;
    button.textContent = action?.label || "";
    const handler = action ? async () => {
      button.disabled = true;
      try { await action.run(); }
      catch (error) {
        if (button.onclick === handler) message(error.message || "Could not open Library. Try again.", true, action);
      } finally { if (button.onclick === handler) button.disabled = false; }
    } : null;
    button.onclick = handler;
    scheduleLayout();
  }
  async function api(action, payload = {}) {
    const response = await fetch("/api/browser", {method:"POST", headers:{"Content-Type":"application/json", "X-Gewu-Browser":"1"}, body:JSON.stringify({action, ...payload})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Browser data could not be saved.");
    return result;
  }
  function fail(error) { message(error.message || "This browser action could not be completed.", true); }
  function persist(values) {
    Object.assign(data.preferences, values);
    clearTimeout(data.persistTimer);
    data.persistTimer = setTimeout(() => api("preferences", data.preferences).catch(fail), 180);
  }
  async function refresh(append = false) {
    const generation = ++data.fetching;
    const result = await api("state", {query:data.tab === "history" ? data.query : "", offset:append ? data.history.length : 0});
    if (generation !== data.fetching) return;
    data.bookmarks = result.bookmarks;
    data.history = append ? [...data.history, ...result.history] : result.history;
    data.more = result.history_more;
    if (!data.loaded) {
      data.preferences = result.preferences || {};
      data.width = data.preferences.sidebar_width || 250;
      data.hidden = Boolean(data.preferences.sidebar_hidden);
      data.tab = data.preferences.tab || "bookmarks";
      data.expanded = new Set(data.preferences.expanded || []);
      data.loaded = true;
    }
    render();
  }
  function render() {
    root.style.setProperty("--browser-sidebar-width", data.width + "px");
    root.classList.toggle("sidebar-hidden", data.hidden);
    $("browserSidebarToggle").setAttribute("aria-expanded", String(!data.hidden));
    $("browserBookmarksTab").setAttribute("aria-selected", String(data.tab === "bookmarks"));
    $("browserHistoryTab").setAttribute("aria-selected", String(data.tab === "history"));
    $("browserSidebarSearch").placeholder = data.tab === "bookmarks" ? "Search bookmarks" : "Search history";
    $("browserSidebarSearch").setAttribute("aria-label", $("browserSidebarSearch").placeholder);
    $("browserNewFolder").hidden = data.tab !== "bookmarks";
    $("browserClearHistory").hidden = data.tab !== "history";
    $("browserBookmarkTransfer").hidden = data.tab !== "bookmarks";
    faviconObserver.disconnect();
    const list = $("browserCollection"), scroll = list.scrollTop;
    list.setAttribute("aria-label", data.tab === "bookmarks" ? "Bookmarks" : "History");
    if (data.tab === "bookmarks") {
      const rows = bookmarkTree(data.bookmarks, data.expanded, data.query);
      list.innerHTML = rows.map(node => `<div class="browser-bookmark-row${data.selected === node.id ? " selected" : ""}" data-bookmark-id="${node.id}" data-kind="${node.kind}" style="--depth:${Math.min(node.depth, 10)}" draggable="true" tabindex="0" title="${escape(node.url || node.title)}">
        <button class="browser-disclosure" data-disclose="${node.id}" ${node.kind !== "folder" ? 'tabindex="-1" disabled' : `aria-expanded="${data.expanded.has(node.id)}" aria-label="${data.expanded.has(node.id) ? "Collapse" : "Expand"} ${escape(node.title)}"`}>${node.kind === "folder" ? icon(data.expanded.has(node.id) ? "down" : "right") : ""}</button>
        <span class="browser-entry-icon ${node.kind}">${bookmarkIcon(node)}</span><span class="browser-entry-title">${escape(node.title)}</span></div>`).join("") || `<div class="browser-empty">${data.query ? "No matching bookmarks." : "Your saved websites will appear here.<br>Use Add Bookmark or ⌘D to save a page."}</div>`;
      list.querySelectorAll('[data-icon-host]').forEach(element => faviconObserver.observe(element));
    } else {
      let day = "";
      list.innerHTML = data.history.map(visit => {
        const label = dayLabel(visit.visited_at), heading = day === label ? "" : `<div class="browser-history-day">${escape(label)}</div>`;
        day = label;
        return heading + `<button class="browser-history-row" data-history-id="${visit.id}" title="${escape(visit.url)}"><span>${escape(visit.title)}</span><small>${escape(new URL(visit.url).hostname)} · ${escape(new Date(visit.visited_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}))}</small></button>`;
      }).join("") || `<div class="browser-empty">${data.query ? "No matching history." : "Pages you visit will appear here."}</div>`;
      if (data.more) list.insertAdjacentHTML("beforeend", '<button class="browser-more" id="browserHistoryMore">Load More</button>');
      $("browserHistoryMore")?.addEventListener("click", () => refresh(true).catch(fail));
    }
    list.scrollTop = scroll;
    renderFavorites();
    scheduleLayout();
  }
  let capturePanel = null;
  const captureFields = ["Unknown", "Published version", "Preprint", "Accepted manuscript", "Corrected published version", "Correction notice", "Supplementary material", "Peer review file", "Other"];
  function closeCapture() {
    const c = capturePanel;
    if (!c || c.saving) return;
    if (typeof closeLibraryAddMenus === "function") closeLibraryAddMenus();
    capturePanel = null;
    clearTimeout(c.timer);
    native({action:"capture-cancel", request_id:c.requestID, token:c.review?.token || "", snapshot_id:c.snapshot?.snapshot_id || ""});
    if (c.review?.token) api("capture_cancel", {token:c.review.token}).catch(() => {});
    c.element.querySelector(".capture-page-backdrop").removeAttribute("src");
    c.element.remove(); scheduleLayout(); $("browserSaveGewu").focus();
  }
  function captureStatus(c, text, error = false) {
    const status = c.element.querySelector(".capture-status");
    status.textContent = text;
    status.hidden = !text;
    status.classList.toggle("error", error);
  }
  function captureDetails(c, expanded) {
    c.element.querySelector(".capture-details-content").hidden = !expanded;
    c.element.querySelector('[data-capture="details"]').setAttribute("aria-expanded", String(expanded));
    c.element.classList.toggle("details-expanded", expanded);
    scheduleLayout();
  }
  function captureBusy(c, busy, status = "") {
    c.busy = busy;
    if (busy && typeof closeLibraryAddMenus === "function") closeLibraryAddMenus();
    for (const control of c.element.querySelectorAll("input,select,button")) control.disabled = busy;
    c.element.querySelector('[data-capture="details"]').disabled = false;
    c.element.querySelector('[data-capture="cancel"]').disabled = Boolean(c.saving);
    c.element.querySelector('[data-capture="save"]').disabled = busy || !c.review?.can_save;
    c.element.querySelector('[data-capture="download"]').disabled = busy || !c.review?.snapshot.pdf_urls.length;
    c.element.querySelector('[data-capture="origin"]').hidden = !c.review?.origin || Boolean(c.review?.paper);
    c.element.querySelector('[name="include_pdf"]').disabled = busy || !c.review?.pdf_ready;
    if (status) captureStatus(c, status);
  }
  function renderCapture(c, review) {
    c.review = review;
    const q = s => c.element.querySelector(s), p = review.paper;
    q(".capture-identity").textContent = p ? `${p.title}\n${p.existing ? "Existing article" : "New article"} · ${p.gewu_key}${p.doi ? "\nDOI: " + p.doi : ""}${p.journal ? "\n" + p.journal : ""}` : "Article not identified yet. Enter its DOI/arXiv ID, or confirm a title below.";
    q('[name="identifier"]').value = review.identifier || "";
    if (!q('[name="title"]').value) q('[name="title"]').value = review.suggested_title || "";
    q(".capture-manual").hidden = Boolean(p);
    const target = q('[name="folder_id"]');
    if (!c.folderSelectionExplicit) target.value = String(review.destination?.folder_id || 0);
    const folder = review.folders.find(f => String(f.id) === target.value);
    const folderTitle = folder?.title || review.destination?.title || "Library / unsorted";
    q('[data-capture="folder"]').textContent = folderTitle + " ▸";
    q('[data-capture="folder"]').title = folderTitle;
    const urls = q('[name="pdf_url"]'), selected = urls.value;
    urls.replaceChildren(...review.snapshot.pdf_urls.map(url => new Option(url, url)));
    if ([...urls.options].some(o => o.value === selected)) urls.value = selected;
    q('[name="include_pdf"]').checked = review.pdf_ready;
    q(".capture-file").textContent = review.pdf_ready ? `Ready: ${review.pdf_name}` : "No PDF attached. You can save the article alone.";
    if (!c.fileTypeManual) q('[name="file_type"]').value = review.suggested_file_type || "unknown";
    q(".capture-file-type-hint").textContent = c.fileTypeManual ? "Your selected file type will be used." : review.file_type_reason || "";
    if (review.origin) q('[data-capture="origin"]').textContent = `Use source article: ${review.origin.title} (${review.origin.gewu_key})`;
    captureBusy(c, false);
    if (!review.can_save) captureDetails(c, true);
    captureStatus(c, review.conflict || review.warning || (review.pdf_ready ? "" : "Article only · Open Details to add a PDF."), Boolean(review.conflict));
  }
  async function reviewCapture(c, options = c.identity || {}) {
    if (capturePanel !== c) return;
    c.identity = options;
    c.review.can_save = false;
    captureBusy(c, true, "Identifying the article…");
    try {
      const review = await api("capture_review", {token:c.review.token, ...options});
      if (capturePanel === c) renderCapture(c, review);
    } catch (error) { if (capturePanel === c) { captureBusy(c, false); captureStatus(c, error.message, true); } }
  }
  function downloadCapture(c) {
    if (!c.review || capturePanel !== c) return;
    captureBusy(c, true, "Retrieving PDF from this browser session…");
    native({action:"capture-download", token:c.review.token, upload_token:c.review.upload_token,
      snapshot_id:c.snapshot.snapshot_id, url:c.element.querySelector('[name="pdf_url"]').value});
  }
  function startCapture() {
    if (capturePanel) return;
    if (!bridge() || !data.url || data.home) { message("Open an article or PDF in Gewu Insight.app first.", true); return; }
    closeContext(); closeSuggestions();
    const element = document.createElement("div"); element.className = "browser-capture-overlay";
    element.setAttribute("role", "dialog"); element.setAttribute("aria-modal", "true"); element.setAttribute("aria-labelledby", "browserCaptureTitle");
    element.innerHTML = `<img class="capture-page-backdrop" alt="" aria-hidden="true" hidden><section class="browser-capture-panel" tabindex="-1">
      <h2 id="browserCaptureTitle">Save to Gewu</h2><p class="capture-status" role="status">Reading article metadata…</p>
      <button type="button" class="capture-details-toggle" data-capture="details" aria-expanded="false" aria-controls="browserCaptureDetails"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 3 4 3 4-3M4 9l4 3 4-3"/></svg><span>Details</span></button>
      <div class="capture-details-content" id="browserCaptureDetails" hidden>
      <div class="capture-identity"></div>
      <label>DOI or arXiv ID<div class="capture-row"><input name="identifier" placeholder="10.… or 2601.01234"><button data-capture="lookup">Identify</button></div></label>
      <div class="capture-manual"><label>Article title<input name="title" maxlength="1000" placeholder="Enter the article title"></label><button data-capture="manual">Use this title</button></div>
      <button data-capture="origin" hidden></button>
      <label>PDF link<div class="capture-row"><select name="pdf_url" aria-label="PDF link"></select><button data-capture="download">Get PDF</button></div></label>
      <div class="capture-file"></div><label class="capture-local">Or choose a local PDF<input name="local_pdf" type="file" accept="application/pdf,.pdf"></label>
      <label class="capture-check"><input name="include_pdf" type="checkbox"> Include this PDF in Paper Files</label>
      <p class="capture-file-type-hint"></p>
      </div>
      <div class="capture-row"><label>File type<select name="file_type">${captureFields.map(t => `<option value="${t.toLowerCase().replaceAll(" ","_")}">${t}</option>`).join("")}</select></label><div class="capture-folder-control library-add-control"><span id="browserCaptureDestinationLabel">Add to Library</span><input name="folder_id" type="hidden" value="0"><button type="button" data-capture="folder" data-action="add-library" aria-haspopup="menu" aria-expanded="false" aria-labelledby="browserCaptureDestinationLabel">Library / unsorted ▸</button><div class="library-add-menu browser-capture-folder-menu" data-role="library-add-menu" role="menu" aria-hidden="true"></div></div></div>
      <footer><button data-capture="cancel">Cancel</button><button data-capture="save" class="capture-primary">Save to Library</button></footer>
    </section>`;
    const c = capturePanel = {element, requestID:crypto.randomUUID(), busy:true, review:null, snapshot:null};
    c.originLibraryItemId = typeof state !== "undefined" && state.librarySelection?.type === "item"
      ? Number(state.librarySelection.id || 0) : 0;
    document.body.append(element);
    captureDetails(c, typeof state !== "undefined" && state.browserCaptureDetailsExpanded === true);
    captureBusy(c, true); scheduleLayout();
    element.querySelector('[data-capture="cancel"]').focus();
    element.addEventListener("keydown", event => {
      event.stopPropagation();
      if (event.key === "Escape") {
        event.preventDefault();
        if (element.querySelector(".library-add-menu.open")) closeLibraryAddMenus();
        else closeCapture();
      }
      if (event.key === "Tab") {
        const focusable = [...element.querySelectorAll("button,input,select")].filter(x => !x.disabled && x.getClientRects().length);
        const index = focusable.indexOf(document.activeElement);
        if (event.shiftKey && index <= 0 || !event.shiftKey && index === focusable.length - 1) {
          event.preventDefault(); focusable[event.shiftKey ? focusable.length - 1 : 0]?.focus();
        }
      }
    });
    element.onclick = async event => {
      const action = event.target.closest("[data-capture]")?.dataset.capture;
      if (action === "cancel") { closeCapture(); return; }
      if (action === "details") {
        captureDetails(c, element.querySelector('[data-capture="details"]').getAttribute("aria-expanded") !== "true");
        return;
      }
      if (!action || c.busy || !c.review) return;
      const q = name => element.querySelector(`[name="${name}"]`);
      if (action === "lookup") return reviewCapture(c, {identifier:q("identifier").value});
      if (action === "manual") return reviewCapture(c, {manual:true, title:q("title").value, identifier:q("identifier").value});
      if (action === "origin") return reviewCapture(c, {use_origin:true});
      if (action === "download") return downloadCapture(c);
      if (action === "folder") {
        if (typeof openLibraryAddMenu !== "function") { captureStatus(c, "The Library folder picker is unavailable. Reopen Gewu Insight.app.", true); return; }
        event.preventDefault(); event.stopPropagation();
        const control = element.querySelector(".capture-folder-control");
        return openLibraryAddMenu(control, c.review.paper?.paper_id || "", control.querySelector('[data-capture="folder"]'), null, {
          portalRoot:element, selectedFolderId:Number(q("folder_id").value),
          onSelect:selection => {
            if (capturePanel !== c) return;
            c.folderSelectionExplicit = true;
            q("folder_id").value = String(selection.folderId);
            const button = element.querySelector('[data-capture="folder"]');
            button.textContent = selection.path + " ▸"; button.title = selection.path;
          }
        });
      }
      if (action === "save") {
        c.saving = true; captureBusy(c, true, "Saving to Library…");
        try {
          const result = await api("capture_save", {token:c.review.token, folder_id:Number(q("folder_id").value), folder_selection_explicit:Boolean(c.folderSelectionExplicit), file_type:q("file_type").value, file_type_manual:Boolean(c.fileTypeManual), include_pdf:q("include_pdf").checked});
          if (typeof applyPaperFilesPayloads === "function") applyPaperFilesPayloads(result.paper_files);
          if (typeof state !== "undefined" && (result.ok || result.metadata_saved)) state.libraryLoaded = false;
          if (!result.ok) throw new Error(result.error || "The article could not be saved.");
          c.saving = false; closeCapture();
          message(`Saved to Library · ${result.gewu_key}${result.pdf_saved ? result.duplicate_file ? " · Existing PDF reused" : " · PDF added to Paper Files" : " · Article only"}`, false, {
            label:"Show in Library",
            run:async () => {
              if (typeof navigateToPaperInLibrary !== "function") throw new Error("Reopen Gewu Insight.app to show this article in Library.");
              await navigateToPaperInLibrary(result.paper_id, result.item_id);
              document.getElementById("libraryShell")?.focus({preventScroll:true});
            }
          });
        } catch (error) { c.saving = false; captureBusy(c, false); captureStatus(c, error.message, true); }
      }
    };
    element.querySelector('[name="file_type"]').onchange = () => {
      c.fileTypeManual = true;
      element.querySelector(".capture-file-type-hint").textContent = "Your selected file type will be used.";
    };
    element.querySelector('[name="identifier"]').oninput = () => {
      if (c.review) c.review.can_save = false;
      element.querySelector('[data-capture="save"]').disabled = true;
      captureStatus(c, "Click Identify to review the changed identifier before saving.");
    };
    element.querySelector('[name="local_pdf"]').onchange = async event => {
      const file = event.target.files[0];
      if (!file || c.busy || !c.review) return;
      if (!file.size || file.size > 64 * 1024 * 1024) { captureStatus(c, "Choose a PDF up to 64 MB.", true); return; }
      captureBusy(c, true, "Checking the selected PDF…");
      try {
        const response = await fetch("/api/browser-capture-file", {method:"POST", headers:{"Content-Type":"application/pdf", "X-Gewu-Capture-Token":c.review.upload_token, "X-Gewu-Filename":encodeURIComponent(file.name)}, body:file});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not read the PDF.");
        await reviewCapture(c);
      } catch (error) { if (capturePanel === c) { captureBusy(c, false); captureStatus(c, error.message, true); } }
      event.target.value = "";
    };
    c.timer = setTimeout(() => { if (capturePanel === c && !c.snapshot) { captureBusy(c, false); captureStatus(c, "The page did not respond. Close this panel and retry after it loads.", true); } }, 15000);
    native({action:"capture", request_id:c.requestID});
  }
  async function captureEvent(event) {
    const c = capturePanel;
    if (!c) {
      if (event.snapshot) native({action:"capture-cancel", snapshot_id:event.snapshot.snapshot_id});
      return;
    }
    if (event.event === "capture-backdrop") {
      if (event.request_id !== c.requestID || typeof event.image !== "string" || event.image.length > 6 * 1024 * 1024 || !event.image.startsWith("data:image/jpeg;base64,")) return;
      const image = c.element.querySelector(".capture-page-backdrop");
      image.src = event.image; image.hidden = false; scheduleLayout();
    } else if (event.event === "capture-metadata") {
      if (event.request_id !== c.requestID) return;
      clearTimeout(c.timer);
      if (event.error) { captureBusy(c, false); captureStatus(c, event.error, true); return; }
      c.snapshot = event.snapshot;
      try {
        const review = await api("capture_begin", {snapshot:{...event.snapshot, origin_library_item_id:c.originLibraryItemId}});
        if (capturePanel !== c) { api("capture_cancel", {token:review.token}).catch(() => {}); return; }
        renderCapture(c, review);
        if (review.snapshot.is_pdf && review.snapshot.pdf_urls.length) downloadCapture(c);
      } catch (error) { if (capturePanel === c) { captureBusy(c, false); captureStatus(c, error.message, true); } }
    } else if (event.event === "capture-pdf" && event.token === c.review?.token) {
      if (event.error) { captureBusy(c, false); captureStatus(c, event.error + " You can save the article alone or choose a local PDF.", true); }
      else await reviewCapture(c);
    }
  }
  $("browserSaveGewu").onclick = startCapture;

  function visibleDialog() {
    return [...document.querySelectorAll('[role="dialog"], dialog[open], .finder-drop-overlay')].some(element => {
      const style = getComputedStyle(element);
      return element.getClientRects().length && style.visibility !== "hidden" && style.display !== "none";
    });
  }
  function layout() {
    if (data.active) {
      const footer = data.hidden ? 33 : root.querySelector(".browser-sidebar-footer").offsetHeight;
      root.style.setProperty("--browser-footer-height", footer + "px");
      const column = root.querySelector(".browser-page-column");
      const available = column.clientHeight - $("browserTabs").offsetHeight - root.querySelector(".browser-page-footer").offsetHeight - $("browserFindBar").offsetHeight - $("browserMessage").offsetHeight;
      if (data.home && data.favoriteLayout !== `${column.clientWidth}:${available}`) renderFavorites();
    }
    const rect = $(data.home ? "browserFavorites" : "browserViewport").getBoundingClientRect();
    if (capturePanel) {
      const image = capturePanel.element.querySelector(".capture-page-backdrop");
      Object.assign(image.style, {left:rect.x+"px", top:rect.y+"px", width:rect.width+"px", height:rect.height+"px"});
    }
    const active = data.active;
    const payload = {action:"layout", active, visible:active && !visibleDialog(), sidebarVisible:!data.hidden, canReturnToWorkspace:active && Boolean(data.workspaceReturn), x:rect.x, y:rect.y, width:rect.width, height:rect.height, viewportWidth:innerWidth};
    const signature = JSON.stringify(payload);
    if (signature !== data.layout) { data.layout = signature; native(payload); }
  }
  // The workspace WKWebView can stop receiving animation frames while the
  // independent webpage view has focus. Layout must still track sidebar sizes,
  // sheets, and messages; coalesce changes without depending on a paint frame.
  const scheduleLayout = microtaskScheduler(layout);
  function setActive(active) {
    data.active = active; root.hidden = !active; closeContext();
    closeSuggestions();
    if (!active) { data.workspaceReturn = null; data.layout = ""; layout(); return; }
    render(); layout();
    if (!bridge()) {
      $("browserNativeHint").textContent = "Open Gewu Insight.app to use the embedded browser. Bookmarks and history remain available here.";
      refresh().catch(fail); return;
    }
    if (!data.opened) { data.opened = true; native({action:"home"}); }
    refresh().catch(fail);
  }
  function open() {
    if (typeof closeLibraryQuickLook === "function" && state.libraryQuickLookOpen) closeLibraryQuickLook();
    setPrimaryView("browser"); state.mode = "browser";
  }
  function openURL(value, context = {}) {
    // Product links are destinations, never address-bar search text. Native
    // navigation applies the stricter public-network policy before any load.
    const url = new URL(String(value || "").trim());
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.href.length > 8192)
      throw new Error("Use an HTTP or HTTPS website link without embedded credentials.");
    if (!bridge()) {
      // CLI/browser-hosted UI has no embedded WebKit surface. Keep the request
      // in this user's browser, not a server-side Safari process.
      global.open(url.href, "_blank", "noopener,noreferrer");
      return "browser tab";
    }
    const first = !data.opened;
    if (state.mode !== "browser") {
      data.workspaceReturn = typeof captureBrowserWorkspaceReturn === "function" ? captureBrowserWorkspaceReturn() : null;
    }
    // Suppress cold Home navigation: the first product link uses the unused
    // initial tab. Later links always preserve every existing Browser document.
    data.opened = true;
    open();
    message("");
    native({action:first ? "navigate" : "new-tab", url:url.href, ...(context.paper_id ? {origin_paper_id:context.paper_id} : {})});
    return "Browser";
  }
  function returnToWorkspace() {
    if (!data.active || state.mode !== "browser" || !data.workspaceReturn || visibleDialog()) return false;
    const restore = data.workspaceReturn;
    data.workspaceReturn = null;
    restore();
    return true;
  }
  function navigate(value) {
    try {
      const url = address(value);
      closeSuggestions();
      message("");
      $("browserAddress").value = url;
      native(url ? {action:"navigate", url} : {action:"home"});
    } catch (error) { fail(error); }
  }
  async function edit(node = null, kind = "bookmark", parent = null) {
    if (!bridge()) { message("Use the native App to add or edit bookmarks."); return; }
    if (data.editor || data.confirm) return;
    const choices = folderChoices(data.bookmarks, node?.kind === "folder" ? node.id : null);
    const chosen = parent ?? node?.parent_id ?? data.preferences.last_folder ?? 0;
    const initial = {id:node?.id || null, kind:node?.kind || kind, title:node?.title || (kind === "folder" ? "Untitled Folder" : data.title || data.url), url:node?.url || data.url,
      parent_id:choices.some(folder => folder.id === chosen) ? chosen : 0};
    data.editor = initial;
    native({action:"editor", ...initial, folders:choices});
  }
  async function confirm(options) {
    if (!bridge() || data.confirm || data.editor) return {confirmed:false};
    return new Promise(resolve => { data.confirm = resolve; native({action:"confirm", ...options}); });
  }
  async function remove(node) {
    const result = await confirm({title:node.kind === "folder" ? "Delete Folder" : "Delete Bookmark", button:"Delete", message:node.kind === "folder" ? `Delete “${node.title}” and all bookmarks inside it? Your browsing history and paper files will not change.` : `Delete “${node.title}” from Bookmarks? This does not delete the website or any downloaded files.`});
    if (result.confirmed) { await api("delete_bookmark", {id:node.id}); await refresh(); }
  }
  async function clearHistory() {
    const result = await confirm({title:"Clear History", button:"Clear History", history:true, message:"Choose the browsing history to remove. Bookmarks, downloads, cookies, and website sign-ins will be kept."});
    if (result.confirmed) { await api("clear_history", {range:result.range}); await refresh(); }
  }
  function closeContext() { $("browserContext").hidden = true; $("browserBookmarkMenu").setAttribute("aria-expanded", "false"); }
  function bookmarkMenu() {
    const menu = $("browserContext"), anchor = $("browserBookmarkMenu"), rect = anchor.getBoundingClientRect();
    closeContext(); menu.replaceChildren(); menu.setAttribute("role", "menu");
    const startSync = source => {
      if (data.sourceSyncBusy) return;
      data.sourceSyncBusy = true; native({action:"read-bookmark-source", source});
    };
    for (const [id, title, action] of [
      ["browserImportBookmarks", "Import…", () => native({action:"import-bookmarks"})],
      ["browserExportBookmarks", "Export…", () => exportBookmarks()],
      ["browserSyncSafari", "Sync from Safari…", () => startSync("safari")],
      ["browserSyncChrome", "Sync from Chrome…", () => startSync("chrome")]
    ]) {
      const item = document.createElement("button"); item.id = id; item.textContent = title; item.setAttribute("role", "menuitem");
      item.disabled = Boolean(data.sourceSyncBusy);
      item.onclick = () => { closeContext(); anchor.focus(); Promise.resolve(action()).catch(fail); };
      menu.append(item);
    }
    menu.hidden = false; anchor.setAttribute("aria-expanded", "true");
    menu.style.left = rect.left + "px"; menu.style.top = Math.max(46, rect.top - menu.offsetHeight - 5) + "px";
    menu.querySelector("button:not(:disabled)")?.focus();
  }
  function context(event, node, visit) {
    event.preventDefault(); closeContext();
    const menu = $("browserContext");
    const items = node ? [
      ...(node.kind === "bookmark" ? [["Open", () => navigate(node.url)], ["Open in New Tab", () => newTab(node.url)]] : [["New Folder", () => edit(null, "folder", node.id)]]),
      [node.kind === "folder" ? "Rename or Move" : "Edit Bookmark", () => edit(node)],
      ...(node.kind === "folder" ? [["Export Folder", () => exportBookmarks(node.id)]] : []),
      ["Delete", () => remove(node)]
    ] : visit ? [["Open", () => navigate(visit.url)], ["Open in New Tab", () => newTab(visit.url)], ["Add Bookmark", () => edit({title:visit.title, url:visit.url})],
      ["Delete Visit", async () => { await api("clear_history", {id:visit.id}); await refresh(); }]] : [["New Folder", () => edit(null, "folder", 0)], ["Add Bookmark", () => edit()]];
    menu.replaceChildren();
    items.forEach(([title, handler]) => {
      const button = document.createElement("button"); button.textContent = title;
      button.onclick = () => { closeContext(); Promise.resolve(handler()).catch(fail); };
      menu.append(button);
    });
    menu.hidden = false;
    const minimumTop = event.target.closest("#browserFavorites") ? $("browserFavorites").getBoundingClientRect().top : 46;
    menu.style.left = Math.max(6, Math.min(event.clientX, innerWidth - 196)) + "px";
    menu.style.top = Math.max(minimumTop, Math.min(event.clientY, innerHeight - menu.offsetHeight - 6)) + "px";
    menu.querySelector("button")?.focus();
  }

  global.gewuBrowserNativeEvent = event => {
    if (["capture-metadata", "capture-pdf", "capture-backdrop"].includes(event.event)) { captureEvent(event); return; }
    if (event.event === "bookmark-source-cancel") {
      data.sourceSync = null; data.sourceSyncBusy = false;
      if (event.message) message(event.message, true);
    } else if (event.event === "bookmark-source") {
      data.sourceSync = {source:event.source, source_id:event.source_id, content_base64:event.content_base64};
      api("preview_bookmark_source", data.sourceSync).then(result => native({action:"choose-bookmark-source-folder", folders:result.folders})).catch(error => {
        data.sourceSync = null; data.sourceSyncBusy = false; fail(error);
      });
    } else if (event.event === "bookmark-source-folder" && data.sourceSync) {
      const snapshot = data.sourceSync; data.sourceSync = null;
      message("Syncing selected bookmark folder.");
      api("sync_bookmarks", {...snapshot, folder_id:event.folder_id}).then(async result => {
        const info = result.sync_result;
        data.tab = "bookmarks"; data.query = ""; data.hidden = false; data.expanded.add(info.folder_id);
        $("browserSidebarSearch").value = "";
        await refresh(); persist({tab:"bookmarks",sidebar_hidden:false,expanded:[...data.expanded]});
        message(`Synced ${info.imported} new bookmarks · ${info.updated} updated · ${info.kept_local} local changes kept · ${info.skipped} unsupported or sensitive links skipped. No source or local bookmarks were deleted.`);
      }).catch(fail).finally(() => { data.sourceSyncBusy = false; });
    } else if (event.event === "favicon") {
      const value = /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(event.data_url || "") && event.data_url.length < 90000 ? event.data_url : "";
      siteIcons.set(event.host, value);
      data.tabsSignature = ""; renderTabs();
      for (const element of root.querySelectorAll('[data-icon-host]')) if (element.dataset.iconHost === event.host && value) {
        const img = document.createElement("img"); img.alt = ""; img.src = value; element.replaceChildren(img);
      }
    } else if (event.event === "bookmark-import") {
      message("Importing bookmarks.");
      api("import_bookmarks", {content_base64:event.content_base64}).then(async result => {
        const info = result.import_result;
        data.expanded.add(info.folder_id); data.tab = "bookmarks"; data.query = ""; $("browserSidebarSearch").value = "";
        await refresh(); persist({expanded:[...data.expanded],tab:"bookmarks"});
        message(`Imported ${info.imported} bookmarks · ${info.folders_created} folders created · ${info.duplicates} duplicates reused · ${info.skipped} unsupported or sensitive links skipped. Existing bookmarks were kept.`);
      }).catch(fail);
    } else if (event.event === "tabs") {
      data.browserTabs = event.tabs || [];
      for (const id of data.tabChrome.keys()) if (!data.browserTabs.some(tab => tab.id === id)) data.tabChrome.delete(id);
      renderTabs();
    } else if (event.event === "state") {
      const switched = event.tab_id && event.tab_id !== data.browserTab;
      if (switched) {
        if (data.browserTab) data.tabChrome.set(data.browserTab, {favoritePath:data.favoritePath, favoritePage:data.favoritePage});
        data.browserTab = event.tab_id;
        Object.assign(data, data.tabChrome.get(data.browserTab) || {favoritePath:null, favoritePage:0});
        closeSuggestions(); closeContext();
        $("browserFindBar").hidden = true; $("browserFindInput").value = ""; $("browserFindResult").textContent = "";
        message(event.error || "", Boolean(event.error));
        // Force geometry delivery even when two tabs happen to have equal frames.
        data.layout = ""; data.favoriteLayout = ""; scheduleLayout();
      }
      data.url = event.url ?? data.url; data.title = event.title || ""; data.loading = event.loading;
      updateHome(event.home === true);
      if (switched && data.home) renderFavorites();
      if (switched || document.activeElement !== $("browserAddress")) $("browserAddress").value = data.url;
      $("browserSiteIcon").href = data.url || "#";
      $("browserSiteIcon").draggable = Boolean(data.url);
      $("browserSaveGewu").disabled = !data.url || data.home || event.loading || Boolean(event.error);
      $("browserAddBookmark").disabled = !data.url;
      $("browserDownload").disabled = !data.url;
      $("browserExternal").disabled = !data.url;
      $("browserShare").disabled = !data.url;
      $("browserSiteIcon").title = data.home ? "Local Favorites" : data.url.startsWith("https:") ? "HTTPS website · Drag to bookmarks" : "Not encrypted · Drag to bookmarks";
      $("browserBack").disabled = !event.canBack; $("browserForward").disabled = !event.canForward;
      $("browserReload").innerHTML = icon(event.loading ? "stop" : "reload");
      $("browserReload").title = event.loading ? "Stop loading" : "Reload";
      $("browserReload").setAttribute("aria-label", $("browserReload").title);
      $("browserProgress").style.width = (event.loading ? Math.max(3, event.progress * 100) : 0) + "%";
      $("browserPageTitle").textContent = data.title;
      if (event.error) message(event.error, true);
      else if (event.openingPDF) message(event.progress > 0 ? `Opening PDF… ${Math.floor(event.progress * 100)}%` : "Opening PDF…");
      else if (data.openingPDF) message("");
      data.openingPDF = Boolean(event.openingPDF);
    } else if (event.event === "navigation-start") { message(""); }
    else if (event.event === "visit") {
      api("visit", {event_id:event.event_id, url:event.url, title:event.title}).then(() => {
        if (data.active && data.tab === "history") refresh().catch(fail);
      }).catch(fail);
    } else if (event.event === "error") { message(event.message, true); }
    else if (event.event === "download") { message(event.message); }
    else if (event.event === "return-workspace") { returnToWorkspace(); }
    else if (event.event === "focus-chrome" && data.active && !visibleDialog()) {
      state.primaryKeyboardLayer = "content"; syncPrimaryKeyboardLayer({focus:false});
      if (event.destination === "sidebar") keyboard.focusSidebar(); else keyboard.focusTabs();
    }
    else if (event.event === "focus-address") { closeSuggestions(); $("browserAddress").focus(); $("browserAddress").select(); }
    else if (event.event === "address-suggestion") { navigate(event.url); $("browserAddress").blur(); native({action:"focus"}); }
    else if (event.event === "suggestions-dismissed") { closeSuggestions(); }
    else if (event.event === "bookmark") { edit().catch(fail); }
    else if (event.event === "find") { $("browserFindBar").hidden = false; $("browserFindInput").focus(); scheduleLayout(); }
    else if (event.event === "find-result") { $("browserFindResult").textContent = event.found ? "" : "Not found"; }
    else if (event.event === "editor-result") {
      const initial = data.editor; data.editor = null;
      if (!initial || event.cancelled) return;
      const payload = {...initial, title:event.title, url:event.url, parent_id:event.parent_id || null};
      api("save_bookmark", payload).then(async result => {
        if (payload.parent_id) data.expanded.add(payload.parent_id);
        data.tab = "bookmarks"; data.hidden = false;
        data.selected = result.bookmark.id;
        persist({last_folder:payload.parent_id, expanded:[...data.expanded], tab:"bookmarks", sidebar_hidden:false});
        await refresh();
        message(result.already_saved ? "This page is already bookmarked in that folder." : "Bookmark saved.");
      }).catch(error => {
        fail(error);
        // Keep edited values available so retrying never discards the user's input.
        edit({...payload, id:payload.id || null}, payload.kind, payload.parent_id).catch(fail);
      });
    } else if (event.event === "confirm-result") { const resolve = data.confirm; data.confirm = null; resolve?.(event); }
  };
  const keyboard = global.createBrowserKeyboard({root, data, native, closeSuggestions, closeContext, visibleDialog});
  global.gewuBrowser = {open, setActive, openURL, ...keyboard};
  async function exportBookmarks(rootID = null) {
    const result = await api("export_bookmarks", {root_id:rootID});
    native({action:"export-bookmarks", html:result.html});
  }
  $("browserBookmarkMenu").onclick = bookmarkMenu;
  $("browserPasswords").onclick = () => native({action:"passwords"});
  $("browserNewTab").onclick = () => newTab();
  $("browserTabs").onclick = event => {
    const close = event.target.closest("[data-close-tab]");
    const tab = event.target.closest("[data-browser-tab]");
    if (!tab) return;
    closeSuggestions(); closeContext();
    native({action:close ? "close-tab" : "select-tab", tab_id:tab.dataset.browserTab});
  };
  $("browserTabs").onauxclick = event => {
    const tab = event.target.closest("[data-browser-tab]");
    if (event.button === 1 && tab) { event.preventDefault(); native({action:"close-tab",tab_id:tab.dataset.browserTab}); }
  };
  $("browserTabs").onkeydown = event => {
    if (event.target.closest("[data-close-tab]")) return;
    const index = data.browserTabs.findIndex(tab => tab.id === data.browserTab);
    let target = index;
    if (event.key === "ArrowRight") target = (index + 1) % data.browserTabs.length;
    else if (event.key === "ArrowLeft") target = (index - 1 + data.browserTabs.length) % data.browserTabs.length;
    else if (event.key === "Home") target = 0;
    else if (event.key === "End") target = data.browserTabs.length - 1;
    else if (["Delete", "Backspace"].includes(event.key)) { event.preventDefault(); native({action:"close-tab",tab_id:data.browserTab}); return; }
    else return;
    event.preventDefault();
    if (data.browserTabs[target]) native({action:"select-tab",tab_id:data.browserTabs[target].id});
  };
  $("browserFavoritesTrail").onclick = event => {
    const button = event.target.closest("[data-favorite-folder]");
    if (button) { data.favoritePath = Number(button.dataset.favoriteFolder); data.favoritePage = 0; renderFavorites(); }
  };
  $("browserFavoritesGrid").onclick = event => {
    const button = event.target.closest("[data-favorite-id]");
    const node = data.bookmarks.find(item => item.id === Number(button?.dataset.favoriteId));
    if (!node) return;
    if (node.kind === "folder") { data.favoritePath = node.id; data.favoritePage = 0; renderFavorites(); }
    else if (event.metaKey) newTab(node.url); else navigate(node.url);
  };
  $("browserFavoritesGrid").oncontextmenu = event => {
    const button = event.target.closest("[data-favorite-id]");
    const node = data.bookmarks.find(item => item.id === Number(button?.dataset.favoriteId));
    if (node) context(event, node);
  };
  $("browserMode").addEventListener("click", open);
  $("browserAddressForm").onsubmit = event => { event.preventDefault(); navigate(data.suggestions[data.suggestionIndex]?.url || $("browserAddress").value); $("browserAddress").blur(); native({action:"focus"}); };
  function showSuggestions() {
    const r = $("browserAddressForm").getBoundingClientRect();
    $("browserAddress").setAttribute("aria-expanded", String(data.suggestions.length > 0));
    native({action:"suggestions", items:data.suggestions, selected:data.suggestionIndex,
      x:r.x, y:r.bottom + 4, width:r.width, viewportWidth:innerWidth});
  }
  function closeSuggestions() {
    clearTimeout(data.addressTimer); data.suggestionGeneration++;
    data.suggestions = []; data.suggestionIndex = -1;
    $("browserAddress").setAttribute("aria-expanded", "false");
    native({action:"suggestions", items:[]});
  }
  function querySuggestions(complete = false) {
    clearTimeout(data.addressTimer);
    const field = $("browserAddress"), query = field.value;
    data.addressQuery = query;
    const generation = ++data.suggestionGeneration;
    data.suggestions = []; data.suggestionIndex = -1; showSuggestions();
    if (!query.trim() || data.composing) return;
    data.addressTimer = setTimeout(async () => {
      try {
        const result = await api("suggestions", {query});
        if (generation !== data.suggestionGeneration || document.activeElement !== field || !data.active || data.composing) return;
        data.suggestions = result.suggestions || [];
        data.suggestionIndex = -1;
        if (complete && field.selectionStart === query.length && field.selectionEnd === query.length && data.suggestions.length) {
          const completion = inlineCompletion(query, data.suggestions[0].url);
          if (completion) { field.value = completion; field.setSelectionRange(query.length, completion.length); data.suggestionIndex = 0; }
        }
        showSuggestions();
      } catch (_) { if (generation === data.suggestionGeneration) closeSuggestions(); }
    }, 110);
  }
  $("browserAddress").oninput = event => querySuggestions(!event.isComposing && ["insertText", "insertFromPaste"].includes(event.inputType));
  $("browserAddress").oncompositionstart = () => { data.composing = true; closeSuggestions(); };
  $("browserAddress").oncompositionend = () => { data.composing = false; querySuggestions(false); };
  $("browserAddress").onblur = closeSuggestions;
  $("browserAddress").onkeydown = event => {
    if (event.isComposing || data.composing) return;
    if (event.key === "Escape") { event.preventDefault(); $("browserAddress").value = data.addressQuery || data.url; closeSuggestions(); }
    if (["ArrowDown", "ArrowUp"].includes(event.key) && data.suggestions.length) {
      event.preventDefault();
      data.suggestionIndex = data.suggestionIndex < 0 ? (event.key === "ArrowDown" ? 0 : data.suggestions.length - 1) :
        (data.suggestionIndex + (event.key === "ArrowDown" ? 1 : -1) + data.suggestions.length) % data.suggestions.length;
      $("browserAddress").value = data.suggestions[data.suggestionIndex].url; showSuggestions();
    }
    if (event.key === "Tab") closeSuggestions();
  };
  $("browserSiteIcon").onclick = event => event.preventDefault();
  $("browserSiteIcon").ondragstart = event => { event.dataTransfer.setData("text/uri-list", data.url); event.dataTransfer.setData("text/plain", data.url); event.dataTransfer.effectAllowed = "copy"; };
  $("browserSidebarToggle").onclick = () => { data.hidden = !data.hidden; persist({sidebar_hidden:data.hidden}); render(); };
  for (const [id, action] of [["browserBack","back"],["browserForward","forward"],["browserHome","home"],["browserDownload","download"],["browserExternal","external"]]) $(id).onclick = () => native({action});
  $("browserReload").onclick = () => {
    if (data.home && !data.loading) refresh().catch(fail);
    native({action:data.loading ? "stop" : "reload"});
  };
  $("browserAddBookmark").onclick = () => edit().catch(fail);
  $("browserShare").onclick = () => { const r = $("browserShare").getBoundingClientRect(); native({action:"share", x:r.x, y:r.bottom, viewportWidth:innerWidth}); };
  $("browserNewFolder").onclick = () => edit(null, "folder", data.bookmarks.find(n => n.id === data.selected && n.kind === "folder")?.id || 0).catch(fail);
  $("browserClearHistory").onclick = () => clearHistory().catch(fail);
  $("browserMessageDismiss").onclick = () => message("");
  for (const tab of ["bookmarks", "history"]) $(tab === "bookmarks" ? "browserBookmarksTab" : "browserHistoryTab").onclick = () => {
    data.tab = tab; data.query = ""; $("browserSidebarSearch").value = "";
    persist({tab}); $("browserCollection").scrollTop = 0; render(); refresh().catch(fail);
  };
  $("browserSidebarSearch").oninput = () => {
    data.query = $("browserSidebarSearch").value; clearTimeout(data.searchTimer);
    if (data.tab === "bookmarks") render(); else data.searchTimer = setTimeout(() => refresh().catch(fail), 180);
  };
  $("browserCollection").onclick = event => {
    const row = event.target.closest("[data-bookmark-id]"), visit = event.target.closest("[data-history-id]");
    if (row) {
      const node = data.bookmarks.find(n => n.id === Number(row.dataset.bookmarkId));
      data.selected = node.id;
      if (node.kind === "folder") {
        if (data.expanded.has(node.id)) data.expanded.delete(node.id); else data.expanded.add(node.id);
        persist({expanded:[...data.expanded]}); render();
      } else { if (event.metaKey) newTab(node.url); else navigate(node.url); render(); }
    } else if (visit) { const url = data.history.find(n => n.id === Number(visit.dataset.historyId)).url; if (event.metaKey) newTab(url); else navigate(url); }
  };
  $("browserCollection").oncontextmenu = event => {
    const row = event.target.closest("[data-bookmark-id]"), visit = event.target.closest("[data-history-id]");
    context(event, data.bookmarks.find(n => n.id === Number(row?.dataset.bookmarkId)), data.history.find(n => n.id === Number(visit?.dataset.historyId)));
  };
  $("browserCollection").onkeydown = event => {
    const row = event.target.closest("[data-bookmark-id]");
    if (!row) return;
    const node = data.bookmarks.find(n => n.id === Number(row.dataset.bookmarkId));
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); row.click(); }
    if (event.key === "Backspace" || event.key === "Delete") { event.preventDefault(); remove(node).catch(fail); }
  };
  document.addEventListener("pointerdown", event => { if (!$("browserContext").contains(event.target)) closeContext(); });
  root.addEventListener("keydown", event => { if (event.key === "Escape") { closeContext(); $("browserFindBar").hidden = true; scheduleLayout(); } }, true);

  let dragged = null;
  $("browserCollection").ondragstart = event => {
    const row = event.target.closest("[data-bookmark-id]"); if (!row) return;
    dragged = Number(row.dataset.bookmarkId);
    event.dataTransfer.setData("application/x-gewu-bookmark", String(dragged));
    event.dataTransfer.effectAllowed = "move";
  };
  function destination(event) {
    const row = event.target.closest("[data-bookmark-id]");
    if (!row) return {parent_id:null, before_id:null};
    const node = data.bookmarks.find(n => n.id === Number(row.dataset.bookmarkId));
    const rect = row.getBoundingClientRect(), fraction = (event.clientY - rect.top) / rect.height;
    if (node.kind === "folder" && fraction > .22 && fraction < .78) return {parent_id:node.id, before_id:null, row, inside:true};
    const siblings = data.bookmarks.filter(n => n.parent_id === node.parent_id && n.id !== dragged);
    const index = siblings.findIndex(n => n.id === node.id);
    return {parent_id:node.parent_id, before_id:fraction < .5 ? node.id : siblings[index + 1]?.id || null, row, after:fraction >= .5};
  }
  function clearDrop() { root.querySelectorAll(".drop-inside,.drop-before,.drop-after").forEach(row => row.classList.remove("drop-inside","drop-before","drop-after")); }
  for (const target of [$("browserCollection"), $("browserBookmarksTab")]) {
    target.ondragover = event => {
      if (data.tab !== "bookmarks" || ![...event.dataTransfer.types].some(t => ["application/x-gewu-bookmark","text/uri-list","text/plain"].includes(t))) return;
      event.preventDefault(); event.stopPropagation(); clearDrop();
      const dest = destination(event);
      dest.row?.classList.add(dest.inside ? "drop-inside" : dest.after ? "drop-after" : "drop-before");
    };
    target.ondrop = event => {
      if (data.tab !== "bookmarks") return;
      event.preventDefault(); event.stopPropagation(); clearDrop();
      const dest = destination(event), id = dragged; dragged = null;
      if (id) {
        if (dest.before_id === id) return;
        api("move_bookmark", {id, parent_id:dest.parent_id, before_id:dest.before_id}).then(() => { if (dest.parent_id) data.expanded.add(dest.parent_id); persist({expanded:[...data.expanded]}); return refresh(); }).catch(fail);
      } else {
        const text = event.dataTransfer.getData("text/uri-list") || event.dataTransfer.getData("text/plain");
        try { const url = droppedURL(text); edit({url, title:url === data.url ? data.title || url : new URL(url).hostname}, "bookmark", dest.parent_id || 0).catch(fail); } catch (error) { fail(error); }
      }
    };
  }
  root.addEventListener("dragend", () => { dragged = null; clearDrop(); });
  const resize = $("browserResize");
  resize.onpointerdown = event => {
    if (event.button !== 0) return;
    event.preventDefault(); resize.setPointerCapture(event.pointerId);
    resize.onpointermove = move => { data.width = Math.max(190, Math.min(420, move.clientX)); root.style.setProperty("--browser-sidebar-width", data.width + "px"); scheduleLayout(); };
    resize.onpointerup = () => { resize.onpointermove = null; persist({sidebar_width:data.width}); };
    resize.onpointercancel = resize.onpointerup;
  };
  resize.onkeydown = event => {
    if (!["ArrowLeft","ArrowRight"].includes(event.key)) return;
    event.preventDefault(); data.width = Math.max(190, Math.min(420, data.width + (event.key === "ArrowRight" ? 10 : -10))); persist({sidebar_width:data.width}); render();
  };
  function find(backwards = false) { native({action:"find", text:$("browserFindInput").value, backwards}); }
  $("browserFindInput").onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); find(event.shiftKey); } };
  $("browserFindNext").onclick = () => find(); $("browserFindPrevious").onclick = () => find(true);
  $("browserFindClose").onclick = () => { $("browserFindBar").hidden = true; scheduleLayout(); };
  $("browserFavoritesPrevious").onclick = () => { data.favoritePage--; renderFavorites(); };
  $("browserFavoritesNext").onclick = () => { data.favoritePage++; renderFavorites(); };
  const layoutObserver = new ResizeObserver(scheduleLayout);
  for (const element of [$("browserViewport"), root.querySelector(".browser-sidebar-footer"), root.querySelector(".browser-page-column")]) layoutObserver.observe(element);
  new MutationObserver(() => { if (data.active) scheduleLayout(); }).observe(document.body, {subtree:true, childList:true, attributes:true, attributeFilter:["class","hidden","open","aria-hidden"]});
  addEventListener("resize", () => { scheduleLayout(); if (data.suggestions.length) showSuggestions(); });
  $("browserBack").disabled = true; $("browserForward").disabled = true;
})(globalThis);
