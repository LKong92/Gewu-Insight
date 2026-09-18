// Two list-sorting UIs with product CSS/handlers and synthetic records only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium, webkit} = require('playwright');
const root = path.resolve(__dirname, '..');
const html = JSON.parse(execFileSync(process.env.GEWU_TEST_PYTHON || 'python3', ['-c',
  'import json; from paper_monitor.ui_server import INDEX_HTML; print(json.dumps(INDEX_HTML))'],
  {cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024}));
function fn(name) {
  const start = html.search(new RegExp('    (?:async )?function ' + name + '\\('));
  assert.ok(start >= 0, name);
  return html.slice(start, html.indexOf('\n    }', start) + 6);
}
const functions = ['clearListReorderMarker', 'showListReorderMarker', 'setListReorderDragImage',
  'wireMyPublicationInteractions', 'clearMyPublicationDragMarkers', 'myPublicationDropPosition',
  'renderAuthorMonitorRail', 'reorderAuthorMonitors', 'reorderMyPublications'].map(fn).join('\n');
const fixture = `<style>${html.match(/<style>([\s\S]*?)<\/style>/)[1]}</style>
<style>body{display:block;min-width:0;padding:60px 24px 24px;background:#fff}
.fixture{display:grid;grid-template-columns:280px minmax(0,1fr);gap:28px;height:470px}
#authorMonitorAuthors,.my-publications-table-wrap{height:410px;overflow:auto}
#libraryShell{display:block;min-width:0}.my-publications-table{min-width:0;width:100%}
.my-publications-table td:first-child{width:38px}.my-publications-table td:nth-child(2){width:65%}
h2{font-size:16px;margin:0 0 12px}</style>
<div class="app author-mode" style="display:block"><div class="fixture">
<section><h2>Author Monitor</h2><div class="author-monitor-authors" id="authorMonitorAuthors"></div></section>
<section><h2>My Publications</h2><div id="libraryShell"><div class="my-publications-table-wrap"><table class="my-publications-table"><tbody></tbody></table></div></div></section>
</div></div>`;
const setup = `
const $ = id => document.getElementById(id);
let listReorderMarker = null, listReorderMarkerRow = null;
const state = {mode:'author',authorMonitorSelectedId:2,authorMonitorDragId:0,
  authorMonitors:Array.from({length:18},(_,i)=>({id:i+1,name:'Researcher '+(i+1),affiliation:'Institute of Physics',unread_count:0})),
  myPublications:Array.from({length:30},(_,i)=>({id:i+1,paper:{title:'Study '+(i+1)+' — Superconducting quantum states',paper_id:'fixture-'+i},sort_order:i})),
  myPublicationSelectionId:2,myPublicationSort:'date',myPublicationSelectedIds:new Set([2])};
const requests = [], selections = [];
const escapeHtml = s => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;'), escapeAttr = escapeHtml;
const authorMonitorLinkedAvatarMarkup = () => '<span class="author-monitor-avatar">AB</span>';
const wireAuthorMonitorAvatarLinks = () => {}, authorMonitorIsScholar = () => true, authorMonitorSourceShortLabel = () => 'GS';
const selectAuthorMonitorScope = id => selections.push(id), showAuthorMonitorContextMenu = () => {};
const myPublicationById = id => state.myPublications.find(p=>p.id===id), sortedMyPublications = () => state.myPublications;
const applyMyPublications = d => {state.myPublications=d.publications};
const startDragSelection = () => {}, shouldPreserveInteractiveFocus = () => true;
const selectMyPublication = (id,options) => selections.push({id,options});
const refreshAuthorMonitorSummary = async () => {}, showMonitorStatusMessage = () => {};
async function fetch(url, options) {
  const payload=JSON.parse(options.body);requests.push({url,payload});
  return {ok:true,json:async()=>({authors:state.authorMonitors,publications:state.myPublications})};
}
function renderMyPublications() {
  document.querySelector('tbody').innerHTML = state.myPublications.map((p,i)=>
    '<tr class="my-publications-row '+(p.id===2?'active':p.id===3?'review-article':p.id===4?'head-excluded':'')+'" draggable="true" data-publication-id="'+p.id+'">'+
    '<td>'+(i+1)+'</td><td><span class="my-publications-title-text">'+p.paper.title+'</span></td><td class="my-publications-id">Nature Physics (2026)</td></tr>').join('');
  wireMyPublicationInteractions();
}
${functions}
renderAuthorMonitorRail();renderMyPublications();
let transfer, draggedRow, previewSnapshot;
function dispatchDrag(row, type, fraction=.75, relatedTarget=null) {
  const r=row.getBoundingClientRect();
  row.dispatchEvent(new DragEvent(type,{bubbles:true,cancelable:true,dataTransfer:transfer,
    clientX:r.left+Math.min(80,r.width/2),clientY:r.top+r.height*fraction,relatedTarget}));
}
function startDrag(selector) {
  draggedRow=document.querySelector(selector);transfer=new DataTransfer();
  dispatchDrag(draggedRow,'dragstart');
  const p=document.querySelector('.list-reorder-drag-image');
  previewSnapshot=p?{text:p.textContent,color:getComputedStyle(p).color,background:getComputedStyle(p).backgroundColor,
    width:p.getBoundingClientRect().width,ariaHidden:p.getAttribute('aria-hidden')}:null;
}
function finishDrag() {dispatchDrag(draggedRow,'dragend');}
function geometry(selector) {return [...document.querySelectorAll(selector)].map(r=>{const b=r.getBoundingClientRect();return [r.dataset.authorId||r.dataset.publicationId,b.top,b.height]});}
function markerInfo(selector,after) {
 const row=document.querySelector(selector),r=row.getBoundingClientRect(),m=document.querySelector('.list-reorder-marker');
 if(!m)return null;const b=m.getBoundingClientRect(),s=getComputedStyle(m),dot=getComputedStyle(m,'::before');
 return {delta:b.top+1-(after?r.bottom:r.top),width:b.width,colour:s.backgroundColor,events:s.pointerEvents,dot:dot.borderRadius};
}
`;

