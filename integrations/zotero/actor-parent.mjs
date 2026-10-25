import { Zotero } from "chrome://zotero/content/zotero.mjs";

export class GewuMonitorParent extends JSWindowActorParent {
  receiveMessage({ name, data }) {
    return Zotero.GewuMonitor?.actorMessage(this, name, data) || false;
  }
}
