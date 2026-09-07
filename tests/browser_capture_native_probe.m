// Inert WebKit surfaces and generated responses only. No browser profile or network.
#import "GewuBrowserController.m"
static int checks=0;
static void check(BOOL condition, NSString *name) { if(!condition){fprintf(stderr,"FAIL: %s\n",name.UTF8String);exit(1);} checks++; }
@interface CaptureFakeDownload:NSObject
@property(weak) id delegate;
@property int cancellations;
@end
@implementation CaptureFakeDownload
- (void)cancel:(id)callback {self.cancellations++;}
@end
@interface CaptureFakeView:NSObject
@property(strong) NSURL *URL;
@property BOOL loading;
@property(strong) CaptureFakeDownload *download;
@property(strong) NSURLRequest *request;
@property(copy) void (^probe)(id,NSError *);
@property NSRect bounds;
@property(strong) WKSnapshotConfiguration *snapshotConfiguration;
@property(copy) void (^snapshotCompletion)(NSImage *,NSError *);
@end
@implementation CaptureFakeView
- (BOOL)isLoading { return self.loading; }
- (void)startDownloadUsingRequest:(NSURLRequest *)request completionHandler:(void (^)(WKDownload *))done {self.request=request;self.download=[CaptureFakeDownload new];done((id)self.download);}
- (void)evaluateJavaScript:(NSString *)script inFrame:(id)frame inContentWorld:(WKContentWorld *)world completionHandler:(void (^)(id,NSError *))done {check([world.name isEqual:@"GewuBrowserCapture"],@"metadata uses isolated world");self.probe=done;}
- (void)takeSnapshotWithConfiguration:(WKSnapshotConfiguration *)configuration completionHandler:(void (^)(NSImage *,NSError *))done {self.snapshotConfiguration=configuration;self.snapshotCompletion=done;}
@end
int main(void){@autoreleasepool {
    NSURL *public=[NSURL URLWithString:@"https://example.org/paper.pdf"], *local=[NSURL URLWithString:@"http://127.0.0.1:9876/"];
    CaptureFakeView *view=[CaptureFakeView new];view.URL=[NSURL URLWithString:@"https://example.org/article"];
    NSString *token=@"abcdefghijklmnopqrstuvwxyz0123456789";
    __block int finished=0;
    __block NSString *lastError=nil;
    void (^done)(NSString *)=^(NSString *error){finished++;lastError=error;};
    for(NSURL *url in @[local,[NSURL URLWithString:@"file:///tmp/private.pdf"]]) {
        GewuBrowserCapture *transfer=[GewuBrowserCapture new];
        [transfer downloadURL:url fromView:(id)view workspaceURL:local uploadToken:token completion:done];
        check(lastError.length && !view.request,@"nonpublic PDF cannot start request");
    }
    GewuBrowserCapture *(^start)(void)=^{GewuBrowserCapture *x=[GewuBrowserCapture new];[x downloadURL:public fromView:(id)view workspaceURL:local uploadToken:token completion:done];return x;};
    GewuBrowserCapture *x=start();
    check(![view.request valueForHTTPHeaderField:@"X-Gewu-Capture-Token"],@"upload capability never sent to publisher");
    [x download:(id)view.download willPerformHTTPRedirection:nil newRequest:[NSURLRequest requestWithURL:local] decisionHandler:^(WKDownloadRedirectPolicy policy){check(policy==WKDownloadRedirectPolicyCancel,@"private redirect blocked");}];
    check(lastError.length && view.download.cancellations==1,@"redirect failure finishes and cancels once");
    for(NSString *mime in @[@"text/html",@"application/pdf"]){
        x=start();
        NSURLResponse *r=[[NSURLResponse alloc] initWithURL:public MIMEType:mime expectedContentLength:[mime isEqual:@"text/html"]?10:70*1024*1024 textEncodingName:nil];
        [x download:(id)view.download decideDestinationUsingResponse:r suggestedFilename:@"paper.pdf" completionHandler:^(NSURL *dest){check(!dest,@"HTML and oversized response rejected before destination");}];
    }
    x=start(); __block NSURL *destination;
    NSURLResponse *r=[[NSURLResponse alloc] initWithURL:public MIMEType:@"application/pdf" expectedContentLength:-1 textEncodingName:nil];
    [x download:(id)view.download decideDestinationUsingResponse:r suggestedFilename:@"../../paper.pdf" completionHandler:^(NSURL *dest){destination=dest;}];
    check(destination && [destination.lastPathComponent isEqual:@"capture.pdf"],@"temporary destination ignores remote path");
    check([NSFileManager.defaultManager fileExistsAtPath:destination.URLByDeletingLastPathComponent.path],@"temporary staging created");
    [@"synthetic" writeToURL:destination atomically:YES encoding:NSUTF8StringEncoding error:nil];
    [x cancel];check(![NSFileManager.defaultManager fileExistsAtPath:destination.URLByDeletingLastPathComponent.path],@"cancel removes temporary bytes");
    int count=finished; [x downloadDidFinish:(id)view.download];
    check(finished==count,@"late completion cannot deliver a second result");
    GewuBrowserController *controller=[GewuBrowserController new];controller.active=YES;
    GewuBrowserPage *page=[GewuBrowserPage new];page.view=(id)view;page.captureDocumentID=@"first-document";
    GewuBrowserTab *tab=[GewuBrowserTab new];tab.currentPage=page;tab.contentPage=page;tab.originPaperID=@"existing-paper";
    controller.tabs=[NSMutableArray arrayWithObject:tab];controller.selectedTab=tab;
    __block NSDictionary *event;
    controller.onEvent=^(NSDictionary *value){event=value;};
    [controller capturePage:@{@"request_id":@"one"}];
    check(view.probe!=nil,@"collector evaluates once on explicit command");
    page.captureDocumentID=@"second-document";
    view.probe(@{@"metadata":@{},@"pdf_urls":@[]},nil);
    check([event[@"request_id"] isEqual:@"one"] && event[@"error"],@"navigation during metadata extraction rejects stale snapshot");
    [controller capturePage:@{@"request_id":@"two"}];
    view.probe(@{@"metadata":@{@"title":@"Example"},@"url":@"https://untrusted.example",@"pdf_urls":@[local.absoluteString,public.absoluteString]},nil);
    NSDictionary *snapshot=event[@"snapshot"];
    check([snapshot[@"url"] isEqual:view.URL.absoluteString],@"source URL comes from native document");
    check([snapshot[@"pdf_urls"] isEqual:@[public.absoluteString]],@"private candidates filtered");
    check([snapshot[@"origin_paper_id"] isEqual:@"existing-paper"],@"Open Website source passed as hint");
    [controller captureDownload:@{@"token":@"ticket",@"snapshot_id":snapshot[@"snapshot_id"],@"url":@"https://example.org/another.pdf"}];
    check(event[@"error"]!=nil,@"unrecognized candidate cannot download");
    controller.active=NO;
    [controller handleCommand:@{@"action":@"capture-cancel",@"snapshot_id":snapshot[@"snapshot_id"],@"token":@"ticket"}];
    check(controller.captureSnapshots.count==0,@"cancel releases snapshot even after workspace exit");
    controller.active=YES; view.bounds=NSMakeRect(0,0,2000,1200);
    [controller captureBackdropForPage:page requestID:@"backdrop-one"];
    check(NSEqualRects(view.snapshotConfiguration.rect,view.bounds),@"backdrop captures only the visible viewport");
    check(view.snapshotConfiguration.snapshotWidth.intValue==1600,@"backdrop resolution is bounded");
    NSBitmapImageRep *bitmap=[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:20 pixelsHigh:20 bitsPerSample:8 samplesPerPixel:3 hasAlpha:NO isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:0 bitsPerPixel:0];
    memset(bitmap.bitmapData,255,bitmap.bytesPerRow*bitmap.pixelsHigh);
    NSImage *image=[[NSImage alloc] initWithSize:NSMakeSize(20,20)];[image addRepresentation:bitmap];
    event=nil; view.snapshotCompletion(image,nil);
    check([event[@"event"] isEqual:@"capture-backdrop"] && [event[@"image"] hasPrefix:@"data:image/jpeg;base64,"],@"backdrop goes to the trusted workspace as an in-memory image");
    void (^oldSnapshot)(NSImage *,NSError *)=view.snapshotCompletion;
    [controller captureBackdropForPage:page requestID:@"backdrop-two"];
    event=nil;oldSnapshot(image,nil);check(!event,@"superseded backdrop cannot update a new dialog");
    [controller handleCommand:@{@"action":@"capture-cancel",@"request_id":@"backdrop-two"}];
    view.snapshotCompletion(image,nil);check(!event,@"closing the dialog rejects its late backdrop");
    [controller captureBackdropForPage:page requestID:@"backdrop-three"];
    page.captureDocumentID=@"new-document";view.snapshotCompletion(image,nil);check(!event,@"navigation invalidates pending backdrop");
    [controller captureBackdropForPage:page requestID:@"backdrop-four"];
    controller.active=NO;view.snapshotCompletion(image,nil);check(!event,@"workspace exit cannot reveal a pending backdrop");
    printf("%d native capture boundary and lifecycle checks passed.\n",checks);
}}
