const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path').posix;
const adapter = require('../integrations/zotero/import.js');

global.PathUtils={join:path.join,normalize:path.normalize,joinRelative:path.join,filename:path.basename};
global.Zotero={Prefs:{get:()=>'/external/papers'},Attachments:{getStorageDirectory:()=>({path:'/zotero/storage/ABCD1234'})}};
const attachment=(attachmentPath,stored=false)=>({attachmentPath,isFileAttachment:()=>true,isStoredFileAttachment:()=>stored,
  getFilePathAsync(){throw Error('Must not invoke Zotero path repair');},save(){throw Error('Source write forbidden');}});

test('read-only path resolution handles stored, linked and relative attachments',()=>{
  assert.equal(adapter.path(attachment('storage:paper.pdf',true)),'/zotero/storage/ABCD1234/paper.pdf');
  assert.equal(adapter.path(attachment('attachments:2026/paper.pdf')),'/external/papers/2026/paper.pdf');
  assert.equal(adapter.path(attachment('/elsewhere/paper.pdf')),'/elsewhere/paper.pdf');
  assert.throws(()=>adapter.path(attachment('AAAAlegacy-alias')));
  assert.throws(()=>adapter.path(attachment('storage:../unsafe.pdf',true)));
});

test('stable comparison ignores object key order but detects source edits',()=>{
  assert.deepEqual(adapter.stable({b:1,a:{y:2,x:3}}),adapter.stable({a:{x:3,y:2},b:1}));
  assert.notDeepEqual(adapter.stable({a:'old'}),adapter.stable({a:'new'}));
});

test('PDF export explicitly keeps original Zotero annotation records',async()=>{
  const entry={data:{key:'PAPER001'},attachments:[{key:'ATTACH01',path:'/original.pdf',filename:'paper.pdf',contentType:'application/pdf',annotations:[{type:'highlight'}]}]};
  const record=adapter.record;let called;
  adapter.record=async()=>entry;
  global.Services={uuid:{generateUUID:()=>({toString:()=>'{export-id}'})}};
  global.IOUtils={exists:async()=>false,stat:async()=>({size:42,lastModified:1})};
  Zotero.Items={getByLibraryAndKeyAsync:async()=>({id:9,deleted:false})};
  Zotero.PDFWorker={export:async(...args)=>{called=args;}};
  try{
    const result=await adapter.exportRecord({config:{library_id:1},entry,export_dir:'/owned-export'});
    assert.equal(result.attachments.length,1);
    assert.equal(called[4],false);
    assert.equal(called[1],'/owned-export/export-id.pdf');
    assert.equal(result.attachments[0].annotated,true);
  }finally{adapter.record=record;}
});

test('source edits after preview block exporting and importing',async()=>{
  const record=adapter.record;
  adapter.record=async()=>({data:{key:'PAPER001',title:'changed'}});
  try{await assert.rejects(adapter.exportRecord({config:{library_id:1},entry:{data:{key:'PAPER001',title:'old'}}}),/changed after preview/);}
  finally{adapter.record=record;}
});

test('export cleanup never removes an original or an unowned replacement',async()=>{
  const calls=[];adapter.ownedExports.clear();adapter.ownedExports.set('/owned/new.pdf',{size:5,mtime:10});
  adapter.ownedExports.set('/owned/changed.pdf',{size:5,mtime:10});
  global.IOUtils={stat:async p=>({type:'regular',size:p.includes('changed')?9:5,lastModified:10}),remove:async p=>calls.push(p)};
  await adapter.releaseExports({attachments:[{path:'/original.pdf'},{path:'/owned/new.pdf'},{path:'/owned/changed.pdf'}]});
  assert.deepEqual(calls,['/owned/new.pdf']);
});

test('connection verifies the selected database before starting an adapter',async()=>{
  const saved={call:adapter.call,catalog:adapter.catalog,loop:adapter.loop};
  global.GewuMonitor={supportPath:name=>path.join('/user/Application Support/Gewu Insight',name)};
  const config={workspace:'/gewudb',origin:'http://127.0.0.1:8765',generation:'a'.repeat(48),requested_at:Date.now()/1000,job_id:'job'};
  global.Ci={nsIFile:{}};global.Services={dirsvc:{get:()=>({path:'/user'})}};
  global.GewuZoteroCore=require('../integrations/zotero/core.js');
  global.IOUtils={readUTF8:async p=>p.endsWith('.gewu-workspace-token')?'b'.repeat(64):JSON.stringify(config)};
  Zotero.File={pathToFile:p=>({path:p,normalize(){}})};
  let matching=false,started=0;
  Zotero.HTTP={request:async()=>({response:{database_path:matching?'/gewudb/data/paper_monitor.sqlite':'/other/data/paper_monitor.sqlite'}})};
  adapter.call=async()=>({ok:true});adapter.catalog=async()=>({});adapter.loop=async()=>{started++;};
  try{
    await assert.rejects(adapter.connect({spec:'zotero://gewu-insight/import?request='+config.generation}),/differs/);
    assert.equal(started,0);matching=true;
    await adapter.connect({spec:'zotero://gewu-insight/import?request='+config.generation});assert.equal(started,1);
    config.requested_at-=600;
    await assert.rejects(adapter.connect({spec:'zotero://gewu-insight/import?request='+config.generation}),/reconnect/);
  }finally{Object.assign(adapter,saved);adapter.connection=null;}
});
