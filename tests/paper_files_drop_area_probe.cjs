// Real Paper Files markup, styles, hit testing and handlers; generated files only.
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const {chromium, webkit} = require('playwright');
const root = path.resolve(__dirname, '..');
const html = JSON.parse(execFileSync(process.env.GEWU_TEST_PYTHON || 'python3', ['-c',
  'import json; from paper_monitor.ui_server import INDEX_HTML; print(json.dumps(INDEX_HTML))'],
  {cwd:root,encoding:'utf8',maxBuffer:8*1024*1024}));
function fn(name) {
  const start=html.search(new RegExp('    (?:async )?function '+name+'\\('));
  assert.ok(start>=0,name);
  return html.slice(start,html.indexOf('\n    }',start)+6);
}
(async()=>{
  const browser=await (process.env.GEWU_TEST_WEBKIT ? webkit : chromium).launch({headless:true,
    ...(process.env.GEWU_TEST_CHROME?{executablePath:process.env.GEWU_TEST_CHROME}:{})});
  try {
    const page=await browser.newPage({viewport:{width:1000,height:800}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/file-icon?*',r=>r.fulfill({status:204}));
    await page.setContent(`${html.match(/<style>([\s\S]*?)<\/style>/)[0]}
      <div id="libraryShell" style="display:block;height:760px"><input id="editor" value="unsaved">
      <div id="libraryColumns" class="library-columns" style="height:700px;width:540px"></div></div>`);
    await page.evaluate(()=>{
      window.$=id=>document.getElementById(id);
      window.state={mode:'library',libraryTab:'library',libraryDragPayload:null,
        libraryPaperResourceSelection:{},expandedPaperResourceProperties:new Set()};
      window.fixtureFiles=[{id:1,display_name:'Default.pdf',local_path:'/fixture/Default.pdf',extension:'pdf',exists:true,is_default:true}];
      window.paperFilesSnapshot=()=>({files:fixtureFiles});
      window.orderedLibraryPaperResources=()=>fixtureFiles;
      for(const name of ['paperFileRoleLabel','paperFileRoleOptions','paperFileAnnotationLabel',
          'paperFileAnnotationOptions','paperFileSourceLabel','paperFileSourceOptions','fileSizeLabel']) window[name]=()=>'';
      window.paperFilesStatusMarkup=()=>'<div class="paper-files-status">Nothing here</div>';
      window.escapeHtml=window.escapeAttr=String;
      window.calls=[];window.moves=[];window.notices=[];window.renders=0;
      window.updateLibraryActivityStatus=t=>notices.push(t);
      window.renderLibrary=()=>renders++;
      window.updatePaperState=()=>{};
      window.loadPaperFiles=async()=>({files:fixtureFiles});
      window.convertLibraryItemToAttachment=async(id,paper)=>moves.push({id,paper});
      window.fetch=async(url,options)=>{
        const data=typeof options.body==='string'?JSON.parse(options.body):Object.fromEntries(options.body.entries());
        calls.push({url,paperId:data.paper_id,fileName:data.file?.name,sourcePath:data.source_path,fileType:data.file_type});
        if(window.failUpload) return {ok:false,json:async()=>({error:'Fixture upload failed'})};
        if(window.holdUpload) await new Promise(resolve=>window.releaseUpload=resolve);
        return {ok:true,json:async()=>({})};
      };
      window.libraryFolderById=window.libraryItemById=()=>null;
      window.libraryDisplayRootId=()=>1;window.libraryFolderPath=()=>'';
      window.runLibraryDroppedPathsImport=()=>{throw Error('Paper Files drop became folder import');};
    });
    const names=['libraryNativeFileDragAttrs','libraryPaperResourcesColumnMarkup','libraryDragPayload',
      'wireLibraryResourceInteractions','uploadPaperFiles','uploadPaperFilePaths',
      'clearLibraryFinderDropTargetVisuals','clearLibraryFinderDropTarget','libraryFileAssociationTargetFromPoint',
      'libraryPdfDropTargetFromPoint','libraryImportDropTargetFolderId','handleNativeFinderDrop'];
    // Optional while reproducing the old code before the regression fix.
    for(const name of ['wireLibraryPaperFilesDropTarget','paperFileDropMetadata']) {
      if(html.includes(`function ${name}(`)) names.push(name);
    }
    await page.addScriptTag({content:names.map(fn).join('\n')});
    await page.evaluate(()=>{
      window.mount=(id,count=1)=>{
        fixtureFiles=Array.from({length:count},(_,i)=>({id:i+1,display_name:`File ${i}.pdf`,
          local_path:`/fixture/${i}.pdf`,extension:'pdf',exists:true,is_default:i===0}));
        $('libraryColumns').innerHTML='<div style="width:260px;flex:none">Adjacent folder</div>'+
          libraryPaperResourcesColumnMarkup({paper_id:id,display_name:'Fixture paper'});
        wireLibraryResourceInteractions($('libraryShell'));
      };
      window.dropAt=async(kind,files=['test.pdf'])=>{
        const column=document.querySelector('[data-library-resource-paper]');
        const body=column.querySelector('.library-resource-body'), rect=body.getBoundingClientRect();
        let target,x,y;
        if(kind==='blank'||kind==='bottom') {
          x=rect.left+rect.width/2;y=kind==='bottom'?rect.bottom-5:rect.top+rect.height*.7;
          target=document.elementFromPoint(x,y);
        } else {
          target=column.querySelector(kind);
          const r=target.getBoundingClientRect();x=r.left+r.width/2;y=r.top+r.height/2;
        }
        if(!target.closest('[data-library-resource-paper]')) throw Error('Fixture point missed Paper Files');
        const transfer=new DataTransfer();
        for(const name of files)transfer.items.add(new File(['test bytes'],name,{type:name.endsWith('.pdf')?'application/pdf':'text/markdown'}));
        const event=new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer,clientX:x,clientY:y});
        target.dispatchEvent(event);
        const accepted=event.defaultPrevented;
        const highlighted=column.classList.contains('finder-drop-association-target');
        target.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer,clientX:x,clientY:y}));
        return {accepted,highlighted};
      };
    });
    for(const scope of ['library','workspace-0']) {
      for(const place of ['.library-resource-inspector-head strong','.library-resource-card','.library-resource-name',
          '.paper-file-version-select','blank','bottom']) {
        await page.evaluate(({scope})=>{state.libraryTab=scope;mount(scope);calls=[];notices=[];}, {scope});
        const result=await page.evaluate(place=>dropAt(place),place);
        assert.equal(result.accepted,true,`${scope}: ${place} must accept Finder files`);
        assert.equal(result.highlighted,true,`${scope}: ${place} highlights whole column`);
        await page.waitForFunction(()=>calls.length===1 && notices.some(n=>n.includes('added')));
        assert.deepEqual(await page.evaluate(()=>calls.map(c=>[c.url,c.paperId,c.fileType])),[['/api/paper-files',scope,'preprint']]);
        assert.equal(await page.locator('.finder-drop-association-target').count(),0);
      }
      for(const count of [0,18]) {
        await page.evaluate(({scope,count})=>{mount(scope,count);calls=[];notices=[];document.querySelector('.library-resource-body').scrollTop=10000;},{scope,count});
        await page.evaluate(()=>dropAt('bottom',['one.pdf','two.md']));
        await page.waitForFunction(()=>calls.length===2 && notices.some(n=>n.includes('added')));
        assert.deepEqual(await page.evaluate(()=>calls.map(c=>c.fileType)),['preprint','unknown']);
      }
      // The native path still resolves every point in the same column.
      await page.evaluate(async(scope)=>{
        mount(scope);calls=[];
        const r=document.querySelector('.library-resource-body').getBoundingClientRect();
        await handleNativeFinderDrop(['/fixture/native.pdf'],{x:r.left+10,y:r.bottom-8});
      },scope);
      assert.deepEqual(await page.evaluate(()=>calls.map(c=>[c.url,c.paperId,c.fileType])),[['/api/paper-files/path',scope,'preprint']]);
    }
    // Replacing the column and rewiring cannot retain an old target or duplicate imports.
    await page.evaluate(()=>{mount('old');mount('current');calls=[];notices=[];});
    await page.evaluate(()=>dropAt('blank'));
    await page.waitForFunction(()=>notices.some(n=>n.includes('added')));
    assert.deepEqual(await page.evaluate(()=>calls.map(c=>c.paperId)),['current']);
    // Explicitly preserve the Library-item move route, including its file flavor.
    await page.evaluate(()=>{
      const t=new DataTransfer();t.items.add(new File(['test'],'export.pdf'));
      t.setData('application/x-paper-monitor-library',JSON.stringify({type:'item',id:7}));
      const target=document.querySelector('.library-resource-body');
      target.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:t}));
      target.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:t}));
    });
    assert.deepEqual(await page.evaluate(()=>moves),[{id:7,paper:'current'}]);
    assert.equal(await page.evaluate(()=>calls.length),1,'Library item is not also uploaded as an external file');
    await page.evaluate(()=>{mount('saving');calls=[];notices=[];holdUpload=true;});
    await page.evaluate(()=>dropAt('blank'));
    await page.waitForFunction(()=>typeof releaseUpload==='function');
    await page.evaluate(()=>{mount('next-selection');holdUpload=false;releaseUpload();});
    await page.waitForFunction(()=>notices.some(n=>n.includes('added')));
    assert.deepEqual(await page.evaluate(()=>calls.map(c=>c.paperId)),['saving'],'async upload keeps the drop-time destination');
    assert.equal(await page.locator('[data-library-resource-paper]').getAttribute('data-library-resource-paper'),'next-selection');
    await page.evaluate(async()=>{calls=[];await uploadPaperFiles(null,'manual-add',[new File(['test'],'manual.pdf')]);});
    assert.equal(await page.evaluate(()=>calls[0].fileType),'unknown','manual Add File classification stays unchanged');
    await page.evaluate(()=>{mount('failure');failUpload=true;notices=[];});
    await page.evaluate(()=>dropAt('blank'));
    await page.waitForFunction(()=>notices.includes('Fixture upload failed'));
    assert.equal(await page.locator('.finder-drop-association-target').count(),0);
    assert.deepEqual(errors,[]);
    console.log('Paper Files full-column drops passed for Library and Space: header/card/control/blank/bottom, empty/scrolled/multiple files, native paths, rerender target, internal move and error cleanup.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
