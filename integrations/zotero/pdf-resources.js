/* Read only the PDF renderer assets shipped with Zotero, never arbitrary URLs/files. */
var GewuPDFResources = {
  assetURL(kind, filename) {
    const folders = {cMapUrl:"cmaps", standardFontDataUrl:"standard_fonts", wasmUrl:"wasm"};
    if (!Object.hasOwn(folders, kind) || typeof filename !== "string"
        || !/^[A-Za-z0-9_-]+\.(?:bcmap|pfb|ttf|wasm)$/.test(filename)) {
      throw new Error("Unsupported PDF renderer asset.");
    }
    return `resource://zotero/reader/pdf/web/${folders[kind]}/${filename}`;
  },
  async engine() {
    if (!this.loading) {
      this.loading = Promise.all(["pdf.mjs", "pdf.worker.mjs"].map(async name => {
        const response = await Zotero.HTTP.request("GET", `resource://zotero/reader/pdf/build/${name}`, {responseType:"text"});
        return response.responseText;
      })).then(([module, worker]) => ({module, worker})).catch(error => {
        this.loading = null; throw error;
      });
    }
    return this.loading;
  },
  async asset({kind, filename}) {
    const response = await Zotero.HTTP.request("GET", this.assetURL(kind, filename), {responseType:"arraybuffer"});
    const bytes = new Uint8Array(response.response);
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 8192) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    }
    return btoa(binary);
  }
};
if (typeof module !== "undefined") module.exports = GewuPDFResources;
