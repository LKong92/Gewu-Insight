// Product layout test with synthetic bookmarks only; no server or user profile.
// Run with Node.js + Playwright; GEWU_TEST_CHROME optionally selects an installed
// Chrome executable instead of Playwright's bundled headless browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.GEWU_TEST_CHROME ? {executablePath:process.env.GEWU_TEST_CHROME} : {})});
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(10000);
    console.log('Synthetic renderer ready');
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => route.abort());
    await page.setContent('<style>*{box-sizing:border-box}body{margin:0}</style><button id="browserMode">Browser</button>');
    await page.addStyleTag({content:fs.readFileSync(path.join(root,'paper_monitor/browser_ui.css'),'utf8')});
    await page.evaluate(() => {
      window.browserCommands = [];
      window.webkit = {messageHandlers:{browser:{postMessage(value){window.browserCommands.push(value);}}}};
      window.fetch = async () => ({ok:true,json:async () => ({
        bookmarks:[{id:1,kind:'folder',title:'Favorites',parent_id:null}, ...Array.from({length:25},(_, i) => ({id:i+2,parent_id:1,kind:'bookmark',title:'Public example '+i,url:'https://example.org/'+i}))],
        history:[],preferences:{sidebar_width:250},history_more:false
      })});
    });
    await page.addScriptTag({content:fs.readFileSync(path.join(root,'paper_monitor/browser_keyboard.js'),'utf8')});
    await page.addScriptTag({content:fs.readFileSync(path.join(root,'paper_monitor/browser_ui.js'),'utf8')});
    console.log('Product UI loaded');
    assert.deepEqual(errors,[]);
    await page.evaluate(() => {
      gewuBrowser.setActive(true);
      gewuBrowserNativeEvent({event:'state',tab_id:'first',home:true,url:'',loading:false,title:'Favorites'});
      gewuBrowserNativeEvent({event:'tabs',selected:'first',tabs:[{id:'first',title:'Favorites',home:true,url:''},{id:'second',title:'Nature',url:'https://www.nature.com/'},{id:'third',title:'Google Scholar',url:'https://scholar.google.com/'}]});
    });
    async function checkTabLayout() {
      const geometry = await page.evaluate(() => {
        const q = s=>document.querySelector(s), rect = s=>q(s).getBoundingClientRect();
        const bar=q('#browserTabs'), tabs=[...bar.children], sidebar=rect('#browserSidebar');
        const style=getComputedStyle(bar), column=rect('.browser-page-column'), viewport=rect(q('#browserFavorites').hidden ? '#browserViewport' : '#browserFavorites');
        return {toolbar:rect('.browser-toolbar').bottom, sidebarTop:sidebar.top, sidebarRight:sidebar.right,
          sidebarHidden:getComputedStyle(q('#browserSidebar')).display==='none',
          barTop:bar.getBoundingClientRect().top, barLeft:bar.getBoundingClientRect().left,
          barBottom:bar.getBoundingClientRect().bottom, barRight:bar.getBoundingClientRect().right,
          columnTop:column.top,columnLeft:column.left,viewportTop:viewport.top,
          native:[...browserCommands].reverse().find(c=>c.action==='layout'),viewport:{x:viewport.x,y:viewport.y,width:viewport.width,height:viewport.height},
          padding:style.padding,gap:style.columnGap,overflow:bar.scrollWidth>bar.clientWidth+1,
          tabs:tabs.map(t=>({left:t.getBoundingClientRect().left,right:t.getBoundingClientRect().right,radius:getComputedStyle(t).borderRadius,shadow:getComputedStyle(t).boxShadow}))};
      });
      assert.equal(geometry.columnTop,geometry.toolbar,'main area starts below the address toolbar');
      assert.equal(geometry.barTop,geometry.toolbar);
      assert.equal(geometry.barLeft,geometry.columnLeft);
      if (!geometry.sidebarHidden) {
        assert.equal(geometry.sidebarTop,geometry.toolbar,'sidebar is not pushed down by webpage tabs');
        assert.equal(geometry.barLeft,geometry.sidebarRight,'tabs belong only to the webpage column');
      } else assert.equal(geometry.barLeft,0);
      assert.equal(geometry.viewportTop,geometry.barBottom,'native webpage begins below its own tabs');
      assert.equal(geometry.padding,'0px'); assert.equal(geometry.gap,'0px');
      geometry.tabs.forEach((tab,i)=>{
        assert.equal(tab.radius,'0px'); assert.equal(tab.shadow,'none');
        if (i) assert.ok(Math.abs(tab.left-geometry.tabs[i-1].right)<1,'adjacent rectangular tabs must touch');
      });
      if (geometry.tabs.length && !geometry.overflow) {
        assert.ok(Math.abs(geometry.tabs[0].left-geometry.barLeft)<1);
        assert.ok(Math.abs(geometry.tabs.at(-1).right-geometry.barRight)<1,'tabs fill the main-area width');
      }
      for (const key of ['x','y','width','height']) assert.ok(Math.abs(geometry.native[key]-geometry.viewport[key])<1,'native viewport excludes tab strip');
    }
    for (const [width,height] of [[1500,1050],[1440,900],[1000,700],[700,560]]) {
      console.log('Checking',width,height);
      await page.setViewportSize({width,height});
      await page.waitForTimeout(100);
      await checkTabLayout();
      const seen = [];
      for (let attempt = 0; attempt < 30; attempt++) {
        const geometry = await page.evaluate(() => {
          const q = value => document.querySelector(value), favorites=q('#browserFavorites');
          const left=q('.browser-sidebar-footer').getBoundingClientRect(), right=q('.browser-page-footer').getBoundingClientRect();
          return {left:left.top,right:right.top,overflow:favorites.scrollHeight-favorites.clientHeight,
            contentOverflow:q('.browser-page-column').scrollHeight-q('.browser-page-column').clientHeight,
            titlesClipped:[...q('#browserFavoritesGrid').querySelectorAll('.browser-favorite-title')].some(x=>x.clientHeight+1 < Math.min(x.scrollHeight,parseFloat(getComputedStyle(x).lineHeight)*2)),
            ids:[...q('#browserFavoritesGrid').querySelectorAll('[data-favorite-id]')].map(x=>Number(x.dataset.favoriteId)),
            next:!q('#browserFavoritesPages').hidden && !q('#browserFavoritesNext').disabled};
        });
        assert.ok(Math.abs(geometry.left-geometry.right)<1, JSON.stringify(geometry));
        assert.ok(geometry.overflow<=1 && geometry.contentOverflow<=1, JSON.stringify(geometry));
        assert.equal(geometry.titlesClipped,false,'two-line titles must not lose their bottom pixels');
        seen.push(...geometry.ids);
        if (!geometry.next) break;
        await page.click('#browserFavoritesNext');
      }
      assert.deepEqual(seen,Array.from({length:25},(_,i)=>i+2));
      await page.evaluate(() => { for(let attempt=0;attempt<30&&!document.querySelector('#browserFavoritesPrevious').disabled;attempt++) document.querySelector('#browserFavoritesPrevious').click(); });
    }
    await page.setViewportSize({width:1500,height:1050});
    await page.evaluate(() => {
      for(let i=0;i<6;i++) document.querySelector('#browserResize').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
    });
    for (const tab of ['browserBookmarksTab','browserHistoryTab']) {
      await page.click('#'+tab);
      await page.waitForTimeout(100);
      const tops = await page.evaluate(() => ['.browser-sidebar-footer','.browser-page-footer'].map(selector=>document.querySelector(selector).getBoundingClientRect().top));
      assert.ok(Math.abs(tops[0]-tops[1])<1, 'wrapped footer alignment');
      await checkTabLayout();
    }
    await page.click('#browserSidebarToggle');
    await page.waitForTimeout(100);
    assert.equal(await page.locator('#browserSidebar').isVisible(),false);
    await checkTabLayout();
    await page.evaluate(() => gewuBrowserNativeEvent({event:'state',url:'https://example.org/article',loading:false}));
    assert.equal(await page.locator('#browserFavorites').isVisible(),false);
    await page.evaluate(() => {
      gewuBrowserNativeEvent({event:'state',tab_id:'first',home:true,url:'',loading:false,title:'Favorites'});
      gewuBrowserNativeEvent({event:'tabs',selected:'first',tabs:[{id:'first',title:'Favorites',home:true,url:''},{id:'second',title:'Nature',url:'https://www.nature.com/'},{id:'third',title:'<img src=x onerror=alert(1)>',url:'https://example.org/'}]});
    });
    assert.equal(await page.locator('#browserTabs [role=tab]').count(),3);
    assert.equal(await page.locator('#browserTabs [aria-selected=true]').getAttribute('data-browser-tab'),'first');
    assert.equal(await page.locator('#browserTabs img[src=x]').count(),0,'page titles must be escaped');
    assert.ok(await page.evaluate(() => {
      const first = document.querySelector('[data-browser-tab=first]');
      document.querySelector('#browserAddress').focus();
      gewuBrowserNativeEvent({event:'tabs',selected:'first',tabs:[{id:'first',title:'Favorites',home:true,url:''},{id:'second',title:'Nature (loaded)',url:'https://www.nature.com/'},{id:'third',title:'Public page',url:'https://example.org/'}]});
      return first === document.querySelector('[data-browser-tab=first]') && document.activeElement.id === 'browserAddress';
    }), 'background updates must retain nodes and input focus');
    await page.click('#browserNewTab');
    assert.ok(await page.evaluate(()=>browserCommands.some(command=>command.action==='new-tab')));
    await page.click('[data-browser-tab=second]');
    assert.ok(await page.evaluate(()=>browserCommands.some(command=>command.action==='select-tab'&&command.tab_id==='second')));
    await page.evaluate(() => gewuBrowserNativeEvent({event:'state',tab_id:'second',url:'https://www.nature.com/',loading:false,title:'Nature'}));
    assert.equal(await page.inputValue('#browserAddress'),'https://www.nature.com/');
    assert.equal(await page.locator('#browserFavorites').isVisible(),false);
    await page.click('[data-close-tab=second]');
    assert.ok(await page.evaluate(()=>browserCommands.some(command=>command.action==='close-tab'&&command.tab_id==='second')));
    await page.evaluate(() => gewuBrowserNativeEvent({event:'state',tab_id:'first',home:true,url:'',loading:false,title:'Favorites'}));
    await page.click('[data-favorite-id="2"]',{button:'right'});
    await page.getByRole('button',{name:'Open in New Tab',exact:true}).click();
    assert.ok(await page.evaluate(()=>browserCommands.some(command=>command.action==='new-tab'&&command.url==='https://example.org/0')));
    await page.click('#browserSidebarToggle');
    await page.click('#browserBookmarksTab');
    await page.evaluate(() => {
      for(let i=0;i<4;i++) document.querySelector('#browserResize').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
    });
    await page.waitForTimeout(100);
    await checkTabLayout();
    await page.screenshot({path:'/private/tmp/gewu-browser-tabs-synthetic.png'});
    for (const count of [1,2]) {
      await page.evaluate(count => gewuBrowserNativeEvent({event:'tabs',selected:'first',tabs:[{id:'first',title:'Favorites',home:true,url:''},...Array.from({length:count-1},(_,i)=>({id:'other'+i,title:'Public webpage '+i,url:'https://example.org/'+i}))]}), count);
      await page.waitForTimeout(100);
      await checkTabLayout();
    }
    await page.setViewportSize({width:700,height:560});
    await page.evaluate(() => gewuBrowserNativeEvent({event:'tabs',selected:'first',tabs:[{id:'first',title:'Favorites',home:true,url:''},...Array.from({length:31},(_,i)=>({id:'other'+i,title:'Public webpage '+i,url:'https://example.org/'+i}))]}));
    await page.waitForTimeout(100);
    await checkTabLayout();
    assert.ok(await page.evaluate(() => {
      const tabs = document.querySelector('#browserTabs');
      return tabs.scrollWidth > tabs.clientWidth && tabs.scrollHeight <= tabs.clientHeight + 1 && document.querySelector('#browserNewTab').getBoundingClientRect().right <= innerWidth;
    }), 'many tabs must scroll horizontally without hiding New Tab');
    await page.evaluate(() => gewuBrowserNativeEvent({event:'state',home:false,tab_id:'google',url:'https://www.google.com/',loading:false,title:'Google'}));
    assert.equal(await page.locator('#browserFavorites').isVisible(),false,'Google opened explicitly is an ordinary webpage');
    assert.equal(await page.locator('#browserViewport').isVisible(),true);
    await page.waitForTimeout(100); await checkTabLayout();
    await page.evaluate(() => gewuBrowserNativeEvent({event:'state',home:true,tab_id:'first',url:'',loading:false,title:'Favorites'}));
    assert.equal(await page.inputValue('#browserAddress'),'');
    assert.equal(await page.locator('#browserViewport').isVisible(),false,'no native webpage overlay on local Home');
    assert.equal(await page.locator('#browserShare').isDisabled(),true);
    assert.equal(await page.locator('#browserSiteIcon').getAttribute('draggable'),'false');
    await page.locator('#browserAddress').fill('quantum paper');
    await page.locator('#browserAddress').press('Enter');
    assert.ok(await page.evaluate(()=>browserCommands.some(c=>c.action==='navigate'&&c.url==='https://www.google.com/search?q=quantum%20paper')));
    assert.ok(await page.evaluate(()=>browserCommands.some(c=>c.action==='home')));
    assert.equal(await page.evaluate(()=>browserCommands.some(c=>c.action==='navigate'&&c.url==='https://www.google.com/')),false,'Home never requests Google');
    console.log('Tabs: square edge-to-edge tabs in the webpage column only, independent sidebar, native viewport geometry, chrome actions, per-tab state and focus passed.');
    assert.deepEqual(errors,[]);
    console.log('Home layout: footer alignment, no vertical overflow, every favorite, and ordinary-page layout passed.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
