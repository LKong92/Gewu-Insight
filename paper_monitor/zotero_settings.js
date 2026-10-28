/* Persistent installation guidance; native handoff waits for Zotero readiness. */
(() => {
  let panel;
  window.openZoteroSettings = async () => {
    if (panel) { panel.querySelector("button").focus(); return; }
    const previousFocus=document.activeElement;
    const backdrop=document.createElement("div");backdrop.className="settings-backdrop open";
    backdrop.innerHTML=`<style>
      .gewu-zotero-settings .settings-modal-body{padding-bottom:14px}
      .gewu-zotero-settings .gewu-status-row{display:flex;justify-content:space-between;gap:20px;padding:7px 0;font-size:13px}
      .gewu-zotero-settings .gewu-status-row span:last-child{color:var(--muted,#6b7280);text-align:right}
      .gewu-zotero-settings .citation-source-setting{display:grid;grid-template-columns:minmax(0,1fr) 148px;gap:18px;align-items:center}
      .gewu-zotero-settings .gewu-copy{min-width:0;overflow-wrap:break-word}
      .gewu-zotero-settings .gewu-copy p:last-child{margin-bottom:0}
      .gewu-zotero-settings button[data-action]{width:148px;min-height:30px;white-space:normal;text-align:center}
      .gewu-zotero-settings .gewu-guide-toggle{margin:12px 0 0;display:block;background:none;border:0;padding:0;color:#28619b;font:inherit;cursor:pointer}
      .gewu-zotero-settings .gewu-guide{margin-top:12px;padding:16px;border:1px solid #d9dce2;border-radius:10px;background:var(--card,#fff)}
      .gewu-zotero-settings [hidden]{display:none!important}
      .gewu-zotero-settings .gewu-step{display:grid;grid-template-columns:24px minmax(0,1fr);gap:10px;margin-bottom:16px}
      .gewu-zotero-settings .gewu-step:last-child{margin-bottom:0}
      .gewu-zotero-settings .gewu-step-number{width:23px;height:23px;border-radius:50%;background:#e8eff9;color:#285b8f;display:grid;place-items:center;font-size:12px;font-weight:600}
      .gewu-zotero-settings .gewu-step p{margin:5px 0 8px;font-size:12px;line-height:1.5;color:var(--muted,#6b7280)}
      .gewu-zotero-settings .gewu-install-diagram{display:flex;align-items:center;gap:8px;margin:8px 0;font-size:12px;color:#42516b}
      .gewu-zotero-settings .gewu-menu-sample{padding:5px 9px;border:1px solid #d9dce2;border-radius:5px;background:#f5f6f8}
      .gewu-zotero-settings .gewu-drop-target{border:1px dashed #7599ca;border-radius:6px;padding:9px 12px;background:#f5f8fd;color:#285b8f}
      .gewu-zotero-settings .gewu-file-name{display:block;font-size:12px;font-weight:600;margin:5px 0;overflow-wrap:anywhere}
      .gewu-zotero-settings .citation-settings-status{min-height:0;margin-top:10px;font-size:12px}
      .gewu-zotero-settings #gewuZoteroStatus:empty{display:none}
    </style><section class="settings-modal preferences-modal gewu-zotero-settings" role="dialog" aria-modal="true" aria-labelledby="gewuZoteroTitle" tabindex="-1">
      <div class="settings-modal-head">
        <div><h2 id="gewuZoteroTitle">Zotero Integration</h2><p>Use your Gewu workspace inside Zotero.</p></div>
        <button class="settings-modal-close" type="button" title="Close settings" aria-label="Close settings">×</button>
      </div>
      <div class="settings-modal-body">
        <div class="gewu-status-row"><strong>Zotero app</strong><span id="gewuZoteroApp">Checking…</span></div>
        <div class="gewu-status-row"><strong>Gewu plugin</strong><span id="gewuZoteroPlugin">Checking…</span></div>
        <div class="citation-source-setting" style="margin-top:10px">
          <div class="gewu-copy"><strong id="gewuActionTitle">Set up Gewu in Zotero</strong><p id="gewuActionDescription">Checking the installed plugin.</p></div>
          <button class="smallbtn primary" type="button" data-action="primary" disabled>Checking…</button>
        </div>
        <button class="gewu-guide-toggle" type="button" aria-expanded="false" aria-controls="gewuInstallGuide">Installation Guide</button>
        <div class="gewu-guide" id="gewuInstallGuide" hidden>
          <div class="gewu-step"><span class="gewu-step-number">1</span><div>
            <strong>Open Plugins Manager</strong><p>In Zotero’s top menu, choose <b>Tools → Plugins</b>.</p>
            <div class="gewu-install-diagram" role="img" aria-label="Zotero menu: Tools, then Plugins"><span class="gewu-menu-sample">Zotero</span><span class="gewu-menu-sample">Tools</span><span>→</span><span class="gewu-menu-sample">Plugins</span></div>
          </div></div>
          <div class="gewu-step"><span class="gewu-step-number">2</span><div>
            <strong>Drag the plugin into Plugins Manager</strong><p>Your file manager selects this file for you:</p><span class="gewu-file-name">Gewu Insight for Zotero.xpi</span>
            <div class="gewu-install-diagram" role="img" aria-label="Drag the XPI file into the Plugins Manager window"><span class="gewu-menu-sample">.xpi file</span><span>→</span><span class="gewu-drop-target">Plugins Manager</span></div>
            <p>Drop it inside the <b>Plugins Manager window</b>, not the Zotero literature list.</p>
            <button class="smallbtn" type="button" data-action="reveal">Show Plugin File</button>
          </div></div>
          <div class="gewu-step"><span class="gewu-step-number">3</span><div>
            <strong>Confirm installation and open Gewu</strong><p>Confirm if Zotero asks. When the status above says <b>Installed</b>, choose <b>Open in Zotero</b>. You can also use Zotero’s <b>Tools → Gewu Insight</b>.</p>
            <p>This guide stays available here whenever you need it.</p>
          </div></div>
        </div>
        <div class="citation-settings-status" id="gewuZoteroVersion"></div>
        <div class="citation-settings-status" id="gewuZoteroStatus" role="status" aria-live="polite"></div>
      </div>
    </section>`;
    panel=backdrop;document.body.append(backdrop);
    let info, busy=false, refreshBusy=false, waitingUpdate=false, updateDeadline=0, timer;
    const find=id=>backdrop.querySelector("#"+id), primary=backdrop.querySelector('[data-action="primary"]');
    const feedback=find("gewuZoteroStatus"), guide=find("gewuInstallGuide"), toggle=backdrop.querySelector(".gewu-guide-toggle");
    const showGuide=()=>{guide.hidden=false;toggle.setAttribute("aria-expanded","true");};
    toggle.onclick=()=>{guide.hidden=!guide.hidden;toggle.setAttribute("aria-expanded",String(!guide.hidden));};
    const close=()=>{clearInterval(timer);backdrop.remove();panel=null;previousFocus?.focus?.();};
    backdrop.querySelector(".settings-modal-close").onclick=close;
    backdrop.addEventListener("keydown",e=>{if(e.key==="Escape"){e.stopPropagation();close();}});
    const render=()=>{
      const plugin=info.plugin, installed=plugin.state==="installed";
      find("gewuZoteroApp").textContent=info.zotero_installed?"Detected":"Not found";
      find("gewuZoteroPlugin").textContent=installed?`Installed · ${plugin.version}`:plugin.state==="disabled"?"Installed, but disabled":plugin.state==="unknown"?"Could not verify":"Not installed";
      find("gewuZoteroVersion").textContent=`Included with this Gewu App: ${info.version}`;
      primary.textContent=installed?(info.update_available?"Update Plugin":"Open in Zotero"):plugin.state==="not_installed"?"Install in Zotero":"Installation Guide";
      primary.disabled=busy||waitingUpdate||!info.zotero_installed;
      find("gewuActionTitle").textContent=installed?(info.update_available?"A plugin update is available":"Continue in Zotero"):"Set up Gewu in Zotero";
      find("gewuActionDescription").textContent=installed?(info.update_available?"Install the version included with this Gewu App. No file dragging is needed.":"After Zotero opens your workspace, the Gewu App quits. Its background service keeps running."):(plugin.message|| (plugin.state==="disabled"?"Enable Gewu Insight in Zotero’s Tools → Plugins.":"Follow the three steps below. You only need to drag the file for the first installation."));
      if(waitingUpdate && installed && !info.update_available){waitingUpdate=false;feedback.textContent="Plugin updated. You can now open your workspace in Zotero.";}
      if(waitingUpdate && Date.now()>updateDeadline){waitingUpdate=false;feedback.textContent="The update has not been confirmed. Check Tools → Plugins in Zotero and try again.";}
      primary.disabled=busy||waitingUpdate||!info.zotero_installed;
    };
    const refresh=async()=>{
      if(refreshBusy || panel!==backdrop)return;
      refreshBusy=true;
      try{const r=await fetch("/api/integrations/zotero");const data=await r.json();if(!r.ok)throw new Error(data.error||"Could not check installation.");if(panel===backdrop){info=data;render();}}
      catch(error){feedback.textContent=error.message;}finally{refreshBusy=false;}
    };
    const act=async action=>{
      busy=true;primary.disabled=true;feedback.textContent=action==="open"?"Opening Zotero. Waiting for the Gewu workspace…":"Preparing…";
      try{
        const r=await fetch("/api/integrations/zotero",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})});
        const data=await r.json();if(!r.ok)throw new Error(data.error||"Setup failed.");
        if(action==="open"){
          const native=window.webkit?.messageHandlers?.zotero;
          if(native)native.postMessage({action:"handoff",request_id:data.request_id});
          else feedback.textContent="Request sent. Open the Gewu Insight tab in Zotero.";
        } else if(action==="update"){waitingUpdate=true;updateDeadline=Date.now()+30000;feedback.textContent="Updating the plugin in Zotero…";}
        else feedback.textContent="The plugin file is selected in your file manager. Drag it into Zotero’s Plugins Manager, as shown above.";
      }catch(error){feedback.textContent=error.message;}finally{busy=false;await refresh();}
    };
    primary.onclick=()=>{if(!info)return;if(info.plugin.state!=="installed"){showGuide();if(info.plugin.state==="not_installed")act("prepare");}else act(info.update_available?"update":"open");};
    backdrop.querySelector('[data-action="reveal"]').onclick=()=>act("prepare");
    window.gewuZoteroHandoffFailed=()=>{feedback.textContent="Zotero did not confirm that the workspace opened. Gewu is still running. Check the plugin in Zotero and try again.";};
    await refresh();if(panel===backdrop)timer=setInterval(refresh,2000);
    backdrop.querySelector(".settings-modal").focus({preventScroll:true});
  };
})();
