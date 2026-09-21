// Deterministic transport/worker races using the actual preview controller.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=JSON.parse(fs.readFileSync(0,'utf8'));
const source=html.slice(html.indexOf('    let libraryMarkdownWorker = null;'),html.indexOf('    async function renderLibraryQuickLookFilePreview'));
const root={innerHTML:'',querySelectorAll:()=>[]},requests=[],workers=[],timers=new Map();let nextTimer=0,token=0;
class Worker {
  constructor(){this.jobs=[];this.terminated=false;workers.push(this);}
  postMessage(job){this.jobs.push(job);}
  terminate(){this.terminated=true;}
  reply(text){const job=this.jobs.shift();assert.ok(job);this.onmessage({data:{path:job.path,token:job.token,html:text??'<h1>'+job.content.text+'</h1>',truncated:job.content.truncated}});}
}
const state={libraryQuickLookOpen:true,libraryQuickLookKind:'file'};
const context=vm.createContext({Map,AbortController,Worker,state,$:()=>root,paperNativePath:p=>p.path,openWebsite(){},
  renderLibraryFilePreviewCard:(_root,_paper,message)=>{root.innerHTML=message;},
  setTimeout:(fn,delay)=>{const id=++nextTimer;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id),
  fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))});
vm.runInContext(source,context);
function show(path){context.cancelLibraryMarkdownPreview();state.libraryQuickLookPath=path;state.libraryQuickLookRenderToken=++token;state.libraryQuickLookOpen=true;state.libraryQuickLookKind='file';return context.renderLibraryMarkdownPreview({path},token);}
function respond(req,status,text='',etag='W/"v1"'){req.resolve({status,ok:status===200,headers:{get:()=>etag},json:async()=>status===200?{text,truncated:false}:{error:'Unavailable '+status}});}
async function fresh(path,text,etag='W/"v1"',rendered){const done=show(path);respond(requests.at(-1),200,text,etag);await done;workers.at(-1).reply(rendered);assert.equal(timers.size,0);}
(async()=>{
  const cold=show('/cold.md');
  assert.equal(workers.length,1);assert.equal(workers[0].jobs.length,0);
  assert.equal(requests.length,1,'file fetch starts without waiting for worker scripts');
  respond(requests.at(-1),200,'First');await cold;
  assert.match(root.innerHTML,/Loading Markdown/);workers[0].reply();assert.match(root.innerHTML,/<h1>First/);
  const warm=show('/cold.md');assert.equal(requests.at(-1).options.headers['If-None-Match'],'W/"v1"');
  assert.match(root.innerHTML,/Loading Markdown/,'do not show stale content before validation');
  respond(requests.at(-1),304);await warm;
  assert.match(root.innerHTML,/<h1>First/);assert.equal(workers[0].jobs.length,0,'unchanged file bypasses parsing');
  await fresh('/cold.md','Edited','W/"v2"');assert.match(root.innerHTML,/<h1>Edited/);
  const denied=show('/cold.md');respond(requests.at(-1),403);await denied;
  assert.equal(root.innerHTML,'Unavailable 403');
  const retry=show('/cold.md');assert.equal(requests.at(-1).options.headers['If-None-Match'],undefined);
  respond(requests.at(-1),200,'Restored');await retry;workers.at(-1).reply();
  const slow=show('/slow.md'),slowRequest=requests.at(-1);
  await fresh('/current.md','Current');assert.equal(slowRequest.options.signal.aborted,true);
  respond(slowRequest,200,'Obsolete');await slow;assert.match(root.innerHTML,/<h1>Current/);
  const parsing=show('/parsing.md');respond(requests.at(-1),200,'Obsolete parse');await parsing;
  const oldWorker=workers.at(-1);await fresh('/new.md','New');assert.equal(oldWorker.terminated,true);
  oldWorker.reply();assert.match(root.innerHTML,/<h1>New/,'late replies from a replaced worker are ignored');
  const sameOld=show('/same.md'),sameRequest=requests.at(-1);
  await fresh('/same.md','Latest');respond(sameRequest,200,'Same-path old');await sameOld;assert.match(root.innerHTML,/<h1>Latest/);
  const hanging=show('/hanging.md'),hangingRequest=requests.at(-1),watchdog=[...timers.values()][0];
  assert.equal(watchdog.delay,15000);watchdog.fn();assert.match(root.innerHTML,/took too long/);
  assert.equal(hangingRequest.options.signal.aborted,true);assert.equal(workers.at(-1).terminated,true);
  await fresh('/recovered.md','Recovered');respond(hangingRequest,200,'Late');await hanging;assert.match(root.innerHTML,/<h1>Recovered/);
  const failed=show('/worker-error.md'),failedRequest=requests.at(-1);
  workers.at(-1).onerror();assert.match(root.innerHTML,/could not be loaded/);assert.equal(failedRequest.options.signal.aborted,true);
  respond(failedRequest,200,'Failed old');await failed;await fresh('/after-error.md','Healthy');
  const rejected=show('/io-error.md');requests.at(-1).reject(new Error('Read failed'));await rejected;assert.equal(root.innerHTML,'Read failed');
  await fresh('/no-etag.md','Unstable','');const unstable=show('/no-etag.md');assert.equal(requests.at(-1).options.headers['If-None-Match'],undefined);
  respond(requests.at(-1),200,'Stable');await unstable;workers.at(-1).reply();
  for(let n=0;n<10;n++)await fresh('/bounded-'+n+'.md','Bounded','W/"same"','<p>'+'x'.repeat(240000)+'</p>');
  const evicted=show('/bounded-0.md');assert.equal(requests.at(-1).options.headers['If-None-Match'],undefined,'old HTML is evicted under the memory limit');
  respond(requests.at(-1),200,'Again');await evicted;workers.at(-1).reply();
  assert.ok(vm.runInContext('libraryMarkdownCache.size <= 8 && libraryMarkdownCacheChars <= 1000000',context));
  const closing=show('/closing.md'),closingRequest=requests.at(-1);
  context.cancelLibraryMarkdownPreview();state.libraryQuickLookKind='pdf';root.innerHTML='PDF';respond(closingRequest,200,'Wrong file');await closing;
  assert.equal(root.innerHTML,'PDF');assert.equal(closingRequest.options.signal.aborted,true);assert.equal(timers.size,0);
  console.log('Markdown preview flow checks passed: parallel start, validated bounded reuse, edits/errors, cancel/late replies, timeout recovery and PDF transition.');
})().catch(e=>{console.error(e);process.exitCode=1;});
