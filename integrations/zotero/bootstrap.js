var GewuMonitor;
var GewuZoteroCore;
var GewuBrowserHost;
var GewuWorkspaceSource;
var GewuPDFResources;
var GewuZoteroUI;

async function startup({ id, version, rootURI }) {
  await Zotero.initializationPromise;
  Services.scriptloader.loadSubScript(rootURI + "workspace-source.js", this);
  Services.scriptloader.loadSubScript(rootURI + "core.js", this);
  Services.scriptloader.loadSubScript(rootURI + "ui.js", this);
  Services.scriptloader.loadSubScript(rootURI + "browser.js", this);
  Services.scriptloader.loadSubScript(rootURI + "pdf-resources.js", this);
  Services.scriptloader.loadSubScript(rootURI + "monitor.js", this);
  GewuMonitor.init({ id, version, rootURI, workspaceScript:GewuWorkspaceSource });
  Zotero.GewuMonitor = GewuMonitor;
  GewuMonitor.registerProtocol();
  Services.io.getProtocolHandler("resource").QueryInterface(Ci.nsIResProtocolHandler)
    .setSubstitution("gewu-monitor", Services.io.newURI(rootURI));
  ChromeUtils.registerWindowActor("GewuMonitor", {
    parent: { esModuleURI: "resource://gewu-monitor/actor-parent.mjs?v=" + version },
    child: { esModuleURI: "resource://gewu-monitor/actor-child.mjs?v=" + version, events: { DOMContentLoaded: {} } },
    allFrames: false,
    matches: ["http://127.0.0.1/*", "http://localhost/*", "http://[::1]/*"]
  });
  ChromeUtils.registerWindowActor("GewuWeb", {
    parent:{esModuleURI:"resource://gewu-monitor/web-parent.mjs?v="+version},
    child:{esModuleURI:"resource://gewu-monitor/web-child.mjs?v="+version,events:{DOMContentLoaded:{},click:{capture:true}}},
    allFrames:false,matches:["https://*/*","http://*/*"]
  });
  for (const window of Zotero.getMainWindows()) GewuMonitor.addToWindow(window);
}

function onMainWindowLoad({ window }) {
  GewuMonitor?.addToWindow(window);
}

function onMainWindowUnload({ window }) {
  GewuMonitor?.removeFromWindow(window);
}

function shutdown() {
  if (!GewuMonitor) return;
  GewuMonitor.unregisterProtocol();
  for (const window of Zotero.getMainWindows()) GewuMonitor.removeFromWindow(window);
  if (Zotero.GewuMonitor === GewuMonitor) delete Zotero.GewuMonitor;
  ChromeUtils.unregisterWindowActor("GewuMonitor");
  ChromeUtils.unregisterWindowActor("GewuWeb");
  Services.io.getProtocolHandler("resource").QueryInterface(Ci.nsIResProtocolHandler)
    .setSubstitution("gewu-monitor", null);
  GewuMonitor = undefined;
}

function install() {}
function uninstall() {}
