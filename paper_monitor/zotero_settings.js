/* Shared integration settings are available from the App menu and embedded workspace. */
(() => {
  let panel;
  window.openZoteroSettings = async () => {
    if (panel) { panel.querySelector("button").focus(); return; }
    const previousFocus=document.activeElement;
    const backdrop = document.createElement("div"); backdrop.className="settings-backdrop open";
    backdrop.innerHTML=`<style>
      .gewu-zotero-settings .settings-modal-body{padding-bottom:10px}
      .gewu-zotero-settings .citation-source-setting{display:grid;grid-template-columns:minmax(0,1fr) 148px;column-gap:18px;align-items:center}
      .gewu-zotero-settings .gewu-zotero-copy{min-width:0;overflow-wrap:break-word}
      .gewu-zotero-settings .citation-source-setting-head{margin-bottom:5px}
      .gewu-zotero-settings .citation-source-setting p:last-child{margin-bottom:0}
      .gewu-zotero-settings button[data-action]{width:100%;min-width:0;text-align:center;white-space:normal}
      .gewu-zotero-settings .citation-settings-status{min-height:0;margin-top:8px}
      .gewu-zotero-settings #gewuZoteroStatus:empty{display:none}
      @media(max-width:480px){.gewu-zotero-settings .citation-source-setting{grid-template-columns:minmax(0,1fr) 132px;column-gap:12px}}
    </style><section class="settings-modal preferences-modal gewu-zotero-settings" role="dialog" aria-modal="true" aria-labelledby="gewuZoteroTitle" aria-describedby="gewuZoteroDescription" tabindex="-1">
      <div class="settings-modal-head">
        <div><h2 id="gewuZoteroTitle">Zotero Integration</h2><p id="gewuZoteroDescription">Use the same Gewu Library, Paper Files, monitors and settings inside Zotero.</p></div>
        <button class="settings-modal-close" type="button" title="Close settings" aria-label="Close settings">×</button>
      </div>
      <div class="settings-modal-body">
        <div class="gewu-zotero-options">
        <div class="citation-source-setting">
          <div class="gewu-zotero-copy">
            <div class="citation-source-setting-head"><strong>Open Your Workspace</strong></div>
            <p>For everyday use after installing the plugin. Opens the current Gewu database in Zotero.</p>
            <p>Gewu can start in the background when you open its Zotero tab.</p>
          </div>
          <button class="smallbtn primary" type="button" data-action="open">Open in Zotero</button>
        </div>
        <div class="citation-source-setting">
          <div class="gewu-zotero-copy">
            <div class="citation-source-setting-head"><strong>First-Time Installation</strong></div>
            <p>Reveals the bundled plugin. In Zotero, open Tools → Plugins, then drag the highlighted file into that window.</p>
          </div>
          <button class="smallbtn" type="button" data-action="prepare">Install in Zotero</button>
        </div>
        <div class="citation-source-setting">
          <div class="gewu-zotero-copy">
            <div class="citation-source-setting-head"><strong>Update the Plugin</strong></div>
            <p>After updating Gewu Insight, install its bundled plugin over the existing version. Saved papers and settings are kept.</p>
          </div>
          <button class="smallbtn" type="button" data-action="update">Update Installed Plugin</button>
        </div>
        </div>
        <div class="citation-settings-status" id="gewuZoteroVersion">Checking the bundled plugin…</div>
        <div class="citation-settings-status" id="gewuZoteroStatus" role="status" aria-live="polite"></div>
      </div>
    </section>`;
    panel=backdrop;document.body.append(backdrop);
    const close=()=>{backdrop.remove();panel=null;previousFocus?.focus?.();};backdrop.querySelector("button").onclick=close;
    backdrop.addEventListener("keydown",e=>{if(e.key==="Escape"){e.stopPropagation();close();}});
    const status=backdrop.querySelector("#gewuZoteroStatus");
    try {
      const response=await fetch("/api/integrations/zotero"), data=await response.json();
      if(!response.ok)throw new Error(data.error||"Could not read plugin information.");
      backdrop.querySelector("#gewuZoteroVersion").textContent=`Bundled plugin: ${data.version} · ${data.zotero_installed ? "Zotero app detected" : "Install the Zotero app first"}`;
    } catch(error){status.textContent=error.message;status.classList.add("err");}
    backdrop.querySelectorAll("button[data-action]").forEach(button=>button.onclick=async()=>{
      button.disabled=true;status.className="citation-settings-status";status.textContent="Preparing…";
      try {
        const response=await fetch("/api/integrations/zotero",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:button.dataset.action})});
        const data=await response.json();if(!response.ok)throw new Error(data.error||"Setup failed.");status.textContent=data.message;
      }catch(error){status.textContent=error.message;status.classList.add("err");}finally{button.disabled=false;}
    });
    backdrop.querySelector(".settings-modal").focus({preventScroll:true});
  };
})();
