/* Native Zotero host. Web content never receives Zotero objects or executable callbacks. */
var GewuMonitor = {
  windows: new Map(),
  saveQueue: Promise.resolve(),
  init(options) { Object.assign(this, options); },
  registerProtocol() {
    this.protocol = Services.io.getProtocolHandler("zotero").wrappedJSObject;
    this.protocolExtension = {noContent:true, doAction:uri => this.protocolAction(uri).catch(error => this.alert(Zotero.getMainWindow(),error.message))};
    this.protocol._extensions["zotero://gewu-insight"] = this.protocolExtension;
  },
  unregisterProtocol() {
    if (this.protocol?._extensions["zotero://gewu-insight"] === this.protocolExtension) delete this.protocol._extensions["zotero://gewu-insight"];
  },
  async protocolAction(uri) {
    if (!Zotero.isMac) throw new Error("This setup link currently supports macOS.");
    const url=new URL(uri.spec), file=PathUtils.join(Services.dirsvc.get("Home", Ci.nsIFile).path,"Library","Application Support","Gewu Insight","zotero-connection.json");
    const config=JSON.parse(await IOUtils.readUTF8(file));
    if (!config.request_id || url.searchParams.get("request") !== config.request_id || Date.now()/1000-config.requested_at>300 || Date.now()/1000<config.requested_at-5)
      throw new Error("Open Zotero Integration in Gewu Insight and try again.");
    if (url.pathname !== "/"+config.action || !["open","update"].includes(config.action)) throw new Error("Unsupported integration request.");
    // Consume the setup request before performing any update.
    const requestID = config.request_id;
    delete config.request_id; await IOUtils.writeUTF8(file,JSON.stringify(config));
    this.setPref("databaseFolder",config.workspace); this.setPref("origin",GewuZoteroCore.origin(config.origin));
    if(config.app_path) this.setPref("appPath",config.app_path);
    if(config.action==="update") {
      if(!config.app_path) throw new Error("Update from an installed Gewu Insight App.");
      const path=PathUtils.join(config.app_path,"Contents","Resources","Gewu Insight for Zotero.xpi");
      const {AddonManager}=ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
      const install=await AddonManager.getInstallForFile(Zotero.File.pathToFile(path));
      if(install.addon.id!==this.id) throw new Error("The bundled plugin has a different identity.");
      await install.install(); return;
    }
    const window=Zotero.getMainWindow(); window.focus();
    const tab=await this.open(window);
    if (tab.folder!==config.workspace || tab.origin!==config.origin) await this.connect(tab,config.workspace,config.origin);
    tab.handoffRequest=requestID;
    if(tab.ready) this.startPresence(tab);
  },

  pref(name) { return Zotero.Prefs.get(`extensions.gewu-monitor.${name}`, true); },
  setPref(name, value) { Zotero.Prefs.set(`extensions.gewu-monitor.${name}`, value, true); },

  addToWindow(window) {
    if (this.windows.has(window)) return;
    const menu = window.document.createXULElement("menuitem");
    menu.id = "gewu-monitor-menu";
    menu.setAttribute("label", "Gewu Insight");
    menu.addEventListener("command", () => this.open(window).catch(e => this.alert(window, e.message)));
    window.document.getElementById("menu_ToolsPopup")?.appendChild(menu);
    // Zotero tab icons use item-type CSS names rather than image URLs.
    // Scope the branded image to our own name, including the tab switcher.
    const iconStyle = this.element(window.document, "style");
    iconStyle.textContent = `.icon-item-type[data-item-type="gewu-insight"] {
      background: url("resource://gewu-monitor/icons/gewu.png?v=${this.version}") center / contain no-repeat !important;
    }`;
    window.document.documentElement.appendChild(iconStyle);
    this.windows.set(window, { menu, iconStyle, tab: null });
  },

  removeFromWindow(window) {
    const state = this.windows.get(window);
    if (!state) return;
    if (state.tab) window.Zotero_Tabs.close(state.tab.id);
    state.menu.remove();
    state.iconStyle.remove();
    this.windows.delete(window);
  },

  alert(window, message) { Services.prompt.alert(window, "Gewu Insight", String(message)); },

  element(document, name, text, attrs = {}) {
    const element = document.createElementNS("http://www.w3.org/1999/xhtml", name);
    if (text) element.textContent = text;
    for (const [k, v] of Object.entries(attrs)) element.setAttribute(k, v);
    return element;
  },

  async open(window) {
    this.addToWindow(window);
    const state = this.windows.get(window);
    if (state.tab) { window.Zotero_Tabs.select(state.tab.id); return state.tab; }
    const initialLibrary = window.ZoteroPane.getSelectedLibraryIDs()[0] || Zotero.Libraries.userLibraryID;
    const initialCollection = window.ZoteroPane.getSelectedCollections()[0]?.id || 0;
    const document = window.document;
    const tab = window.Zotero_Tabs.add({ type: "gewu-monitor", title: "Gewu Insight", select: true,
      data: { icon: "gewu-insight" }, onClose: () => {
        if (state.tab?.timer) window.clearTimeout(state.tab.timer);
        if (state.tab?.statusTimer) window.clearTimeout(state.tab.statusTimer);
        const closing=state.tab;
        if(closing){
          closing.closed=true;
          closing.web?.dispose();
          this.stopPresence(closing).finally(()=>closing.cookies?.dispose());
          closing.token="";
        }
        state.tab = null;
      } });
    state.tab = tab;
    tab.window = window;
    tab.sessionID=Services.uuid.generateUUID().toString().replace(/[{}]/g,"");
    tab.cookies = Zotero.HTTP.newCookieContext();
    const root = this.element(document, "div", "", { class: "gewu-zotero-host" });
    const style = this.element(document, "style");
    style.textContent = `
      .gewu-zotero-host {position:relative;display:flex;flex:1;min-height:0;height:100%;color:CanvasText;background:Canvas;font:13px system-ui;}
      .gewu-zotero-host [hidden] {display:none!important;}
      .gewu-zotero-host button,.gewu-zotero-host select,.gewu-zotero-host input[type=text] {font:inherit;padding:7px 10px;border:1px solid #a7b3c2;border-radius:6px;background:Field;color:FieldText;}
      .gewu-zotero-host button {cursor:pointer;}
      .gewu-zotero-host button:disabled {opacity:.5;cursor:default;}
      .gewu-zotero-host .gewu-save {background:#285b8f;color:white;border-color:#285b8f;}
      .gewu-zotero-host .gewu-status {position:absolute;right:16px;bottom:42px;z-index:20;display:flex;align-items:center;gap:12px;max-width:min(620px,85%);padding:12px 16px;border:1px solid #cbd5e1;border-radius:9px;background:Canvas;box-shadow:0 3px 18px #0002;}
      .gewu-zotero-host .gewu-status[data-error=true] {color:#a52424;border-color:#d8a3a3;}
      .gewu-zotero-modal {position:absolute;inset:0;z-index:10;background:#0003;display:grid;place-items:center;padding:24px;}
      .gewu-zotero-panel {box-sizing:border-box;width:440px;max-width:100%;max-height:100%;overflow:auto;background:Canvas;border:1px solid #cbd5e1;border-radius:12px;padding:24px;box-shadow:0 8px 36px #0002;line-height:1.5;}
      .gewu-zotero-panel h2 {font-size:18px;margin:0 0 12px;}
      .gewu-zotero-panel p {margin:10px 0;}
      .gewu-zotero-panel .gewu-buttons {display:flex;justify-content:flex-end;gap:8px;margin-top:20px;}
      .gewu-zotero-panel .gewu-field {display:grid;gap:6px;margin:14px 0;}
      .gewu-zotero-panel .gewu-target,.gewu-zotero-panel .gewu-address {box-sizing:border-box;width:100%;}
      .gewu-zotero-folder {overflow-wrap:anywhere;font-size:12px;color:GrayText;}
    `;
    root.appendChild(style);
    const make = (...args) => this.element(document, ...args);
    const modal = title => {
      const overlay=make("div", "", {class:"gewu-zotero-modal",hidden:"true",role:"dialog","aria-modal":"true","aria-label":title});
      const panel=make("div","",{class:"gewu-zotero-panel"}); panel.append(make("h2",title)); overlay.append(panel);
      overlay.addEventListener("keydown",event=>{if(event.key==="Escape"){event.stopPropagation();this.closeDialog(tab,overlay);}});
      overlay.addEventListener("click",event=>{if(event.target===overlay&&tab.ready)this.closeDialog(tab,overlay);});
      root.append(overlay); return {overlay,panel};
    };
    tab.status=make("div","",{class:"gewu-status",role:"status","aria-live":"polite",hidden:"true"});
    tab.statusText=make("span");
    tab.show=make("button","Show in Zotero",{hidden:"true"});
    tab.show.onclick=async()=>{if(tab.lastItemID){window.Zotero_Tabs.select("zotero-pane");await window.ZoteroPane.selectItem(tab.lastItemID);}};
    const dismiss=make("button","×",{"aria-label":"Dismiss notification"});
    dismiss.onclick=()=>this.status(tab,""); tab.status.append(tab.statusText,tab.show,dismiss); root.append(tab.status);
    const destination=modal("Save to Zotero"); tab.saveDialog=destination.overlay;
    const targetLabel=make("label","Destination",{class:"gewu-field"});
    tab.target=make("select","",{class:"gewu-target","aria-label":"Save to Zotero collection"});
    targetLabel.append(tab.target); destination.panel.append(targetLabel);
    const pdfLabel=make("label"); tab.copyPDF=make("input","",{type:"checkbox"});
    tab.copyPDF.checked=this.pref("copyPDF")!==false;
    pdfLabel.append(tab.copyPDF,document.createTextNode(" Copy the available Default PDF")); destination.panel.append(pdfLabel);
    const saveButtons=make("div","",{class:"gewu-buttons"}),cancelSave=make("button","Cancel");
    cancelSave.onclick=()=>this.closeDialog(tab,tab.saveDialog);
    tab.save=make("button","Save to Zotero",{class:"gewu-save",disabled:"true"});
    tab.save.onclick=()=>{
      const id=tab.pendingPaper; this.closeDialog(tab,tab.saveDialog);
      this.setPref("copyPDF",tab.copyPDF.checked); this.setPref("destination",tab.target.value);
      this.saveSelected(tab,id);
    };
    saveButtons.append(cancelSave,tab.save);destination.panel.append(saveButtons);
    const connection=modal("Gewu Connection"); tab.setup=connection.overlay;
    connection.panel.append(make("p","Uses the same database and settings as Gewu Insight."));
    tab.folderLabel=make("p","",{class:"gewu-zotero-folder"});connection.panel.append(tab.folderLabel);
    const choose=make("button","Choose Gewu Database…");
    choose.onclick=async()=>{
      try {
        const {FilePicker}=ChromeUtils.importESModule("chrome://zotero/content/modules/filePicker.mjs");
        const picker=new FilePicker();picker.init(window,"Choose the Gewu Database folder",picker.modeGetFolder);
        if(await picker.show()!==picker.returnOK)return;
        await this.connect(tab,picker.file,tab.address.value);
        this.setPref("databaseFolder",picker.file);this.setPref("origin",tab.origin);
      } catch(error){this.status(tab,error.message,true);}
    };
    connection.panel.append(choose);
    const advanced=make("details"),summary=make("summary","Advanced");advanced.style.marginTop="18px";advanced.append(summary);
    const addressLabel=make("label","Local address",{class:"gewu-field"});
    tab.address=make("input","",{type:"text",class:"gewu-address","aria-label":"Local Gewu address"});
    tab.address.value=this.pref("origin")||"http://127.0.0.1:8765";addressLabel.append(tab.address);advanced.append(addressLabel);
    const automatic=make("label");tab.autoStart=make("input","",{type:"checkbox"});
    tab.autoStart.checked=this.pref("autoStart")!==false;
    tab.autoStart.onchange=()=>this.setPref("autoStart",tab.autoStart.checked);
    automatic.append(tab.autoStart,document.createTextNode(" Start Gewu in the background when needed"));
    advanced.append(automatic);connection.panel.append(advanced);
    const connectButtons=make("div","",{class:"gewu-buttons"}),close=make("button","Close"),retry=make("button","Reconnect",{class:"gewu-save"});
    close.onclick=()=>this.closeDialog(tab,tab.setup);
    retry.onclick=()=>this.connect(tab,this.pref("databaseFolder"),tab.address.value).catch(error=>this.status(tab,error.message,true));
    connectButtons.append(close,retry);connection.panel.append(connectButtons);
    const browser = document.createXULElement("browser");
    browser.setAttribute("type", "content");
    browser.setAttribute("remote", "true");
    browser.setAttribute("maychangeremoteness", "true");
    browser.setAttribute("usercontextid", String(tab.cookies.id));
    browser.setAttribute("disableglobalhistory", "true");
    browser.setAttribute("flex", "1");
    browser.style.cssText = "flex:1;min-height:0;width:100%;border:0;";
    browser.hidden = true;
    tab.browser = browser;
    const surface = this.element(document, "div", "", {class:"gewu-zotero-surface"});
    surface.style.cssText = "position:relative;display:flex;flex:1;min-height:0;overflow:hidden";
    surface.append(browser); tab.surface = surface;
    tab.web = new GewuBrowserHost(this, tab);
    root.append(surface);
    tab.container.style.cssText = "display:flex;flex-direction:column;min-height:0;";
    tab.container.appendChild(root);
    await this.targets(tab, initialLibrary, initialCollection);
    if (this.pref("destination") && [...tab.target.options].some(o=>o.value===this.pref("destination"))) tab.target.value=this.pref("destination");
    tab.target.addEventListener("focus", () => this.targets(tab).catch(e => this.status(tab, e.message, true)));
    await this.discoverConnection(tab);
    if (this.pref("databaseFolder")) {
      try { await this.connect(tab, this.pref("databaseFolder"), tab.address.value); }
      catch (e) { this.showConnection(tab); this.status(tab, e.message, true); }
    } else this.showConnection(tab);
    return tab;
  },

  status(tab, message, error = false, showItem = false) {
    if(tab.statusTimer)tab.window.clearTimeout(tab.statusTimer);
    tab.statusText.textContent=String(message);
    tab.status.dataset.error=String(error);tab.status.hidden=!message;
    tab.show.hidden=!showItem||!tab.lastItemID;
    if(message)tab.statusTimer=tab.window.setTimeout(()=>{tab.status.hidden=true;},error?14000:7000);
  },

  closeDialog(tab, overlay) {
    if(overlay===tab.setup&&!tab.ready)return;
    overlay.hidden=true;tab.web?.layout();tab.browser.focus();
  },

  showConnection(tab) {
    tab.folderLabel.textContent=tab.folder||this.pref("databaseFolder")||"Choose the database you use in Gewu Insight.";
    tab.setup.hidden=false;tab.web?.layout();tab.setup.querySelector("button")?.focus();
  },

  async promptSave(tab, paperID) {
    const id=paperID||this.selection(tab);
    if(!id||tab.saving) return false;
    await this.targets(tab);tab.pendingPaper=id;tab.save.disabled=false;
    tab.saveDialog.hidden=false;tab.web?.layout();tab.target.focus();return true;
  },

  async targets(tab, libraryID, collectionID) {
    const selected = libraryID ? `${libraryID}:${collectionID || 0}` : tab.target.value;
    tab.target.replaceChildren();
    for (const library of Zotero.Libraries.getAll()) {
      if (!library.editable || !["user", "group"].includes(library.libraryType)) continue;
      tab.target.appendChild(this.element(tab.window.document, "option", library.name, { value: `${library.libraryID}:0` }));
      const add = (parent, depth) => {
        const children = parent ? Zotero.Collections.getByParent(parent) : Zotero.Collections.getByLibrary(library.libraryID);
        for (const c of children) {
          if (!parent && c.parentID) continue;
          tab.target.appendChild(this.element(tab.window.document, "option", `${"　".repeat(depth)}${c.name}`,
            { value: `${library.libraryID}:${c.id}` }));
          add(c.id, depth + 1);
        }
      };
      add(0, 1);
    }
    if ([...tab.target.options].some(o => o.value === selected)) tab.target.value = selected;
  },

  async request(tab, path, payload) {
    if (!/^\/api\/(?:health$|paper\?|paper-files\?|integrations\/zotero(?:\/session)?$|browser-capture-file$)/.test(path)) throw new Error("Unsupported Gewu request.");
    let response;
    try {
      response = await Zotero.HTTP.request(payload === undefined ? "GET" : "POST", tab.origin + path, {
        body:payload === undefined ? undefined : JSON.stringify(payload),
        headers: { "X-Gewu-Workspace": tab.token, "Content-Type":"application/json" }, responseType: "json", followRedirects: false,
        userContextId: tab.cookies?.id,
        timeout: 15000, successCodes: [200, 401, 403], noCache: true
      });
    } catch (_) { const error = new Error("Cannot reach Gewu Insight. Reconnect or open the app."); error.unreachable = true; throw error; }
    if (response.status !== 200) throw new Error("Gewu rejected this connection. Choose the database used by the running app.");
    return response.response;
  },

  async connect(tab, folder, address) {
    if (tab.connecting || tab.saving) throw new Error("Wait for the current operation to finish before reconnecting.");
    tab.connecting = true;
    try { return await this.connectWorkspace(tab, folder, address); }
    catch(error) { this.showConnection(tab); throw error; }
    finally { tab.connecting = false; }
  },

  async connectWorkspace(tab, folder, address) {
    if (!folder) throw new Error("Choose your Gewu Database folder first.");
    await this.stopPresence(tab);
    tab.sessionID=Services.uuid.generateUUID().toString().replace(/[{}]/g,"");
    tab.save.disabled = true;
    tab.ready = false; tab.selectedPaper = "";
    tab.browser.hidden = true;
    tab.setup.hidden = true;
    this.status(tab, "Opening Gewu Insight…");
    if (tab.timer) tab.window.clearTimeout(tab.timer);
    tab.cookies.dispose();
    tab.web?.reset();
    tab.token = "";
    tab.origin = GewuZoteroCore.origin(address);
    const tokenPath = PathUtils.join(String(folder), "data", ".gewu-workspace-token");
    let token;
    try { token = (await IOUtils.readUTF8(tokenPath)).trim(); }
    catch (_) { throw new Error("This folder is not an active Gewu Database. Open it in Gewu first."); }
    if (!/^[a-f0-9]{64}$/.test(token)) throw new Error("The Gewu workspace credential is invalid.");
    tab.token = token;
    let health;
    try { health = await this.request(tab, "/api/health"); }
    catch (e) {
      if (!e.unreachable || !tab.autoStart.checked) { tab.token = ""; throw e; }
      this.status(tab, "Starting Gewu in the background…");
      await this.startBackground(tab, folder);
      for (let i = 0; i < 60; i++) {
        await Zotero.Promise.delay(500);
        try { health = await this.request(tab, "/api/health"); break; }
        catch (error) { if (!error.unreachable) throw error; }
      }
      if (!health) throw new Error("Gewu did not start. Open Gewu Insight to check its database, then reconnect.");
    }
    if (!health.ok || !health.database_uuid || !health.database_path) {
      tab.token = ""; throw new Error("The server did not confirm an authenticated Gewu workspace.");
    }
    if (health.integrations?.zotero !== 1) throw new Error("Update Gewu Insight to use the complete Zotero workspace.");
    const selectedDatabase=Zotero.File.pathToFile(PathUtils.join(folder,"data","paper_monitor.sqlite"));
    selectedDatabase.normalize();
    if (PathUtils.normalize(health.database_path) !== selectedDatabase.path)
      throw new Error("A different Gewu database is running. Open the intended database in Gewu and reconnect.");
    if (health.app_path) this.setPref("appPath", health.app_path);
    tab.databaseID = String(health.database_uuid);
    tab.folder = String(folder);
    tab.setup.hidden = true;
    tab.browser.hidden = false;
    this.status(tab, "Loading Gewu Insight…");
    // Health deliberately does not set cookies. Authenticate a normal workspace
    // request to establish the HttpOnly session before navigating the browser.
    try {
      await Zotero.HTTP.request("GET", tab.origin + "/", {
        headers: { "X-Gewu-Workspace": tab.token }, responseType: "text",
        userContextId: tab.cookies.id,
        followRedirects: false, timeout: 15000, successCodes: [200], noCache: true
      });
    } catch (_) { tab.token = ""; throw new Error("Could not open the Gewu workspace. Reconnect."); }
    // No secret goes in a URL, document, preference, or web-visible JavaScript object.
    tab.browser.loadURI(Services.io.newURI(tab.origin + "/"), {
      triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()
    });
    tab.timer = tab.window.setTimeout(() => {
      if (tab.ready || !tab.browser.isConnected) return;
      this.showConnection(tab);
      this.status(tab, "Gewu Insight did not finish loading. Reconnect to retry.", true);
    }, 30000);
  },

  actorMessage(actor, name, data) {
    const context = actor.browsingContext;
    const tab = [...this.windows.values()].map(s => s.tab).find(t =>
      t && t.browser.browsingContext === context && t.token);
    if (!tab) return false;
    const uri = actor.manager.documentURI;
    let valid = false;
    try { const url = new URL(uri.spec); valid = url.origin === tab.origin && url.pathname === "/"; } catch (_) {}
    if (!valid) return false;
    if (name === "prepare") return {script:this.workspaceScript};
    if (name === "host") return this.hostRequest(tab, data);
    if (name === "ready") {
      tab.ready = true;
      if (tab.timer) tab.window.clearTimeout(tab.timer);
      tab.setup.hidden = true;
      this.status(tab, "");
      this.startPresence(tab);
    } else if (name === "selection") {
      tab.selectedPaper = String(data || "").slice(0, 200);
      tab.save.disabled = !!tab.saving || !tab.selectedPaper;
    } else if (name === "save") this.promptSave(tab, String(data || "").slice(0, 200));
    else if (name === "website") this.openWebsite(tab, String(data || "").slice(0, 200));
    else if (name === "link") {
      const url = GewuZoteroCore.website(data);
      if (url) Zotero.launchURL(url);
    } else if (name === "error") {
      this.stopPresence(tab);
      tab.ready = false; this.showConnection(tab);
      this.status(tab, "Gewu could not open this workspace. Reconnect using its database folder.", true);
    }
    return true;
  },

  startPresence(tab) {
    if(tab.closed || !tab.ready)return;
    if(tab.presenceTimer)tab.window.clearInterval(tab.presenceTimer);
    const heartbeat=()=>{
      if(tab.closed || !tab.ready || tab.presenceBusy)return;
      tab.presenceBusy=true;
      this.request(tab,"/api/integrations/zotero/session",{
        action:"heartbeat",session:tab.sessionID,version:this.version,handoff_request:tab.handoffRequest||""
      }).catch(()=>{}).finally(()=>{tab.presenceBusy=false;});
    };
    heartbeat();tab.presenceTimer=tab.window.setInterval(heartbeat,2500);
  },

  async stopPresence(tab) {
    if(tab.presenceTimer)tab.window.clearInterval(tab.presenceTimer);
    tab.presenceTimer=null;
    if(tab.token && tab.origin && tab.sessionID){
      try{await this.request(tab,"/api/integrations/zotero/session",{action:"close",session:tab.sessionID});}catch(_){}
    }
  },

  send(tab, name, data) {
    if (!tab.ready) return;
    tab.browser.browsingContext.currentWindowGlobal.getActor("GewuMonitor").sendAsyncMessage("command", {name, data});
  },

  async hostRequest(tab, {channel, payload = {}} = {}) {
    if (channel === "selection") {
      tab.selectedPaper = String(payload.paperID || "").slice(0,200);
      tab.save.disabled = !!tab.saving || !tab.selectedPaper;
    } else if (channel === "save") return this.promptSave(tab, String(payload.paperID || "").slice(0,200));
    else if (channel === "command") return this.command(tab, String(payload.name || ""));
    else if (channel === "browser") return tab.web.command(payload);
    else if (channel === "pdf-engine") return GewuPDFResources.engine();
    else if (channel === "pdf-asset") return GewuPDFResources.asset(payload);
    else if (channel === "status") this.status(tab, String(payload.message || "").slice(0,1000), !!payload.error);
    else throw new Error("Unsupported host request.");
    return true;
  },

  async command(tab, command) {
    if (!command) return;
    if (command === "connection") return this.showConnection(tab);
    if (command === "database") return this.alert(tab.window, tab.folder || "No Gewu database connected.");
    if (command === "app") {
      const file = Zotero.File.pathToFile(this.pref("appPath") || "/Applications/Gewu Insight.app");
      file.launch(); return;
    }
    if (command === "guide") {
      if (!tab.ready) throw new Error("Connect Gewu before opening the User Guide.");
      const help = tab.window.Zotero_Tabs.add({type:"gewu-help",title:"Gewu User Guide",select:true,data:{icon:"gewu-insight"}});
      const browser = tab.window.document.createXULElement("browser");
      for (const [key,value] of Object.entries({type:"content",remote:"true",usercontextid:String(tab.cookies.id),flex:"1"})) browser.setAttribute(key,value);
      help.container.style.cssText="display:flex;height:100%"; browser.style.cssText="flex:1;width:100%;height:100%";
      help.container.append(browser); browser.loadURI(Services.io.newURI(tab.origin+"/user-guide"),{triggeringPrincipal:Services.scriptSecurityManager.getSystemPrincipal()});
      return;
    }
    if (!tab.ready) throw new Error("Connect Gewu before opening its settings.");
    this.send(tab, command);
  },

  async discoverConnection(tab) {
    if (!Zotero.isMac) return;
    const path = PathUtils.join(Services.dirsvc.get("Home", Ci.nsIFile).path, "Library", "Application Support", "Gewu Insight", "zotero-connection.json");
    try {
      const config = JSON.parse(await IOUtils.readUTF8(path));
      if (!this.pref("databaseFolder") && config.workspace) {
        this.setPref("databaseFolder", config.workspace);
        tab.address.value = GewuZoteroCore.origin(config.origin);
        this.setPref("origin", tab.address.value);
      }
      if (!this.pref("appPath") && config.app_path) this.setPref("appPath", config.app_path);
    } catch (_) { /* An explicitly chosen database also works without installation setup. */ }
  },

  async startBackground(tab, folder) {
    if (!Zotero.isMac) throw new Error("Automatic startup is currently available on macOS. Open Gewu Insight and reconnect.");
    const app = this.pref("appPath") || "/Applications/Gewu Insight.app";
    const executable = PathUtils.join(app, "Contents", "MacOS", "Gewu Insight Server");
    if (!await IOUtils.exists(executable)) throw new Error("Gewu Insight is not installed at the connected location. Open the app and reconnect.");
    // Run the packaged helper directly: no shell command, no token argument, no visible App window.
    const process = Cc["@mozilla.org/process/util;1"].createInstance(Ci.nsIProcess);
    process.init(Zotero.File.pathToFile(executable));
    const args = ["--database", String(folder), "--port", new URL(tab.origin).port || "80", "--host", new URL(tab.origin).hostname.replace(/^\[|\]$/g, "")];
    process.runwAsync(args, args.length);
  },

  selection(tab) {
    return tab.ready && tab.browser.currentURI?.spec === tab.origin + "/" ? tab.selectedPaper || "" : "";
  },

  async openWebsite(tab, paperID) {
    try {
      const { paper } = await this.request(tab, "/api/paper?paper_id=" + encodeURIComponent(paperID));
      const url = GewuZoteroCore.website(paper.url);
      if (url) Zotero.launchURL(url);
    } catch (e) { this.status(tab, e.message, true); }
  },

  saveSelected(tab, paperID) {
    const id = paperID || this.selection(tab);
    if (!id || tab.saving) return Promise.resolve();
    const target = tab.target.value;
    const copyPDF = tab.copyPDF.checked;
    const connection = { origin: tab.origin, token: tab.token, databaseID: tab.databaseID, cookies: tab.cookies };
    tab.saving = true; tab.save.disabled = true;
    this.status(tab, "Saving to Zotero…");
    const task = async () => {
      try {
        const result = await this.savePaper(connection, id, target, copyPDF);
        tab.lastItemID = result.itemID; tab.show.disabled = false;
        this.status(tab, result.message, !!result.warning, true);
        return result;
      } catch (e) { this.status(tab, e.message, true); return { error: e.message }; }
      finally { tab.saving = false; tab.save.disabled = !this.selection(tab); }
    };
    const promise = this.saveQueue.then(task, task);
    this.saveQueue = promise.catch(() => {});
    return promise;
  },

  async findExisting(libraryID, data, sourceMarker) {
    const found = new Map();
    const search = async (field, op, value, matches) => {
      if (!value) return;
      const query = new Zotero.Search(); query.libraryID = libraryID;
      query.addCondition(field, op, value);
      for (const id of await query.search()) {
        const item = await Zotero.Items.getAsync(id);
        if (item && !item.deleted && item.isRegularItem() && matches(item)) found.set(id, item);
      }
    };
    await search("extra", "contains", sourceMarker, item => GewuZoteroCore.extraHas(item.getField("extra"), sourceMarker));
    await search("DOI", "contains", data.DOI, item => GewuZoteroCore.doi(item.getField("DOI")) === data.DOI);
    const a = data.extra.split("\n").find(line => line.startsWith("arXiv: "));
    if (a) await search("extra", "contains", a, item => GewuZoteroCore.extraHas(item.getField("extra"), a));
    if (found.size > 1) throw new Error("Multiple Zotero items match this paper. Resolve the duplicates in Zotero before saving.");
    return [...found.values()][0] || null;
  },

  async savePaper(tab, paperID, target, copyPDF) {
    if (!/^\d+:\d+$/.test(target)) throw new Error("Choose a writable Zotero destination.");
    const [libraryID, collectionID] = target.split(":").map(Number);
    const library = Zotero.Libraries.get(libraryID);
    if (!library?.editable) throw new Error("This Zotero library is read-only.");
    if (collectionID) {
      const collection = Zotero.Collections.get(collectionID);
      if (!collection || collection.libraryID !== libraryID) throw new Error("The selected collection no longer exists.");
    }
    const { paper } = await this.request(tab, "/api/paper?paper_id=" + encodeURIComponent(paperID));
    if (!paper || paper.paper_id !== paperID) throw new Error("Gewu returned a different paper. Nothing was saved.");
    const data = GewuZoteroCore.fields(paper, tab.databaseID);
    const sourceMarker = GewuZoteroCore.marker(tab.databaseID, paper);
    let item, reused;
    await Zotero.DB.executeTransaction(async () => {
      item = await this.findExisting(libraryID, data, sourceMarker);
      reused = !!item;
      if (!item) {
        item = new Zotero.Item(data.itemType); item.libraryID = libraryID;
        for (const [key, value] of Object.entries(data)) {
          if (["itemType", "creators"].includes(key) || !value) continue;
          if (Zotero.ItemFields.isValidForType(Zotero.ItemFields.getID(key), item.itemTypeID)) item.setField(key, value);
        }
        if (data.itemType === "preprint") item.setField("repository", "arXiv");
        item.setCreators(data.creators);
      } else if (!GewuZoteroCore.extraHas(item.getField("extra"), sourceMarker)) {
        item.setField("extra", [item.getField("extra"), sourceMarker].filter(Boolean).join("\n"));
      }
      if (collectionID) item.addToCollection(collectionID);
      await item.save();
    });
    let detail = "Metadata saved.";
    let warning = false;
    if (copyPDF) {
      try {
        if (!library.filesEditable) throw new Error("This library does not allow file attachments.");
        const attachments = await Zotero.Items.getAsync(item.getAttachments());
        if (attachments.some(a => a.attachmentContentType === "application/pdf")) detail = "Existing Zotero PDF kept.";
        else {
          const files = await this.request(tab, "/api/paper-files?paper_id=" + encodeURIComponent(paperID));
          const pdf = GewuZoteroCore.defaultPDF(files);
          if (!pdf) detail = "No local Default PDF available; metadata saved.";
          else {
            const header = await IOUtils.read(pdf.local_path, { maxBytes: 5 });
            if (String.fromCharCode(...header) !== "%PDF-") throw new Error("The Default file is not a valid PDF.");
            await Zotero.Attachments.importFromFile({ file: pdf.local_path, parentItemID: item.id,
              contentType: "application/pdf", title: pdf.display_name || "Full Text" });
            detail = "PDF copied into Zotero.";
          }
        }
      } catch (_) { detail = "Metadata saved, but the PDF could not be copied. Retry to add it later."; warning = true; }
    }
    return { itemID: item.id, reused, warning, message: `${reused ? "Already in Zotero; destination updated." : "Saved to Zotero."} ${detail}` };
  }
};
