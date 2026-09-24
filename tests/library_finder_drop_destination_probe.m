// A real, hidden AppKit/WebKit workspace. No desktop gesture or user files.
// The private hit-test selector is diagnostic-only; product routing uses public
// NSDraggingDestination APIs and has no WebKit/private method overrides.
#define main GewuUnusedApplicationEntry
#import "PaperMonitorApp.m"
#undef main

@interface NSView (DropHitTestProbe)
- (NSView *)_hitTest:(NSPoint *)point dragTypes:(NSSet *)types;
@end
@interface FinderInfo : NSObject
@property id draggingSource;
@property NSPasteboard *draggingPasteboard;
@property NSPoint draggingLocation;
@end
@implementation FinderInfo
@end
static void check(BOOL ok, NSString *message) {
    if (!ok) { fprintf(stderr,"%s\n",message.UTF8String);exit(1); }
}
static id evaluate(WKWebView *web, NSString *script) {
    __block BOOL done=NO;__block id value=nil;__block NSError *failure=nil;
    [web evaluateJavaScript:script completionHandler:^(id result,NSError *error){value=result;failure=error;done=YES;}];
    NSDate *limit=[NSDate dateWithTimeIntervalSinceNow:10];
    while(!done && limit.timeIntervalSinceNow>0) [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
    check(done && !failure,[NSString stringWithFormat:@"WebKit evaluation failed: %@",failure]);return value;
}
int main() {
    @autoreleasepool {
        [NSApplication sharedApplication];
        NSWindow *window=[[NSWindow alloc]initWithContentRect:NSMakeRect(0,0,900,600) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        NSView *content=[[NSView alloc]initWithFrame:NSMakeRect(0,0,900,600)];window.contentView=content;
        WKWebViewConfiguration *config=[WKWebViewConfiguration new];config.websiteDataStore=WKWebsiteDataStore.nonPersistentDataStore;
        GewuInsightWebView *web=[[GewuInsightWebView alloc]initWithFrame:content.bounds configuration:config];[content addSubview:web];
        GewuFinderDropView *receiver=[[GewuFinderDropView alloc]initWithFrame:content.bounds];receiver.destinationWebView=web;receiver.autoresizingMask=NSViewWidthSizable|NSViewHeightSizable;[content addSubview:receiver];
        [web loadHTMLString:@"<style>body{margin:0}header{height:60px}section{height:540px;overflow:auto;transform:translateZ(0)}</style><header>Paper Files</header><section><input value='editable'>Blank drop area</section><script>window.drops=[];window.moves=[];window.handleNativeFinderDrop=(paths,p)=>drops.push({paths,target:document.elementFromPoint(p.x,p.y).tagName});window.handleNativeLibraryManagedDrop=payload=>moves.push(payload);</script>" baseURL:nil];
        NSDate *limit=[NSDate dateWithTimeIntervalSinceNow:10];
        while(web.loading && limit.timeIntervalSinceNow>0) [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
        check([evaluate(web,@"Array.isArray(window.drops)") boolValue],@"Fixture must be ready");
        FinderInfo *info=[FinderInfo new];info.draggingPasteboard=[NSPasteboard pasteboardWithUniqueName];
        NSArray *batches=@[@[@"/private/tmp/generated paper.pdf"],@[@"/private/tmp/generated folder"],@[@"/private/tmp/one.md",@"/private/tmp/two.pdf"]];
        NSUInteger count=0;
        for (NSArray *paths in batches) for (NSNumber *y in @[@570,@200]) {
            [info.draggingPasteboard clearContents];NSMutableArray *urls=[NSMutableArray new];
            for(NSString *path in paths)[urls addObject:[NSURL fileURLWithPath:path]];
            [info.draggingPasteboard writeObjects:urls];
            NSPoint point=NSMakePoint(300,y.doubleValue);info.draggingLocation=point;
            NSView *hit=[content _hitTest:&point dragTypes:[NSSet setWithObject:NSPasteboardTypeFileURL]];
            check(hit==receiver,@"Header and scrolling body must both hit the native receiver");
            check([receiver draggingEntered:(id)info]==NSDragOperationCopy && [receiver prepareForDragOperation:(id)info],@"File/folder drop must be accepted");
            check([receiver performDragOperation:(id)info],@"Drop dispatch failed");count++;
            NSArray *drops=evaluate(web,@"window.drops");
            check(drops.count==count,@"One gesture must dispatch one import");
            check([drops.lastObject[@"paths"] isEqual:paths],@"Keep original paths and order");
            check([drops.lastObject[@"target"] isEqual:y.intValue==570?@"HEADER":@"SECTION"],@"Drop coordinates must identify header versus blank area");
            [receiver draggingExited:(id)info];
        }
        check([content hitTest:NSMakePoint(300,200)]!=receiver,@"Ordinary input must pass through to WebKit");
        NSPoint point=NSMakePoint(300,200);
        check([content _hitTest:&point dragTypes:[NSSet setWithObject:NSPasteboardTypeString]]!=receiver,@"HTML row drags must keep WebKit routing");
        info.draggingSource=web;web.nativeFileDragActive=YES;web.pendingLibraryDragPayload=@{@"type":@"paper-file",@"resource_id":@7};
        check([receiver draggingEntered:(id)info]==NSDragOperationMove && [receiver performDragOperation:(id)info],@"Managed file uses ownership routing");
        check([evaluate(web,@"moves.length") intValue]==1 && [evaluate(web,@"drops.length") intValue]==6,@"Internal file must not also import");
        check(![receiver performDragOperation:(id)info],@"Consumed managed drop cannot replay");
        [info.draggingPasteboard releaseGlobally];
        puts("real WebKit file destination checks passed");
    }
}
