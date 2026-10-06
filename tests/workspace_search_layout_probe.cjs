// Actual workspace search CSS/functions, synthetic contents and no live APIs.
const assert = require('node:assert/strict');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const html = execFileSync(path.join(root,'.venv/bin/python'), ['-c',
  'from paper_monitor.ui_server import INDEX_HTML; print(INDEX_HTML)'], {cwd:root,maxBuffer:8e6}).toString();
const styles = html.match(/<style>([\s\S]*?)<\/style>/)[1];
const markup = '<div class="library-search-tools" id="librarySearchTools">' +
  html.split('<div class="library-search-tools" id="librarySearchTools">')[1].split('</div>\n          </div>')[0] + '</div>';
const helpers = 'function updateLibrarySearchTools()' + html.split('function updateLibrarySearchTools()')[1].split('function updateLibraryViewToggle()')[0];
const searchBindings = '$("librarySearchBox").closest(".library-search-wrap")' + html.split('$("librarySearchBox").closest(".library-search-wrap")')[1].split('$("librarySearchBox").addEventListener("input",')[0];
const functionSource = name => {
  const start = html.indexOf('    function '+name+'(');
  return html.slice(start, html.indexOf('\n    function ', start + 1));
};
const routing = ['normalizeQuickLookMode','quickLookUsesNativeForPaper','libraryPaperIsPdfLike','libraryFileExtension','libraryFilePreviewKind'].map(functionSource).join('\n');
const fonts = 'function normalizeFontSizeScale(' + html.split('function normalizeFontSizeScale(')[1].split('function applyFontSizeSettings(')[0];
(async()=>{
  const browser = await chromium.launch({headless:true,...(process.env.GEWU_TEST_CHROME?{executablePath:process.env.GEWU_TEST_CHROME}:{})});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:300},deviceScaleFactor:2});
    await page.route('**/*',r=>r.abort());
    await page.setContent('<style>'+styles+'</style><style>body{background:#fff}#bar{height:40px;background:#dae6ff}.app{display:block}</style><div id="bar"></div><div class="app">'+markup+'</div>');
    await page.evaluate(()=>{
      window.state={mode:'library',libraryTab:'library'}; window.$=id=>document.getElementById(id);
      window.updateLibraryViewToggle=()=>{};
    });
    await page.addScriptTag({content:helpers+fonts+searchBindings+routing});
    const field=page.locator('#librarySearchBox');
    for(const width of [1000,1440,1920]) {
      await page.setViewportSize({width,height:300});
      for(const scale of [90,100,110,120,130]) {
        for(const scope of ['library','my-publications','report','theme','author']) {
          await page.evaluate(({scope,scale})=>{
            state.mode=scope==='my-publications'?'library':scope;
            state.libraryTab=scope==='my-publications'?scope:'library';
            setSurfaceSearchQuery(scope,''); updateLibrarySearchTools(); applyFontSizeScale(scale);
          },{scope,scale});
          await field.focus();
          await page.waitForFunction(()=>document.querySelector('.library-search-wrap').getBoundingClientRect().width>=291);
          const g=await field.evaluate(el=>{
            const r=el.getBoundingClientRect(),s=getComputedStyle(el),icon=document.querySelector('.library-search-icon').getBoundingClientRect();
            return {y:r.y,bottom:r.bottom,height:r.height,width:r.width,shadow:s.boxShadow,radius:s.borderRadius,
              font:parseFloat(s.fontSize),label:el.getAttribute('aria-label'),placeholder:el.placeholder,icon:icon.height};
          });
          assert.equal(g.height,26); assert.equal(g.y,7); assert.equal(g.bottom,33);
          assert.equal(g.shadow,'none'); assert.equal(g.radius,'4px'); assert.equal(g.icon,16);
          assert.ok(g.font>=11.7&&g.font<=16.9); assert.equal(g.label,g.placeholder);
          await field.fill('quantum');
          await page.evaluate(()=>{setSurfaceSearchQuery(currentSurfaceSearchScope(),'quantum');updateLibrarySearchTools();});
          await field.blur();
          assert.equal(await field.inputValue(),'quantum');
          assert.ok(await page.locator('#clearLibrarySearch').isVisible());
        }
      }
    }
    await field.fill('majorana quantum');
    await field.dblclick({position:{x:45,y:13}});
    assert.equal(await field.evaluate(el=>el.value.slice(el.selectionStart,el.selectionEnd)), 'majorana');
    await page.keyboard.type('topological');
    assert.equal(await field.inputValue(), 'topological quantum');
    const box = await field.boundingBox();
    await page.mouse.move(box.x+120,box.y+13);
    await page.mouse.down();
    await page.mouse.move(box.x+10,box.y+13,{steps:15});
    await page.mouse.up();
    const selection = await field.evaluate(el=>({start:el.selectionStart,end:el.selectionEnd,value:el.value}));
    assert.ok(selection.end>selection.start, 'drag must retain a text selection after mouseup/click');
    await page.keyboard.press('Backspace');
    assert.equal(await field.inputValue(),selection.value.slice(0,selection.start)+selection.value.slice(selection.end));
    await page.evaluate(()=>{
      window.paperNativePath = paper=>paper.source_path||'';
      for (const mode of ['builtin_all','hybrid','native_all']) {
        state.quickLookMode=mode;
        for (const ext of ['pdf','md','markdown','mdown','mkd','pptx','png','txt']) {
          const expected=mode==='native_all'||(mode==='hybrid'&&!['pdf','md','markdown','mdown','mkd'].includes(ext));
          const paper={file_extension:ext,import_kind:ext==='pdf'?'pdf':'file',source_path:'/fixture/file.'+ext};
          if(quickLookUsesNativeForPaper(paper)!==expected) throw new Error(mode+' '+ext);
          if(ext!=='pdf') {
            delete paper.file_extension;
            if(quickLookUsesNativeForPaper(paper)!==expected) throw new Error('path fallback '+mode+' '+ext);
          }
        }
      }
    });
    await page.evaluate(()=>{state.mode='author';setSurfaceSearchQuery('author','');updateLibrarySearchTools();applyFontSizeScale(100);});
    await field.focus();
    if(process.env.GEWU_SEARCH_SCREENSHOT) await page.locator('#bar').screenshot({path:process.env.GEWU_SEARCH_SCREENSHOT});
    console.log('Native double-click/drag/replacement/deletion and all Quick Look routing modes passed. Search layout passed: five workspaces, three widths, five font scales, flat 26px field with 7px vertical margins, focus/typing/query retention/clear visibility and scoped labels.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
