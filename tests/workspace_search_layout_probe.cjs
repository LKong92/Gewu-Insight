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
    await page.addScriptTag({content:helpers+fonts});
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
    await page.evaluate(()=>{state.mode='author';setSurfaceSearchQuery('author','');updateLibrarySearchTools();applyFontSizeScale(100);});
    await field.focus();
    if(process.env.GEWU_SEARCH_SCREENSHOT) await page.locator('#bar').screenshot({path:process.env.GEWU_SEARCH_SCREENSHOT});
    console.log('Search layout passed: five workspaces, three widths, five font scales, flat 26px field with 7px vertical margins, focus/typing/query retention/clear visibility and scoped labels.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
