// Only the plugin-owned, authenticated workspace can use this actor.
export class GewuMonitorChild extends JSWindowActorChild {
  async handleEvent(event) {
    if (event.type !== "DOMContentLoaded" || event.target !== this.document) return;
    const config = await this.sendQuery("prepare");
    if (!config) return;
    const doc = this.document;
    if (!doc.getElementById("libraryMode")) { this.sendAsyncMessage("error"); return; }
    this.listener = async event => {
      if (event.target !== doc || typeof event.detail !== "string" || event.detail.length > 20000000) return;
      let message;
      try { message = JSON.parse(event.detail); } catch (_) { return; }
      let result;
      try { result = {id:message.id, value:await this.sendQuery("host", message)}; }
      catch (error) { result = {id:message.id, error:String(error.message || error)}; }
      this.dispatch("gewu-host-response", result);
    };
    doc.addEventListener("gewu-host-request", this.listener);
    const style = doc.createElement("style");
    style.textContent = `.gewu-zotero-save-button{white-space:nowrap}
      .app.author-mode .author-monitor-list-panel,.app.author-mode .author-monitor-paper-list{grid-template-columns:minmax(0,1fr);min-width:0}`;
    doc.head.append(style);
    const script = doc.createElement("script");
    script.textContent = config.script; doc.head.append(script); script.remove();
    this.sendAsyncMessage("ready");
  }
  dispatch(name, detail) {
    if (!this.document) return;
    this.document.dispatchEvent(new this.contentWindow.CustomEvent(name, {detail:JSON.stringify(detail)}));
  }
  receiveMessage({name, data}) {
    if (name === "command") this.dispatch("gewu-host-command", data);
  }
  didDestroy() { if (this.listener) this.document?.removeEventListener("gewu-host-request", this.listener); }
}
