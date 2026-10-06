// Exercise the actual rename/cache handlers with controlled pending responses.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(0,'utf8');
function fn(name){const start=html.search(new RegExp('    (?:async )?function '+name+'\\('));assert(start>=0,name);const text=html.slice(start),end=text.slice(1).search(/\n    (?:async )?function /);return text.slice(0,end+1);}
const functions=['applyFolderRenameResult','commitLibraryEntryRename','renameLibraryWorkspace',
 'ensureLibraryFolderLoaded','loadLibraryItemPaperDetail','loadMyPublicationPaperDetail','loadPaperFiles'];
const paper={paper_id:'p',merged_pdf_path:'/Library/Before/p.pdf',merged_pdf_url:'old',
 native_file_path:'/Library/Before/p.pdf',analysis_path:'/Associated Files/Library/Before/n.md',analysis_url:'old'};
const folder={id:2,parent_id:1,name:'Before',native_folder_path:'/Library/Before'};
const s={libraryPathRevision:0,libraryRootId:1,libraryFolders:[folder,{id:3,native_folder_path:'/Library/Before/sub'}],
 libraryItems:[{id:10,folder_id:2,paper_id:'p',paper},{id:11,paper_id:'q',paper:{paper_id:'q',merged_pdf_path:'/Library/Before-other/q.pdf'}}],
 myPublications:[{paper_id:'p',paper:{...paper}}],papers:[{...paper}],themePapers:[],authorMonitorPapers:[],
 reportCache:{day:{papers:[{...paper}]}},themePapersByDate:{},paperFilesByPaperId:{p:{old:true},q:{kept:true}},
 paperFileRequests:{},libraryPaperDetailRequests:{},libraryFolderLoadPromises:{},
 libraryWorkspaceTabs:[{tab_id:'space',label:'Before'}],libraryRenamingFolderId:2,libraryRenamingItemId:0,
 mode:'library',libraryTab:'library',librarySelection:{type:'folder',id:2}};
let pending=[],appliedFolders=0,rendered=0,focus=0,updates=0,resetSearch=0;
const c={state:s,console,encodeURIComponent,Set,Promise,window:{},fetch:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve})),
 libraryFolderLoaded:()=>false,applyLibraryFolderChildren:()=>appliedFolders++,
 resetRemoteLibrarySearch:()=>resetSearch++,renderLibrary:()=>rendered++,restoreLibraryKeyboardFocus:()=>focus++,
 updateLibraryActivityStatus:()=>{},upsertLibraryFolderLocal:f=>Object.assign(folder,f),
 libraryItemById:id=>s.libraryItems.find(i=>i.id===id),parentFolderId:()=>1,
 setLibraryColumnSelection:(_,selection)=>{s.librarySelection=selection;},applyPaperFilesPayloads:()=>{},
 upsertLibraryItemLocal:()=>{},updatePaperState:()=>updates++,paperFilesSnapshot:id=>s.paperFilesByPaperId[id],
 renderLibraryDetail:()=>{},renderPublicationDetail:()=>{},renderLibraryNavigationContent:()=>{},
 selectedMyPublicationPaper:()=>s.myPublications[0].paper,refreshLibraryQuickLookForSelection:()=>{},
 libraryWorkspaceLabel:()=>s.libraryWorkspaceTabs[0].label,applyLibraryNavigationSnapshot:()=>{},
 $:()=>null};
vm.createContext(c);vm.runInContext(functions.map(fn).join('\n'),c);
const respond=(request,data,ok=true)=>request.resolve({ok,json:async()=>data});
const payload={folder:{...folder,name:'After',native_folder_path:'/Library/After'},renamed_paper_ids:['p'],
 renamed_paths:[{old:'/Library/Before',new:'/Library/After'},
 {old:'/Associated Files/Library/Before',new:'/Associated Files/Library/After'}]};
(async()=>{
 const folderRead=c.ensureLibraryFolderLoaded(2);
 const detailRead=c.loadLibraryItemPaperDetail(s.libraryItems[0]);
 const filesRead=c.loadPaperFiles('p');
 const stale=pending.splice(0);
 const rename=c.commitLibraryEntryRename('folder',2,'After');
 const request=pending.shift();assert.equal(request.url,'/api/library/folders/rename');
 assert.deepEqual(JSON.parse(request.options.body),{folder_id:2,name:'After',snapshot:false});
 respond(request,payload);await rename;
 assert.equal(paper.merged_pdf_path,'/Library/After/p.pdf');
 assert.equal(paper.analysis_path,'/Associated Files/Library/After/n.md');
 assert.equal(paper.merged_pdf_url,'/files?path=%2FLibrary%2FAfter%2Fp.pdf');
 assert.equal(s.myPublications[0].paper.native_file_path,'/Library/After/p.pdf');
 assert.equal(s.reportCache.day.papers[0].merged_pdf_path,'/Library/After/p.pdf');
 assert.equal(s.libraryFolders[1].native_folder_path,'/Library/After/sub');
 assert.equal(s.libraryItems[1].paper.merged_pdf_path,'/Library/Before-other/q.pdf');
 assert.equal(s.paperFilesByPaperId.p,undefined);assert.equal(s.paperFilesByPaperId.q.kept,true);
 assert.equal(s.librarySelection.id,2);assert.equal(focus,1);assert.equal(resetSearch,1);
 stale.forEach(r=>respond(r,{paper:{paper_id:'p',merged_pdf_path:'/Library/Before/stale.pdf'},files:['stale']}));
 await Promise.all([folderRead,detailRead,filesRead]);
 assert.equal(appliedFolders,0);assert.equal(updates,0);assert.equal(s.paperFilesByPaperId.p,undefined);
 const newRead=c.loadPaperFiles('p');respond(pending.shift(),{files:[{path:'/Library/After/p.pdf'}]});await newRead;
 assert.equal(s.paperFilesByPaperId.p.files[0].path,'/Library/After/p.pdf');
 const revision=s.libraryPathRevision;
 const failed=c.commitLibraryEntryRename('folder',2,'Blocked');respond(pending.shift(),{error:'Destination exists'},false);
 await assert.rejects(failed,/Destination exists/);assert.equal(s.libraryPathRevision,revision);assert.equal(folder.name,'After');
 // Space-root rename uses exactly the same cache update.
 const space=c.renameLibraryWorkspace(0,'Final');respond(pending.shift(),{
 ...payload,renamed_paths:[{old:'/Library/After',new:'/Library/Final'}]});await space;
 assert.equal(paper.merged_pdf_path,'/Library/Final/p.pdf');assert.equal(s.libraryTab,'workspace-0');
 console.log('Folder/Space rename: cached paths, attachments, late replies, selection and failure checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
