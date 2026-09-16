// Real product controller + ephemeral WebKit against an explicit localhost fixture.
// Only this test admits its loopback URLs; production URL guards are unchanged.
#import "GewuBrowserNavigation.h"
static NSString *fixtureOrigin;
static BOOL fixtureURL(NSURL *u) { return GewuBrowserPublicURL(u) || [u.absoluteString hasPrefix:[fixtureOrigin stringByAppendingString:@"/"]] || ([u.host isEqual:@"localhost"] && [u.port isEqual:[NSURL URLWithString:fixtureOrigin].port]); }
static BOOL fixtureBlob(NSURL *u, NSURL *s) { return GewuBrowserBlobURL(u,s) || ([s.absoluteString hasPrefix:fixtureOrigin] && [u.absoluteString hasPrefix:[@"blob:" stringByAppendingFormat:@"%@/",fixtureOrigin]]); }
#define GewuBrowserPublicURL fixtureURL
#define GewuBrowserBlobURL fixtureBlob
#import "GewuBrowserController.m"
#import "GewuBrowserCapture.m"
#undef GewuBrowserPublicURL
#undef GewuBrowserBlobURL

static NSInteger checks;
static void check(BOOL ok, const char *name) { if(!ok){fprintf(stderr,"FAIL: %s\n",name);exit(1);} checks++; printf("PASS: %s\n",name);fflush(stdout); }
static BOOL spin(BOOL (^done)(void)) { NSDate *limit=[NSDate dateWithTimeIntervalSinceNow:15]; while(!done()&&limit.timeIntervalSinceNow>0)[NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]]; return done(); }
static BOOL js(WKWebView *v,NSString *script) { __block BOOL done=NO,ok=NO; [v evaluateJavaScript:script completionHandler:^(id r,NSError *e){ok=!e;done=YES;}];return spin(^BOOL{return done;})&&ok; }
@interface PDFBrowser:GewuBrowserController
@property(strong) WKWebsiteDataStore *testStore;
@property NSInteger received;
@property(strong) NSMutableArray<NSURL *> *temporaryDirectories;
@property(strong) NSDictionary *saveRequest;
@end
@implementation PDFBrowser
- (void)saveDisplayedPDF:(NSDictionary *)pdf { self.saveRequest=pdf; }
- (GewuBrowserPage *)makePage {
 WKWebViewConfiguration *c=[WKWebViewConfiguration new]; if(!self.testStore)self.testStore=WKWebsiteDataStore.nonPersistentDataStore;c.websiteDataStore=self.testStore;c.preferences.javaScriptCanOpenWindowsAutomatically=YES;return [super makePageWithConfiguration:c];
}
- (void)download:(WKDownload *)d decideDestinationUsingResponse:(NSURLResponse *)r suggestedFilename:(NSString *)f completionHandler:(void (^)(NSURL *))done {
 [super download:d decideDestinationUsingResponse:r suggestedFilename:f completionHandler:^(NSURL *u){if(u){self.received++;fprintf(stderr,"TRANSFER %ld %s\n",(long)self.received,r.URL.path.UTF8String);[self.temporaryDirectories addObject:u.URLByDeletingLastPathComponent];}done(u);}];
}
@end
static void load(PDFBrowser *b,NSString *path) {
 [b openContentRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:[fixtureOrigin stringByAppendingString:path]]]];
 BOOL loaded=spin(^BOOL{return [b.webView.URL.path isEqual:path]&&!b.webView.loading&&b.currentPage.ready;});
 if(!loaded)fprintf(stderr,"LOAD DEBUG path=%s url=%s ready=%d opening=%d pending=%d transfers=%ld cached=%lu error=%s\n",path.UTF8String,b.webView.URL.absoluteString.UTF8String,b.currentPage.ready,b.currentPage.openingPDF,b.selectedTab.contentPendingFromHome,(long)b.received,(unsigned long)b.currentPage.pdfDocuments.count,b.currentPage.errorMessage.UTF8String);
 check(loaded,"fixture document loads");
}
static NSDictionary *awaitPDF(PDFBrowser *b,GewuBrowserPage *page) {
 static NSDictionary *previous;
 BOOL loaded=spin(^BOOL{return [b PDFDocumentForPage:page]!=nil && [b PDFDocumentForPage:page]!=previous && !page.openingPDF && !page.view.loading && page.ready;});
 if(!loaded)fprintf(stderr,"PDF DEBUG tabs=%lu url=%s ready=%d opening=%d downloads=%lu pendingdoc=%d cached=%lu member=%d error=%s\n",(unsigned long)b.tabs.count,page.view.URL.absoluteString.UTF8String,page.ready,page.openingPDF,(unsigned long)b.downloads.count,page.pendingPDFDocument!=nil,(unsigned long)page.pdfDocuments.count,[b tabForPage:page]!=nil,page.errorMessage.UTF8String);
 check(loaded,"download bytes display as PDF in original surface");
 previous=[b PDFDocumentForPage:page];return previous;
}
int main(int argc,const char **argv){@autoreleasepool{
 fixtureOrigin=@(argv[1]);[NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
 NSWindow *w=[[NSWindow alloc] initWithContentRect:NSMakeRect(40,40,800,600) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];w.releasedWhenClosed=NO;w.title=@"Gewu generated PDF verification";
 WKWebViewConfiguration *c=[WKWebViewConfiguration new];c.websiteDataStore=WKWebsiteDataStore.nonPersistentDataStore;
 WKWebView *workspace=[[WKWebView alloc] initWithFrame:w.contentView.bounds configuration:c];[w.contentView addSubview:workspace];
 PDFBrowser *b=[[PDFBrowser alloc] initWithWorkspace:workspace];[b.favicons invalidate];b.favicons=nil;b.temporaryDirectories=[NSMutableArray array];b.active=YES;b.visible=YES;[b ensureWebView];[w orderBack:nil];
 load(b,@"/start");b.webView.frame=workspace.frame;
 check(js(b.webView,@"document.getElementById('attachment').click()"),"publisher attachment link clicked");
 NSDictionary *first=awaitPDF(b,b.currentPage); NSData *expected=first[@"data"];
 check(b.received==1 && [b.webView.URL.query isEqual:@"download=true"],"one transfer preserves original download URL");
 __block BOOL snapped=NO; [b.webView takeSnapshotWithConfiguration:nil completionHandler:^(NSImage *im,NSError *e){if(im){NSBitmapImageRep *r=[NSBitmapImageRep imageRepWithData:im.TIFFRepresentation];[[r representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:@"/private/tmp/gewu-browser-pdf-qa/product-preview.png" atomically:YES];}snapped=YES;}];spin(^BOOL{return snapped;});
 [b handleCommand:@{@"action":@"reload"}];awaitPDF(b,b.currentPage);check(b.received==1,"reload uses received bytes without repeating download");
 load(b,@"/start");check(js(b.webView,@"document.getElementById('post').click()"),"POST download submitted");awaitPDF(b,b.currentPage);check(b.received==2,"POST download is not reconstructed as GET");
 load(b,@"/binary"); // PDF becomes a data document with the same URL.
 awaitPDF(b,b.currentPage);check(b.received==3,"binary MIME PDF opens inline");
 load(b,@"/start");GewuBrowserTab *opener=b.selectedTab;
 opener.originPaperID=@"source-paper";opener.originLibraryItemID=101;opener.workspaceReturnID=@"source-return";
 check(js(b.webView,@"document.getElementById('popup').click()"),"publisher popup link clicked");check(spin(^BOOL{return b.tabs.count==2;}),"new tab tracked");awaitPDF(b,b.currentPage);check(b.selectedTab!=opener,"PDF uses publisher-created tab");
 check([b.selectedTab.originPaperID isEqual:@"source-paper"] && b.selectedTab.originLibraryItemID==101 && [b.selectedTab.workspaceReturnID isEqual:@"source-return"],"related PDF tab inherits paper, placement and return context");
 [b closeTab:b.selectedTab];check(b.selectedTab==opener,"closing PDF restores opener");
 check(js(b.webView,@"let raw=atob(fixtureBase64);let bytes=Uint8Array.from(raw,x=>x.charCodeAt(0));let u=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));let a=document.createElement('a');a.href=u;a.download='Generated.pdf';a.target='_blank';document.body.appendChild(a);a.click();"),"page creates blob PDF link");
 awaitPDF(b,b.currentPage);check([b.webView.URL.path isEqual:@"/start"],"blob PDF retains public creating page as source");
 check(b.tabs.count<=2,"download attribute respects WebKit tab choice without extra tabs");
 if(b.tabs.count>1)[b closeTab:b.selectedTab];load(b,@"/start");
 check(js(b.webView,@"let raw=atob(fixtureBase64);let bytes=Uint8Array.from(raw,x=>x.charCodeAt(0));let u=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));let a=document.createElement('a');a.href=u;a.target='_blank';document.body.appendChild(a);a.click();"),"blob navigation requests a new tab");
 check(spin(^BOOL{return b.tabs.count==2;}),"blob navigation popup tracked");awaitPDF(b,b.currentPage);
 [b closeTab:b.selectedTab];load(b,@"/start");
 check(js(b.webView,@"document.getElementById('slow').click()"),"slow download started");check(spin(^BOOL{return b.currentPage.openingPDF;}),"opening PDF state visible");GewuBrowserTab *downloading=b.selectedTab;
 GewuBrowserTab *other=[b addTabWithRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:[fixtureOrigin stringByAppendingString:@"/other"]]] configuration:nil];
 check(spin(^BOOL{return [b.webView.title isEqual:@"Other fixture"]&&!b.webView.loading;}),"other tab remains usable during PDF transfer");
 [w makeFirstResponder:workspace];awaitPDF(b,downloading.contentPage);
 check(b.selectedTab==other&&w.firstResponder==workspace,"completion does not switch tab or steal focus");
 [b selectTab:downloading];load(b,@"/start");check(js(b.webView,@"document.getElementById('slow').click()"),"second slow download started");check(spin(^BOOL{return b.currentPage.openingPDF;}),"second download reports progress");
 load(b,@"/other");check(!b.currentPage.openingPDF&&b.downloads.count==0,"navigation cancels stale preview without overwriting new document");
 [b openContentRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:[fixtureOrigin stringByAppendingString:@"/not-pdf"]]]];
 check(spin(^BOOL{return b.currentPage.errorMessage.length>0;}),"HTML masquerading as PDF shows an error");
 // Exercise the actual captureDownload cache branch with a generated public
 // base URL. loadData does not fetch that address or require a live website.
 NSURL *publicSource=[NSURL URLWithString:@"https://example.invalid/one-use-pdf"];
 [workspace loadHTMLString:@"<title>Generated trusted workspace</title>" baseURL:[NSURL URLWithString:fixtureOrigin]];
 check(spin(^BOOL{return workspace.URL!=nil&&!workspace.loading;}),"temporary workspace has capture endpoint origin");
 b.currentPage.pendingPDFDocument=[first mutableCopy];
 b.currentPage.pdfNavigation=[b.webView loadData:expected MIMEType:@"application/pdf" characterEncodingName:@"UTF-8" baseURL:publicSource];awaitPDF(b,b.currentPage);
 __block BOOL uploaded=NO;__block NSString *uploadError;
 b.captureSnapshots=[@{@"fixture":@{@"page":b.currentPage,@"url":publicSource,@"generation":b.currentPage.captureDocumentID,@"urls":@[publicSource.absoluteString]}} mutableCopy];
 b.onEvent=^(NSDictionary *e){if([e[@"event"] isEqual:@"capture-pdf"]){uploaded=YES;uploadError=e[@"error"];}};
 [b captureDownload:@{@"snapshot_id":@"fixture",@"url":publicSource.absoluteString,@"token":@"fixture-ticket",@"upload_token":@"synthetic-capture-token-0123456789abcdef"}];
 check(spin(^BOOL{return uploaded;})&&!uploadError.length,"Save to Gewu uses displayed bytes without another publisher request");
 [b handleCommand:@{@"action":@"download"}];
 check(spin(^BOOL{return b.saveRequest!=nil;}),"Save Download opens its save request");
 check([[NSData dataWithContentsOfURL:[b.saveRequest[@"file"] URL]] isEqual:expected],"explicit Save Download offers the received PDF bytes");
 NSInteger beforeInline=b.received;load(b,@"/inline");check(b.received==beforeInline,"ordinary inline PDF does not enter temporary download flow");
 __block GewuBrowserPDFFile *loadedFile; __block NSString *loadedError; __block BOOL read=NO;
 [b loadedPDFForPage:b.currentPage URL:b.webView.URL.absoluteString completion:^(GewuBrowserPDFFile *file,NSString *error){loadedFile=file;loadedError=error;read=YES;}];
 check(spin(^BOOL{return read;}) && loadedFile && !loadedError,"WebKit exposes an already loaded no-store PDF");
 check([[NSData dataWithContentsOfURL:loadedFile.URL] isEqual:expected],"loaded resource is byte-for-byte original PDF, not a viewer archive or generated PDF");
 NSURL *reusedURL=loadedFile.URL;
 read=NO; [b loadedPDFForPage:b.currentPage URL:b.webView.URL.absoluteString completion:^(GewuBrowserPDFFile *file,NSString *error){check([file.URL isEqual:reusedURL],"cancel/reopen reuses the same scoped copy");read=YES;}];
 check(read,"repeat read reuses local copy immediately");
 b.saveRequest=nil; [b handleCommand:@{@"action":@"download"}];
 check([b.saveRequest[@"file"] URL]==reusedURL,"footer exports the loaded inline PDF");
 b.saveRequest=nil;
 [b _webView:b.webView saveDataToFile:expected suggestedFilename:@"Generated.pdf" mimeType:@"application/pdf" originatingURL:b.webView.URL];
 check(spin(^BOOL{return b.saveRequest!=nil;}),"native PDF HUD callback reaches Save Download");
 check([[NSData dataWithContentsOfURL:[b.saveRequest[@"file"] URL]] isEqual:expected],"native PDF HUD exports its original bytes");
 b.saveRequest=nil;
 GewuBrowserCapture *inlineCapture=[GewuBrowserCapture new];uploaded=NO;uploadError=nil;
 [inlineCapture uploadPDFFile:loadedFile sourceURL:publicSource workspaceURL:workspace.URL uploadToken:@"synthetic-capture-token-0123456789abcdef" completion:^(NSString *error){uploaded=YES;uploadError=error;}];
 check(spin(^BOOL{return uploaded;})&&!uploadError.length,"loaded original goes through capture upload and byte validation");
 load(b,@"/inline");check(!b.currentPage.capturedPDF,"same URL navigation invalidates the previous document copy");
 loadedFile=nil;
 load(b,@"/wrapper");
 __block NSDictionary *frameSnapshot;
 b.onEvent=^(NSDictionary *e){if([e[@"event"] isEqual:@"capture-metadata"])frameSnapshot=e[@"snapshot"];else if([e[@"event"] isEqual:@"capture-pdf"]){uploaded=YES;uploadError=e[@"error"];}};
 [b capturePage:@{@"request_id":@"embedded-review"}];
 check(spin(^BOOL{return frameSnapshot!=nil;}) && [frameSnapshot[@"loaded_pdf_urls"] count]==1 && ![frameSnapshot[@"is_pdf"] boolValue],"HTML wrapper capture exposes its loaded PDF to Save to Gewu");
 check([frameSnapshot[@"origin_paper_id"] isEqual:@"source-paper"] && [frameSnapshot[@"origin_library_item_id"] integerValue]==101,"capture keeps the original Library occurrence");
 __block NSArray *embeddedFrames; __block BOOL foundFrames=NO;
 GewuLoadedBrowserPDFFrames(b.webView,^(NSArray *frames){embeddedFrames=frames;foundFrames=YES;});
 check(spin(^BOOL{return foundFrames;}) && embeddedFrames.count==1,"cross-origin embedded PDF discovered without a filename suffix");
 NSDictionary *boundFrame=embeddedFrames[0];
 read=NO;loadedError=nil;
 [b loadedPDFForPage:b.currentPage frame:boundFrame completion:^(GewuBrowserPDFFile *file,NSString *error){loadedFile=file;loadedError=error;read=YES;}];
 BOOL embeddedRead=spin(^BOOL{return read;});
 if(!loadedFile)fprintf(stderr,"Embedded PDF error: %s\n",(loadedError?:@"callback pending").UTF8String);
 check(embeddedRead && loadedFile && !loadedError,"loaded embedded PDF can be exported");
 check([[NSData dataWithContentsOfURL:loadedFile.URL] isEqual:expected],"embedded bytes exactly match the original, not viewer HTML");
 uploaded=NO;uploadError=nil;
 [b captureDownload:@{@"snapshot_id":frameSnapshot[@"snapshot_id"],@"url":boundFrame[@"url"],@"token":@"embedded-ticket",@"upload_token":@"synthetic-capture-token-0123456789abcdef"}];
 check(spin(^BOOL{return uploaded;})&&!uploadError.length,"Save to Gewu uploads loaded embedded PDF without a second GET");
 b.saveRequest=nil;[b handleCommand:@{@"action":@"download"}];
 check(spin(^BOOL{return b.saveRequest!=nil;}),"footer saves the embedded PDF");
 check([[NSData dataWithContentsOfURL:[b.saveRequest[@"file"] URL]] isEqual:expected],"footer embedded export keeps original bytes");
 check(js(b.webView,@"document.getElementById('pdf').src='/other'"),"child frame changes independently of top document");
 __block BOOL stale=NO;
 check(spin(^BOOL{__block BOOL checked=NO;GewuBrowserPDFFrameIsCurrent(b.webView,boundFrame,^(BOOL current){stale=!current;checked=YES;});spin(^BOOL{return checked;});return stale;}),"old embedded document reference is invalidated");
 read=NO;loadedFile=nil;
 [b loadedPDFForPage:b.currentPage frame:boundFrame completion:^(GewuBrowserPDFFile *file,NSString *error){loadedFile=file;loadedError=error;read=YES;}];
 check(spin(^BOOL{return read;})&&!loadedFile&&loadedError.length,"cached embedded bytes cannot be reused after frame navigation");
 load(b,@"/start");check(js(b.webView,@"document.getElementById('slow').click()"),"download started before tab close");check(spin(^BOOL{return b.currentPage.openingPDF;}),"closing test download reports progress");
 [b closeTab:b.selectedTab];check(b.downloads.count==0,"closing source tab cancels its pending preview");
 [b invalidate];check(spin(^BOOL{for(NSURL *u in b.temporaryDirectories)if([NSFileManager.defaultManager fileExistsAtPath:u.path])return NO;return YES;}),"all preview temporary directories removed");
 check(!b.testStore.persistent,"no persistent browser profile used");[w close];printf("Real WebKit PDF preview: %ld checks passed.\n",(long)checks);
}}
