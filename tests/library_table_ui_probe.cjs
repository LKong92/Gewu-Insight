// Full product JS/CSS against disposable data, never the running user workspace.
const assert=require('node:assert/strict'), fs=require('node:fs');
const {chromium}=require('playwright');
const f=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.GEWU_TEST_CHROME});
 try {
  const context=await browser.newContext({viewport:{width:1400,height:900},timezoneId:'Asia/Shanghai',extraHTTPHeaders:{'X-Gewu-Workspace':f.token}});
  await context.route('**/*',r=>r.request().url().startsWith(f.url)?r.continue():r.abort());
  const page=await context.newPage(),errors=[],posts=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST')posts.push({url:r.url(),data:r.postDataJSON()});});
  await page.goto(f.url);await page.waitForFunction(()=>appBootCompleted);
  const open=async(type)=>{
   await page.evaluate(async({type,f})=>{
    state.query='';
    if(type==='workspace')await openLibraryWorkspaceTab(0);
    else if(type==='shortcut')await openLibraryShortcutTab(0);
    else {state.libraryTab='library';state.librarySelection=null;await loadLibraryFolderAndRender(f.parent_id);focusLibraryFolder(f.parent_id);}
    applyLibraryContentView('table');
   },{type,f});
   await page.locator('.table-column .library-table-row[data-library-type="item"]').first().waitFor();
  };
  const order=()=>page.locator('.table-column .library-table-row[data-library-type="item"] .library-table-title-text').allTextContents().then(a=>a.map(s=>s.replace(/›/g,'').trim()));
  const selection=()=>page.evaluate(()=>JSON.stringify([state.librarySelection,state.libraryPaperResourceSelection]));
  for(const type of ['library','workspace','shortcut']) {
   await open(type);
   assert.equal(await page.locator('.workspace-tools').count(),0);
   await page.locator('.table-column .library-table-row[data-library-type="item"]').first().click();
   const selected=await selection();
   for(const [key,expected] of [
    ['title',['Alpha wave','Beta interference','Gamma phase','Unknown metadata']],
    ['authors',['Beta interference','Gamma phase','Alpha wave','Unknown metadata']],
    ['year',['Beta interference','Gamma phase','Alpha wave','Unknown metadata']],
    ['journal',['Gamma phase','Alpha wave','Beta interference','Unknown metadata']],
    ['added',['Gamma phase','Alpha wave','Beta interference','Unknown metadata']]
   ]) {
    await page.evaluate(()=>{state.libraryTableSort=null;renderLibrary();});
    const button=page.locator(`[data-library-table-sort="${key}"]`);
    await button.click();assert.deepEqual(await order(),expected,type+' '+key+' ascending');
    assert.equal(await button.locator('..').getAttribute('aria-sort'),'ascending');
    assert.equal(await selection(),selected,'sorting preserves paper selection');
    await button.click();
    const descending=key==='title'?[...expected].reverse():[...expected.slice(0,3)].reverse().concat(expected[3]);
    assert.deepEqual(await order(),descending,type+' '+key+' descending');
    assert.equal(await button.locator('..').getAttribute('aria-sort'),'descending');
    if(type!=='workspace') assert.equal(await page.locator('.table-column .library-row').first().getAttribute('data-library-type'),'folder');
   }
   const times=await page.locator('.table-column .library-table-row[data-library-type="item"] .time-added').allTextContents();
   assert.deepEqual(times,['2026-09-21 11:00','2026-09-21 10:00','2026-09-21 09:30','—'],type+' placement times in local timezone');
  }
  // Native button keyboard activation must sort, not open Quick Look.
  const title=page.locator('[data-library-table-sort="title"]');await title.focus();await page.keyboard.press('Enter');
  assert.deepEqual(await order(),['Alpha wave','Beta interference','Gamma phase','Unknown metadata']);
  await page.keyboard.press('Space');assert.equal((await order())[0],'Unknown metadata');
  assert.equal(await page.evaluate(()=>state.libraryQuickLookOpen),false);
  // Pointer / Shift and arrow keys follow the visible order.
  await title.click();
  await page.locator('.table-column [data-library-type="item"]').first().click();
  await page.keyboard.press('ArrowDown');
  assert.match(await page.locator('.table-column .library-row.active').innerText(),/Beta interference/);
  await page.keyboard.press('Shift+ArrowDown');
  const range=await page.locator('.table-column .range-selected .library-table-title-text').allTextContents();
  assert.ok(range.some(t=>t.includes('Beta'))&&range.some(t=>t.includes('Gamma')));
  // Root title survives nested folder navigation and view switches.
  await open('workspace');
  await page.locator(`.library-row[data-library-type="folder"][data-library-id="${f.nested_id}"]`).click();
  await page.locator(`.table-column[data-library-column-folder="${f.nested_id}"]`).waitFor();
  assert.equal(await page.locator('#libraryNavigationHeader .library-table-folder-title').innerText(),'Interferometry');
  assert.equal(await page.locator('#libraryNavigationHeader').isVisible(),true);
  assert.equal(await page.locator('.table-column .library-table-folder-title').innerText(),'Experiments');
  const headerBox=await page.locator('#libraryNavigationHeader').boundingBox();
  const columnsBox=await page.locator('#libraryColumns').boundingBox();
  const detailsBox=await page.locator('#libraryShell > .library-pane').boundingBox();
  assert.ok(Math.abs(headerBox.x-columnsBox.x)<1,'root title starts at the first column');
  assert.ok(Math.abs(headerBox.width-columnsBox.width)<1,'root title spans only folder/content columns');
  assert.ok(headerBox.x+headerBox.width<=detailsBox.x,'root title does not enter Paper Details');
  assert.ok(Math.abs(headerBox.y-detailsBox.y)<1,'Paper Details retains its original top');
  assert.ok(headerBox.y+headerBox.height<=columnsBox.y+1,'folder/content columns stay below the root title');
  await page.evaluate(()=>applyLibraryContentView('list'));
  assert.equal(await page.locator('#libraryNavigationHeader').isVisible(),true);
  await page.evaluate(()=>applyLibraryContentView('table'));
  // Shared Add Paper in each root/subfolder; Escape cancels without writes.
  for(const [type,folder] of [['workspace',f.nested_id],['shortcut',f.nested_library_id],['library',f.nested_library_id]]) {
   await open(type);
   await page.evaluate(async folder=>{await loadLibraryFolderAndRender(folder);focusLibraryFolder(folder);},folder);
   const body=page.locator(`.table-column[data-library-column-folder="${folder}"] .library-column-body`);
   await body.click({button:'right',position:{x:100,y:300}});
   await page.locator('#libraryContextMenu [data-action="add-paper"]').click();
   const input=page.locator('[data-library-inline-add-paper-input]');await input.fill('cancelled');
   const count=posts.length;await input.press('Escape');assert.equal(posts.length,count);
   await body.click({button:'right',position:{x:100,y:300}});
   await page.locator('#libraryContextMenu [data-action="add-paper"]').click();
   await input.fill(type);await input.press('Enter');await page.waitForFunction(()=>!state.libraryInlineAddBusy);
   assert.equal(await input.count(),0,await page.evaluate(()=>state.libraryInlineAddError));
   const req=posts.filter(p=>p.url.endsWith('/add-paper')).at(-1);
   assert.equal(req.data.folder_id,folder);assert.equal(req.data.tab_type,type);
   assert.equal(await page.evaluate(()=>state.libraryActiveFolderId),folder);
   assert.match(await page.locator('.table-column .library-row.active').innerText(),new RegExp('Added '+type));
  }
  // Subtle root menu and source-rail right-click share rename/move actions.
  await open('workspace');await page.locator('[data-library-navigation-menu]').click();
  assert.equal(await page.locator('#libraryTabContextMenu [data-action="move-tab-library"]').isVisible(),true);
  await page.locator('#libraryTabContextMenu [data-action="move-tab-library"]').click();
  await page.waitForFunction(()=>document.querySelector('#libraryNavBackdrop').classList.contains('open'));
  assert.equal(await page.locator('#libraryNavTitle').innerText(),'Move Space to Library');
  await page.keyboard.press('Escape');
  page.once('dialog',d=>d.accept('Interferometry renamed'));
  await page.locator('[data-library-navigation-menu]').click();await page.locator('#libraryTabContextMenu [data-action="rename-tab"]').click();
  await page.waitForFunction(()=>libraryWorkspaceLabel(0)==='Interferometry renamed');
  assert.equal(await page.locator('#libraryNavigationHeader .library-table-folder-title').innerText(),'Interferometry renamed');
  await open('shortcut');
  await page.locator('[data-shortcut-tab="0"]').click({button:'right'});
  assert.equal(await page.locator('#libraryTabContextMenu [data-action="move-tab-library"]').isVisible(),false);
  page.once('dialog',d=>d.accept('Reading shortcut'));
  await page.locator('#libraryTabContextMenu [data-action="rename-tab"]').click();
  await page.waitForFunction(()=>libraryShortcutLabel(0)==='Reading shortcut');
  assert.equal(await page.evaluate(id=>libraryFolderById(id).name,f.parent_id),'Reading','shortcut rename preserves real folder');
  // Shortcut breadcrumbs follow the physical ancestry, not the shortcut label.
  await page.evaluate(id=>{state.librarySelection={type:'folder',id};state.libraryActiveFolderId=id;renderLibrary();},f.parent_id);
  assert.equal(await page.evaluate(()=>librarySelectionPathText()),'Library > Reading');
  await page.evaluate(async id=>{await loadLibraryFolderAndRender(id);focusLibraryFolder(id);},f.nested_library_id);
  assert.equal(await page.evaluate(()=>librarySelectionPathText()),'Library > Reading > Experiments');
  await page.locator('.table-column [data-library-type="item"]').first().click();
  assert.ok((await page.locator('#libraryPathBar').getAttribute('title')).startsWith('Library > Reading > Experiments > '));
  assert.ok((await page.locator('#libraryPathBar').innerText()).includes('Library'));
  // A shortcut to an independent Space uses that Space root, never an invented Library prefix.
  await page.evaluate(({nested,space})=>{
    state.libraryShortcutTabs[0].folder_id=nested;
    state.libraryShortcutTabs[0].label='Unrelated alias';
    state.librarySelection={type:'folder',id:nested};
    state.libraryActiveFolderId=nested;
  },{nested:f.nested_id,space:f.space_id});
  assert.equal(await page.evaluate(()=>librarySelectionPathText()),'Interferometry renamed > Experiments');
  await page.evaluate(id=>{state.libraryShortcutTabs[0].folder_id=id;},f.parent_id);
  // Persisted sort survives reload; choosing a context-menu sort clears it.
  await page.locator('[data-library-table-sort="added"]').click();
  const saved=await page.evaluate(()=>JSON.stringify(state.libraryTableSort));
  await page.reload();await page.waitForFunction(()=>appBootCompleted);
  assert.equal(await page.evaluate(()=>JSON.stringify(state.libraryTableSort)),saved);
  await open('workspace');await page.evaluate(()=>setLibrarySortMode('modified'));
  assert.equal(await page.evaluate(()=>state.libraryTableSort),null);
  assert.equal(await page.locator('[aria-sort="none"]').count(),5);
  // The added column remains reachable with its header aligned at narrow widths.
  for(const width of [1024,1400,1920]) {
   await page.setViewportSize({width,height:900});
   await page.locator('[data-library-table-sort="added"]').scrollIntoViewIfNeeded();
   const geometry=await page.evaluate(()=>{
    const header=document.querySelector('[data-library-table-sort="added"]').getBoundingClientRect();
    const cell=document.querySelector('.table-column [data-library-type="item"] .time-added').getBoundingClientRect();
    const body=document.querySelector('.table-column .library-table-body');
    return {headerX:header.x,cellX:cell.x,cellWidth:cell.width,extraBodyScroll:body.scrollWidth-body.clientWidth};
   });
   assert.ok(Math.abs(geometry.headerX-geometry.cellX)<2,JSON.stringify({width,...geometry}));
   assert.equal(geometry.cellWidth,138);
   assert.ok(geometry.extraBodyScroll<=1,'columns scroll together, never just the row body');
   if(process.env.GEWU_TEST_ARTIFACT_DIR) {
    fs.mkdirSync(process.env.GEWU_TEST_ARTIFACT_DIR,{recursive:true});
    await page.screenshot({path:process.env.GEWU_TEST_ARTIFACT_DIR+`/time-added-${width}.png`});
   }
  }
  if(process.env.GEWU_TEST_ARTIFACT_DIR){
   fs.mkdirSync(process.env.GEWU_TEST_ARTIFACT_DIR,{recursive:true});
   await page.screenshot({path:process.env.GEWU_TEST_ARTIFACT_DIR+'/space-table.png'});
  }
  assert.deepEqual(errors,[]);
  console.log('Table UI: all five sorts/both directions/three roots; local added times, three widths, selection, keyboard/range, root header, nested adds, rename/move menus and persisted sort passed.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
