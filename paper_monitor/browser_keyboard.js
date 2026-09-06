/* Arrow navigation for trusted Browser chrome. Remote DOM is never handled here. */
(function(global) {
  "use strict";
  global.createBrowserKeyboard = function({root, data, native, closeSuggestions, closeContext, visibleDialog}) {
    const $ = id => document.getElementById(id);
    const controls = selector => [...root.querySelectorAll(selector)].filter(e => !e.disabled && e.getClientRects().length && !e.closest('[hidden]'));
    function focus(element) {
      if (!element) return;
      root.classList.add('browser-keyboard-active');
      element.focus({preventScroll:true});
      $("browserAddress").readOnly = element === $("browserAddress");
      element.scrollIntoView({block:"nearest", inline:"nearest"});
    }
    const toolbar = () => focus(controls('.browser-toolbar button')[0]);
    const tabs = () => focus(root.querySelector('[data-browser-tab][aria-selected="true"]') || root.querySelector('[data-browser-tab]') || $("browserHome"));
    const sidebar = () => data.hidden ? tabs() : focus($(data.tab === "history" ? "browserHistoryTab" : "browserBookmarksTab"));
    function page() {
      if (data.home) focus(controls('#browserFavorites button')[0] || $("browserHome"));
      else { closeSuggestions(); native({action:"focus"}); }
    }
    function handleKeydown(event) {
      if (!data.active || visibleDialog() || event.defaultPrevented || event.isComposing || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return false;
      const target = event.target, key = event.key;
      if (!root.contains(target) || target.id === "browserResize") return false;
      if (target === $("browserAddress") && target.readOnly && !key.startsWith("Arrow") && !["Enter", "Escape", "Tab"].includes(key)) target.readOnly = false;
      const editing = target.matches('input:not([readonly]),textarea,select') || target.isContentEditable;
      if (editing) {
        if (key !== "Escape") return false;
        closeSuggestions(); focus($("browserHome"));
      } else if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", " ", "Escape"].includes(key)) return false;
      else if (target.closest('#browserContext')) {
        const items = controls('#browserContext button'), index = items.indexOf(target);
        if (key === "Escape") { closeContext(); focus($("browserBookmarkMenu")); }
        else if (key === "ArrowUp" || key === "ArrowDown") focus(items[(index + (key === "ArrowUp" ? -1 : 1) + items.length) % items.length]);
        else if (key === "Enter" || key === " ") target.click();
      } else if (key === "Enter" || key === " ") {
        if (target === $("browserAddress")) { target.readOnly = false; target.select(); }
        else if (target.matches('[data-browser-tab]')) native({action:"select-tab",tab_id:target.dataset.browserTab});
        else {
          const bookmark = target.closest('[data-bookmark-id]')?.dataset.bookmarkId;
          const favorite = target.closest('#browserFavorites');
          target.click();
          if (bookmark) focus(root.querySelector(`[data-bookmark-id="${bookmark}"]`));
          else if (favorite) queueMicrotask(() => { if (data.home && !document.activeElement?.closest('#browserFavorites')) page(); });
        }
      } else if (target.closest('.browser-toolbar')) {
        const items = controls('.browser-toolbar button, #browserAddress'), index = items.indexOf(target);
        if (key === "ArrowUp") { $("browserAddress").readOnly = false; activatePrimaryKeyboardRoot(); }
        else if (key === "ArrowDown") tabs();
        else if (key === "ArrowLeft" || key === "ArrowRight") focus(items[Math.max(0, Math.min(items.length - 1, index + (key === "ArrowLeft" ? -1 : 1)))]);
      } else if (target.closest('#browserTabs')) {
        const items = controls('[data-browser-tab]'), index = items.indexOf(target.closest('[data-browser-tab]'));
        if (key === "ArrowUp") toolbar();
        else if (key === "ArrowDown") page();
        else if (key === "ArrowLeft" && index === 0 && !data.hidden) sidebar();
        else if (key === "ArrowLeft" || key === "ArrowRight") {
          const tab = items[Math.max(0, Math.min(items.length - 1, index + (key === "ArrowLeft" ? -1 : 1)))];
          if (tab) { focus(tab); native({action:"select-tab",tab_id:tab.dataset.browserTab}); }
        }
      } else if (target.closest('#browserSidebar')) {
        const header = target.closest('.browser-sidebar-tabs');
        const items = controls('#browserCollection [data-bookmark-id], #browserCollection .browser-history-row, #browserHistoryMore, .browser-sidebar-footer button, #browserSidebarSearch');
        const index = items.indexOf(target.closest('[data-bookmark-id], .browser-history-row') || target);
        if (key === "ArrowRight") { if (data.home) page(); else tabs(); }
        else if (header && key === "ArrowUp") toolbar();
        else if (header && key === "ArrowDown") focus(items[0]);
        else if (header && key === "ArrowLeft") focus(target.id === "browserHistoryTab" ? $("browserBookmarksTab") : $("browserHistoryTab"));
        else if (key === "ArrowUp") { if (index <= 0) sidebar(); else focus(items[index - 1]); }
        else if (key === "ArrowDown") focus(items[Math.min(items.length - 1, index + 1)]);
      } else if (target.closest('#browserFavorites')) {
        const rect = target.getBoundingClientRect(), dx = key === "ArrowLeft" ? -1 : key === "ArrowRight" ? 1 : 0;
        const dy = key === "ArrowUp" ? -1 : key === "ArrowDown" ? 1 : 0;
        const items = controls('#browserFavorites button').filter(item => item !== target).map(item => ({item, r:item.getBoundingClientRect()}))
          .filter(({r}) => dx ? dx * (r.x - rect.x) > 1 && Math.abs(r.y - rect.y) < 20 : dy * (r.y - rect.y) > 1)
          .sort((a,b) => dx ? Math.abs(a.r.x - rect.x) - Math.abs(b.r.x - rect.x) : Math.abs(a.r.y - rect.y) + Math.abs(a.r.x - rect.x) * .25 - Math.abs(b.r.y - rect.y) - Math.abs(b.r.x - rect.x) * .25);
        if (items.length) focus(items[0].item);
        else if (key === "ArrowUp") tabs();
        else if (key === "ArrowLeft" && !data.hidden) sidebar();
      } else return false;
      event.preventDefault(); event.stopImmediatePropagation(); return true;
    }
    $("browserAddress").addEventListener("pointerdown", () => { $("browserAddress").readOnly = false; });
    $("browserAddress").addEventListener("blur", () => { $("browserAddress").readOnly = false; });
    root.addEventListener('pointerdown', () => root.classList.remove('browser-keyboard-active'), true);
    return {focusToolbar:toolbar, focusTabs:tabs, focusSidebar:sidebar, handleKeydown};
  };
})(globalThis);
