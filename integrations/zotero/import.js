/* Read-only Zotero source adapter. Writes only new files in Gewu's export staging
 * directory. Never calls item.save/erase, attachment move/rename, or sync APIs. */
var GewuZoteroImport = {
  connection: null,
  stopped: false,
  connecting: false,
  ownedExports: new Map(),

  async connect(uri) {
    if (this.connecting) return;
    this.connecting = true;
    try {
      const home = Services.dirsvc.get("Home", Ci.nsIFile).path;
      const file = PathUtils.join(home, "Library", "Application Support", "Gewu Insight", "zotero-import-connection.json");
      const config = JSON.parse(await IOUtils.readUTF8(file));
      const url = new URL(uri.spec);
      if (url.searchParams.get("request") !== config.generation || !/^[a-f0-9]{48}$/.test(config.generation)
          || Date.now()/1000-config.requested_at>300 || Date.now()/1000<config.requested_at-5)
        throw new Error("Open Import from Zotero in Gewu and reconnect.");
      const token = (await IOUtils.readUTF8(PathUtils.join(config.workspace, "data", ".gewu-workspace-token"))).trim();
      if (!/^[a-f0-9]{64}$/.test(token)) throw new Error("The selected Gewu database is not available.");
      const connection = {...config, origin: GewuZoteroCore.origin(config.origin), token};
      const health = await Zotero.HTTP.request("GET", connection.origin+"/api/health", {
        headers:{"X-Gewu-Workspace":token}, responseType:"json", followRedirects:false, timeout:15000, successCodes:[200]
      });
      const selected = Zotero.File.pathToFile(PathUtils.join(config.workspace, "data", "paper_monitor.sqlite")); selected.normalize();
      if (PathUtils.normalize(health.response.database_path || "") !== selected.path)
        throw new Error("The running Gewu database differs from the selected destination.");
      await this.call(connection, "hello", {catalog: await this.catalog()});
      this.connection = connection;
      this.stopped = false;
      this.loop(connection).catch(error => {
        if (this.connection === connection) GewuMonitor.alert(Zotero.getMainWindow(), error.message);
      });
    } finally { this.connecting = false; }
  },

  async call(connection, action, data={}) {
    const response = await Zotero.HTTP.request("POST", connection.origin+"/api/zotero-import/host", {
      headers:{"X-Gewu-Workspace":connection.token,"Content-Type":"application/json"},
      body:JSON.stringify({id:connection.job_id, generation:connection.generation, action, ...data}),
      responseType:"json",followRedirects:false,timeout:600000,successCodes:[200,400,403,500],noCache:true
    });
    if (response.status !== 200) throw new Error(response.response?.error || "Gewu could not continue the migration.");
    return response.response;
  },

  async catalog() {
    let localID = GewuMonitor.pref("migrationSourceID");
    if (!localID) {
      localID = Services.uuid.generateUUID().toString().replace(/[{}]/g, "");
      GewuMonitor.setPref("migrationSourceID", localID); // Only our own identity preference.
    }
    const libraries = [];
    for (const library of Zotero.Libraries.getAll()) {
      if (!["user", "group"].includes(library.libraryType)) continue;
      const group = library.libraryType === "group" ? Zotero.Groups.getByLibraryID(library.libraryID) : null;
      const user = Zotero.Users.getCurrentUserID();
      const preference = group ? 'migrationGroupSource.'+group.id : 'migrationUserSource';
      let source = GewuMonitor.pref(preference);
      if (!source) {
        source = group ? `zotero:group:${group.id}` : user ? `zotero:user:${user}` : `zotero:local:${localID}`;
        GewuMonitor.setPref(preference, source);
      }
      const collections = Zotero.Collections.getByLibrary(library.libraryID, true).map(c => ({key:c.key,name:c.name,parent:c.parentKey || ""}));
      libraries.push({id:library.libraryID, source_id:source, name:library.name, type:library.libraryType, collections});
    }
    const protected_roots = [Zotero.DataDirectory.dir, Zotero.getStorageDirectory().path];
    const base = Zotero.Prefs.get("baseAttachmentPath");
    if (base) protected_roots.push(base);
    return {protocol:1,zotero_version:Zotero.version,libraries,protected_roots,
      notice:"Collections and available attachments are imported. Trash and saved-search rules are not imported. Tags, citation keys and original fields are retained in Zotero Metadata. External backup/tablet copies not registered in Zotero need separate review."};
  },

  path(attachment) {
    // Do not use getFilePathAsync(): it can repair old alias paths in Zotero's DB.
    if (!attachment.isFileAttachment()) return "";
    let path = attachment.attachmentPath;
    if (!path) return "";
    if (attachment.isStoredFileAttachment()) {
      if (!path.startsWith("storage:")) throw new Error("Invalid stored attachment path.");
      const filename = path.slice(8);
      if (!filename || /[\\/]/.test(filename) || filename.startsWith(".zotero")) throw new Error("Invalid stored attachment name.");
      return PathUtils.join(Zotero.Attachments.getStorageDirectory(attachment).path, filename);
    }
    if (path.startsWith("attachments:")) {
      const base = Zotero.Prefs.get("baseAttachmentPath");
      if (!base) throw new Error("Set Zotero's Linked Attachment Base Directory to locate this file.");
      return PathUtils.joinRelative(base, path.slice("attachments:".length));
    }
    if (path.startsWith("AAAA")) throw new Error("This legacy Mac alias needs to be relinked in Zotero before import.");
    return PathUtils.normalize(path);
  },

  async attachment(item, annotations=true) {
    const raw = item.toJSON();
    const result = {key:item.key,title:raw.title || "",url:raw.url || "",contentType:item.attachmentContentType,
                    filename:raw.filename || raw.title || "Attachment",stored:item.isStoredFileAttachment(),data:raw};
    if (item.isFileAttachment()) {
      try {
        result.path = this.path(item);
        if (!result.path) throw new Error("Attachment path is unavailable.");
        const info = await IOUtils.stat(result.path);
        if (info.type !== "regular") throw new Error("Attachment is not a regular file.");
        result.size = info.size; result.mtime = info.lastModified;
        result.filename = PathUtils.filename(result.path);
      } catch(error) { result.path = ""; result.missing = `${result.filename}: ${error.message} Download or locate the file in Zotero, then scan again.`; }
      if (annotations) {
        result.annotations = [];
        for (const annotation of item.getAnnotations()) {
          if (!annotation.deleted) result.annotations.push(await Zotero.Annotations.toJSON(annotation));
        }
      }
      // Legacy HTML snapshots may depend on sibling files. Preserve the bundle,
      // but do not traverse symlinks or include Zotero's internal cache files.
      if (result.path && result.stored && /(?:text\/html|application\/xhtml\+xml)/.test(result.contentType)) {
        result.snapshot_files = [];
        const root = Zotero.Attachments.getStorageDirectory(item).path;
        const walk = async (directory, prefix="") => {
          for (const path of await IOUtils.getChildren(directory)) {
            const filename = PathUtils.filename(path);
            if (filename.startsWith('.zotero')) continue;
            const info = await IOUtils.stat(path);
            if (info.type === 'directory') await walk(path, prefix+filename+'/');
            else if (info.type === 'regular') result.snapshot_files.push({path,relative:prefix+filename,size:info.size,mtime:info.lastModified});
          }
        };
        await walk(root);
        result.snapshot_files.sort((a,b)=>a.relative.localeCompare(b.relative));
      }
    }
    return result;
  },

  async note(item) {
    const data = item.toJSON();
    const images = [];
    for (const id of item.getAttachments()) {
      const image = await Zotero.Items.getAsync(id);
      if (image.isEmbeddedImageAttachment() && !image.deleted) images.push(await this.attachment(image, false));
    }
    return {key:item.key,title:item.getNoteTitle(),html:item.getNote(),data,images};
  },

  async record(item) {
    const entry = {data:item.toJSON(), attachments:[], notes:[], warnings:[]};
    if (item.isAttachment()) entry.attachments.push(await this.attachment(item));
    else if (item.isNote()) entry.notes.push(await this.note(item));
    else if (item.isRegularItem()) {
      for (const id of item.getAttachments()) {
        const attachment = await Zotero.Items.getAsync(id);
        if (!attachment.deleted) entry.attachments.push(await this.attachment(attachment));
      }
      for (const id of item.getNotes()) {
        const note = await Zotero.Items.getAsync(id);
        if (!note.deleted) entry.notes.push(await this.note(note));
      }
    }
    for (const note of entry.notes) for (const image of note.images) if (image.missing) entry.warnings.push(image.missing);
    return entry;
  },

  stable(value) {
    if (Array.isArray(value)) return value.map(x => this.stable(x));
    if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(k => [k,this.stable(value[k])]));
    return value;
  },

  async scan(connection, config) {
    const keys = new Set(config.collection_keys);
    const ids = await Zotero.Items.getAll(config.library_id, true, false, true);
    for (const id of ids) {
      if (this.stopped || this.connection !== connection) return;
      const item = await Zotero.Items.getAsync(id);
      if (item.deleted || item.isAnnotation?.()) continue;
      const data = item.toJSON();
      if (keys.size && !(data.collections || []).some(k => keys.has(k))) continue;
      const entry = await this.record(item);
      const response = await this.call(connection, "entries", {entries:[entry]});
      if (response.stop) return;
    }
    await this.call(connection, "scanned");
  },

  async exportRecord(command) {
    const item = await Zotero.Items.getByLibraryAndKeyAsync(command.config.library_id, command.entry.data.key);
    if (!item || item.deleted) throw new Error("This Zotero item was removed after preview. Scan again.");
    const fresh = await this.record(item);
    if (JSON.stringify(this.stable(fresh)) !== JSON.stringify(this.stable(command.entry)))
      throw new Error("This Zotero item, note or attachment changed after preview. Start a new scan to import its current contents.");
    const result = {attachments:[],warnings:[]};
    for (const file of fresh.attachments) {
      if (!file.path || file.contentType !== "application/pdf" || !(file.annotations || []).some(a => !a.isExternal)) continue;
      const attachment = await Zotero.Items.getByLibraryAndKeyAsync(command.config.library_id, file.key);
      const filename = file.filename.replace(/\.pdf$/i, "") + " — Zotero annotations.pdf";
      const path = PathUtils.join(command.export_dir, Services.uuid.generateUUID().toString().replace(/[{}]/g, "") + ".pdf");
      try {
        if (await IOUtils.exists(path)) throw new Error("Export destination already exists.");
        // Explicitly disable transfer: source annotation records must remain intact.
        await Zotero.PDFWorker.export(attachment.id, path, false, undefined, false);
        const info = await IOUtils.stat(path);
        this.ownedExports.set(path, {size:info.size,mtime:info.lastModified});
        result.attachments.push({key:file.key+":annotated",path,filename,size:info.size,mtime:info.lastModified,
                                 contentType:"application/pdf",annotated:true,annotation_count:file.annotations.length});
      } catch(error) { result.warnings.push(`${file.filename}: Could not export annotated PDF (${error.message}). Original PDF and annotation text are retained.`); }
    }
    return result;
  },

  async releaseExports(exports) {
    // Only newly generated export copies, never a Zotero attachment path.
    // Interrupted exports stay in Gewu's staging directory for recovery.
    for (const file of exports?.attachments || []) {
      const owned = this.ownedExports.get(file.path);
      if (!owned) continue;
      try {
        const info = await IOUtils.stat(file.path);
        if (info.type === 'regular' && info.size === owned.size && info.lastModified === owned.mtime)
          await IOUtils.remove(file.path);
      } catch (_) {}
      this.ownedExports.delete(file.path);
    }
  },

  async loop(connection) {
    let failures = 0;
    const heartbeat = setInterval(()=>{
      if(!this.stopped&&this.connection===connection)this.call(connection,'ping').catch(()=>{});
    },10000);
    try {
    while (!this.stopped && this.connection === connection) {
      let worked = false;
      try {
        const command = await this.call(connection, "next");
        worked = ['scan', 'export'].includes(command.command);
        failures = 0;
        if (command.state === "complete") { if(this.connection===connection)this.connection=null; return; }
        if (command.command === "scan") {
          try { await this.scan(connection, command.config); }
          catch(error) { await this.call(connection, "scan_error", {message:error.message}); }
        } else if (command.command === "export") {
          let exports;
          try {
            exports = await this.exportRecord(command);
            await this.call(connection, "apply", {key:command.entry.data.key, lease:command.lease, exports});
            await this.releaseExports(exports);
          } catch(error) {
            await this.call(connection, "item_error", {key:command.entry.data.key, lease:command.lease, message:error.message});
          }
        }
      } catch(error) {
        if (++failures > 5) throw error;
      }
      await Zotero.Promise.delay(failures ? 5000 : worked ? 0 : 1000);
    }
    } finally { clearInterval(heartbeat); }
  },

  shutdown() { this.stopped = true; this.connection = null; }
};

if (typeof module !== "undefined") module.exports = GewuZoteroImport;