(async () => {
  const engine = process.env.GEWU_TEST_WEBKIT ? webkit : chromium;
  const browser = await engine.launch({headless:true, ...(!process.env.GEWU_TEST_WEBKIT && process.env.GEWU_TEST_CHROME ? {executablePath:process.env.GEWU_TEST_CHROME} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1300,height:700}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',r=>r.abort());
    await page.setContent(fixture);await page.addScriptTag({content:setup});
    for (const kind of ['author','publication']) {
      const selector = id => kind==='author'?'.author-monitor-author[data-author-id="'+id+'"]':'.my-publications-row[data-publication-id="'+id+'"]';
      const all = kind==='author'?'.author-monitor-author':'.my-publications-row';
      const original = await page.evaluate(sel=>geometry(sel),all);
      const before = await page.evaluate(()=>requests.length);
      await page.evaluate(sel=>startDrag(sel),selector(2));
      const preview = await page.evaluate(()=>previewSnapshot);
      assert.ok(preview.text.includes(kind==='author'?'Researcher 2':'Study 2'),'visible drag label');
      assert.equal(preview.color,'rgb(37, 51, 72)','active white text cannot leak into preview');
      assert.equal(preview.ariaHidden,'true');assert.ok(preview.width>=160&&preview.width<=480);
      for (const [target,after] of [[4,false],[4,true],[1,false],[3,true]]) {
        await page.evaluate(({s,after})=>dispatchDrag(document.querySelector(s),'dragover',after?.8:.2),{s:selector(target),after});
        assert.deepEqual(await page.evaluate(sel=>geometry(sel),all),original,'no target displacement during drag');
        const marker=await page.evaluate(({s,after})=>markerInfo(s,after),{s:selector(target),after});
        assert.ok(marker&&Math.abs(marker.delta)<1);assert.ok(marker.width>100);
        assert.equal(marker.colour,'rgb(52, 120, 237)');assert.equal(marker.events,'none');assert.equal(marker.dot,'50%');
        assert.equal(await page.evaluate(()=>requests.length),before,'hover cannot save order');
        // Crossing children within the same row must retain the insertion line.
        await page.evaluate(s=>{const r=document.querySelector(s);dispatchDrag(r,'dragleave',.8,r.firstElementChild)},selector(target));
        assert.equal(await page.locator('.list-reorder-marker').count(),1);
      }
      await page.evaluate(s=>dispatchDrag(document.querySelector(s),'dragover'),selector(2));
      assert.equal(await page.locator('.list-reorder-marker').count(),0,'self drop has no false insertion point');
      await page.evaluate(s=>dispatchDrag(document.querySelector(s),'dragover'),selector(4));
      await page.evaluate(()=>finishDrag());
      assert.equal(await page.locator('.list-reorder-marker').count(),0,'cancel cleans marker');
      assert.deepEqual(await page.evaluate(sel=>geometry(sel),all),original,'cancel preserves order and row geometry');
      assert.equal(await page.evaluate(()=>requests.length),before);
      // Verify actual existing reorder functions emit the order shown by the marker.
      for (const [target,after,expected] of [[4,true,[1,3,4,2,5]],[1,false,[2,1,3,4,5]]]) {
        await page.evaluate(sel=>startDrag(sel),selector(2));
        await page.evaluate(({s,after})=>{const r=document.querySelector(s);dispatchDrag(r,'dragover',after?.8:.2);dispatchDrag(r,'drop',after?.8:.2);finishDrag()}, {s:selector(target),after});
        const request=await page.evaluate(()=>requests.at(-1));
        assert.equal(request.url,kind==='author'?'/api/author-monitor/reorder':'/api/my-publications/reorder');
        assert.deepEqual((request.payload.author_ids||request.payload.publication_ids).slice(0,5),expected);
        assert.equal(await page.locator('.list-reorder-marker').count(),0,'drop cleans marker before rerender');
      }
      await page.evaluate(sel=>startDrag(sel),selector(2));
      await page.evaluate(s=>dispatchDrag(document.querySelector(s),'dragover'),selector(4));
      const scroll=await page.evaluate(kind=>{const el=document.querySelector(kind==='author'?'#authorMonitorAuthors':'.my-publications-table-wrap');el.scrollTop=70;return {top:el.scrollTop,height:el.clientHeight,total:el.scrollHeight,overflow:getComputedStyle(el).overflowY}},kind);
      assert.ok(scroll.top>0,kind+' fixture must actually scroll: '+JSON.stringify(scroll));
      await page.waitForFunction(()=>!document.querySelector('.list-reorder-marker'));
      assert.equal(await page.locator('.list-reorder-marker').count(),0,kind+' scroll clears stale position');
      await page.evaluate(()=>finishDrag());
    }
    // A real browser gesture also exercises protected DataTransfer types and Escape.
    await page.evaluate(()=>{
      document.querySelector('#authorMonitorAuthors').scrollTop=0;
      document.querySelector('.my-publications-table-wrap').scrollTop=0;
    });
    await page.waitForTimeout(50);
    for (const [source,target] of [
      ['[data-author-id="2"]','[data-author-id="4"]'],
      ['[data-publication-id="2"]','[data-publication-id="4"]']
    ]) {
      const before=await page.evaluate(()=>requests.length);
      const a=await page.locator(source).boundingBox(),b=await page.locator(target).boundingBox();
      await page.mouse.move(a.x+80,a.y+a.height/2);await page.mouse.down();
      await page.mouse.move(a.x+90,a.y+a.height/2+6,{steps:3});
      await page.mouse.move(b.x+80,b.y+b.height*.8,{steps:6});
      await page.mouse.move(b.x+81,b.y+b.height*.8);
      await page.waitForFunction(()=>Boolean(document.querySelector('.list-reorder-marker')));
      await page.keyboard.press('Escape');await page.mouse.up();
      await page.waitForFunction(()=>!document.querySelector('.list-reorder-marker'));
      assert.equal(await page.evaluate(()=>requests.length),before,'native cancel does not save');
    }
    assert.equal(await page.evaluate(()=>state.authorMonitorSelectedId),2);
    assert.equal(await page.evaluate(()=>state.myPublicationSelectionId),2);
    assert.equal(await page.evaluate(()=>state.myPublications.find(p=>p.id===2).paper.paper_id),'fixture-1');
    for (const width of [850,1500]) {
      await page.setViewportSize({width,height:750});
      await page.evaluate(()=>{
        document.querySelector('#authorMonitorAuthors').scrollTop=0;
        document.querySelector('.my-publications-table-wrap').scrollTop=0;
      });
      await page.waitForTimeout(30);
      await page.evaluate(()=>{startDrag('.author-monitor-author[data-author-id="2"]');dispatchDrag(document.querySelector('[data-author-id="4"]'),'dragover')});
      assert.ok((await page.locator('.list-reorder-marker').boundingBox()).width>100);
      await page.evaluate(()=>finishDrag());
    }
    if(process.env.GEWU_DRAG_QA_DIR) {
      fs.mkdirSync(process.env.GEWU_DRAG_QA_DIR,{recursive:true});
      await page.evaluate(()=>{showListReorderMarker(document.querySelector('[data-author-id="4"]'),false)});
      await page.screenshot({path:path.join(process.env.GEWU_DRAG_QA_DIR,'author-insertion.png')});
      await page.evaluate(()=>{showListReorderMarker(document.querySelector('[data-publication-id="4"]'),true)});
      await page.screenshot({path:path.join(process.env.GEWU_DRAG_QA_DIR,'publication-insertion.png')});
      fs.writeFileSync(path.join(process.env.GEWU_DRAG_QA_DIR,'fixture.html'),fixture+'<script>'+setup+'</script>');
    }
    assert.deepEqual(errors,[]);
    console.log('Both lists: readable previews, stable geometry, before/after payloads, self-drop, child transitions, cancel, scroll cleanup, widths, selection and paper identity passed.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
