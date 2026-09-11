const assert = require('node:assert/strict'), fs = require('node:fs');
const {chromium} = require('playwright');
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
(async () => {
 const browser = await chromium.launch({headless:true, executablePath:process.env.GEWU_TEST_CHROME});
 try {
  const context = await browser.newContext({viewport:{width:1280,height:900}, extraHTTPHeaders:{'X-Gewu-Workspace':fixture.token}});
  await context.route('**/*', route => route.request().url().startsWith(fixture.url) ? route.continue() : route.abort());
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(fixture.url);
  await page.waitForFunction(() => appBootCompleted);
  const show = async (id,type='folder') => page.evaluate(({id,type}) => showLibraryContextMenu(new MouseEvent('contextmenu',{clientX:250,clientY:200}),1,type,id),{id,type});
  await show(fixture.recycle_id);
  assert.equal(await page.locator('[data-action="refresh-folder-info"]').isVisible(), false);
  const itemId = await page.evaluate(() => state.libraryItems[0].id);
  await show(itemId,'item');
  assert.equal(await page.locator('[data-action="refresh-folder-info"]').isVisible(), false);
  await show(fixture.folder_id);
  await page.locator('[data-action="refresh-folder-info"]').click();
  assert.equal(await page.locator('#libraryImportMetadataMode').inputValue(), 'full');
  assert.match(await page.locator('#libraryImportPath').inputValue(), /Refresh scope.*all subfolders/);
  await page.locator('#libraryImportMetadataMode').selectOption('quick');
  await page.locator('#libraryRunImport').click();
  await page.waitForFunction(() => state.libraryImportJobId && state.libraryImportJob?.total===3);
  const jobId = await page.evaluate(() => state.libraryImportJobId);
  await page.locator('#libraryStopImport').click();
  await page.evaluate(() => fetch('/qa/release',{method:'POST'}));
  await page.waitForFunction(() => state.libraryImportJob?.status==='paused');
  assert.equal(await page.locator('#libraryRunImport').innerText(), 'Continue');
  assert.equal(await page.locator('#libraryImportMetadataMode').isDisabled(), true);
  assert.equal(await page.evaluate(() => state.libraryImportJob.current), 1);
  // Reload the page, then restore the durable task through the actual task menu.
  await page.reload(); await page.waitForFunction(() => appBootCompleted);
  await page.evaluate(() => openMetadataRefreshWindow());
  await page.waitForFunction(() => document.querySelectorAll('#metadataJobHistory option').length>1);
  await page.locator('#metadataJobHistory').selectOption(jobId);
  await page.waitForFunction(() => document.querySelector('#libraryRunImport')?.textContent==='Continue');
  assert.match(await page.locator('#libraryImportPath').inputValue(), /Refresh scope/);
  await page.locator('#libraryRunImport').click();
  await page.evaluate(() => {closeLibraryLoader();updateLibraryActivityStatus('Downloading another paper…',{live:true,clear:false});document.getElementById('libraryMode').focus();window.savedFocus=document.activeElement;window.savedSelection=JSON.stringify(state.librarySelection);});
  await page.waitForFunction(() => state.libraryImportJob?.status==='completed');
  await page.evaluate(() => pollMetadataJobs());
  assert.equal(await page.evaluate(() => document.activeElement===savedFocus), true, JSON.stringify(await page.evaluate(() => ({saved:savedFocus.outerHTML.slice(0,160),connected:savedFocus.isConnected,current:document.activeElement.outerHTML.slice(0,160),loader:state.libraryLoaderOpen}))));
  assert.equal(await page.evaluate(() => JSON.stringify(state.librarySelection)===savedSelection), true);
  assert.equal(await page.evaluate(() => state.libraryActivityLive), true);
  assert.match(await page.locator('#libraryActivityStatus').innerText(), /Downloading another paper/);
  await page.evaluate(id => showMetadataJob(id),jobId);
  assert.equal(await page.evaluate(() => state.libraryImportJob.counts.unchanged),2);
  assert.equal(await page.evaluate(() => state.libraryImportJob.counts.missing_identifier),1);
  assert.match(await page.locator('#libraryLoaderSide').innerText(),/Missing DOI\/arXiv/);
  // Repeating the same scope uses shared history and performs no further lookup.
  await page.locator('#libraryRunImport').click();
  await page.waitForFunction(old => state.libraryImportJobId!==old && state.libraryImportJob?.status==='completed', jobId);
  assert.equal(await page.evaluate(() => state.libraryImportJob.counts.skipped_recent),2);
  for (const width of [1280,960,640]) {
   await page.setViewportSize({width,height:900});
   const bounds = await page.locator('#libraryLoaderModalBody').boundingBox();
   assert.ok(bounds.x>=0 && bounds.x+bounds.width<=width+1, 'loader fits viewport '+width);
  }
  if (process.env.GEWU_TEST_ARTIFACT_DIR) {
   fs.mkdirSync(process.env.GEWU_TEST_ARTIFACT_DIR,{recursive:true});
   await page.setViewportSize({width:1280,height:900});
   await page.screenshot({path:process.env.GEWU_TEST_ARTIFACT_DIR+'/folder-refresh.png'});
  }
  assert.deepEqual(errors,[]);
  console.log('Full product refresh UI: folder menu, Quick/Full, recursive scope, pause/continue after reload, counts, task history, cooldown, independent download/focus and three widths passed.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
