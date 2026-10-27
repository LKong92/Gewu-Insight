/* Opt-in migration window. Existing Loader, Library and settings remain intact. */
(() => {
  let panel;
  window.openZoteroImport = async () => {
    if (panel) { panel.querySelector('section').focus(); return; }
    const previous = document.activeElement;
    const backdrop = document.createElement('div'); backdrop.className='settings-backdrop open'; panel=backdrop;
    backdrop.innerHTML=`<style>
      .zotero-import-window{width:640px;max-width:calc(100vw - 40px)}
      .zotero-import-window [hidden]{display:none!important}
      .zotero-import-window .settings-modal-body{padding:14px 16px;max-height:70vh;overflow:auto}
      .zotero-import-window .zi-group{border-radius:9px;background:var(--card,#fff);overflow:hidden;margin-bottom:12px}
      .zotero-import-window .zi-row{display:grid;grid-template-columns:118px minmax(0,1fr);align-items:center;gap:14px;padding:11px 12px;font-size:12px}
      .zotero-import-window .zi-row+.zi-row{border-top:1px solid #8882}
      .zotero-import-window .zi-row label{font-weight:600}
      .zotero-import-window select,.zotero-import-window input[type=text]{box-sizing:border-box;width:100%;min-width:0;padding:5px 8px;border:1px solid #8884;border-radius:6px;background:var(--card,#fff);color:var(--ink);font:inherit}
      .zotero-import-window .zi-check{display:flex;gap:7px;align-items:flex-start;padding:4px 0;font-size:12px;font-weight:400}
      .zotero-import-window .zi-collections{max-height:150px;overflow:auto;margin-top:5px}
      .zotero-import-window .zi-hint{font-size:12px;line-height:1.5;color:var(--muted,#6b7280);margin:5px 0 10px;overflow-wrap:anywhere}
      .zotero-import-window .zi-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:13px 12px;font-size:11px;color:var(--muted,#6b7280)}
      .zotero-import-window .zi-stats strong{display:block;font-size:18px;color:var(--ink);font-variant-numeric:tabular-nums;margin-bottom:3px}
      .zotero-import-window .zi-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap;margin-top:12px}
      .zotero-import-window .zi-actions button{width:148px;min-height:30px;white-space:normal;text-align:center}
      .zotero-import-window progress{width:100%;height:7px;accent-color:#0a72d8}
      .zotero-import-window .zi-issues{max-height:170px;overflow:auto;padding:0 12px;font-size:12px}
      .zotero-import-window .zi-issues p{margin:10px 0;overflow-wrap:anywhere}
      .zotero-import-window .zi-issues strong{display:block;margin-bottom:3px;color:var(--ink)}
      .zotero-import-window .zi-state{font-size:12px;line-height:1.5;white-space:pre-wrap;margin:8px 0 0;overflow-wrap:anywhere}
      .zotero-import-window .zi-state[data-error=true]{color:#a13830}
      .zotero-import-window .zi-link{border:0;background:none;color:#28619b;font:inherit;padding:0;cursor:pointer;font-size:12px}
      @media(max-width:520px){.zotero-import-window .zi-row{grid-template-columns:1fr;gap:5px}}
    </style><section class="settings-modal preferences-modal zotero-import-window" role="dialog" aria-modal="true" aria-labelledby="zi-title" tabindex="-1">
      <div class="settings-modal-head"><div><h2 id="zi-title">Import from Zotero</h2><p>Bring your Zotero library into this Gewu database.</p></div><button class="settings-modal-close" type="button" aria-label="Close import window">×</button></div>
      <div class="settings-modal-body">
        <p class="zi-hint">Files are copied and verified. Your Zotero library, original attachments and annotations stay unchanged.</p>
        <div class="zi-group"><div class="zi-row"><label for="zi-history">Import session</label><select id="zi-history"><option value="">New import</option></select></div></div>
        <div id="zi-config" class="zi-group" hidden>
          <div class="zi-row"><label for="zi-source">Zotero library</label><select id="zi-source"></select></div>
          <div class="zi-row"><label>Collections</label><div><label class="zi-check"><input id="zi-all" type="checkbox" checked>All collections and unfiled items</label><div id="zi-collections" class="zi-collections" hidden></div></div></div>
          <div class="zi-row"><label for="zi-target">Gewu destination</label><select id="zi-target"></select></div>
          <div class="zi-row"><label for="zi-name">Import folder</label><input type="text" id="zi-name" value="Zotero Library" maxlength="150"></div>
        </div>
        <div id="zi-summary" class="zi-group" hidden><div class="zi-row"><strong id="zi-summary-context" style="grid-column:1/-1;font-weight:400;line-height:1.5;white-space:pre-line;overflow-wrap:anywhere"></strong></div><div class="zi-stats"><div><strong id="zi-papers">0</strong>Items</div><div><strong id="zi-files">0</strong>Available attachments</div><div><strong id="zi-size">0 MB</strong>Original file size</div></div></div>
        <details id="zi-scope" class="zi-hint" hidden><summary>What's included</summary><p>Collection folders, metadata, available attachments, notes and PDF annotations. Tags and citation keys are kept in Zotero Metadata. Annotated PDFs and notes may require extra disk space.</p><p id="zi-notice" hidden></p></details>
        <progress id="zi-progress" max="1" value="0" hidden></progress>
        <div id="zi-problems" class="zi-group" hidden><div class="zi-row"><strong id="zi-issue-title">Items to review</strong></div><div id="zi-issues" class="zi-issues"></div></div>
        <p id="zi-state" class="zi-state" role="status" aria-live="polite">Connect Zotero to choose a library and preview the import. Requires Gewu’s Zotero plugin 0.4 or later.</p>
        <div class="zi-actions"><button id="zi-reconnect" class="smallbtn" type="button" hidden>Reconnect Zotero</button><button id="zi-pause" class="smallbtn" type="button" hidden>Pause Import</button><button id="zi-primary" class="smallbtn primary" type="button">Connect Zotero</button></div>
        <p class="zi-hint" id="zi-setup"><button class="zi-link" type="button">Plugin installation and update</button></p>
      </div></section>`;
    document.body.append(backdrop);
    const el=id=>backdrop.querySelector('#zi-'+id), state=el('state'), primary=el('primary');
    let job=null, busy=false, fetching=false, timer, closed=false, catalogID='', destinations=[];
    const running=()=>['running','scanning','scan_requested'].includes(job?.state);
    const refresh=()=>{window.signalLibraryRefresh?.('zotero-import');window.refreshMainLibrarySnapshot?.('zotero-import')?.catch(()=>{});};
    const text=(message,error=false)=>{state.textContent=message;state.dataset.error=String(error);};
    const request=async(action,extra={})=>{
      const response=await fetch('/api/zotero-import'+(action?'':job?'?id='+encodeURIComponent(job.id):''),action?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,id:job?.id,...extra})}:{});
      const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not continue the import.');return data;
    };
    const addOption=(select,value,label)=>{const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);};
    const collections=()=>{
      const library=job?.catalog?.libraries?.find(x=>x.source_id===el('source').value);
      el('collections').replaceChildren();
      const list=library?.collections||[], byKey=new Map(list.map(c=>[c.key,c]));
      for(const c of list){
        const label=document.createElement('label');label.className='zi-check';const box=document.createElement('input');box.type='checkbox';box.value=c.key;
        const names=[c.name],seen=new Set([c.key]);let parent=c.parent;
        while(byKey.has(parent)&&!seen.has(parent)){seen.add(parent);names.unshift(byKey.get(parent).name);parent=byKey.get(parent).parent;}
        label.append(box,document.createTextNode(names.join(' / ')));el('collections').append(label);
      }
      if(library)el('name').value='Zotero — '+library.name;
    };
    el('source').onchange=collections;
    el('all').onchange=()=>{el('collections').hidden=el('all').checked;};
    const render=()=>{
      if(closed)return;
      const s=job?.state||'', editable=['connected','scan_failed'].includes(s), active=['running','scanning','scan_requested'].includes(s);
      const historyOption=[...el('history').options].find(option=>option.value===job?.id);
      if(historyOption&&job.created)historyOption.textContent=new Date(job.created*1000).toLocaleString()+' · '+s.replaceAll('_',' ');
      el('config').hidden=!job?.catalog?.libraries?.length||['ready','running','paused','needs_attention','complete'].includes(s);
      if(job?.catalog?.libraries?.length&&catalogID!==job.id){
        catalogID=job.id;el('all').checked=true;el('collections').hidden=true;el('source').replaceChildren();for(const lib of job.catalog.libraries)addOption(el('source'),lib.source_id,lib.name);
        if(job.config?.source_id)el('source').value=job.config.source_id;
        collections();
        if(job.config?.root_name)el('name').value=job.config.root_name;
        el('target').value=String(job.config?.target_id||1);
        if(job.config?.collection_keys?.length){el('all').checked=false;el('collections').hidden=false;for(const box of el('collections').querySelectorAll('input'))box.checked=job.config.collection_keys.includes(box.value);}
      }
      for(const control of el('config').querySelectorAll('input,select'))control.disabled=busy||!editable;
      el('summary').hidden=!job||!['ready','running','paused','needs_attention','complete'].includes(s);
      el('scope').hidden=el('summary').hidden;
      const source=job?.catalog?.libraries?.find(x=>x.source_id===job.config?.source_id),target=destinations.find(d=>d.id===job?.config?.target_id);
      el('summary-context').textContent=(source?.name||'Zotero')+' · '+(job?.config?.collection_keys?.length?'Selected collections and subcollections':'All collections and unfiled items')+'\n'+(target?.title||'Library')+' / '+(job?.config?.root_name||'Zotero Library');
      el('papers').textContent=String(job?.total||0);el('files').textContent=String(job?.files||0);
      const bytes=job?.bytes||0;el('size').textContent=bytes>1024**3?(bytes/1024**3).toFixed(1)+' GB':(bytes/1024**2).toFixed(1)+' MB';
      el('notice').hidden=!job?.catalog?.notice;el('notice').textContent=job?.catalog?.notice||'';
      el('progress').hidden=!job?.total||el('summary').hidden||s==='ready';el('progress').max=job?.total||1;
      el('progress').value=(job?.counts?.done||0)+(job?.counts?.partial||0)+(job?.counts?.failed||0);
      el('problems').hidden=!job?.issues?.length;el('issue-title').textContent=`Items to review (${job?.issue_count||0})`;
      el('issues').replaceChildren();for(const issue of job?.issues||[]){const p=document.createElement('p'),title=document.createElement('strong');title.textContent=issue.title;p.append(title,document.createTextNode(issue.message));el('issues').append(p);}
      primary.textContent=!job||s==='connecting'?'Connect Zotero':editable?'Preview Import':s==='ready'?'Import into Gewu':s==='paused'?'Resume Import':s==='needs_attention'?'Retry Unfinished':s==='complete'?'New Import':'Working…';
      primary.disabled=busy||active||(s==='paused'&&!job.config?.source_id);
      el('pause').hidden=!active;el('pause').disabled=busy;el('pause').textContent=s==='running'?'Pause Import':'Stop Preview';
      el('reconnect').hidden=!job||s==='connecting'||s==='complete';el('reconnect').disabled=busy;
      el('history').disabled=busy||active;
      if(job)text(!job.connected&&!['complete','connecting'].includes(s)?'Zotero is not connected. Reconnect to continue; completed imports are kept.':job.message+(s==='running'?`\n${el('progress').value} of ${job.total} items processed. You can close this window; keep Zotero running.`:''));
    };
    const act=async(action,extra={})=>{busy=true;render();let failure;try{job=await request(action,extra);if(![...el('history').options].some(o=>o.value===job.id))addOption(el('history'),job.id,new Date().toLocaleString());el('history').value=job.id;}catch(error){failure=error;}finally{busy=false;render();if(failure)text(failure.message,true);}};
    primary.onclick=async()=>{
      const s=job?.state;
      if(s==='complete'){job=null;catalogID='';el('history').value='';render();text('Connect Zotero to start a new import. Existing imported items will be recognized.');return;}
      if(!job||s==='connecting')return act('connect');
      if(['connected','scan_failed'].includes(s)){
        const keys=el('all').checked?[]:[...el('collections').querySelectorAll('input:checked')].map(c=>c.value);
        if(!el('all').checked&&!keys.length){text('Select at least one collection, or choose all collections.',true);return;}
        return act('scan',{source_id:el('source').value,target_id:Number(el('target').value),root_name:el('name').value,collection_keys:keys});
      }
      if(['ready','paused','needs_attention'].includes(s))return act('start');
    };
    el('pause').onclick=()=>act('pause');el('reconnect').onclick=()=>act('connect');
    el('setup').querySelector('button').onclick=()=>window.openZoteroSettings?.();
    const embedded=!!window.GewuZoteroHost;
    if(embedded)el('setup').hidden=true;
    el('history').onchange=async()=>{const id=el('history').value;catalogID='';job=id?{id}:null;if(job){try{job=await request();render();}catch(error){text(error.message,true);}}else{render();text('Connect Zotero to prepare a new import.');}};
    const close=()=>{closed=true;if(!busy&&!running())clearInterval(timer);if(job?.counts?.done||job?.counts?.partial)refresh();backdrop.remove();panel=null;previous?.focus?.();};
    backdrop.querySelector('.settings-modal-close').onclick=close;
    backdrop.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}
      if(event.key==='Tab'){const controls=[...backdrop.querySelectorAll('button,input,select')].filter(c=>!c.disabled&&c.getClientRects().length);const first=controls[0],last=controls.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}
    });
    try{
      const list=await request();destinations=list.destinations||[];for(const d of destinations)addOption(el('target'),d.id,d.title);
      for(const j of list.jobs||[])addOption(el('history'),j.id,new Date(j.created*1000).toLocaleString()+' · '+j.state.replaceAll('_',' '));
      const latest=list.jobs?.[0];if(latest&&latest.state!=='complete'){job={id:latest.id};el('history').value=latest.id;job=await request();render();}
    }catch(error){text(error.message,true);}
    if(!closed)timer=setInterval(async()=>{if(!job||busy||fetching)return;if(closed&&!running()){clearInterval(timer);return;}fetching=true;const id=job.id,wasRunning=running();try{const next=await request();if(!busy&&job?.id===id){job=next;if(wasRunning&&!running())refresh();render();}}catch(error){if(!closed&&job?.id===id)text(error.message,true);}finally{fetching=false;}},2000);
    backdrop.querySelector('section').focus({preventScroll:true});
  };
})();
