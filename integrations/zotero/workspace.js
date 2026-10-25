/* Authenticated workspace only. No Zotero object or credential is exposed. */
(() => {
  "use strict";
  if (window.GewuZoteroHost) return;
  const pending = new Map(); let sequence = 0;
  function request(channel, payload = {}) {
    const id = String(++sequence);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(new Error("The Zotero host did not respond.")); }, 60000);
      pending.set(id, {resolve, reject, timer});
      document.dispatchEvent(new CustomEvent("gewu-host-request", {detail:JSON.stringify({id, channel, payload})}));
    });
  }
  document.addEventListener("gewu-host-response", event => {
    const result = JSON.parse(event.detail), operation = pending.get(result.id);
    if (!operation) return;
    pending.delete(result.id); clearTimeout(operation.timer);
    if (result.error) operation.reject(new Error(result.error)); else operation.resolve(result.value);
  });
  const report = error => request("status", {message:String(error.message || error), error:true}).catch(() => {});
  window.GewuZoteroHost = Object.freeze({request});
  window.webkit = {messageHandlers:{browser:{postMessage:payload => request("browser", payload).catch(report)}}};
  document.addEventListener("gewu-host-command", event => {
    const {name, data} = JSON.parse(event.detail);
    Promise.resolve().then(() => {
      if (name === "browser-event") return window.GewuEmbedded.browserEvent(data);
      if (name === "website") return window.GewuEmbedded.openWebsite(data);
      return window.GewuEmbedded.command(name);
    }).catch(report);
  });
  const style = document.createElement("style");
  style.textContent = `
    #gewuHostMenuButton{position:fixed;top:7px;right:12px;z-index:78;width:30px;height:26px;border:0;border-radius:6px;background:transparent;color:#42516b;font-size:21px;line-height:20px;cursor:pointer}
    #gewuHostMenuButton:hover,#gewuHostMenuButton[aria-expanded=true]{background:#c2d4f2}
    .library-search-tools{right:54px!important}
    #primaryViewSwitcher{max-width:calc(100vw - 180px);overflow-x:auto;scrollbar-width:none}
    .library-detail .paper-detail-action-row{max-width:100%;flex-wrap:wrap}
    #gewuHostMenu{position:fixed;right:12px;top:42px;z-index:10000;width:260px;max-height:calc(100vh - 64px);overflow:auto;padding:8px;background:#fff;color:#263347;border:1px solid #d6dce6;border-radius:10px;box-shadow:0 6px 28px #0002;font:13px system-ui}
    #gewuHostMenu[hidden]{display:none!important}
    #gewuHostMenu summary{padding:9px 10px;cursor:pointer;font-weight:600;border-radius:5px}
    #gewuHostMenu button{display:block;text-align:left;width:100%;padding:8px 12px;border:0;border-radius:5px;background:transparent;color:inherit;font:inherit;cursor:pointer}
    #gewuHostMenu details button{padding-left:25px}
    #gewuHostMenu button:hover,#gewuHostMenu summary:hover{background:#edf3fc}
    #gewuHostMenu hr{border:0;border-top:1px solid #e4e8ef;margin:5px 4px}
  `;
  document.head.append(style);
  const menuButton=document.createElement("button");
  menuButton.id="gewuHostMenuButton";menuButton.type="button";menuButton.textContent="⋯";
  menuButton.title="Gewu menu";menuButton.setAttribute("aria-label","Gewu menu");
  menuButton.setAttribute("aria-expanded","false");menuButton.setAttribute("aria-controls","gewuHostMenu");
  const menu=document.createElement("div");menu.id="gewuHostMenu";menu.hidden=true;
  menu.setAttribute("role","dialog");menu.setAttribute("aria-label","Gewu menu");
  const closeMenu=()=>{menu.hidden=true;menuButton.setAttribute("aria-expanded","false");};
  const action=(parent,name,label)=>{
    const button=document.createElement("button");button.type="button";button.textContent=label;
    button.onclick=()=>{closeMenu();request("command",{name}).catch(report);};parent.append(button);
  };
  for(const [title,choices] of [
    ["View",[["list","List View"],["table","Table View"]]],
    ["Loader",[["loader","Open Loader"],["metadata","Refresh All Metadata"],["identifiers","Find Missing Identifiers"]]],
    ["Settings",[["name-title","Naming Rule: Title"],["name-citation","Naming Rule: Citation"],["naming","PDF Rename"],["preview","Quick Look"],["destination","Add to Library"],["websites","Website Links"],["ai","AI Access"],["arxiv","arXiv Scope"],["sources","Literature Data Source"],["fields","Fields"],["font","Font Size"],["cache","Clear Monitor Cache"]]],
    ["Help",[["guide","User Guide"],["database","Database Location"],["app","Open Gewu App"]]],
  ]){
    const group=document.createElement("details"),heading=document.createElement("summary");heading.textContent=title;group.append(heading);
    group.ontoggle=()=>{if(group.open)for(const other of menu.querySelectorAll("details"))if(other!==group)other.open=false;};
    for(const [name,label] of choices)action(group,name,label);menu.append(group);
  }
  menu.append(document.createElement("hr"));action(menu,"connection","Connection…");
  menuButton.onclick=()=>{menu.hidden=!menu.hidden;menuButton.setAttribute("aria-expanded",String(!menu.hidden));if(!menu.hidden)menu.querySelector("summary").focus();};
  document.addEventListener("pointerdown",event=>{if(!menu.hidden&&!menu.contains(event.target)&&event.target!==menuButton)closeMenu();});
  menu.onkeydown=event=>{if(event.key==="Escape"){event.stopPropagation();closeMenu();menuButton.focus();}};
  document.body.append(menuButton,menu);
  let previous = null, queued = false;
  const update = () => {
    queued = false;
    const selected = window.GewuEmbedded.selection();
    if (selected !== previous) { previous = selected; request("selection", {paperID:selected}).catch(report); }
    for(const actions of document.querySelectorAll(".library-detail > .paper-detail-actions")){
      if(actions.querySelector(".gewu-zotero-save-button"))continue;
      const button=document.createElement("button");button.type="button";button.className="action gewu-zotero-save-button";button.textContent="Save to Zotero";
      button.onclick=event=>{event.stopPropagation();request("save",{paperID:window.GewuEmbedded.selection()}).catch(report);};
      (actions.querySelector(".paper-detail-action-row")||actions).append(button);
    }
    for(const button of document.querySelectorAll('[title="Open in Safari"]')){button.title="Open in Default Browser";if(button.textContent.trim()==="Open in Safari")button.textContent="Open in Default Browser";}
    for (const row of document.querySelectorAll("article.paper[data-paper-id],article.author-paper-card[data-paper-id]")) {
      for (const button of row.querySelectorAll('[data-action="add-library"]')) {
        if (button.textContent.trim() === "Add to Library") { button.textContent="Save to Gewu"; button.title="Save to Gewu Library or Space"; }
      }
      if (row.querySelector(".gewu-zotero-save-button")) continue;
      const actions = row.querySelector(".actions,.author-paper-action-stack");
      if (!actions) continue;
      const compact = row.classList.contains("author-paper-card");
      const button = document.createElement("button"); button.type = "button";
      button.className = `${compact ? "author-paper-mini-button" : "action"} gewu-zotero-save-button`;
      button.textContent = compact ? "Z" : "Save to Zotero";
      button.title = "Save to Zotero"; button.setAttribute("aria-label", "Save to Zotero");
      button.onclick = event => { event.stopPropagation(); request("save", {paperID:row.dataset.paperId}).catch(report); };
      actions.append(button);
    }
  };
  const observer = new MutationObserver(() => {
    if (!queued) { queued = true; setTimeout(update, 60); }
  });
  observer.observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:["class", "aria-selected"]});
  window.addEventListener("pagehide", () => observer.disconnect(), {once:true});
  document.addEventListener("click", event => {
    const link = event.target.closest?.("a[href]");
    if (!link || !/^https?:/.test(link.href) || new URL(link.href).origin === location.origin) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (event.isTrusted) window.GewuEmbedded.openWebsite(link.href);
  }, true);
  update();
})();
