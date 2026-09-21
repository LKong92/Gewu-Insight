// Generated local files and UI only: no formal SQLite, Library or browser profile.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const {execFileSync} = require('node:child_process');
const {chromium, webkit} = require('playwright');
const root = path.resolve(__dirname, '..');
const html = JSON.parse(execFileSync(process.env.GEWU_TEST_PYTHON || 'python3', ['-c', 'import json; from paper_monitor.ui_server import INDEX_HTML; print(json.dumps(INDEX_HTML))'], {cwd: root, encoding: 'utf8', maxBuffer: 8*1024*1024}));
function fn(name) {
  const start = html.search(new RegExp('    (?:async )?function '+name+'\\('));
  assert.ok(start >= 0, name);
  const text = html.slice(start), end = text.slice(1).search(/\n    (?:async )?function /);
  return text.slice(0, end+1);
}
const note = '# Research notes\n\n## 分析结果\n\nA **strong result**, *emphasis*, and `inline code`.\n\n1. First point\n2. Second point\n   - Nested evidence\n\n> A quoted observation.\n\n```python\nprint("result")\n```\n\n| Method | Result |\n| --- | --- |\n| Measurement | 42 |\n\n[Paper](https://example.org/paper)\n';
let workerLoads = 0;
const server = http.createServer((req,res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/markdown-preview-worker.js' || url.pathname === '/markdown-it.min.js' || url.pathname === '/js-yaml.min.js') {
    workerLoads++;
    res.setHeader('Content-Type','text/javascript');
    res.end(fs.readFileSync(path.join(root,'paper_monitor',url.pathname.includes('worker') ? 'markdown_preview_worker.js' : url.pathname.includes('yaml') ? 'vendor/js-yaml/js-yaml.min.js' : 'vendor/markdown-it/markdown-it.min.js')));
  } else if (url.pathname === '/api/markdown-preview') {
    const file = url.searchParams.get('path');
    const reply = () => {res.setHeader('Content-Type','application/json');res.end(JSON.stringify({text:file.includes('large') ? note.repeat(550) : note.replace('Research notes', file.includes('new') ? 'Latest note' : 'Research notes'), truncated:false}));};
    if (file.includes('slow')) setTimeout(reply, 350); else reply();
  } else {res.setHeader('Content-Type','text/html');res.end('<!doctype html><html><body></body></html>');}
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await (process.env.GEWU_TEST_WEBKIT ? webkit : chromium).launch({headless:true, ...(process.env.GEWU_TEST_CHROME ? {executablePath:process.env.GEWU_TEST_CHROME} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1100,height:900}});
    const errors=[]; page.on('pageerror', e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.setContent(`<style>${html.match(/<style>([\s\S]*?)<\/style>/)[1]}</style><style>body{display:block;min-width:0;background:#fff}#rail{position:absolute;left:16px;top:20px;width:30px;height:240px}#cards{position:absolute;left:65px;top:20px;width:390px}.library-resource-column{width:100%}#libraryQuickLookPages{position:absolute;left:470px;right:10px;top:20px;bottom:20px;overflow:auto;border:1px solid #ddd} </style><aside class="library-tab-rail keyboard-active" id="rail"><button id="tab" class="library-tab workspace-tab active" style="--library-tab-length:185px;--library-vertical-tab-thickness:30px;--tab-top:0px"><span>Wigner Crystal</span></button></aside><div id="cards"></div><div id="libraryQuickLookPages"></div>`);
    await page.evaluate(() => {
      window.$ = id => document.getElementById(id);
      window.state = {libraryQuickLookOpen:true,libraryQuickLookKind:'file',libraryQuickLookRenderToken:1,libraryQuickLookPath:'/tmp/note.md',expandedPaperResourceProperties:new Set()};
      window.escapeHtml = value => String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
      window.escapeAttr=escapeHtml; window.paperNativePath=p=>p.path||''; window.fileNameFromPath=p=>p.split('/').pop();
      window.paperFilesSnapshot=()=>({files:[{id:1,display_name:'Analysis.md',local_path:'/tmp/note.md',extension:'.md',size_bytes:1280,exists:true}]});
      window.libraryPaperDisplayName=()=> 'Analysis results';
      window.paperFileRoleLabel=()=> 'Other'; window.paperFileRoleOptions=()=> '<option>Other</option>';
      window.paperFileAnnotationLabel=()=> 'Unannotated'; window.paperFileAnnotationOptions=()=> '<option>Unannotated</option>';
      window.paperFileSourceLabel=()=> 'User import'; window.paperFileSourceOptions=()=> '<option>User import</option>';
      window.fileSizeLabel=()=> '1.2 KB'; window.setLibraryPaperResourceSelection=()=>{};
      // File imports are covered by the drop probe; this fixture only previews.
      window.wireLibraryPaperFilesDropTarget=()=>{};
      window.openWebsite=url=>window.openedWebsite=url;
      window.renderLibraryFilePreviewCard=(root,paper,message)=>root.textContent=message;
      window.nativeDrags=[];window.webkit={messageHandlers:{nativeFileDrag:{postMessage:p=>nativeDrags.push(p)}}};
    });
    const functions = ['libraryNativeFileDragAttrs','libraryDragToken','prepareNativeFileDrag','orderedLibraryPaperResources','libraryPaperResourcesColumnMarkup','wireLibraryResourceInteractions','libraryFileExtension','libraryFilePreviewKind','nativeFilePreviewUrl','libraryFilePreviewTitle'];
    await page.addScriptTag({content:functions.map(fn).join('\n')+'\n'+html.split('    let libraryMarkdownWorker = null;')[1].split('    async function quickLookLibraryFile')[0].replace(/^/,'let libraryMarkdownWorker = null;')});
    await page.evaluate(() => {
      const shell=$('cards'); shell.innerHTML=libraryPaperResourcesColumnMarkup({paper_id:'fixture',paper:{title:'Analysis results'}});
      wireLibraryResourceInteractions(shell);
      shell.addEventListener('mousedown', event => {if(event.button===0) {const handle=event.target.closest('[data-native-file-drag-handle]');if(handle) prepareNativeFileDrag(handle);}});
      window.showNote=(path,kind='file')=>{cancelLibraryMarkdownPreview();state.libraryQuickLookPath=path;state.libraryQuickLookKind=kind;state.libraryQuickLookRenderToken++;if(kind==='file')return renderLibraryQuickLookFilePreview({path},state.libraryQuickLookRenderToken);$('libraryQuickLookPages').innerHTML='<div id="pdf-fixture">PDF remains selected</div>';};
    });
    assert.equal(workerLoads,0,'renderer must not load at startup');
    await page.locator('#tab').focus();
    const ring=await page.locator('#tab').evaluate(el=>{const a=getComputedStyle(el),b=getComputedStyle(el,'::after');return {outline:a.outlineStyle,bottom:b.borderBottomWidth,top:b.borderTopWidth,left:b.borderLeftWidth,right:b.borderRightWidth};});
    assert.deepEqual(ring,{outline:'none',bottom:'0px',top:'2px',left:'2px',right:'2px'});
    const toggle=page.locator('[data-library-resource-toggle]');
    assert.equal(await toggle.getAttribute('aria-expanded'),'false');
    assert.equal(await toggle.locator('.resource-properties-chevron').textContent(),'⌄');
    await toggle.click();
    assert.equal(await toggle.getAttribute('aria-expanded'),'true');
    assert.equal(await toggle.locator('.resource-properties-chevron').textContent(),'⌃');
    await page.locator('.library-resource-name').dispatchEvent('mousedown',{button:0});
    await page.locator('.library-resource-icon-tile').dispatchEvent('mousedown',{button:0});
    assert.deepEqual(await page.evaluate(()=>nativeDrags.map(p=>p.path)),['/tmp/note.md','/tmp/note.md']);
    await page.evaluate(()=>showNote('/tmp/note.md'));
    await page.waitForSelector('.library-markdown-document table');
    assert.equal(await page.locator('.library-markdown-document h1').textContent(),'Research notes');
    for (const tag of ['strong','em','pre','table','blockquote','ol','ul']) assert.ok(await page.locator('.library-markdown-document '+tag).count(),tag);
    await page.locator('[data-markdown-url]').click();
    assert.equal(await page.evaluate(()=>openedWebsite),'https://example.org/paper');
    await page.evaluate(()=>showNote('/tmp/slow.md'));
    await page.evaluate(()=>showNote('/tmp/new.md'));
    await page.waitForFunction(()=>document.querySelector('.library-markdown-document h1')?.textContent==='Latest note');
    await page.waitForTimeout(400);
    assert.equal(await page.locator('.library-markdown-document h1').textContent(),'Latest note');
    await page.evaluate(()=>{showNote('/tmp/slow.md');showNote('/tmp/paper.pdf','pdf');});
    await page.waitForTimeout(400);
    assert.equal(await page.locator('#pdf-fixture').textContent(),'PDF remains selected');
    await page.evaluate(()=>showNote('/tmp/note.md'));
    await page.waitForSelector('.library-markdown-document table');
    for (const width of [900,1100,1400]) {
      await page.setViewportSize({width,height:900});
      const overflow=await page.locator('.library-markdown-document').evaluate(el=>el.scrollWidth>el.clientWidth+1);
      assert.equal(overflow,false);
    }
    await page.locator('#tab').focus();
    await page.screenshot({path:'/private/tmp/gewu-library-ui-refinements.png'});
    await page.evaluate(()=>{window.longTasks=[];window.observer=new PerformanceObserver(list=>longTasks.push(...list.getEntries().map(e=>e.duration)));try{observer.observe({type:'longtask',buffered:false});}catch(_){};showNote('/tmp/large.md');});
    await page.waitForSelector('.library-markdown-document table');
    assert.equal(workerLoads,3,'one worker and both offline parsers for all file switches');
    assert.deepEqual(errors,[]);
    console.log('Library preview UI checks passed: open focus ring, arrows, both drag handles, rendered Markdown, obsolete replies, PDF transition, three widths; long tasks (ms):',await page.evaluate(()=>longTasks));
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;server.close();});
