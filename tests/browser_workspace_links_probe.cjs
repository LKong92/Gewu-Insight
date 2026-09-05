// Actual DOM/Browser-chrome routing using synthetic pages only. Every network
// request is intercepted; this does not use a saved browser or WebKit profile.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const workspace = fs.readFileSync(path.join(root, 'paper_monitor/ui_server.py'), 'utf8');
const router = 'function openWebsite(' + workspace.split('function openWebsite(')[1].split('async function openLibraryWebsite(')[0];
const primary = 'function captureBrowserWorkspaceReturn(' + workspace.split('function captureBrowserWorkspaceReturn(')[1].split('function wireWindowDragRegion(')[0];

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.GEWU_TEST_CHROME ? {executablePath:process.env.GEWU_TEST_CHROME} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:900}});
    const errors=[];
    page.on('pageerror', e=>errors.push(e.message));
    await page.route('**/*', route=>route.fulfill({contentType:'text/html',body:'<!doctype html><button id="browserMode">Browser</button><div class="app"><div class="sidebar"></div><div id="papers"><div id="source"></div></div></div>'}));
    await page.goto('http://127.0.0.1:8765/');
    await page.evaluate(() => {
      window.commands=[]; window.external=[]; window.statusMessages=[];
      window.state={mode:'library',libraryQuickLookOpen:false,librarySelectedId:17,selectedDate:'2026-09-06',authorMonitorSelectedId:9};
      window.open=(...args)=>external.push(args);
      window.webkit={messageHandlers:{browser:{postMessage:p=>commands.push(p)}}};
      window.$=id=>document.getElementById(id);
      for(const name of ['renderMonitorSidebarSummary','syncPrimaryKeyboardLayer','updateLibrarySearchTools',
        'updateReportRefreshButton','updateThemeFetchButton','startAutoMonitorStatusPolling','stopAutoMonitorStatusPolling']) window[name]=()=>{};
      window.stashes=0;window.stashCurrentMonitorPaperSurface=()=>stashes++;
      window.showMonitorStatusMessage=m=>statusMessages.push(m);
      window.fetch=async()=>({ok:true,json:async()=>({bookmarks:[],history:[],preferences:{},history_more:false})});
      window.sourceClicks=0;
      document.querySelector('#source').onclick=()=>sourceClicks++;
    });
    await page.addStyleTag({content:fs.readFileSync(path.join(root,'paper_monitor/browser_ui.css'),'utf8')});
    await page.addScriptTag({content:fs.readFileSync(path.join(root,'paper_monitor/browser_ui.js'),'utf8')});
    await page.addScriptTag({content:primary});
    await page.addScriptTag({content:router+'\nwireWorkspaceWebsiteLinks();'});
    async function fromSource(mode, url, options={}) {
      await page.evaluate(({mode,url})=>{
        gewuBrowser.setActive(false); state.mode=mode==='my-publications'?'library':mode;
        state.libraryTab=mode==='my-publications'?mode:'workspace-2';
        document.querySelector('#papers').dataset.monitorMode=['report','theme'].includes(mode)?mode:'';
        setPrimaryView(mode); commands.length=0;stashes=0;
        const a=document.createElement('a'); a.href=url; a.target='_blank'; a.id='destination';
        a.innerHTML='<span>Public website</span>';
        document.querySelector('#source').replaceChildren(a);
      },{mode,url});
      await page.click('#destination span',options);
      return page.evaluate(()=>({commands,mode:state.mode,external,sourceClicks}));
    }
    const cold=await fromSource('library','https://example.org/paper.pdf');
    assert.equal(cold.mode,'browser');
    assert.equal(cold.sourceClicks,0,'link does not also select/re-render its parent paper row');
    assert.deepEqual(cold.commands.filter(p=>p.url),[{action:'navigate',url:'https://example.org/paper.pdf'}]);
    assert.ok(cold.commands.some(p=>p.action==='layout'&&p.active&&p.width>0&&p.height>0));
    for(const mode of ['library','my-publications','report','theme','author']) {
      const result=await fromSource(mode,'https://example.org/'+mode);
      assert.deepEqual(result.commands.filter(p=>p.url),[{action:'new-tab',url:'https://example.org/'+mode}]);
      assert.equal(result.external.length,0);
      assert.equal(await page.evaluate(()=>stashes),0,'Browser detour must not detach the source monitor DOM');
      await page.evaluate(()=>gewuBrowserNativeEvent({event:'return-workspace'}));
      assert.equal(await page.evaluate(()=>state.mode),mode==='my-publications'?'library':mode);
      assert.equal(await page.locator('#destination').count(),1,'same source link survives return');
    }
    for(const options of [{button:'middle'},{modifiers:['Meta']}]) {
      const result=await fromSource('report','https://example.org/modified',options);
      assert.deepEqual(result.commands.filter(p=>p.url),[{action:'new-tab',url:'https://example.org/modified'}]);
    }
    // Exercise real retained DOM, scroll geometry and focus with the actual
    // primary-view switcher, not only state mocks. No paper loader is installed.
    await page.evaluate(()=>{
      state.mode='report';setPrimaryView('report');
      const papers=document.querySelector('#papers'), sidebar=document.querySelector('.sidebar');
      papers.dataset.monitorMode='report';
      papers.style.cssText='width:420px;height:220px;overflow:auto';
      sidebar.style.cssText='width:150px;height:100px;overflow:auto';
      sidebar.innerHTML='<div style="height:900px">Generated calendar</div>';
      document.querySelector('#source').innerHTML='<a id="returnSource" href="https://example.org/return">Return source</a><div style="height:1600px;width:900px">Generated paper</div>';
      const link=document.querySelector('#returnSource'); link.focus({preventScroll:true});
      papers.scrollTop=310;papers.scrollLeft=83;sidebar.scrollTop=142;
      window.retainedPaper=papers.firstChild;window.retainedLink=link;
      commands.length=0;stashes=0;link.click();
    });
    const layout=await page.evaluate(()=>commands.filter(c=>c.action==='layout').at(-1));
    assert.equal(layout.canReturnToWorkspace,true,'native shortcut receives only return availability');
    await page.evaluate(()=>{
      document.querySelector('#papers').scrollTop=0;document.querySelector('.sidebar').scrollTop=0;
      commands.length=0;gewuBrowserNativeEvent({event:'return-workspace'});
    });
    const returned=await page.evaluate(()=>({mode:state.mode,top:document.querySelector('#papers').scrollTop,
      left:document.querySelector('#papers').scrollLeft,side:document.querySelector('.sidebar').scrollTop,
      same:document.querySelector('#papers').firstChild===retainedPaper,focus:document.activeElement===retainedLink,
      stashes,navigation:commands.filter(c=>['navigate','new-tab','back','close-tab','reload'].includes(c.action))}));
    assert.deepEqual(returned,{mode:'report',top:310,left:83,side:142,same:true,focus:true,stashes:0,navigation:[]});
    // Use real native state events to ensure switching to a new page does not
    // overwrite the existing tab list or force Home while waiting for WebKit.
    await page.evaluate(()=>{
      gewuBrowserNativeEvent({event:'tabs',selected:'old',tabs:[{id:'old',url:'https://example.org/draft',title:'Existing draft'}]});
      gewuBrowserNativeEvent({event:'state',tab_id:'old',url:'https://example.org/draft',title:'Existing draft',loading:false});
      gewuBrowser.open();commands.length=0; openWebsite('https://example.org/next');
    });
    assert.equal(await page.locator('#browserTabs [data-browser-tab="old"]').count(),1);
    const snapshot=await page.evaluate(()=>({state,commands,statusMessages}));
    assert.equal(snapshot.state.librarySelectedId,17);
    assert.equal(snapshot.state.authorMonitorSelectedId,9);
    assert.equal(snapshot.state.selectedDate,'2026-09-06');
    assert.deepEqual(snapshot.commands.filter(p=>p.url),[{action:'new-tab',url:'https://example.org/next'}]);
    assert.deepEqual(snapshot.statusMessages,[]);
    assert.deepEqual(errors,[]);
    console.log('Workspace Browser DOM routing passed: cold direct destination, five modes and return, dynamic anchors, modified clicks, identical retained DOM, restored source focus/scroll and no return navigation; zero external launches.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
