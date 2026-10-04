// Generated PDF.js-shaped documents in ephemeral WebKit. No live websites.
#import "GewuBrowserController.m"
static int checks=0;
static void check(BOOL ok,NSString *label){if(!ok){fprintf(stderr,"FAIL: %s\n",label.UTF8String);exit(1);}checks++;}
static BOOL spin(BOOL (^done)(void)){NSDate *end=[NSDate dateWithTimeIntervalSinceNow:10];while(!done()&&end.timeIntervalSinceNow>0)[NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];return done();}
static id js(WKWebView *v,NSString *script){__block BOOL done=NO;__block id value;[v evaluateJavaScript:script completionHandler:^(id x,NSError *e){if(e)fprintf(stderr,"%s\n",e.description.UTF8String);check(!e,@"fixture script succeeds");value=x;done=YES;}];check(spin(^BOOL{return done;}),@"fixture script completes");return value;}
@interface ScienceCaptureView:WKWebView
@property NSURL *testURL;
@property BOOL recordResize;
@property BOOL hiddenAtResize;
@property int renderingResumes;
@end
@implementation ScienceCaptureView
- (NSURL *)URL{return self.testURL?:super.URL;}
- (void)setFrame:(NSRect)frame{if(self.recordResize)self.hiddenAtResize=self.hidden;[super setFrame:frame];}
- (void)evaluateJavaScript:(NSString *)script inFrame:(WKFrameInfo *)frame inContentWorld:(WKContentWorld *)world completionHandler:(void (^)(id,NSError *))completion{
 if([script containsString:@"app.forceRendering"]){check(!self.hidden,@"Science rendering resumes after the view is visible");self.renderingResumes++;}
 [super evaluateJavaScript:script inFrame:frame inContentWorld:world completionHandler:completion];
}
@end
int main(void){@autoreleasepool{
 [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
 NSURL *source=[NSURL URLWithString:@"https://www.science.org/doi/epdf/10.1126/science.fixture"];
 WKWebViewConfiguration *config=[WKWebViewConfiguration new];config.websiteDataStore=WKWebsiteDataStore.nonPersistentDataStore;
 ScienceCaptureView *view=[[ScienceCaptureView alloc]initWithFrame:NSMakeRect(0,0,1200,800) configuration:config];
 NSData *pdf=[[[NSView alloc]initWithFrame:NSMakeRect(0,0,300,400)] dataWithPDFInsideRect:NSMakeRect(0,0,300,400)];
 NSString *html=[NSString stringWithFormat:@"<a href='/doi/pdf/10.1126/science.fixture?download=true' aria-label='Download PDF'>get_app</a><script>window.original=Uint8Array.from(atob('%@'),c=>c.charCodeAt(0));window.PDFViewerApplication={url:'/doi/pdfdirect/10.1126/science.fixture?hmac=synthetic',pdfDocument:{numPages:1,fingerprints:['fixture-fingerprint'],getData:async()=>original}};</script>",[pdf base64EncodedStringWithOptions:0]];
 [view loadData:[html dataUsingEncoding:NSUTF8StringEncoding] MIMEType:@"text/html" characterEncodingName:@"utf-8" baseURL:source];
 check(spin(^BOOL{return !view.loading;}),@"generated Science reader loads");
 NSString *probe=[NSString stringWithContentsOfFile:@"scripts/GewuBrowserCaptureProbe.js" encoding:NSUTF8StringEncoding error:nil];
 NSDictionary *snapshot=js(view,probe);
 check([snapshot[@"pdf_urls"] isEqual:@[@"https://www.science.org/doi/pdf/10.1126/science.fixture?download=true"]],@"icon-only Science DOI download link is recognized");
 __block NSArray *refs;GewuLoadedBrowserPDFFrames(view,^(NSArray *x){refs=x;});check(spin(^BOOL{return refs!=nil;})&&refs.count==1,@"Science HTML reader exposes one loaded PDF");
 NSDictionary *reference=refs[0];check([reference[@"science"] boolValue]&&![reference[@"url"] containsString:@"hmac"],@"reference omits the signed reader URL");
 __block BOOL done=NO;__block GewuBrowserPDFFile *file;__block NSString *error;
 void (^received)(GewuBrowserPDFFile *,NSString *)=^(GewuBrowserPDFFile *x,NSString *e){file=x;error=e;done=YES;};
 GewuReadLoadedBrowserPDFFrame(view,reference,received);
 check(spin(^BOOL{return done;})&&file&&!error,@"original Science PDF can be read");
 check([[NSData dataWithContentsOfURL:file.URL] isEqual:pdf],@"capture keeps original PDF bytes");
 js(view,@"PDFViewerApplication.url='/doi/pdfdirect/10.1126/science.other'");
 done=NO;GewuReadLoadedBrowserPDFFrame(view,reference,received);check(spin(^BOOL{return done;})&&!file&&error.length,@"different DOI cannot be attached from a stale reader");
 js(view,@"PDFViewerApplication.url='/doi/pdfdirect/10.1126/science.fixture';PDFViewerApplication.pdfDocument.fingerprints=['new-fingerprint']");
 done=NO;GewuReadLoadedBrowserPDFFrame(view,reference,received);check(spin(^BOOL{return done;})&&!file&&error.length,@"changed PDF fingerprint rejects capture");
 js(view,@"PDFViewerApplication.pdfDocument.fingerprints=['fixture-fingerprint'];PDFViewerApplication.pdfDocument.getData=()=>new Promise(r=>window.releasePDF=r);void 0");
 done=NO;GewuReadLoadedBrowserPDFFrame(view,reference,received);
 check(spin(^BOOL{return [js(view,@"typeof releasePDF==='function'") boolValue];}),@"asynchronous read started");
 js(view,@"PDFViewerApplication.pdfDocument={numPages:1,fingerprints:['fixture-fingerprint'],getData:async()=>original};releasePDF(original)");
 check(spin(^BOOL{return done;})&&!file&&error.length,@"document replacement during transfer is rejected even with the same fingerprint");
 view.testURL=[NSURL URLWithString:@"https://example.org/doi/epdf/10.1126/science.fixture"];
 check(!GewuBrowserScienceEPDFURL(view.URL),@"Science path on another host retains the ordinary capture path");
 GewuBrowserController *controller=[GewuBrowserController new];
 WKWebView *workspace=[[WKWebView alloc]initWithFrame:NSMakeRect(0,0,1200,900) configuration:config];controller.workspace=workspace;
 GewuBrowserPage *page=[GewuBrowserPage new];page.view=view;
 GewuBrowserTab *tab=[GewuBrowserTab new];tab.currentPage=page;tab.contentPage=page;
 controller.tabs=[NSMutableArray arrayWithObject:tab];controller.selectedTab=tab;controller.webView=view;
 NSDictionary *layout=@{@"action":@"layout",@"active":@YES,@"visible":@YES,@"x":@0,@"y":@100,@"width":@1200,@"height":@740,@"viewportWidth":@1200};
 view.testURL=source;view.hidden=YES;controller.visible=NO;view.recordResize=YES;[controller handleCommand:layout];
 check(view.renderingResumes==1,@"Science PDF rendering resumes after the success-banner resize");
 view.testURL=[NSURL URLWithString:@"https://example.org/article"];view.hidden=YES;controller.visible=NO;[controller handleCommand:layout];
 check(view.hiddenAtResize,@"ordinary page layout order is unchanged");
 check(view.renderingResumes==1,@"ordinary pages receive no Science rendering call");
 printf("%d Science capture and layout checks passed.\n",checks);return 0;
}}
