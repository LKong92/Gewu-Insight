// Disposable Quick Look page using the product CSS, handlers and offline worker.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {execFileSync,spawn}=require('node:child_process');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const html=JSON.parse(execFileSync(process.env.GEWU_TEST_PYTHON||'python3',['-c','import json; from paper_monitor.ui_server import INDEX_HTML; print(json.dumps(INDEX_HTML))'],{cwd:root,encoding:'utf8',maxBuffer:8*1024*1024}));
const qa=process.env.GEWU_UI_QA_DIR||'/private/tmp/gewu-markdown-quicklook-qa';
fs.mkdirSync(qa,{recursive:true});
function fn(name){const start=html.search(new RegExp('    (?:async )?function '+name+'\\('));assert(start>=0,name);const text=html.slice(start),end=text.slice(1).search(/\n    (?:async )?function /);return text.slice(0,end+1);}
const note='---\ngewu_ai: {"gewu_key":"gw_0123456789","connection":"Fixture","source_sha256":"'+'a'.repeat(64)+'","pages":[1,2,30]}\n---\n\n---\ntitle: "研究笔记：机器人实验室"\nauthors: ["First Author", "另一位作者", "A long author name"]\ntags:\n  - AI\n  - Chemistry\nsummary: |\n  第一行说明\n  第二行说明\nsource_sha256: "'+'b'.repeat(64)+'"\n---\n\n# 正文标题\n\n'+'很长的中英文说明 LongURLwithoutspaces'.repeat(12)+'\n\n```text\n'+('long_code_'.repeat(80))+'\n```\n\n|'+Array.from({length:16},(_,i)=>'Column '+i).join('|')+'|\n|'+Array(16).fill('---').join('|')+'|\n|'+Array(16).fill('Long content preserved').join('|')+'|\n\n## 普通小标题\n\n[Website](https://example.org/reading)\n';
let externalNote=process.env.GEWU_TEST_NOTE_PATH?fs.readFileSync(process.env.GEWU_TEST_NOTE_PATH,'utf8'):null;
const shell=html.slice(html.indexOf('      <div class="library-quicklook"'),html.indexOf('      <div class="settings-backdrop" id="libraryNavBackdrop"'));
const handlers=['libraryFileExtension','libraryFilePreviewKind','nativeFilePreviewUrl','libraryFilePreviewTitle','renderLibraryQuickLookFileThumb','quickLookLibraryFile','defaultLibraryMarkdownQuickLookFrame','defaultLibraryQuickLookFrame','applyLibraryQuickLookFrame','closeLibraryQuickLook','quickLookLibraryPdf'];
const markdownHandlers='let libraryMarkdownWorker = null;'+html.split('    let libraryMarkdownWorker = null;')[1].split('    async function quickLookLibraryFile')[0];
const setup=`
window.$=id=>document.getElementById(id);
window.state={libraryQuickLookOpen:false,libraryQuickLookKind:'',libraryQuickLookRenderToken:0,libraryQuickLookPath:'',libraryQuickLookManualFrame:false,libraryColumnWidths:{},libraryActiveFolderId:1};
window.paperNativePath=p=>p.path||p.native_file_path||'';
window.escapeHtml=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');window.escapeAttr=escapeHtml;
window.libraryPreviewPathTitle=(p,f)=>f;window.fileNameFromPath=p=>p.split('/').pop();
window.nativeQuickLookBridgeAvailable=()=>false;window.quickLookUsesNativeForPaper=()=>false;
window.captureLibraryQuickLookReturnFocus=()=>{};window.restoreLibraryQuickLookReturnFocus=()=>{};
window.setNativePdfQuickLookActive=()=>{};window.reclaimLibraryQuickLookFocus=()=>{};
window.openWebsite=url=>window.openedWebsite=url;
window.renderLibraryFilePreviewCard=(root,paper,message)=>{root.textContent=message;};
window.renderLibraryQuickLookThumbs=()=>{};window.renderLibraryQuickLookPages=()=>{$('libraryQuickLookPages').innerHTML='<p>PDF fixture</p>';};window.loadLibraryQuickLookInfo=()=>{};
window.addEventListener('resize',()=>{if(state.libraryQuickLookOpen&&$('libraryQuickLook').classList.contains('markdown-preview'))applyLibraryQuickLookFrame();});
`;
async function runChecks(){
 let count=0;const check=(v,m)=>{if(!v)throw Error(m);count++;};
 const wait=async test=>{const end=Date.now()+8000;while(!test()){if(Date.now()>end)throw Error('Markdown worker timeout');await new Promise(r=>setTimeout(r,20));}};
 const overlay=$('libraryQuickLook'),pages=$('libraryQuickLookPages');
 const bounds=()=>{const r=overlay.getBoundingClientRect();check(r.left>=10&&r.right<=innerWidth-10,'preview width stays on screen');check(r.top>=45&&r.bottom<=innerHeight-10,'preview height stays on screen');check(pages.scrollWidth<=pages.clientWidth+1,'document never overflows its reading pane');};
 state.libraryQuickLookManualFrame=false;await quickLookLibraryFile({path:'/fixture/note.md'});
 await wait(()=>pages.querySelector('.library-markdown-document h1'));
 bounds();check(overlay.clientWidth>=Math.min(990,innerWidth-36),'Markdown uses a readable initial width');
 const firstHTML=pages.querySelector('.library-markdown-document').innerHTML;
 const firstWorker=libraryMarkdownWorker;
 closeLibraryQuickLook();await quickLookLibraryFile({path:'/fixture/note.md'});await wait(()=>pages.querySelector('h1'));
 check(pages.querySelector('.library-markdown-document').innerHTML===firstHTML,'validated reopen keeps the complete rendering');
 check(libraryMarkdownWorker===firstWorker,'a repeated open keeps the ready worker');
 check(pages.querySelectorAll('.library-markdown-properties').length===2,'both leading metadata blocks are retained');
 check(!pages.querySelector('.library-markdown-properties').open,'source record is compact');
 check(pages.querySelectorAll('h1').length===1&&pages.querySelector('h1').textContent==='正文标题','only the body title is a heading');
 check(pages.querySelectorAll('h2').length===1,'ordinary headings remain');
 check(pages.querySelector('dd').textContent.includes('gw_'),'provenance fields are present');
 const props=pages.querySelectorAll('.library-markdown-properties')[1];check(props.open,'note properties are initially readable');
 check(props.textContent.includes('另一位作者')&&props.textContent.includes('第二行说明'),'arrays and multiline values are complete');
 check(getComputedStyle($('libraryQuickLookThumbs')).display==='none','Markdown has no redundant PDF thumbnail rail');
 const table=pages.querySelector('.library-markdown-table'),code=pages.querySelector('.library-markdown-document pre');
 check(table.scrollWidth>table.clientWidth,'wide table has its own scroll area');
 check(code.scrollWidth>code.clientWidth,'long code has its own scroll area');
 table.scrollLeft=table.scrollWidth;code.scrollLeft=code.scrollWidth;
 check(table.scrollLeft>0&&code.scrollLeft>0,'all wide content can be reached');
 pages.querySelector('[data-markdown-url]').click();check(openedWebsite==='https://example.org/reading','links retain website routing');
 for(const width of [360,520,800,1100]){applyLibraryQuickLookFrame({left:innerWidth-20,top:innerHeight-20,width,height:900});bounds();}
 applyLibraryQuickLookFrame(defaultLibraryMarkdownQuickLookFrame());
 const before=overlay.getBoundingClientRect().width;props.open=false;props.open=true;bounds();check(overlay.getBoundingClientRect().width===before,'property expansion does not resize the window');
 state.libraryQuickLookManualFrame=true;applyLibraryQuickLookFrame({left:20,top:60,width:480,height:500});
 closeLibraryQuickLook();await quickLookLibraryFile({path:'/fixture/reopen.md'});await wait(()=>pages.querySelector('h1'));check(overlay.clientWidth<=482,'manual width survives reopen');bounds();
 state.libraryQuickLookManualFrame=false;quickLookLibraryPdf({merged_pdf_path:'/fixture/paper.pdf'});
 check(!overlay.classList.contains('markdown-preview'),'PDF transition clears Markdown layout');
 check(getComputedStyle($('libraryQuickLookThumbs')).display!=='none','PDF thumbnails return');
 closeLibraryQuickLook();await quickLookLibraryFile({path:'/fixture/plain.txt'});check(!overlay.classList.contains('markdown-preview'),'ordinary file layout unchanged');
 closeLibraryQuickLook();await quickLookLibraryFile({path:'/fixture/final.md'});await wait(()=>pages.querySelector('h1'));bounds();
 return {checks:count,width:innerWidth,height:innerHeight};
}
const fixture='<!doctype html><html><head><meta charset="utf-8"><style>'+html.match(/<style>([\s\S]*?)<\/style>/)[1]+'</style><style>body{display:block;min-width:0;background:#f3f5f8}#libraryColumns{position:absolute;left:20px;top:60px;width:90vw;height:80vh}</style></head><body><div id="libraryColumns"></div>'+shell+'<script>'+setup+handlers.map(fn).join('\n')+'\n'+markdownHandlers+'\nwindow.runChecks='+runChecks.toString()+';</script></body></html>';
const resources={'/markdown-preview-worker.js':'markdown_preview_worker.js','/markdown-it.min.js':'vendor/markdown-it/markdown-it.min.js','/js-yaml.min.js':'vendor/js-yaml/js-yaml.min.js'};
const server=http.createServer((req,res)=>{const url=new URL(req.url,'http://localhost');if(resources[url.pathname]){res.setHeader('Content-Type','text/javascript');res.end(fs.readFileSync(path.join(root,'paper_monitor',resources[url.pathname])));}else if(url.pathname==='/api/markdown-preview'){res.setHeader('Content-Type','application/json');res.setHeader('ETag','W/"fixture-v1"');if(req.headers['if-none-match']==='W/"fixture-v1"'){res.statusCode=304;res.end();}else{res.end(JSON.stringify({text:url.searchParams.get('path').includes('reported')&&externalNote?externalNote:note,truncated:false}));}}else if(url.pathname==='/api/native-file-preview'){res.end('Plain text fixture');}else{res.setHeader('Content-Type','text/html');res.end(fixture);}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const url=`http://127.0.0.1:${server.address().port}/`;let browser;
 try {
  if(process.env.GEWU_NATIVE_PROBE){await new Promise((resolve,reject)=>{const child=spawn(process.env.GEWU_NATIVE_PROBE,[url],{stdio:'inherit'});child.on('exit',code=>code?reject(Error('Native probe failed: '+code)):resolve());child.on('error',reject);});return;}
  browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>route.request().url().startsWith(url)?route.continue():route.abort());
  for(const width of [1280,800,520]){await page.setViewportSize({width,height:900});await page.goto(url);console.log('Quick Look',await page.evaluate(()=>runChecks()));await page.screenshot({path:path.join(qa,`markdown-${width}.png`)});}
  // The same live preview also reflows if the App window is narrowed.
  await page.setViewportSize({width:440,height:660});await page.waitForTimeout(100);assert.equal(await page.locator('#libraryQuickLookPages').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
  if(externalNote){await page.setViewportSize({width:1280,height:900});await page.evaluate(async()=>{closeLibraryQuickLook();state.libraryQuickLookManualFrame=false;await quickLookLibraryFile({path:'/fixture/reported.md'});});await page.waitForSelector('.library-markdown-document h1');assert.equal(await page.locator('.library-markdown-properties').count(),2);assert.equal(await page.locator('#libraryQuickLookPages').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);await page.screenshot({path:path.join(qa,'reported-note.png')});console.log('Reported note rendered read-only with both metadata blocks.');}
  assert.deepEqual(errors,[]);console.log('Markdown Quick Look UI checks passed');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(error=>{console.error(error);process.exitCode=1;server.close();});
