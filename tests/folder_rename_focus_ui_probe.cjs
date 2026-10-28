// Full product UI against library_table_ui_fixture.py's disposable database.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.GEWU_TEST_CHROME});
  try {
    const context=await browser.newContext({viewport:{width:1400,height:900},
      extraHTTPHeaders:{'X-Gewu-Workspace':fixture.token}});
    await context.route('**/*',route=>route.request().url().startsWith(fixture.url)?route.continue():route.abort());
    const page=await context.newPage(),errors=[],writes=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>{
      if(request.method()==='POST'&&request.url().endsWith('/api/library/folders/rename')) writes.push(request.postDataJSON());
    });
    await page.goto(fixture.url);await page.waitForFunction(()=>appBootCompleted);
    for(const view of ['list','table']) for(const finish of ['Enter','blur','navigation']) {
      await page.evaluate(async ({parent,view})=>{
        state.query='';state.libraryTab='library';
        await loadLibraryFolderAndRender(parent);focusLibraryFolder(parent);applyLibraryContentView(view);
      },{parent:fixture.parent_id,view});
      const known=await page.evaluate(()=>state.libraryFolders.map(folder=>Number(folder.id)));
      let release,received;
      const gate=new Promise(resolve=>release=resolve),waiting=new Promise(resolve=>received=resolve);
      const pattern='**/api/library/folder?folder_id=*';
      await page.route(pattern,async route=>{
        const id=Number(new URL(route.request().url()).searchParams.get('folder_id'));
        if(known.includes(id))return route.continue();
        const response=await route.fetch();received();await gate;await route.fulfill({response});
      });
      const body=page.locator(`[data-library-column-folder="${fixture.parent_id}"] .library-column-body`).first();
      await body.click({button:'right',position:{x:120,y:350}});
      await page.locator('#libraryContextMenu [data-action="new-folder"]').click();
      await waiting;
      const id=await page.evaluate(()=>state.librarySelection.id);
      const before=writes.length;
      const draft=`Draft ${view} ${finish}`;
      if(finish!=='navigation') {
        await page.keyboard.press('Enter');
        await page.waitForFunction(()=>document.activeElement?.matches('[data-library-rename-input]'));
        await page.locator('[data-library-rename-input]').fill(draft);
        await page.evaluate(()=>{
          window.keptRenameInput=document.querySelector('[data-library-rename-input]');
          keptRenameInput.setSelectionRange(2,5);
        });
      }
      release();
      await page.waitForFunction(id=>libraryFolderLoaded(id)&&!state.libraryFolderLoadPromises[id],id);
      await page.unroute(pattern);
      if(finish==='navigation') {
        await page.locator(`[data-library-column-folder="${id}"]`).getByText('Empty folder',{exact:true}).waitFor();
        assert.equal(await page.locator('[data-library-rename-input]').count(),0);
      } else {
        assert.deepEqual(await page.evaluate(()=>{
          const input=document.querySelector('[data-library-rename-input]');
          return {same:input===window.keptRenameInput,focused:input===document.activeElement,
            value:input?.value,start:input?.selectionStart,end:input?.selectionEnd};
        }),{same:true,focused:true,value:draft,start:2,end:5},`${view}: delayed load preserves draft and selection`);
        assert.equal(writes.length,before,'loading must not submit the rename');
        if(finish==='blur')await page.locator('#libraryDetail h3').click();
        else await page.keyboard.press(finish);
        await page.waitForFunction(()=>!state.libraryRenamingFolderId);
        assert.equal(await page.locator('[data-library-rename-input]').count(),0);
        assert.equal(await page.evaluate(id=>libraryFolderById(id).name,id),draft);
        assert.equal(writes.length-before,1,'only the user finishing edit may write');
        await page.locator(`[data-library-column-folder="${id}"]`).getByText('Empty folder',{exact:true}).waitFor();
      }
      console.log(`${view}: delayed folder load + ${finish} passed`);
    }
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
