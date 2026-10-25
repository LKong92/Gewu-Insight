import { Zotero } from "chrome://zotero/content/zotero.mjs";
export class GewuWebParent extends JSWindowActorParent {
  receiveMessage({name, data}) {
    for (const state of Zotero.GewuMonitor?.windows.values() || []) {
      const web = state.tab?.web;
      const page = web && [...web.pages.values()].find(p => p.browser.browsingContext === this.browsingContext);
      if (page) return web.pageMessage(page, name, data);
    }
    return false;
  }
}
