const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const f=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.GEWU_TEST_CHROME});
 try {
  const context=await browser.newContext({viewport:{width:1280,height:900},extraHTTPHeaders:{'X-Gewu-Workspace':f.token}});
  await context.route('**/*',r=>r.request().url().startsWith(f.url)?r.continue():r.abort());
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(f.url);await page.waitForFunction(()=>appBootCompleted);
  const open=()=>page.evaluate(()=>openLibraryDestinationSettings());
  const menu=page.locator('.library-add-menu.open');
  const read=()=>page.evaluate(()=>fetchJson('/api/settings/add-to-library'));
  await open();assert.match(await page.locator('#libraryDestinationPath').innerText(),/unsorted/);
  await page.locator('#chooseLibraryDestination').click();
  await menu.locator(`button[data-folder-id="${f.parent_id}"]`).click();
  await menu.locator(`button[data-folder-id="${f.inbox_id}"]`).click();
  assert.equal(await menu.locator(`button[data-folder-id="${f.recycle_id}"]`).count(),0);
  await menu.locator('[data-action="confirm-library-add"]').click();
  assert.match(await page.locator('#libraryDestinationPath').innerText(),/Reading \/ Inbox/);
  assert.match((await read()).title,/unsorted/,'selection does not save preferences');
  await page.locator('#closeLibraryDestinationSettings').click();await open();
  assert.match(await page.locator('#libraryDestinationPath').innerText(),/unsorted/,'cancel discards draft');
  await page.locator('#chooseLibraryDestination').click();
  await menu.locator(`button[data-workspace-root-id="${f.space_id}"]`).click();
  await menu.locator('[data-action="confirm-library-add"]').click();
  // Failure must not apply an unsaved destination.
  await page.route('**/api/settings/add-to-library',r=>r.request().method()==='POST'?r.fulfill({status:400,contentType:'application/json',body:'{"error":"Synthetic save failure"}'}):r.continue());
  await page.locator('#saveLibraryDestinationSettings').click();
  await page.waitForFunction(()=>document.querySelector('#libraryDestinationSettingsStatus').textContent==='Synthetic save failure');
  assert.match((await read()).title,/unsorted/);
  await page.unroute('**/api/settings/add-to-library');
  await page.locator('#saveLibraryDestinationSettings').click();
  await page.waitForFunction(()=>document.querySelector('#libraryDestinationSettingsStatus').textContent==='Default folder saved.');
  assert.equal((await read()).folder_id,f.space_id);
  await page.reload();await page.waitForFunction(()=>appBootCompleted);await open();
  assert.equal(await page.locator('#libraryDestinationPath').innerText(),'Project Space');
  for(const width of [1280,960,640]) {
   await page.setViewportSize({width,height:900});
   await page.locator('#chooseLibraryDestination').click();
   const m=await menu.boundingBox();assert.ok(m.x>=0&&m.x+m.width<=width+1&&m.y>=0&&m.y+m.height<=901,'picker fits '+width);
   assert.match(await menu.locator('.library-add-selected-path').innerText(),/Project Space/);
   await menu.locator('button[data-workspace-root-id="1"]').click();
   await menu.locator(`button[data-folder-id="${f.parent_id}"]`).click();
   await menu.locator(`button[data-folder-id="${f.long_id}"]`).click();
   await menu.locator('[data-action="confirm-library-add"]').click();
   const modal=await page.locator('#libraryDestinationSettingsBackdrop section.settings-modal').boundingBox();
   assert.ok(modal.x>=0&&modal.x+modal.width<=width+1,'settings fit '+width);
   await page.keyboard.press('Escape');await open();
  }
  if(process.env.GEWU_TEST_ARTIFACT_DIR){fs.mkdirSync(process.env.GEWU_TEST_ARTIFACT_DIR,{recursive:true});await page.screenshot({path:process.env.GEWU_TEST_ARTIFACT_DIR+'/settings.png'});}
  await page.locator('#closeLibraryDestinationSettings').click();
  // All three Monitor callers share the actual picker and add implementation.
  for(const [pid,mode] of [['journal','report'],['subject','theme'],['author','author']]) {
   await page.evaluate(({pid,mode})=>{
    state.mode=mode;
    const old=document.getElementById('syntheticMonitor');if(old)old.remove();
    const a=document.createElement('article');a.id='syntheticMonitor';a.dataset.paperId=pid;
    a.style='position:fixed;left:30px;top:100px;z-index:50;background:white';
    a.innerHTML='<button data-action="add-library">Add to Library</button><div class="library-add-menu" data-role="library-add-menu"></div>';
    document.body.appendChild(a);
    return openLibraryAddMenu(a,pid,a.querySelector('button'));
   },{pid,mode});
   assert.match(await menu.locator('.library-add-selected-path').innerText(),/Project Space/);
   await menu.locator('[data-action="confirm-library-add"]').click();
   await page.waitForFunction(()=>document.querySelector('#syntheticMonitor button').textContent==='Show in Library');
  }
  await page.evaluate(()=>{state.mode='library';document.getElementById('syntheticMonitor').remove();});
  await open();await page.locator('#resetLibraryDestinationSettings').click();
  await page.waitForFunction(()=>document.querySelector('#libraryDestinationSettingsStatus').textContent==='Default folder saved.');
  assert.match((await read()).title,/unsorted/);
  await page.locator('#closeLibraryDestinationSettings').click();
  await require('./zotero_import_destination_ui_probe.cjs')(page,f);
  assert.deepEqual(errors,[]);
  console.log('Full product UI: default/choose/cancel/save/failure/reload/reset, Space destinations, three Monitor adds, Recycle exclusion and three widths passed.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
