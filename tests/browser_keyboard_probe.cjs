// Actual product chrome + primary navigation, isolated generated documents only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root,p),'utf8');
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.GEWU_TEST_CHROME ? {executablePath:process.env.GEWU_TEST_CHROME} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1200,height:800}}), errors=[];
    page.on('pageerror', e=>errors.push(e.message));
    await page.route('**/*', route=>route.abort());
    await page.setContent('<style>*{box-sizing:border-box}body{margin:0}</style><div id="primaryViewSwitcher">'+['libraryMode','myPublicationsMode','reportMode','themeMode','authorMode','browserMode'].map(id=>`<button id="${id}">${id}</button>`).join('')+'</div>');
    await page.addStyleTag({content:read('paper_monitor/browser_ui.css')});
    await page.evaluate(() => {
      window.$=id=>document.getElementById(id);
      window.state={mode:'browser',primaryKeyboardLayer:'content'};
      window.commands=[];
      window.webkit={messageHandlers:{browser:{postMessage:c=>commands.push(c)}}};
      window.setPrimaryView=mode=>{state.mode=mode; gewuBrowser.setActive(mode==='browser');};
      window.openAuthorMonitor=()=>setPrimaryView('author');
      window.openThemeMonitor=()=>setPrimaryView('theme');
      window.openJournalMonitor=()=>setPrimaryView('report');
      window.loadMyPublications=()=>{state.libraryTab='my-publications';setPrimaryView('library');};
      window.loadLibrary=()=>{state.libraryTab='library';setPrimaryView('library');};
      window.showMonitorStatusMessage=()=>{};
      window.fetch=async()=>({ok:true,json:async()=>({bookmarks:[
        {id:1,kind:'folder',title:'Favorites',parent_id:null},
        ...Array.from({length:15},(_,i)=>({id:i+2,kind:'bookmark',title:'Public '+i,url:'https://example.org/'+i,parent_id:1}))
      ],history:[{id:1,title:'Public history',url:'https://example.org/',visited_at:'2026-09-06T00:00:00Z'}],preferences:{expanded:[1],sidebar_width:190},history_more:false})});
    });
    const source=read('paper_monitor/ui_server.py');
    const primary='const PRIMARY_KEYBOARD_VIEWS ='+source.split('const PRIMARY_KEYBOARD_VIEWS =')[1].split('function reportKeyboardTargetIsEditable')[0];
    await page.addScriptTag({content:primary});
    await page.addScriptTag({content:read('paper_monitor/browser_keyboard.js')});
    await page.addScriptTag({content:read('paper_monitor/browser_ui.js')});
    await page.evaluate(()=>{
      window.addEventListener('keydown',e=>{if(handlePrimaryKeyboardNavigation(e))return; gewuBrowser.handleKeydown(e);},true);
      gewuBrowser.setActive(true);
      gewuBrowserNativeEvent({event:'state',tab_id:'one',home:true,url:'',title:'Favorites'});
      gewuBrowserNativeEvent({event:'tabs',tabs:[{id:'one',title:'Favorites',home:true},{id:'two',title:'Example',url:'https://example.org/'}]});
      gewuBrowser.focusToolbar();
    });
    const focused=()=>page.evaluate(()=>document.activeElement.id || document.activeElement.dataset.browserTab || document.activeElement.dataset.favoriteId || document.activeElement.dataset.bookmarkId);
    const key=async k=>{await page.keyboard.press(k);await page.waitForTimeout(35);};
    assert.equal(await focused(),'browserSidebarToggle');
    await key('ArrowUp'); assert.equal(await focused(),'browserMode');
    await key('ArrowLeft'); assert.equal(await focused(),'authorMode');
    await key('ArrowRight'); assert.equal(await focused(),'browserMode');
    await key('ArrowDown'); assert.equal(await focused(),'browserSidebarToggle');
    await key('ArrowDown'); assert.equal(await focused(),'one');
    await key('ArrowRight'); assert.equal(await focused(),'two');
    assert.equal(await page.evaluate(()=>commands.filter(c=>c.action==='select-tab').at(-1).tab_id),'two');
    await key('ArrowLeft'); await key('ArrowDown'); assert.equal(await focused(),'2');
    await key('ArrowRight'); assert.equal(await focused(),'3');
    await key('ArrowUp'); assert.equal(await focused(),'one');
    await key('ArrowLeft'); assert.equal(await focused(),'browserBookmarksTab');
    await key('ArrowDown'); assert.equal(await focused(),'1');
    await key('ArrowDown'); assert.equal(await focused(),'2');
    await key('ArrowRight'); assert.equal(await focused(),'2'); // first Favorite
    assert.equal(await page.evaluate(()=>!!document.activeElement.closest('#browserFavorites')),true);
    await page.click('#browserHistoryTab');
    await page.evaluate(()=>gewuBrowser.focusSidebar());
    assert.equal(await focused(),'browserHistoryTab');
    await key('ArrowDown'); assert.equal(await page.evaluate(()=>document.activeElement.dataset.historyId),'1');
    await key('ArrowUp'); assert.equal(await focused(),'browserHistoryTab');
    await key('ArrowRight'); assert.equal(await page.evaluate(()=>!!document.activeElement.closest('#browserFavorites')),true);
    await page.click('#browserSidebarToggle');
    await page.evaluate(()=>gewuBrowser.focusTabs()); await key('ArrowLeft');
    assert.equal(await focused(),'one','hidden sidebar cannot be selected');
    await key('ArrowUp');
    // Disabled toolbar items are skipped; address becomes an editable field
    // only on Enter/click/typing. Editing arrows belong to the text field.
    for(let i=0;i<3;i++) await key('ArrowRight');
    assert.equal(await focused(),'browserAddress');
    await key('Enter'); await page.keyboard.type('nature'); await key('ArrowLeft');
    assert.equal(await page.$eval('#browserAddress',e=>e.value),'nature');
    assert.equal(await focused(),'browserAddress');
    await key('Escape'); assert.equal(await focused(),'browserHome');
    await page.click('#browserSidebarToggle'); await page.click('#browserBookmarksTab');
    await page.click('#browserBookmarkMenu');
    assert.equal(await focused(),'browserImportBookmarks');
    await key('ArrowDown'); assert.equal(await focused(),'browserExportBookmarks');
    await key('ArrowDown'); assert.equal(await focused(),'browserSyncSafari');
    await key('ArrowDown'); assert.equal(await focused(),'browserSyncChrome');
    await key('Enter');
    assert.equal(await page.evaluate(()=>commands.at(-1).source),'chrome');
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'bookmark-source-cancel'}));
    await page.click('#browserBookmarkMenu'); await key('Escape');
    assert.equal(await focused(),'browserBookmarkMenu');
    const geometry=await page.evaluate(()=>['browserBookmarkMenu','browserNewFolder','browserSidebarSearch'].map(id=>{const r=$(id).getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,width:r.width};}));
    assert.ok(geometry[0].right<=geometry[1].left && geometry[1].right<=geometry[2].left && geometry[2].right<=190);
    assert.ok(geometry[2].width>90,'search remains usable at minimum sidebar width');
    await page.evaluate(()=>{gewuBrowserNativeEvent({event:'state',tab_id:'two',home:false,url:'https://example.org/'});gewuBrowser.focusTabs();});
    await key('ArrowDown'); assert.equal(await page.evaluate(()=>commands.at(-1).action),'focus');
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'focus-chrome',destination:'tabs'}));
    await key('ArrowUp'); await key('ArrowUp'); assert.equal(await focused(),'browserMode');
    for(let i=0;i<5;i++) await key('ArrowLeft'); assert.equal(await focused(),'libraryMode');
    assert.deepEqual(errors,[]);

    const remote=await browser.newPage(); await remote.route('**/*',r=>r.abort());
    await remote.setContent('<main style="height:2000px"><input id="login" autocomplete="username"><textarea id="text"></textarea><button id="button">Test</button><div id="widget" role="listbox" tabindex="0">Widget</div><div id="scroll" tabindex="0" style="overflow:auto;height:40px"><div style="height:400px">Scroll</div></div><iframe id="frame"></iframe></main>');
    const probe=read('scripts/GewuBrowserNavigationProbe.js');
    const boundary=()=>remote.evaluate(script=>eval('('+script+')("up")'),probe);
    assert.equal(await boundary(),true);
    for(const id of ['login','text','widget','frame']) {await remote.focus('#'+id);assert.equal(await boundary(),false,id);}
    await remote.focus('#button'); assert.equal(await boundary(),true);
    await remote.evaluate(()=>{document.activeElement.blur();scrollTo(0,200);}); assert.equal(await boundary(),false);
    await remote.evaluate(()=>{scrollTo(0,0);document.querySelector('#scroll').focus();document.querySelector('#scroll').scrollTop=200;});
    assert.equal(await boundary(),false,'nested scroll position blocks escape');
    console.log('Browser arrows: primary/toolbar/tabs/Favorites/sidebar, editing, menu, narrow footer and remote boundary exclusions passed.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
