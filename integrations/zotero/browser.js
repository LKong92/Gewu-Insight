/* Gecko host for the existing Gewu Browser UI. Publisher cookies are separate from the workspace. */
var GewuBrowserHost = class {
  constructor(plugin, tab) { this.plugin = plugin; this.tab = tab; this.pages = new Map(); this.reset(); }
  reset() {
    for (const page of this.pages.values()) { page.browser.removeProgressListener(page.listener); page.browser.remove(); }
    this.pages.clear(); this.currentID = ""; this.geometry = {}; this.capture = null;
    this.cookies?.dispose(); this.cookies = Zotero.HTTP.newCookieContext();
  }
  dispose() { this.reset(); this.cookies.dispose(); this.suggestions?.remove(); this.dialog?.remove(); }
  get current() { return this.pages.get(this.currentID); }
  emit(event) { this.plugin.send(this.tab, "browser-event", event); }
  url(value) { return GewuZoteroCore.browserURL(value); }
  actor(page = this.current) { return page.browser.browsingContext.currentWindowGlobal.getActor("GewuWeb"); }
  create(url = "", context = {}) {
    const browser = this.tab.window.document.createXULElement("browser");
    for (const [key,value] of Object.entries({type:"content", remote:"true", maychangeremoteness:"true", disableglobalhistory:"true", usercontextid:String(this.cookies.id)})) browser.setAttribute(key,value);
    browser.style.cssText = "position:absolute;border:0;background:white;z-index:2"; browser.hidden = true;
    const page = {id:Zotero.Utilities.randomString(16), browser, url:"", title:"Favorites", home:true, loading:false, context};
    const host = this;
    const listener = {
      QueryInterface:ChromeUtils.generateQI(["nsIWebProgressListener", "nsISupportsWeakReference"]),
      onStateChange(progress, request, flags) {
        if (!progress.isTopLevel || !(flags & Ci.nsIWebProgressListener.STATE_IS_WINDOW)) return;
        if (flags & Ci.nsIWebProgressListener.STATE_START) page.loading = true;
        if (flags & Ci.nsIWebProgressListener.STATE_STOP) page.loading = false;
        host.state(page);
      },
      onLocationChange(progress, request, location) {
        if (!progress.isTopLevel || location.spec === "about:blank") return;
        try { page.url = host.url(location.spec); page.home = false; }
        catch (_) { browser.stop(); host.emit({event:"error",message:"This address cannot be opened in Gewu Browser."}); }
        host.state(page);
      },
      onProgressChange() {}, onStatusChange() {}, onSecurityChange() {}, onContentBlockingEvent() {},
    };
    page.listener = listener; this.pages.set(page.id,page); this.currentID = page.id;
    this.tab.surface.append(browser); browser.addProgressListener(listener);
    if (url) this.navigate(page,url,context); else this.state(page);
    return page;
  }
  navigate(page, value, context = {}) {
    const url = this.url(value); page.context = context; page.home = false; page.url = url; page.loading = true;
    page.browser.loadURI(Services.io.newURI(url), {triggeringPrincipal:Services.scriptSecurityManager.createNullPrincipal({userContextId:this.cookies.id})});
    this.state(page);
  }
  state(page = this.current) {
    this.emit({event:"tabs",tabs:[...this.pages.values()].map(p => ({id:p.id,title:p.title,url:p.url,active:p.id===this.currentID,home:p.home,loading:p.loading}))});
    if (page?.id === this.currentID) this.emit({event:"state",tab_id:page.id,url:page.home ? "" : page.url,title:page.title,
      home:page.home,loading:page.loading,progress:page.loading?.2:1,canBack:page.browser.canGoBack,canForward:page.browser.canGoForward,
      workspace_return_id:page.context.workspace_return_id || ""});
    this.layout();
  }
  layout() {
    const g = this.geometry;
    const width = this.tab.surface.clientWidth, height = this.tab.surface.clientHeight;
    const scale = g.viewportWidth ? width / g.viewportWidth : 1;
    for (const page of this.pages.values()) {
      page.browser.hidden = !(page.id === this.currentID && g.visible && !page.home && !this.dialog && this.tab.setup.hidden && this.tab.saveDialog.hidden);
      Object.assign(page.browser.style, {left:Math.max(0,g.x*scale||0)+"px", top:Math.max(0,g.y*scale||0)+"px",
        width:Math.max(0,Math.min(width,(g.width||0)*scale))+"px",height:Math.max(0,Math.min(height,(g.height||0)*scale))+"px"});
    }
  }
  pageMessage(page, name, data) {
    if (name === "open") { this.create(this.url(data.url)); return true; }
    if (name === "loaded") {
      page.title = String(data.title || page.url).slice(0,1000); page.loading = false;
      this.state(page);
      if (page.url && !page.home) this.emit({event:"visit",event_id:Services.uuid.generateUUID().toString().slice(1,-1),url:page.url,title:page.title});
    }
    return true;
  }
  async picker(mode, title, name = "") {
    const { FilePicker } = ChromeUtils.importESModule("chrome://zotero/content/modules/filePicker.mjs");
    const picker = new FilePicker(); picker.init(this.tab.window,title,picker[mode]);
    if (name) picker.defaultString = name;
    const status = await picker.show();
    return [picker.returnOK,picker.returnReplace].includes(status) ? picker.file : null;
  }
  async form(title, fields, button = "Save", description = "") {
    if (this.dialog) return null;
    const doc = this.tab.window.document, make = (...args) => this.plugin.element(doc,...args);
    return new Promise(resolve => {
      const finish = result => { dialog.overlay.remove(); this.dialog = null; this.layout(); this.tab.browser.focus(); resolve(result); };
      const dialog=GewuZoteroUI.dialog(make,this.tab.surface,title,"",()=>finish(null),true);
      const group=make("div","",{class:"gewu-group"}),inputs={};
      if(description){const row=make("div","",{class:"gewu-row"});row.append(make("p",description,{class:"gewu-confirm-message"}));group.append(row);}
      for (const field of fields) {
        const label=make("label",field.label,{class:"gewu-field gewu-row"});
        const input=make(field.options?"select":"input","",field.options?{}:{type:"text"});
        if(field.options)for(const option of field.options)input.append(make("option",option.label,{value:String(option.value)}));
        input.value=field.value||"";inputs[field.name]=input;label.append(input);group.append(label);
      }
      dialog.body.append(group);
      const row=make("div","",{class:"gewu-buttons"}),cancel=make("button","Cancel",{type:"button"}),save=make("button",button,{type:"submit",class:"gewu-save"});
      row.append(cancel,save);dialog.body.append(row);dialog.overlay.hidden=false;this.dialog=dialog.overlay;this.layout();
      cancel.onclick=()=>finish(null);
      dialog.panel.onsubmit=event=>{event.preventDefault();finish(Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value])));};
      (Object.values(inputs)[0] || cancel).focus();
    });
  }
  async command(p) {
    const page = this.current;
    switch (p.action) {
      case "layout": this.geometry = p; this.layout(); return true;
      case "home": { const target = page || this.create(); target.home = true; target.loading = false; target.url = ""; target.title = "Favorites"; target.browser.loadURI(Services.io.newURI("about:blank"), {triggeringPrincipal:Services.scriptSecurityManager.getSystemPrincipal()}); this.state(target); break; }
      case "navigate": this.navigate(page || this.create(),p.url,p); break;
      case "new-tab": this.create(p.url ? this.url(p.url) : "",p); break;
      case "select-tab": if (this.pages.has(p.tab_id)) { this.currentID = p.tab_id; this.state(); } break;
      case "close-tab": {
        const target = this.pages.get(p.tab_id); if (!target) break;
        target.browser.removeProgressListener(target.listener); target.browser.remove(); this.pages.delete(target.id);
        if (this.currentID === target.id) this.currentID = [...this.pages.keys()].at(-1) || "";
        if (!this.current) this.create(); else this.state(); break;
      }
      case "back": if (page?.browser.canGoBack) page.browser.goBack(); break;
      case "forward": if (page?.browser.canGoForward) page.browser.goForward(); break;
      case "reload": if (page && !page.home) page.browser.reload(); break;
      case "stop": page?.browser.stop(); break;
      case "focus": page?.browser.focus(); break;
      case "external": if (page?.url) Zotero.launchURL(this.url(page.url)); break;
      case "find": if (page && !page.home) this.emit({event:"find-result",found:await this.actor().sendQuery("find",p)}); break;
      case "editor": {
        const result = await this.form(p.kind === "folder" ? "Bookmark Folder" : "Bookmark",[
          {name:"title",label:"Name",value:p.title}, ...(p.kind === "folder" ? [] : [{name:"url",label:"Website",value:p.url}]),
          {name:"parent_id",label:"Folder",value:String(p.parent_id||0),options:[{value:0,label:"Bookmarks"},...p.folders.map(f=>({value:f.id,label:f.title||f.name||f.path||"Bookmarks"}))]},
        ]);
        this.emit({event:"editor-result",cancelled:!result,...result}); break;
      }
      case "confirm": {
        const fields=p.history?[{name:"message",label:"Time range",value:"all",options:[{value:"hour",label:"Last hour"},{value:"day",label:"Today"},{value:"all",label:"All history"}]}]:[];
        const result = await this.form(p.title,fields,p.button,p.message);
        this.emit({event:"confirm-result",confirmed:!!result,range:result?.message||"all"}); break;
      }
      case "capture": await this.capturePage(p); break;
      case "capture-download": await this.capturePDF(p); break;
      case "capture-cancel": if (this.capture?.snapshot_id === p.snapshot_id) this.capture = null; break;
      case "import-bookmarks": {
        const file = await this.picker("modeOpen","Import HTML Bookmarks"); if (!file) break;
        const bytes = await IOUtils.read(file,{maxBytes:10*1024*1024+1});
        if (bytes.length>10*1024*1024) throw new Error("Choose a bookmark export up to 10 MB.");
        this.emit({event:"bookmark-import",content_base64:this.base64(bytes)}); break;
      }
      case "export-bookmarks": {
        const file = await this.picker("modeSave","Export Bookmarks","Gewu Bookmarks.html");
        if (file) await IOUtils.writeUTF8(file,String(p.html||"")); break;
      }
      case "read-bookmark-source": await this.bookmarkSource(p.source); break;
      case "choose-bookmark-source-folder": {
        const result = await this.form("Choose Bookmark Folder",[{name:"folder_id",label:"Source folder",value:"",options:p.folders.map(f=>({value:f.id,label:f.path||f.title}))}]);
        this.emit(result ? {event:"bookmark-source-folder",folder_id:result.folder_id} : {event:"bookmark-source-cancel"}); break;
      }
      case "share": {
        const result = await this.form("Page Actions",[{name:"action",label:"Choose an action",value:"copy",options:[{value:"copy",label:"Copy Link"},{value:"external",label:"Open in Default Browser"},{value:"download",label:"Save Download"}]}],"Continue");
        if (result?.action === "copy") Cc["@mozilla.org/widget/clipboardhelper;1"].getService(Ci.nsIClipboardHelper).copyString(page?.url||"");
        else if (result) await this.command({action:result.action}); break;
      }
      case "download": await this.download(); break;
      case "passwords": {
        if (!Zotero.isMac) throw new Error("Open your system password manager to copy a password.");
        const app = Zotero.File.pathToFile("/System/Applications/Passwords.app");
        if (!app.exists()) throw new Error("The system Passwords app is unavailable on this macOS version."); app.launch(); break;
      }
      case "suggestions": this.showSuggestions(p); break;
      case "favicon": break; // The shared UI already supplies a deterministic site icon.
      default: throw new Error("This Browser action is not available: " + String(p.action));
    }
    return true;
  }
  base64(bytes) { let s=""; for(let i=0;i<bytes.length;i+=8192) s+=String.fromCharCode(...bytes.subarray(i,i+8192)); return btoa(s); }
  async capturePage(p) {
    try {
      if (!this.current || this.current.home) throw new Error("Open an article or PDF first.");
      const page = this.current, snapshot = await this.actor(page).sendQuery("snapshot");
      snapshot.url = this.url(snapshot.url); snapshot.pdf_urls = snapshot.pdf_urls.map(u=>{try{return this.url(u);}catch(_){return "";}}).filter(Boolean);
      Object.assign(snapshot,{snapshot_id:Zotero.Utilities.randomString(32),tab_id:page.id,
        origin_paper_id:page.context.origin_paper_id||"",origin_library_item_id:page.context.origin_library_item_id||0});
      this.capture = snapshot; this.emit({event:"capture-metadata",request_id:p.request_id,snapshot});
    } catch(error) { this.emit({event:"capture-metadata",request_id:p.request_id,error:error.message}); }
  }
  async fetchBytes(value) {
    let url = this.url(value);
    for (let redirects=0;redirects<6;redirects++) {
      const response = await Zotero.HTTP.request("GET",url,{responseType:"arraybuffer",userContextId:this.cookies.id,
        followRedirects:false,timeout:60000,successCodes:[200,301,302,303,307,308]});
      if (response.status !== 200) { url=this.url(new URL(response.getResponseHeader("Location"),url).href); continue; }
      const bytes = new Uint8Array(response.response);
      if (!bytes.length || bytes.length>128*1024*1024) throw new Error("The download is empty or larger than 128 MB.");
      return bytes;
    }
    throw new Error("The download redirected too many times.");
  }
  async capturePDF(p) {
    try {
      if (!this.capture || p.snapshot_id !== this.capture.snapshot_id || !this.capture.pdf_urls.includes(p.url)) throw new Error("This PDF does not belong to the reviewed page. Start Save to Gewu again.");
      const bytes=await this.fetchBytes(p.url);
      if (String.fromCharCode(...bytes.subarray(0,5))!=="%PDF-") throw new Error("The website did not provide a PDF. Complete any required sign-in in Browser, or choose a local PDF.");
      const response=await Zotero.HTTP.request("POST",this.tab.origin+"/api/browser-capture-file",{
        headers:{"X-Gewu-Workspace":this.tab.token,"X-Gewu-Capture-Token":p.upload_token,"Content-Type":"application/pdf","X-Gewu-Filename":"article.pdf","X-Gewu-PDF-Source":encodeURIComponent(p.url)},
        body:bytes.buffer,responseType:"json",followRedirects:false,userContextId:this.tab.cookies.id,timeout:60000,successCodes:[200]});
      this.emit({event:"capture-pdf",token:p.token,...response.response});
    } catch(error) { this.emit({event:"capture-pdf",token:p.token,error:error.message}); }
  }
  async download() {
    if (!this.current?.url) return;
    const url=this.url(this.current.url), name=decodeURIComponent(new URL(url).pathname.split("/").pop()||"download");
    const file=await this.picker("modeSave","Save Download",name); if (!file) return;
    const bytes=await this.fetchBytes(url); await IOUtils.write(file,bytes);
    this.emit({event:"download",message:"Download saved."});
  }
  async bookmarkSource(source) {
    const file=await this.picker("modeOpen",source==="safari" ? "Choose Safari Bookmarks.plist" : "Choose Chrome Bookmarks");
    if (!file) {this.emit({event:"bookmark-source-cancel"});return;}
    try {
      const bytes=await IOUtils.read(file,{maxBytes:10*1024*1024+1});
      if(bytes.length>10*1024*1024) throw new Error("Bookmark source exceeds 10 MB.");
      this.emit({event:"bookmark-source",source,source_id:file,content_base64:this.base64(bytes)});
    } catch(error) {this.emit({event:"bookmark-source-cancel",message:error.message});}
  }
  showSuggestions(p) {
    this.suggestions?.remove(); this.suggestions=null;
    if(!p.items?.length) return;
    const doc=this.tab.window.document, box=this.plugin.element(doc,"div","",{class:"gewu-suggestions"});
    box.style.cssText=`left:${Math.max(0,p.x)}px;top:${Math.max(0,p.y)}px;width:${Math.max(100,p.width)}px;max-width:100%`;
    for(const [index,item] of p.items.slice(0,8).entries()) {
      const button=this.plugin.element(doc,"button",item.title||item.url,{"aria-selected":String(index===p.selected)});
      button.onmousedown=event=>{event.preventDefault();this.emit({event:"address-suggestion",url:this.url(item.url)});box.remove();};
      box.append(button);
    }
    this.tab.surface.append(box);this.suggestions=box;
  }
};
