// Documentation-only rendering of current product chrome with synthetic data.
// No live website, native App, user profile, SQLite, history, or credentials.
// Requires Playwright; GEWU_TEST_CHROME may select an installed Chrome binary.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');

(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.GEWU_TEST_CHROME ? {executablePath:process.env.GEWU_TEST_CHROME} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1200,height:770},deviceScaleFactor:2});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => route.abort());
    await page.setContent(`<style>*{box-sizing:border-box}body{margin:0;font:13px -apple-system,BlinkMacSystemFont,sans-serif}
      nav{height:40px;display:flex;align-items:stretch;background:#dae6ff;padding-left:30px;gap:6px}
      nav span,nav button{padding:12px 22px;border:0;background:transparent;font:600 12px -apple-system,sans-serif;color:#506078}
      nav button{background:#f6f6f7;color:#285981;border-radius:10px 10px 0 0}</style>
      <nav aria-label="Main workspaces"><span>Library</span><span>My Publications</span><span>Journal Monitor</span><span>Subject Monitor</span><span>Author Monitor</span><button id="browserMode">Browser</button></nav>`);
    await page.addStyleTag({content:fs.readFileSync(path.join(root,'paper_monitor/browser_ui.css'),'utf8')});
    await page.evaluate(() => {
      window.webkit = {messageHandlers:{browser:{postMessage(){}}}};
      window.fetch = async () => ({ok:true,json:async () => ({
        bookmarks:[
          {id:1,kind:'folder',title:'Favorites',parent_id:null},
          {id:2,kind:'bookmark',title:'Nature',url:'https://www.nature.com/',parent_id:1},
          {id:3,kind:'bookmark',title:'Science',url:'https://www.science.org/',parent_id:1},
          {id:4,kind:'bookmark',title:'Google Scholar',url:'https://scholar.google.com/',parent_id:1},
          {id:5,kind:'bookmark',title:'arXiv',url:'https://arxiv.org/',parent_id:1},
          {id:6,kind:'bookmark',title:'Physical Review Letters',url:'https://journals.aps.org/prl/',parent_id:1},
          {id:7,kind:'bookmark',title:'NASA ADS',url:'https://ui.adsabs.harvard.edu/',parent_id:1}
        ], history:[], preferences:{sidebar_width:270,expanded:[1]},history_more:false
      })});
    });
    await page.addScriptTag({content:fs.readFileSync(path.join(root,'paper_monitor/browser_ui.js'),'utf8')});
    await page.evaluate(() => {
      gewuBrowser.setActive(true);
      gewuBrowserNativeEvent({event:'state',tab_id:'home',home:true,url:'',loading:false,title:'Favorites'});
      gewuBrowserNativeEvent({event:'tabs',selected:'home',tabs:[
        {id:'home',title:'Favorites',home:true,url:''},
        {id:'nature',title:'Nature',url:'https://www.nature.com/'},
        {id:'scholar',title:'Google Scholar',url:'https://scholar.google.com/'}]});
    });
    await page.waitForFunction(() => document.querySelectorAll('[data-favorite-id]').length === 6);
    await page.waitForTimeout(150);
    assert.deepEqual(errors,[]);
    const geometry = await page.evaluate(() => {
      const r = selector => document.querySelector(selector).getBoundingClientRect();
      return {toolbar:r('.browser-toolbar').bottom,sidebar:r('#browserSidebar').top,
        tabs:r('#browserTabs').left,sidebarRight:r('#browserSidebar').right,
        leftFooter:r('.browser-sidebar-footer').top,rightFooter:r('.browser-page-footer').top};
    });
    assert.equal(geometry.toolbar,geometry.sidebar);
    assert.equal(geometry.tabs,geometry.sidebarRight);
    assert.ok(Math.abs(geometry.leftFooter-geometry.rightFooter)<1);
    const output = path.join(root,'assets/user-guide/screenshots/browser.png');
    await page.screenshot({path:output});
    console.log(`Rendered current Browser layout example: ${output}`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
