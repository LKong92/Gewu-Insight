/* Use the real shared picker; intercept only the Zotero migration session. */
const assert=require('node:assert/strict');
module.exports=async(page,f)=>{
 const initialSettings=await page.evaluate(()=>fetchJson('/api/settings/add-to-library'));
 const destinations=await page.evaluate(()=>fetchJson('/api/library/add-targets'));
 const targets=destinations.folders.map(folder=>({id:folder.id,title:folder.name}));
 let job={id:'destination-fixture',created:Date.now()/1000,state:'connected',connected:true,message:'Zotero connected.',
   catalog:{libraries:[{source_id:'zotero-fixture',name:'My Library',collections:[]}]},config:{},counts:{}};
 const scans=[];
 await page.route('**/api/zotero-import*',async route=>{
  const request=route.request();
  if(request.method()==='POST'){
   const body=request.postDataJSON();assert.equal(body.action,'scan','Only a preview request is allowed');
   scans.push(body);job={...job,state:'ready',config:body};
   return route.fulfill({json:job});
  }
  return route.fulfill({json:request.url().includes('?id=')?job:{jobs:[job],destinations:targets}});
 });
 const open=()=>page.evaluate(()=>window.openZoteroImport());
 const window=page.locator('.zotero-import-window'),target=page.locator('#zi-target');
 const menu=page.locator('.library-add-menu.open');
 const confirm=()=>menu.locator('[data-action="confirm-library-add"]').click();
 await open();await target.waitFor({state:'visible'});
 assert.equal(await page.locator('select#zi-target').count(),0);
 assert.equal(await target.getAttribute('value'),'1');
 await target.click();await menu.locator(`button[data-folder-id="${f.parent_id}"]`).click();
 assert.ok(await menu.locator('.library-add-column').count()>=3,'child hierarchy opens in another column');
 await menu.locator(`button[data-folder-id="${f.inbox_id}"]`).click();
 assert.equal(await menu.locator(`button[data-folder-id="${f.recycle_id}"]`).count(),0);
 await confirm();assert.equal(await target.getAttribute('value'),String(f.inbox_id));
 assert.match(await target.innerText(),/My Library \/ Reading \/ Inbox/);
 const beforeCancel=await target.innerText();
 await target.click();await menu.locator(`button[data-workspace-root-id="${f.space_id}"]`).click();
 await menu.locator('[data-action="cancel-library-add"]').click();
 assert.equal(await target.innerText(),beforeCancel,'Cancel retains the prior destination');
 await target.click();await page.keyboard.press('Escape');
 assert.equal(await menu.count(),0);assert.ok(await window.isVisible(),'Escape dismisses picker only');
 assert.equal(await target.getAttribute('value'),String(f.inbox_id));
 for(const width of [1280,960,640]){
  await page.setViewportSize({width,height:900});await target.click();
  await menu.locator('button[data-workspace-root-id="1"]').click();
  await menu.locator(`button[data-folder-id="${f.parent_id}"]`).click();
  await menu.locator(`button[data-folder-id="${f.long_id}"]`).click();
  const rect=await menu.boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=width+1&&rect.y>=0&&rect.y+rect.height<=901,'picker fits '+width);
  await confirm();assert.equal(await target.getAttribute('value'),String(f.long_id));
 }
 await target.click();await menu.locator(`button[data-workspace-root-id="${f.space_id}"]`).click();await confirm();
 assert.equal(await target.getAttribute('value'),String(f.space_id));
 await target.click();await menu.locator('button[data-workspace-root-id="1"]').click();await confirm();
 assert.equal(await target.getAttribute('value'),'1','Library root remains selectable after switching from a Space');
 await target.click();await menu.locator(`button[data-folder-id="${f.parent_id}"]`).click();
 await menu.locator(`button[data-folder-id="${f.inbox_id}"]`).click();await confirm();
 await page.locator('#zi-primary').click();await page.locator('#zi-summary').waitFor({state:'visible'});
 assert.equal(scans.length,1);assert.equal(scans[0].target_id,f.inbox_id);
 assert.equal(scans[0].root_name,'Zotero — My Library');
 assert.match(await page.locator('#zi-summary-context').innerText(),/Reading \/ Inbox/);
 assert.deepEqual(await page.evaluate(()=>fetchJson('/api/settings/add-to-library')),initialSettings,'Import target must not change the Save to Gewu default');
 await window.locator('.settings-modal-close').click();
 assert.equal(await page.locator('[data-library-add-portal]').count(),0);
 // Closing the import window with a picker open must not leave a floating menu.
 job={...job,state:'connected'};await open();await target.waitFor({state:'visible'});await target.click();
 await window.locator('.settings-modal-close').click();assert.equal(await menu.count(),0);
 await page.unroute('**/api/zotero-import*');
 console.log('Zotero destination: hierarchy, Library/Space roots, long paths, cancel/Escape, preview ID, cleanup and unchanged save defaults passed.');
};
