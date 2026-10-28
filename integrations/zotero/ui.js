/* Plugin-owned surfaces mirror Gewu's macOS utility windows. Scoped to this host. */
var GewuZoteroUI = {
  css: `
    .gewu-zotero-host {position:relative;display:flex;flex:1;min-height:0;height:100%;background:#fff;color:#1d2433;font:12px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
    .gewu-zotero-host [hidden] {display:none!important;}
    .gewu-zotero-host button,.gewu-zotero-host select,.gewu-zotero-host input {box-sizing:border-box;margin:0;font-family:inherit;letter-spacing:normal;}
    .gewu-zotero-host button {appearance:none;min-width:0;min-height:28px;padding:4px 12px;border:1px solid rgba(60,60,67,.2);border-radius:6px;background:#f7f7f8;color:#2c2c2e;box-shadow:0 1px 1px #0000000a;font-size:10.5px;font-weight:600;line-height:18px;text-align:center;cursor:pointer;}
    .gewu-zotero-host button:hover {background:#e4e4e6;}
    .gewu-zotero-host button:disabled {opacity:.5;cursor:default;}
    .gewu-zotero-host .gewu-save {background:#0a72d8;color:#fff;border-color:#0a72d8;}
    .gewu-zotero-host .gewu-save:hover {background:#0868c6;}
    .gewu-zotero-host :is(button,input,select,summary):focus-visible {outline:2px solid #0a72d8;outline-offset:2px;}
    .gewu-zotero-host input[type=text],.gewu-zotero-host select {width:100%;min-width:0;min-height:28px;padding:4px 8px;border:1px solid rgba(60,60,67,.24);border-radius:6px;background:#fff;color:#1d1d1f;font-size:11px;line-height:18px;box-shadow:0 1px 1px #00000009;}
    .gewu-zotero-host select {appearance:none;padding-right:27px;background-image:linear-gradient(45deg,transparent 50%,#77777d 50%),linear-gradient(135deg,#77777d 50%,transparent 50%);background-position:calc(100% - 12px) 50%,calc(100% - 8px) 50%;background-size:4px 4px;background-repeat:no-repeat;}
    .gewu-zotero-host input[type=checkbox] {appearance:auto;flex:none;width:13px;height:13px;min-height:0;margin-top:2px;accent-color:#0a72d8;}
    .gewu-zotero-host .gewu-zotero-modal {position:absolute;inset:0;z-index:10;display:grid;place-items:center;padding:22px;background:rgba(45,48,54,.18);backdrop-filter:blur(2px);}
    .gewu-zotero-host .gewu-zotero-panel {box-sizing:border-box;display:flex;flex-direction:column;width:480px;max-width:100%;max-height:100%;min-height:0;overflow:hidden;border:1px solid rgba(60,60,67,.22);border-radius:12px;background:#ececee;box-shadow:0 20px 52px #0003,0 1px 1px #0000001a;outline:none;}
    .gewu-zotero-host .gewu-dialog-head {position:relative;flex:none;box-sizing:border-box;min-height:46px;padding:10px 42px 9px;border-bottom:1px solid rgba(60,60,67,.18);background:#f6f6f7;text-align:center;}
    .gewu-zotero-host .gewu-dialog-head h2 {margin:0;font-size:14px;font-weight:700;line-height:1.2;letter-spacing:-.006em;}
    .gewu-zotero-host .gewu-dialog-head p {margin:3px 0 0;color:#6e6e73;font-size:10.5px;line-height:1.32;}
    .gewu-zotero-host button.gewu-dialog-close {position:absolute;left:14px;top:50%;transform:translateY(-50%);width:13px;min-width:13px;height:13px;min-height:13px;padding:0;border:1px solid #0000001f;border-radius:50%;background:#ff5f57;color:transparent;font-size:0;line-height:1;box-shadow:none;}
    .gewu-zotero-host button.gewu-dialog-close::after {content:"×";position:absolute;inset:-1px 0 0;display:grid;place-items:center;color:transparent;font-size:9px;}
    .gewu-zotero-host button.gewu-dialog-close:hover::after {color:#520000b8;}
    .gewu-zotero-host .gewu-dialog-body {min-height:0;overflow:auto;padding:12px 14px 14px;}
    .gewu-zotero-host .gewu-group {overflow:hidden;border-radius:8px;background:rgba(255,255,255,.82);}
    .gewu-zotero-host .gewu-group + .gewu-group {margin-top:10px;}
    .gewu-zotero-host .gewu-row {padding:11px 12px;}
    .gewu-zotero-host .gewu-row + .gewu-row {border-top:1px solid rgba(60,60,67,.13);}
    .gewu-zotero-host .gewu-field {display:grid;grid-template-columns:92px minmax(0,1fr);align-items:center;gap:12px;margin:0;color:#1d1d1f;font-size:11.5px;font-weight:600;}
    .gewu-zotero-host .gewu-field input,.gewu-zotero-host .gewu-field select {font-weight:400;}
    .gewu-zotero-host .gewu-check {display:flex;align-items:flex-start;gap:9px;font-size:11.5px;line-height:1.45;cursor:pointer;}
    .gewu-zotero-host .gewu-check span {min-width:0;}
    .gewu-zotero-host .gewu-hint {display:block;margin:4px 0 0;color:#6e6e73;font-size:10.5px;font-weight:400;line-height:1.4;overflow-wrap:anywhere;}
    .gewu-zotero-host .gewu-database-row {display:grid;grid-template-columns:minmax(0,1fr) 128px;gap:16px;align-items:center;}
    .gewu-zotero-host .gewu-database-row > div {min-width:0;}
    .gewu-zotero-host .gewu-database-row strong {font-size:11.5px;font-weight:650;}
    .gewu-zotero-host .gewu-zotero-folder {margin:4px 0 0;color:#6e6e73;font-size:10.5px;line-height:1.4;overflow-wrap:anywhere;user-select:text;}
    .gewu-zotero-host .gewu-connection-state {display:flex;align-items:center;gap:6px;margin:0 0 10px;color:#6e6e73;font-size:10.5px;}
    .gewu-zotero-host .gewu-connection-state::before {content:"";width:6px;height:6px;border-radius:50%;background:#b58a34;}
    .gewu-zotero-host .gewu-connection-state[data-connected=true]::before {background:#328452;}
    .gewu-zotero-host .gewu-advanced {margin-top:12px;}
    .gewu-zotero-host .gewu-advanced summary {width:fit-content;padding:3px 0;color:#525763;font-size:11px;font-weight:600;cursor:pointer;}
    .gewu-zotero-host .gewu-advanced > .gewu-group {margin-top:8px;}
    .gewu-zotero-host .gewu-buttons {display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;margin-top:14px;}
    .gewu-zotero-host .gewu-buttons button {width:128px;max-width:100%;}
    .gewu-zotero-host .gewu-confirm-message {margin:0;font-size:12px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere;}
    .gewu-zotero-host .gewu-status {position:absolute;right:16px;bottom:40px;z-index:20;box-sizing:border-box;width:max-content;max-width:min(420px,calc(100% - 32px));display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;padding:12px 12px 12px 14px;border:1px solid rgba(60,60,67,.18);border-radius:10px;background:#f6f6f7;box-shadow:0 6px 24px #0002;}
    .gewu-zotero-host .gewu-status-copy {min-width:0;overflow-wrap:anywhere;}
    .gewu-zotero-host .gewu-status-title {display:block;font-size:11.5px;line-height:1.4;font-weight:650;}
    .gewu-zotero-host .gewu-status .gewu-hint {margin-top:3px;}
    .gewu-zotero-host .gewu-status[data-error=true] .gewu-status-title {color:#a13830;}
    .gewu-zotero-host .gewu-status-action {margin-top:8px;min-width:112px;}
    .gewu-zotero-host button.gewu-status-dismiss {width:22px;min-height:22px;height:22px;padding:0;border:0;background:transparent;box-shadow:none;color:#77777d;font-size:16px;font-weight:400;line-height:22px;}
    .gewu-zotero-host button.gewu-status-dismiss:hover {background:#e4e4e6;}
    .gewu-zotero-host .gewu-suggestions {position:absolute;box-sizing:border-box;padding:4px;background:#f6f6f7;border:1px solid rgba(60,60,67,.22);border-radius:8px;z-index:6;box-shadow:0 8px 24px #0002;}
    .gewu-zotero-host .gewu-suggestions button {display:block;width:100%;padding:6px 9px;border:0;background:transparent;box-shadow:none;text-align:left;font-size:11px;font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .gewu-zotero-host .gewu-suggestions button:hover,.gewu-zotero-host .gewu-suggestions button[aria-selected=true] {background:#dbe7f8;color:#1d4c7d;}
    @media(max-width:460px){.gewu-zotero-host .gewu-field{grid-template-columns:1fr;gap:6px}.gewu-zotero-host .gewu-database-row{grid-template-columns:1fr}.gewu-zotero-host .gewu-database-row button{width:128px;justify-self:end}}
  `,

  dialog(make, parent, title, subtitle, onClose, form = false) {
    const overlay=make("div","",{class:"gewu-zotero-modal",hidden:"true"});
    const panel=make(form?"form":"section","",{class:"gewu-zotero-panel",role:"dialog","aria-modal":"true","aria-label":title,tabindex:"-1"});
    const head=make("header","",{class:"gewu-dialog-head"}), close=make("button","Close",{type:"button",class:"gewu-dialog-close","aria-label":"Close "+title});
    close.onclick=onClose; head.append(close,make("h2",title));
    if(subtitle)head.append(make("p",subtitle));
    const body=make("div","",{class:"gewu-dialog-body"});
    panel.append(head,body);overlay.append(panel);parent.append(overlay);
    overlay.addEventListener("keydown",event=>{
      if(event.key==="Escape"){event.preventDefault();event.stopPropagation();onClose();}
      if(event.key!=="Tab")return;
      const controls=[...panel.querySelectorAll('button,input,select,summary,[tabindex="0"]')].filter(el=>!el.disabled&&!el.hidden&&el.getClientRects().length);
      const first=controls[0],last=controls.at(-1),active=panel.ownerDocument.activeElement;
      if(!first){event.preventDefault();panel.focus();}
      else if(event.shiftKey&&(active===first||active===panel)){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&active===last){event.preventDefault();first.focus();}
    });
    return {overlay,panel,body,close};
  }
};
