// Run against an isolated installed/payload WebView2, never the daily Library.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.GEWU_PLAYWRIGHT_MODULE || 'playwright');
const [endpoint, output] = process.argv.slice(2);
fs.mkdirSync(output, {recursive:true});
(async () => {
  let browser;
  for(let attempt=0;attempt<100;attempt++){
    try{browser=await chromium.connectOverCDP(endpoint,{timeout:1000});break;}
    catch(error){if(attempt===99)throw error;await new Promise(resolve=>setTimeout(resolve,250));}
  }
  try {
    const context = browser.contexts()[0];
    let page;
    for (let i=0;i<100;i++) {
      page = context.pages().find(p=>/^http:\/\/127\.0\.0\.1:\d+\/$/.test(p.url()));
      if (page) break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    assert.ok(page, 'workspace page');
    await page.waitForFunction(()=>typeof confirmRecycleDeletion==='function' && typeof window.gewuConfirmDeletion==='function');
    await page.waitForFunction(()=>document.querySelector('#appStartupOverlay')?.hidden || !document.querySelector('#appStartupOverlay'));
    const nativeDialogs=[]; page.on('dialog', async dialog=>{nativeDialogs.push(dialog.message());await dialog.dismiss();});
    const mutations=[]; page.on('request', request=>{if(request.method()==='POST' && /\/delete|\/clear/.test(request.url()))mutations.push(request.url());});
    await page.evaluate(()=>{
      window.probeShortcutCount=0;
      window.addEventListener('keydown',()=>window.probeShortcutCount++,true);
      const trigger=document.createElement('button');trigger.id='probeFocus';trigger.textContent='Probe';document.body.append(trigger);
    });
    const open=async (kind='paper', long=false)=>{
      await page.locator('#probeFocus').focus();
      await page.evaluate(({kind,long})=>{
        window.probeResult='pending';
        const name=long?'<img src=x onerror=alert(1)>'+ '研究附件'.repeat(100)+'.pdf':'Supplementary Information.pdf';
        const preview={requires_confirmation:true,metadata_paper_count:1,shortcut_only_paper_count:1,
          local_copy_paths:['C:\\private\\Library\\internal.pdf'],folder_paths:[],orphan_local_copy_paths:[]};
        const pending=kind==='paper'?confirmPaperFileDeletion(name)
          :confirmRecycleDeletion(kind==='empty'?'all items in Recycle':'“Example paper.pdf”',preview);
        pending.then(result=>window.probeResult=result);
      },{kind,long});
      await page.locator('dialog.gewu-delete-dialog[open]').waitFor();
      assert.equal(await page.locator('dialog h2').innerText(),'Delete File');
      assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Delete');
      assert.doesNotMatch(await page.locator('dialog').innerText(),/127\.0\.0\.1|C:\\|metadata|source\/resource|managed copy/i);
    };
    const result=async expected=>{
      await page.waitForFunction(()=>window.probeResult!=='pending');
      assert.equal(await page.evaluate(()=>window.probeResult),expected);
      assert.equal(await page.locator('dialog.gewu-delete-dialog').count(),0);
      assert.equal(await page.evaluate(()=>document.activeElement.id),'probeFocus');
    };
    const checks=[];
    for(const kind of ['paper','recycle','empty']){
      await open(kind);
      await page.screenshot({path:`${output}/${kind}.png`});
      await page.getByRole('button',{name:'Cancel',exact:true}).click();await result(false);
      checks.push(kind+' Cancel');
    }
    await open();await page.keyboard.press('Escape');await result(false);checks.push('Escape');
    await open();
    const count=await page.evaluate(()=>window.probeShortcutCount);
    await page.keyboard.press('Delete');assert.equal(await page.evaluate(()=>window.probeShortcutCount),count);
    await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Cancel');
    await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Delete');
    assert.equal(await page.evaluate(()=>window.gewuConfirmDeletion({title:'Duplicate',message:'No'})),false);
    await page.keyboard.press('Enter');await result(true);checks.push('shortcut guard, focus trap, duplicate guard, Enter');
    await open();await page.getByRole('button',{name:'Delete',exact:true}).click();await result(true);checks.push('Delete');
    await open();await page.evaluate(()=>document.querySelector('dialog').close());await result(false);checks.push('close');
    for(const [width,height] of [[900,650],[420,480]]){
      await page.setViewportSize({width,height});await open('paper',true);
      assert.equal(await page.locator('dialog img').count(),1);
      const layout=await page.locator('dialog').evaluate(d=>({width:d.getBoundingClientRect().width,height:d.getBoundingClientRect().height,scroll:d.scrollWidth,client:d.clientWidth}));
      assert.ok(layout.width<=width-39&&layout.height<=height-39);assert.ok(layout.scroll<=layout.client);
      await page.getByRole('button',{name:'Cancel',exact:true}).click();await result(false);
      checks.push(`long name ${width}x${height}`);
    }
    await page.evaluate(()=>{
      window.probeResult='pending';
      deleteSelectedLibraryPaperResource({paper_id:'isolated-probe',id:999,display_name:'Cancel fixture.txt'})
        .then(value=>window.probeResult=value);
    });
    await page.getByRole('button',{name:'Cancel',exact:true}).click();
    await page.waitForFunction(()=>window.probeResult!=='pending');
    assert.equal(mutations.length,0);assert.equal(nativeDialogs.length,0);
    checks.push('Paper Files workflow cancellation: zero mutation requests; zero native browser dialogs');
    fs.writeFileSync(`${output}/dialog-results.json`,JSON.stringify({ok:true,checks},null,2));
    console.log(JSON.stringify({ok:true,checks}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
