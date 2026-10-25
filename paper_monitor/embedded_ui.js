/* Versioned host contract. Both the App and embedded clients use this workspace. */
(() => {
  "use strict";
  async function post(path, payload) {
    const response = await fetch(path, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || "Operation failed."); return data;
  }
  const commands = {
    "name-title": () => post("/api/settings/library-naming", {rule:"title"}),
    "name-citation": () => post("/api/settings/library-naming", {rule:"citation"}),
    cache: async () => { const result=await post("/api/cache/clear-web", {}); alert(`Removed ${result.removed_files || 0} monitor cache files.`); },
    list: () => window.setLibraryContentView("list"), table: () => window.setLibraryContentView("table"),
    loader: () => window.openLibraryLoader(), metadata: () => window.openMetadataRefreshWindow(),
    identifiers: () => window.openIdentifierRecoveryWindow(), naming: () => window.openPdfRenameSettings(),
    preview: () => window.openQuickLookSettings(), destination: () => window.openLibraryDestinationSettings(),
    websites: () => window.openWebsiteLinkSettings(), ai: () => window.openAIAccessSettings(),
    arxiv: () => window.openArxivSettings(), sources: () => window.openCitationSettings(),
    fields: () => window.openFieldSettings(), font: () => window.openFontSizeSettings(),
    integrations: () => window.openZoteroSettings(),
  };
  window.GewuEmbedded = Object.freeze({
    version: 1,
    command(name) {
      if (!Object.hasOwn(commands, name)) throw new Error("Unsupported Gewu command.");
      return commands[name]();
    },
    selection() {
      if (state.mode === "library") return selectedLibraryPaper()?.paper_id || "";
      if (state.mode === "author") return selectedAuthorMonitorPaper()?.paper_id || "";
      if (["report", "theme"].includes(state.mode)) return selectedReportPaper()?.paper_id || "";
      return "";
    },
    openWebsite(url) { return window.gewuBrowser.openURL(url); },
    browserEvent(event) { window.gewuBrowserNativeEvent(event); },
  });
})();
