// Exercise product drag routing and cache updates on generated DOM only.
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const {chromium, webkit} = require('playwright');
const root = path.resolve(__dirname, '..');
const html = JSON.parse(execFileSync(process.env.GEWU_TEST_PYTHON || 'python3', ['-c', 'import json; from paper_monitor.ui_server import INDEX_HTML; print(json.dumps(INDEX_HTML))'], {cwd:root,encoding:'utf8',maxBuffer:8*1024*1024}));
function fn(name) {
  const start = html.search(new RegExp('    (?:async )?function '+name+'\\('));
  assert.ok(start>=0,name);
  let value=html.slice(start);const next=value.slice(1).search(/\n    (?:async )?function /);
  value=value.slice(0,next+1);
  if(name==='importDroppedPdfForLibraryPaper')value=value.split('    const pendingNativePublisherDownloads')[0];
  return value;
}
(async()=>{
 const browser=await (process.env.GEWU_TEST_WEBKIT?webkit:chromium).launch({headless:true,...(process.env.GEWU_TEST_CHROME?{executablePath:process.env.GEWU_TEST_CHROME}:{})});
 try {
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<div id="libraryShell"><div id="libraryDetail"></div></div>');
  await page.evaluate(()=>{
   window.$=id=>document.getElementById(id);
   window.state={mode:'library',libraryTab:'my-publications',libraryActiveFolderId:1,libraryRootId:1,librarySelection:null,paperFilesByPaperId:{},paperFileRequests:{}};
   window.calls=[];window.updated={};window.rendered=[];
   window.updatePaperState=(id,p)=>{updated[id]=p;};
   window.renderMyPublications=window.renderLibrary=()=>rendered.push(JSON.stringify(state.paperFilesByPaperId));
   window.updateLibraryActivityStatus=()=>{};window.setMyPublicationActivity=()=>{};window.clearMyPublicationActivity=()=>{};window.refreshLibraryQuickLookForSelection=()=>{};
   window.libraryItemById=()=>null;window.libraryFolderById=()=>null;window.libraryFolderPath=()=>'';window.libraryDisplayRootId=()=>1;
   window.uploadPaperFilePaths=()=>{throw Error('Button was misrouted as a generic attachment');};
   window.runLibraryDroppedPathsImport=()=>{throw Error('Button was misrouted as a Library folder import');};
   window.fetch=async(url,options)=>{
    const payload=typeof options.body==='string'?JSON.parse(options.body):Object.fromEntries(options.body.entries());
    calls.push({url,payload});const id=payload.paper_id;
    const paper={paper_id:id,merged_pdf_path:'/managed/'+id+'.pdf'};
    return {ok:true,json:async()=>({paper,paper_files:[{paper_id:id,paper,files:[{id:42,local_path:paper.merged_pdf_path,is_default:true}]}]})};
   };
   window.makeButton=(id,replacing=false)=>{
    $('libraryDetail').innerHTML=`<button data-library-pdf-drop-target data-paper-id="${id}" data-pdf-replace="${replacing?'1':'0'}"><span>Download PDF</span></button><div id="libraryDetailStatus"></div>`;
   };
  });
  await page.addScriptTag({content:['paperFilesSnapshot','applyPaperFilesPayloads','libraryPdfContextPayload','libraryPdfDropFile','showLibraryPdfDropError','clearLibraryFinderDropTargetVisuals','clearLibraryFinderDropTarget','libraryFileAssociationTargetFromPoint','libraryPdfDropTargetFromPoint','libraryImportDropTargetFolderId','handleNativeFinderDrop','wireLibraryPdfDropTarget','importDroppedPdfForLibraryPaper'].map(fn).join('\n')});
  for(const workspace of ['my-publications','library']) {
   await page.evaluate(async(workspace)=>{
    state.libraryTab=workspace;makeButton(workspace);
    // Old GET in flight and an empty cache must be replaced by the mutation.
    state.paperFileRequests[workspace]=Promise.resolve({files:[]});state.paperFilesByPaperId[workspace]={files:[]};
    const button=document.querySelector('button');const rect=button.getBoundingClientRect();
    await handleNativeFinderDrop(['/Users/fixture/Desktop/paper.PDF'],{x:rect.x+5,y:rect.y+5});
   },workspace);
   const snapshot=await page.evaluate(workspace=>({call:calls.at(-1),files:state.paperFilesByPaperId[workspace].files,pending:Boolean(state.paperFileRequests[workspace]),render:rendered.at(-1)}),workspace);
   assert.equal(snapshot.call.url,'/api/manual-pdf-path');assert.equal(snapshot.call.payload.context,workspace);
   assert.equal(snapshot.call.payload.paper_id,workspace);assert.equal(snapshot.files.length,1);assert.equal(snapshot.pending,false);
   assert.ok(snapshot.render.includes('"id":42'));
  }
  await page.evaluate(async()=>{
   makeButton('old');wireLibraryPdfDropTarget($('libraryDetail'),{paper_id:'old'});
   // Replace the button while the drop session is in progress; delegate must
   // use its new paper ID, not a closure from a prior selection.
   makeButton('current',true);wireLibraryPdfDropTarget($('libraryDetail'),{paper_id:'current'});
   const file=new File(['%PDF fixture'],'local.pdf',{type:'application/pdf'});
   const transfer=new DataTransfer();transfer.items.add(file);
   document.querySelector('button span').dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer}));
   document.querySelector('button span').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
  });
  await page.waitForFunction(()=>updated.current);
  assert.equal(await page.evaluate(()=>calls.filter(c=>c.payload.paper_id==='current').length),1);
  assert.equal(await page.evaluate(()=>calls.at(-1).url),'/api/manual-pdf');
  assert.equal(await page.locator('#libraryDetailStatus').textContent(),'PDF replaced');
  await page.evaluate(async()=>{
   state.libraryTab='my-publications';makeButton('busy');document.querySelector('button').disabled=true;
   const r=document.querySelector('button').getBoundingClientRect();await handleNativeFinderDrop(['/tmp/paper.pdf'],{x:r.x+2,y:r.y+2});
  });
  assert.ok((await page.locator('#libraryDetailStatus').textContent()).includes('already running'));
  assert.equal(await page.evaluate(()=>calls.some(c=>c.payload.paper_id==='busy')),false);
  await page.evaluate(async()=>{makeButton('invalid');let r=document.querySelector('button').getBoundingClientRect();await handleNativeFinderDrop(['/tmp/one.pdf','/tmp/two.pdf'],{x:r.x+2,y:r.y+2});});
  assert.equal(await page.locator('#libraryDetailStatus').textContent(),'Drop exactly one PDF file here.');
  await page.evaluate(async()=>{await handleNativeFinderDrop(['/tmp/paper.pdf'],{x:600,y:600});});
  assert.equal(await page.evaluate(()=>state.libraryTab),'my-publications');
  assert.ok((await page.locator('#libraryDetailStatus').textContent()).includes('Drop the PDF on'));
  assert.deepEqual(errors,[]);
  console.log('PDF drop UI passed: Finder paths in both workspaces, current button after replacement, current file snapshot, stale-read invalidation, busy/multiple-file/missed-target handling.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
