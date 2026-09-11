const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const source=fs.readFileSync(path.resolve(__dirname,'../paper_monitor/ui_server.py'),'utf8');
const names=['metadataRefreshActivityText','applyAuthorMonitorIndex','openAuthorMonitor','scheduleAuthorMonitorIdleEnrichment','authorMonitorIdleActivity','authorMonitorDisplayedActivity','authorMonitorActivityStatusClass','syncAuthorMonitorActivityDisplay','updateAuthorMonitorActivityStatus','refreshAuthorMonitorInPlace','wireAuthorMonitorIncrementalRender'];
const functions=names.map(n=>{const re=new RegExp('    (?:async )?function '+n+'\\(');const start=source.search(re);assert.ok(start>=0,n);return source.slice(start,source.indexOf('\n    }',start)+6)}).join('\n');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.GEWU_TEST_CHROME});
 try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<button id="authorTab">Author Monitor</button><input id="editor" value="unsaved"><div id="authorMonitorAuthors"><div data-author-id="1">A</div></div><div id="authorMonitorPaperList" style="height:170px;overflow:auto"></div><div id="authorMonitorActivityStatus"></div><div id="authorMonitorSecondaryActivityStatus"></div><div id="papers"></div>');
 await page.addScriptTag({content:`
 const paperMetadataRequests=new Map();
 const $=id=>document.getElementById(id),AUTHOR_MONITOR_INITIAL_CARD_COUNT=10,AUTHOR_MONITOR_CARD_BATCH_SIZE=10;
 const state={mode:'author',authorMonitorLoaded:true,authorMonitorLoadedAt:Date.now()-3600000,authorMonitorSelectedId:1,authorMonitorSelectedPaperId:'p3',authorMonitors:[{id:1,name:'A',status:'success',last_success_at:'2026-09-10T10:00:00+08:00',message:'No new publications.'}],authorMonitorMetadataWork:{status:'waiting_retry',waiting_retry:7,retry_at:'2026-09-17T10:00:00+08:00'}};
 let loads=0,summaryReads=0,remoteRequests=0,paused=false;
 const loadFieldSettings=async()=>{},closeLibraryQuickLook=()=>{},closeAnalysis=()=>{},stopArxivUpdateCountdown=()=>{},setPrimaryView=()=>{},authorMonitorScopeHasExpectedPapers=()=>true,renderAuthorMonitor=()=>{},refreshAuthorMonitorSummary=()=>{summaryReads++},pollAuthorMonitorInitialImport=()=>{},loadAuthorMonitorScope=async()=>{loads++},fetch=async()=>{remoteRequests++;throw Error('opening must not start remote work')};
 const selectedAuthorMonitor=()=>state.authorMonitors[0],scholarGlobalCooldownActive=()=>paused,authorMonitorIsScholar=()=>true,scholarGlobalCooldownText=()=> 'Google Scholar paused until tomorrow',autoStatusTime=x=>x||'',authorMonitorIsBackgroundScholarJob=a=>['idle','queued','refreshing'].includes(a.status);
 const persistAuthorMonitorSelectedId=()=>{},invalidateAuthorMonitorViewCache=()=>{},syncAuthorMonitorBackgroundScholarStatus=()=>{},initialAuthorMonitorSelectedId=()=>1,authorMonitorVisiblePapers=()=>state.authorMonitorPapers;
 let papers=Array.from({length:8},(_,i)=>({paper_id:'p'+i,title:'Paper '+i,citation_count:i}));
 const authorMonitorPartitionedPapers=()=>({articles:state.authorMonitorPapers || papers,conferences:[]}),publicationTitleMarkup=t=>t,authorMonitorCitationText=p=>'Citation '+p.paper_id,authorMonitorPaperIsUnread=()=>false,updateAuthorMonitorTopDot=()=>{},appendAuthorMonitorPaperCards=()=>{};
 function renderAuthorMonitorPaperCard(p){const n=document.createElement('article');n.className='author-paper-card';n.dataset.paperId=p.paper_id;n._paperModel=p;n.tabIndex=-1;n.style.height='55px';n.innerHTML='<span class="author-paper-title"></span><span class="author-paper-citation"></span><span class="author-paper-scholar-citations"></span><button>+</button>';return n;}
 ${functions}
 `});
 await page.evaluate(async()=>{for(let i=0;i<12;i++)await openAuthorMonitor();});
 assert.deepEqual(await page.evaluate(()=>({loads,remoteRequests})),{loads:0,remoteRequests:0},'expired memory cache opens without blocking or starting enrichment');
 assert.match(await page.locator('#authorMonitorActivityStatus').innerText(),/Last successful check/);
 assert.match(await page.locator('#authorMonitorSecondaryActivityStatus').innerText(),/7 waiting for retry/);
 await page.evaluate(()=>updateAuthorMonitorActivityStatus('Finished',{delay:15}));
 await page.waitForTimeout(35);
 assert.match(await page.locator('#authorMonitorActivityStatus').innerText(),/Last successful check/,'completed transient restores durable status');
 await page.evaluate(()=>{paused=true;syncAuthorMonitorActivityDisplay();});
 assert.match(await page.locator('#authorMonitorActivityStatus').innerText(),/paused/);
 await page.evaluate(()=>{paused=false;refreshAuthorMonitorInPlace();$('authorMonitorPaperList').scrollTop=160;window.retained=$('authorMonitorPaperList').querySelector('[data-paper-id="p3"]');$('editor').focus();});
 const before=await page.evaluate(()=>{const l=$('authorMonitorPaperList'),a=l.querySelector('[data-paper-id="p3"]');return a.getBoundingClientRect().top-l.getBoundingClientRect().top});
 await page.evaluate(()=>{papers=[{paper_id:'new',title:'New paper'},...papers.map(p=>({...p,citation_count:99}))];refreshAuthorMonitorInPlace();});
 assert.equal(await page.evaluate(()=>document.activeElement.id),'editor');
 assert.equal(await page.locator('#editor').inputValue(),'unsaved');
 assert.equal(await page.evaluate(()=>window.retained===$('authorMonitorPaperList').querySelector('[data-paper-id="p3"]')),true,'existing cards remain mounted');
 const after=await page.evaluate(()=>{const l=$('authorMonitorPaperList'),a=l.querySelector('[data-paper-id="p3"]');return a.getBoundingClientRect().top-l.getBoundingClientRect().top});
 assert.ok(Math.abs(after-before)<2,'new paper insertion preserves the reading anchor');
 assert.equal(await page.locator('[data-paper-id="p3"] .author-paper-scholar-citations').innerText(),'Cited by 99');
 await page.evaluate(()=>{$('authorTab').focus();refreshAuthorMonitorInPlace();});
 assert.equal(await page.evaluate(()=>document.activeElement.id),'authorTab');
 await page.evaluate(()=>{state.mode='browser';refreshAuthorMonitorInPlace();});
 assert.equal(await page.evaluate(()=>state.mode),'browser');
 await page.evaluate(()=>{
   state.mode='author';state.authorMonitorSelectedPaperId='p3';state.authorMonitorPaperCache=new Map();
   state.authorMonitorSelectedPaperByAuthor=new Map([[1,'p0']]);state.authorMonitorPapers=papers;
   applyAuthorMonitorIndex({indexReady:true,papers:papers.map(p=>({...p})),authors:state.authorMonitors});
 });
 assert.equal(await page.evaluate(()=>state.authorMonitorSelectedPaperId),'p3','background index cannot restore an older remembered selection');
 assert.deepEqual(errors,[]);console.log('Expired cache, durable status, cooldown display, retained cards, reading anchor, input/tab focus and background workspace checks passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
