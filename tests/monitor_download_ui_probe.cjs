// Synthetic DOM regression: no research data, network downloads or real App writes.
const fs=require('fs'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {execFileSync}=require('node:child_process');
const path=require('node:path');
const html=JSON.parse(execFileSync(process.env.GEWU_TEST_PYTHON || 'python3', ['-c','import json; from paper_monitor.ui_server import INDEX_HTML; print(json.dumps(INDEX_HTML))'], {cwd:path.resolve(__dirname,'..'),encoding:'utf8',maxBuffer:8*1024*1024}));
const blocks=[['function renderPaper(', 'function themePaperMetaMarkup('],['function monitorPaperSignature(', 'function monitorSidebarSummaryRow('],['function updatePaperState(', 'function initialAuthorMonitorSelectedId('],['async function addPaperToLibrary(', 'async function moveLibraryEntry('],['function setReportLibraryButtonShowState(', 'async function navigateToPaperInLibrary('],['async function downloadReportPaper(', 'async function deletePaperAsset('],['function captureMonitorViewport(', 'async function uploadManualPdf('],['function monitorPaperForId(', 'function captureMonitorViewport(']];
const productionFunctions=blocks.map(([start,end])=>start+html.split(start)[1].split(end)[0]).join('\n');
(async()=>{
 const browser=await chromium.launch({...(process.env.GEWU_TEST_CHROME?{executablePath:process.env.GEWU_TEST_CHROME}:{}),headless:true,args:['--no-first-run','--no-default-browser-check']});
 const results=[];
 for(const mode of ['report','theme']){
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 await page.setContent(`<style>${html.match(/<style>([\s\S]*?)<\/style>/)[1]} #papers{height:500px;overflow:auto;display:block}.paper{min-height:230px}#editor{display:block}</style><input id="editor" value="reading notes"><div id="papers"></div>`);
 await page.addScriptTag({content:`
const $=id=>document.getElementById(id), FIELD_LABELS={};
const state={mode:${JSON.stringify(mode)}, papers:[],themePapers:[],reportCache:{},themePapersByDate:{},libraryLoaded:false,libraryItems:[],myPublications:[],authorMonitorPapers:[],monitorPaperDomCache:{},figureFailures:new Set(),showFigures:false,reportSelectedPaperId:'b',activeReportJournal:'Fixture',activeThemeGroupKey:'group',selectedDate:'2026-09-10',monitorPaperOperations:new Map()};
const fixture=Array.from({length:8},(_,i)=>({paper_id:String.fromCharCode(97+i),title:'Synthetic paper '+i,abstract:'A synthetic reading paragraph. '.repeat(12),journal:'Fixture',section:'research',publication_date:'2026-09-10',theme_groups:[{key:'group'}]}));
state.papers=fixture;state.themePapers=fixture;state.reportCache.day={papers:fixture};state.themePapersByDate.day=fixture;
const escapeHtml=s=>String(s??''), escapeAttr=escapeHtml, inlineLatexMarkup=escapeHtml, publicationTitleMarkup=escapeHtml;
const authorLineMarkup=()=>'',paperFieldValues=()=>[],themePaperMetaMarkup=()=>'';
function invalidateAuthorMonitorViewCache(){} function updateReportPaperSelectionDom(){}
const reportVisiblePapers=()=>state.papers,activeThemePapers=()=>state.themePapers;
const groupedReportPapers=papers=>[{journal:'Fixture',papers}];
let quickLookOpen=true;
function renderReport(){state.mode='report';quickLookOpen=false;renderMonitorPaperList($('papers'),state.papers,'report');}
function renderThemeMonitor(){quickLookOpen=false;renderMonitorPaperList($('papers'),state.themePapers,'theme');}
function renderAuthorMonitor(){throw Error('Unexpected Author render');}function renderActiveLibraryTab(){throw Error('Unexpected Library render');}
function selectReportPaper(id){state.reportSelectedPaperId=id;} function syncPrimaryKeyboardLayer(){}function setMonitorKeyboardPane(){}
function openPdf(){}function deletePaperAsset(){} function viewAnalysis(){} function openWebsite(){}
function showPaperInLibrary(){throw Error('Unexpected Library navigation');}function toggleLibraryAddMenu(){}
let resolveDownload,rejectDownload,downloadCalls=0;
async function requestPaperPdfDownload(){downloadCalls++;return await new Promise((resolve,reject)=>{resolveDownload=resolve;rejectDownload=reject;});}
async function fetch(){return {ok:true,json:async()=>({paper:{paper_id:'b',in_library:true,library_item_count:1,library_status_loaded:true}})};}
`});
 let functions=productionFunctions;
 // Exercise the real download handler with a deterministic pending transport.
 functions=functions.split('const pendingPaperPdfDownloads =')[0];
 await page.addScriptTag({content:functions});
 const before=await page.evaluate(async()=>{
 renderMonitorPaperList($('papers'),state.papers,state.mode);
 window.a=$('papers').querySelector('[data-paper-id="a"]');window.b=$('papers').querySelector('[data-paper-id="b"]');
 window.pending=downloadReportPaper(a,'a');
 const before=a.querySelector('[data-role="status"]').textContent;
 $('papers').scrollTop=175;$('editor').focus();
 await addPaperToLibrary(b,'b',{folderId:1});
 await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
 return {before,after:$('papers').querySelector('[data-paper-id="a"] [data-role="status"]').textContent,sameA:a===$('papers').querySelector('[data-paper-id="a"]'),scroll:$('papers').scrollTop,focused:document.activeElement.id,quickLookOpen};
 });
 const redraw=await page.evaluate(async()=>{
 state.papers[0]={...state.papers[0],abstract:state.papers[0].abstract+' New metadata.'};
 renderMonitorPaperList($('papers'),state.papers,state.mode);
 const current=$('papers').querySelector('[data-paper-id="a"]');
 await downloadReportPaper(current,'a');
 return {detached:!a.isConnected,status:current.querySelector('[data-role="status"]').textContent,disabled:current.querySelector('[data-action="download"]').disabled,downloadCalls};
 });
 assert.equal(redraw.detached,true);assert.equal(redraw.status,'Downloading...');assert.equal(redraw.disabled,true);assert.equal(redraw.downloadCalls,1);
 const after=await page.evaluate(async()=>{state.mode='browser';resolveDownload({paper:{paper_id:'a',merged_pdf_path:'synthetic.pdf',download_status:'partial'}});await pending;return {mode:state.mode,selected:state.reportSelectedPaperId,status:$('papers').querySelector('[data-paper-id="a"] [data-role="status"]').textContent,pdf:!!$('papers').querySelector('[data-paper-id="a"] [data-action="open-pdf"]')};});
 results.push({mode,before,redraw,after});
 {
 assert.equal(before.after,'Downloading...');assert.equal(before.sameA,true);assert.equal(before.scroll,175);assert.equal(before.focused,'editor');assert.equal(before.quickLookOpen,true);assert.equal(after.mode,'browser');assert.equal(after.selected,'b');assert.equal(after.pdf,true);
 }
 const failure=await page.evaluate(async()=>{
 state.mode='theme';
 const current=$('papers').querySelector('[data-paper-id="a"]');
 const retry=downloadReportPaper(current,'a');
 // Keep the current DOM offscreen while an unrelated paper surface is mounted.
 stashCurrentMonitorPaperSurface($('papers'));
 state.mode='library';
 rejectDownload(new Error('Synthetic network failure'));
 await retry;
 const cache=Object.values(state.monitorPaperDomCache).find(entry=>entry?.fragment);
 const old=cache.fragment.querySelector('[data-paper-id="a"]');
 const status=old.querySelector('[data-role="status"]').textContent;
 const disabled=old.querySelector('[data-action="download"]').disabled;
 return {status,disabled,mode:state.mode};
 });
 assert.equal(failure.status,'Synthetic network failure');assert.equal(failure.disabled,false);assert.equal(failure.mode,'library');
 await page.close();
 }
 console.log(JSON.stringify(results,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
