// Real tab click wiring, focus layer, and delayed focus callbacks in a synthetic DOM.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const source=fs.readFileSync(path.resolve(__dirname,'../paper_monitor/ui_server.py'),'utf8');
const names=['currentPrimaryKeyboardView','primaryKeyboardButton','syncPrimaryKeyboardLayer',
  'focusClickedPrimaryTab','leavePrimaryKeyboardRoot','activeMonitorKeyboardMode',
  'focusMonitorCalendarCursor','focusMonitorPaperSelection','restoreMonitorKeyboardFocus'];
const functions=names.map(name=>{const start=source.indexOf('    function '+name+'(');assert.ok(start>=0);return source.slice(start,source.indexOf('\n    }',start)+6);}).join('\n');
const start=source.indexOf('    $("primaryViewSwitcher").addEventListener("click", focusClickedPrimaryTab, true);');
const wiring=source.slice(start,source.indexOf('    wireLibraryImportTools();',start));
const tabs=['libraryMode','myPublicationsMode','reportMode','themeMode','authorMode','browserMode'];
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.GEWU_TEST_CHROME?{executablePath:process.env.GEWU_TEST_CHROME}:{})});
 try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent(`<div id="primaryViewSwitcher">${tabs.map(id=>`<button class="view-switch" id="${id}"><span>${id}</span></button>`).join('')}</div><div id="papers" tabindex="0"><button class="paper" data-paper-id="selected">Selected paper</button><input id="editor"></div><div id="calendar"><button class="day" data-date="2026-09-10">10</button></div><div id="libraryShell" tabindex="0"></div>${['sideLibraryMode','sideReportMode','sideThemeMode','sideAuthorMode'].map(id=>`<button id="${id}"></button>`).join('')}`);
 await page.addScriptTag({content:`
 const PRIMARY_KEYBOARD_VIEWS=['library','my-publications','report','theme','author','browser'];
 const $=id=>document.getElementById(id);
 const state={mode:'report',libraryTab:'library',primaryKeyboardLayer:'content',monitorKeyboardPanes:{report:'papers',theme:'papers'},monitorCalendarCursorDates:{report:'2026-09-10',theme:'2026-09-10'},reportSelectedPaperId:'selected'};
 const activeReportPapers=()=>[{paper_id:'selected'}],ensureReportPaperSelection=()=>{},showMonitorStatusMessage=()=>{};
 let release=null;
 async function load(view){await new Promise(resolve=>{release=resolve;});state.mode=['library','my-publications'].includes(view)?'library':view;state.libraryTab=view;restoreMonitorKeyboardFocus(state.mode);}
 const loadLibrary=()=>load('library'),loadMyPublications=()=>load('my-publications'),openJournalMonitor=()=>load('report'),openThemeMonitor=()=>load('theme'),openAuthorMonitor=()=>load('author');
 ${functions}
 ${wiring}
 $('browserMode').addEventListener('click',()=>load('browser'));
 `});
 for(const id of tabs){
   await page.evaluate(()=>{state.mode='report';state.primaryKeyboardLayer='content';$('editor').focus();});
   await page.click('#'+id+' span');
   assert.equal(await page.evaluate(()=>document.activeElement.id),id);
   assert.equal(await page.evaluate(()=>state.primaryKeyboardLayer),'root');
   assert.equal(await page.locator('#primaryViewSwitcher').evaluate(e=>e.classList.contains('keyboard-active')),true);
   await page.evaluate(async()=>{release();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));});
   assert.equal(await page.evaluate(()=>document.activeElement.id),id,'completion preserves the clicked tab focus');
 }
 // A focus callback queued before a tab click must not steal focus afterward.
 for(const pane of ['papers','calendar']){
   await page.evaluate(pane=>{
     state.mode='report';state.primaryKeyboardLayer='content';state.monitorKeyboardPanes.report=pane;
     if(pane==='papers')focusMonitorPaperSelection('report');else focusMonitorCalendarCursor('report');
     $('reportMode').click();
   },pane);
   await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
   assert.equal(await page.evaluate(()=>document.activeElement.id),'reportMode');
   await page.evaluate(()=>release());
 }
 await page.click('#editor');
 assert.equal(await page.evaluate(()=>state.primaryKeyboardLayer),'content','clicking content leaves root normally');
 assert.equal(await page.evaluate(()=>document.activeElement.id),'editor');
 assert.deepEqual(errors,[]);console.log('Six primary tabs retain click focus through delayed loading; stale paper/calendar focus is ignored; content clicks still work.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
