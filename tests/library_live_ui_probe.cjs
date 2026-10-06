// Actual UI + external standard STDIO MCP, entirely synthetic data.
const assert=require('node:assert/strict'),fs=require('node:fs'),{spawn}=require('node:child_process');
const {createInterface}=require('node:readline');const {chromium}=require('playwright');
const f=JSON.parse(fs.readFileSync(process.argv[2]));
(async()=>{
 const processMcp=spawn(process.env.GEWU_TEST_PYTHON||'python3',['scripts/gewu_mcp.py'],{env:{...process.env,GEWU_API_URL:f.url,GEWU_API_TOKEN:f.mcp_token},stdio:['pipe','pipe','pipe']});
 let serial=0;const waiting=new Map();createInterface({input:processMcp.stdout}).on('line',line=>{const r=JSON.parse(line);waiting.get(r.id)?.(r);waiting.delete(r.id);});
 const rpc=(method,params)=>new Promise(resolve=>{const id=++serial;waiting.set(id,resolve);processMcp.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
 const tool=async(name,args)=>{const r=await rpc('tools/call',{name,arguments:args});assert(!r.error,JSON.stringify(r.error));assert(!r.result.isError,JSON.stringify(r.result));return JSON.parse(r.result.content[0].text);};
 let browser;
 try{
 await rpc('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'synthetic-live-check',version:'1'}});
 browser=await chromium.launch({headless:true,channel:'chrome'});
 const context=await browser.newContext({viewport:{width:1300,height:880},extraHTTPHeaders:{'X-Gewu-Workspace':f.token}});
 await context.route('**/*',r=>r.request().url().startsWith(f.url)?r.continue():r.abort());
 const page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 page.setDefaultTimeout(12000);
 await page.goto(f.url);await page.waitForFunction(()=>appBootCompleted&&libraryExternalCursor!==null&&!libraryExternalPending);
 const bootstraps=()=>requests.filter(x=>x.includes('/api/library/bootstrap')).length;const initialBootstraps=bootstraps();
 const current=()=>page.evaluate(()=>JSON.stringify([state.libraryTab,state.librarySelection,state.libraryCurrentFolderId,state.libraryActiveFolderId,state.libraryPaperResourceSelection]));
 // Keep the original paper and a scrolled Markdown preview open throughout external writes.
 await page.locator(`[data-library-type="item"][data-library-id="${f.item_id}"]`).click();
 await page.waitForFunction(()=>!Object.keys(state.paperFileRequests).length);
 await page.evaluate(async f=>{const p=paperFilesSnapshot('one');const n=p.files.find(x=>x.id===f.note_id);await quickLookLibraryFile({native_file_path:n.local_path});},f);
 await page.waitForFunction(()=>document.querySelector('#libraryQuickLookPages math'));
 await page.evaluate(()=>{window.keptPreview=document.querySelector('#libraryQuickLookPages .library-markdown-document');$('libraryQuickLookPages').scrollTop=180;document.querySelector('.library-column-body').scrollTop=300;});
 const original=await current();
 const space=await tool('create_space',{name:'External Space',request_id:'ui-live-space-001'});
 await page.locator('#libraryShortcutTabs').getByText('External Space',{exact:true}).waitFor();
 assert.equal(await current(),original,'new Space preserves current view');
 assert.equal(await page.evaluate(()=>window.keptPreview===document.querySelector('#libraryQuickLookPages .library-markdown-document')),true);
 assert.equal(await page.evaluate(()=>$('libraryQuickLookPages').scrollTop),180);
 assert.equal(await page.evaluate(()=>document.querySelector('.library-column-body').scrollTop),300);
 const note=await tool('save_analysis',{gewu_key:f.key,title:'Appended while reading',markdown:'# New analysis\n\n$y^2$',request_id:'ui-live-note-001'});
 await page.locator(`[data-library-resource-id="${note.file.file_id}"]`).waitFor({state:'attached'});
 assert.equal(await current(),original,'new analysis preserves selection');
 assert.equal(await page.evaluate(()=>window.keptPreview===document.querySelector('#libraryQuickLookPages .library-markdown-document')),true,'new analysis does not rebuild the open preview');
 // Drafts defer refresh, then converge without losing text or acknowledging too early.
 await page.evaluate(()=>{closeLibraryQuickLook();beginLibraryInlineAddPaper(1);});
 const input=page.locator('[data-library-inline-add-paper-input]');await input.fill('unsaved DOI draft');
 const folder=await tool('create_folder',{parent_id:1,name:'Live destination',request_id:'ui-live-folder-001'});
 await page.waitForTimeout(3300);
 assert.equal(await input.inputValue(),'unsaved DOI draft');
 assert.equal(await page.locator(`[data-library-type="folder"][data-library-id="${folder.folder_id}"]`).count(),0);
 await input.press('Escape');await page.locator(`[data-library-type="folder"][data-library-id="${folder.folder_id}"]`).waitFor();
 // Read-only MCP calls do not repaint. Disabled access makes no poll requests.
 await page.waitForFunction(()=>!libraryExternalPending);
 await page.evaluate(()=>{window.keptRow=document.querySelector('[data-library-type="item"]');});
 await tool('get_paper',{gewu_key:f.key});
 await page.evaluate(()=>pollExternalLibraryChanges());
 assert.equal(await page.evaluate(()=>keptRow===document.querySelector('[data-library-type="item"]')),true);
 await page.evaluate(()=>window.setGewuAIAccessEnabled(false));
 const pollCount=()=>requests.filter(x=>x.includes('/api/library/changes?')).length;
 const disabledCount=pollCount();await page.waitForTimeout(3200);
 assert.equal(pollCount(),disabledCount,'disabled AI access does not poll');
 // A delayed response must not overwrite newer navigation or acknowledge a write.
 const raceFolder=await tool('create_folder',{parent_id:1,name:'Delayed update',request_id:'ui-live-delayed'});
 let releaseResponse,receivedResponse;
 const received=new Promise(r=>receivedResponse=r),release=new Promise(r=>releaseResponse=r);
 await page.route('**/api/library/changes?**',async route=>{const response=await route.fetch();receivedResponse();await release;await route.fulfill({response});},{times:1});
 const oldCursor=await page.evaluate(()=>libraryExternalCursor);
 await page.evaluate(()=>{window.setGewuAIAccessEnabled(true);void pollExternalLibraryChanges();});
 await received;
 await page.evaluate(()=>{state.libraryContentView='table';renderLibraryNavigationContent();});
 releaseResponse();await page.waitForFunction(()=>!libraryExternalPending);
 assert.equal(await page.evaluate(()=>libraryExternalCursor),oldCursor,'stale response stays unacknowledged');
 await page.route('**/api/library/changes?**',r=>r.fulfill({status:503,body:'temporary fixture outage'}),{times:1});
 await page.evaluate(()=>pollExternalLibraryChanges());
 assert.equal(await page.evaluate(()=>libraryExternalCursor),oldCursor,'temporary failure stays unacknowledged');
 await page.evaluate(()=>pollExternalLibraryChanges());
 await page.locator(`[data-library-type="folder"][data-library-id="${raceFolder.folder_id}"]`).waitFor();
 assert.equal(await page.evaluate(()=>state.libraryContentView),'table');
 await page.evaluate(()=>{state.libraryContentView='list';renderLibraryNavigationContent();});
 // New Space children and imports appear while that same Space remains open.
 await page.evaluate(async id=>{const i=state.libraryWorkspaceTabs.findIndex(t=>t.root_folder_id===id);await openLibraryWorkspaceTab(i);},space.folder_id);
 const sub=await tool('create_folder',{parent_id:space.folder_id,name:'Nonlocal Readout',request_id:'ui-live-subfolder-001'});
 await page.locator(`[data-library-type="folder"][data-library-id="${sub.folder_id}"]`).waitFor();
 await page.locator(`[data-library-type="folder"][data-library-id="${sub.folder_id}"]`).click();
 const upload=await tool('upload_file',{local_path:f.pdf,request_id:'ui-live-upload-001'});
 const paper=await tool('import_paper',{folder_id:sub.folder_id,upload_id:upload.upload_id,request_id:'ui-live-import-001',file_type:'preprint',metadata:{title:'Live imported paper',authors:['Synthetic Author'],journal:'arXiv',publication_date:'2026',publication_type:'preprint',doi:null,arxiv_id:'2601.12345',source_url:'https://example.org/synthetic'}});
 await page.locator(`[data-library-type="item"][data-library-id="${paper.membership_id}"]`).waitFor();
 await page.locator(`[data-library-type="item"][data-library-id="${paper.membership_id}"]`).click();
 await page.waitForFunction(()=>!Object.keys(state.paperFileRequests).length);
 // PNG and math in the same saved analysis use only same-directory paths.
 const up=await tool('upload_file',{local_path:f.png,request_id:'ui-live-png-upload'});
 const figure=await tool('add_paper_file',{gewu_key:paper.gewu_key,upload_id:up.upload_id,file_type:'other',request_id:'ui-live-png-attach'});
 const detail=await tool('get_paper',{gewu_key:paper.gewu_key});
 const imageName=detail.files.find(x=>x.file_id===figure.file.file_id).name;
 assert(imageName,'MCP file has a stable relative filename');
 const illustrated=await tool('save_analysis',{gewu_key:paper.gewu_key,title:'Illustrated analysis',request_id:'ui-live-illustrated',markdown:`# Illustrated\n\n$E_M$\n\n$$\\begin{pmatrix}0&1\\\\1&0\\end{pmatrix}$$\n\n![Synthetic figure](${encodeURIComponent(imageName)})\n\nFigure 1 — synthetic offline image.\n\n![Missing fixture](missing.png)\n\n![Outside blocked](../outside.png)`});
 await page.locator(`[data-library-resource-id="${illustrated.file.file_id}"]`).waitFor();
 const openNote=async()=>{await page.evaluate(async fid=>{const item=libraryItemById(state.librarySelection.id);const n=paperFilesSnapshot(item.paper_id).files.find(x=>x.id===fid);await quickLookLibraryFile({native_file_path:n.local_path});},illustrated.file.file_id);await page.waitForFunction(()=>document.querySelector('#libraryQuickLookPages img')?.naturalWidth>0);};
 await openNote();assert.equal(await page.locator('#libraryQuickLookPages math').count(),2);assert.equal(await page.locator('#libraryQuickLookPages img').first().evaluate(el=>el.naturalWidth),48);
 assert.match(await page.locator('#libraryQuickLookPages').innerText(),/Outside blocked/);
 assert.equal(await page.locator('#libraryQuickLookPages img').nth(1).getAttribute('alt'),'Missing fixture');
 // Rename/move the whole folder using MCP: relative images remain valid.
 await page.evaluate(()=>closeLibraryQuickLook());
 await tool('rename_folder',{folder_id:sub.folder_id,name:'Readout renamed',request_id:'ui-live-rename-001'});
 await page.waitForFunction(id=>libraryFolderById(id)?.name==='Readout renamed',sub.folder_id);
 await openNote();await page.evaluate(()=>closeLibraryQuickLook());
 await tool('move_folder',{folder_id:sub.folder_id,parent_id:1,request_id:'ui-live-move-folder'});
 await page.waitForFunction(id=>libraryFolderById(id)?.parent_id===1,sub.folder_id);
 // Navigate through Library to the moved object (its old Space no longer owns it).
 await page.evaluate(async id=>{state.libraryTab='library';setLibraryColumnSelection(1,{type:'folder',id});await loadLibraryFolderAndRender(id);},sub.folder_id);
 await page.locator(`[data-library-type="item"][data-library-id="${paper.membership_id}"]`).click();await page.waitForFunction(()=>!Object.keys(state.paperFileRequests).length);await openNote();
 await page.evaluate(()=>closeLibraryQuickLook());
 await tool('move_file',{source:{membership_id:paper.membership_id},target:{folder_id:folder.folder_id},request_id:'ui-live-move-paper'});
 await page.waitForFunction(id=>!document.querySelector(`[data-library-type="item"][data-library-id="${id}"]`),paper.membership_id);
 assert.equal(bootstraps(),initialBootstraps,'external writes never bootstrap or reload all papers');
 assert.deepEqual(errors,[]);
 fs.mkdirSync(process.env.GEWU_UI_QA_DIR||'/private/tmp/gewu-live-sep27',{recursive:true});
 await page.screenshot({path:(process.env.GEWU_UI_QA_DIR||'/private/tmp/gewu-live-sep27')+'/live-final.png'});
 console.log('PASS: real STDIO MCP Space/folder/import/analysis/move/rename updates; selection, scroll, draft and preview preserved; image+math, move/rename and access boundaries; no bootstrap reload.');
 } finally {processMcp.stdin.end();processMcp.kill();if(browser)await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
