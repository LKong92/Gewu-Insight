// Actual native source contract and file-URL pasteboard, no visible window or
// real drag gesture, and no user's general clipboard or Library file writes.
#define main GewuUnusedApplicationEntry
#import "PaperMonitorApp.m"
#undef main
#import <objc/runtime.h>

static NSUInteger checks = 0;
static void check(BOOL ok, NSString *message) {
    checks++;
    if (!ok) { fprintf(stderr, "%s\n", message.UTF8String); exit(1); }
}
// Execute the production destination/lifecycle methods with deterministic
// coordinates and a recording JavaScript sink. No live Library is opened.
@interface MoveReceiver : NSObject
@property BOOL nativeFileDragActive;
@property NSDictionary *pendingLibraryDragPayload;
@property NSInteger pendingLibraryItemDragId;
@property NSString *nativeDragCleanupPath;
@property NSWindow *window;
@property NSMutableArray *scripts;
@property NSRect bounds;
- (NSArray *)finderDropPathsFromDraggingInfo:(id)sender;
- (void)updateFinderDropTargetForDraggingInfo:(id)sender;
- (void)clearFinderDropTarget;
- (void)evaluateJavaScript:(NSString *)script completionHandler:(id)handler;
- (NSPoint)browserClientPointForDraggingInfo:(id)sender;
- (NSPoint)browserClientPointForViewPoint:(NSPoint)point;
- (NSPoint)convertPoint:(NSPoint)point fromView:(NSView *)view;
- (void)scheduleNativeDragCleanup:(NSString *)path afterDelay:(NSTimeInterval)delay;
- (void)dispatchPendingLibraryItemDropAtClientPoint:(NSPoint)point;
@end
@implementation MoveReceiver
- (NSArray *)finderDropPathsFromDraggingInfo:(id)sender {
 NSArray *(*call)(id,SEL,id)=(void *)[GewuInsightWebView instanceMethodForSelector:_cmd];return call(self,_cmd,sender);
}
- (void)updateFinderDropTargetForDraggingInfo:(id)sender {
 void (*call)(id,SEL,id)=(void *)[GewuInsightWebView instanceMethodForSelector:_cmd];call(self,_cmd,sender);
}
- (void)clearFinderDropTarget {
 void (*call)(id,SEL)=(void *)[GewuInsightWebView instanceMethodForSelector:_cmd];call(self,_cmd);
}
- (void)evaluateJavaScript:(NSString *)script completionHandler:(id)handler {[self.scripts addObject:script];}
- (NSPoint)browserClientPointForDraggingInfo:(id)sender {return NSMakePoint(100,200);}
- (NSPoint)browserClientPointForViewPoint:(NSPoint)p {return p;}
- (NSPoint)convertPoint:(NSPoint)p fromView:(NSView *)view {return p;}
- (void)scheduleNativeDragCleanup:(NSString *)path afterDelay:(NSTimeInterval)delay {}
- (void)dispatchPendingLibraryItemDropAtClientPoint:(NSPoint)p {
 SEL sel=_cmd; void (*call)(id,SEL,NSPoint)=(void *)[GewuInsightWebView instanceMethodForSelector:sel];call(self,sel,p);
}
@end
@interface MoveInfo : NSObject
@property id draggingSource;
@property NSPasteboard *draggingPasteboard;
@end
@implementation MoveInfo
@end

// Stub only the superclass boundary in this disposable test process. The
// production override must forward WebKit-owned DOM drags, even though their
// draggingSource is the same view. No WebKit page or mouse gesture is created.
static NSUInteger forwarded = 0;
static BOOL webDrop(id receiver, SEL selector, id sender) { forwarded++; return YES; }
static NSDragOperation webEnter(id receiver, SEL selector, id sender) { forwarded++; return NSDragOperationLink; }
static void webExit(id receiver, SEL selector, id sender) { forwarded++; }
static NSDragOperation webMask(id receiver, SEL selector, id session, NSDraggingContext context) { forwarded++; return NSDragOperationLink; }
static void webBegin(id receiver, SEL selector, id session, NSPoint point) { forwarded++; }
static void webEnd(id receiver, SEL selector, id session, NSPoint point, NSDragOperation operation) { forwarded++; }
static Method installOptionalWebMethod(SEL selector, IMP implementation) {
    Method method=class_getInstanceMethod(WKWebView.class,selector);
    if (!method) {
        const char *types=method_getTypeEncoding(class_getInstanceMethod(GewuInsightWebView.class,selector));
        class_addMethod(WKWebView.class,selector,implementation,types);
        method=class_getInstanceMethod(WKWebView.class,selector);
    }
    return method;
}

int main(void) {
    @autoreleasepool {
        MoveReceiver *receiver=[MoveReceiver new];receiver.scripts=[NSMutableArray new];receiver.bounds=NSMakeRect(0,0,500,500);
        receiver.nativeFileDragActive=YES;
        SEL selector = @selector(draggingSession:sourceOperationMaskForDraggingContext:);
        NSDragOperation (*mask)(id, SEL, NSDraggingSession *, NSDraggingContext) =
            (void *)[GewuInsightWebView instanceMethodForSelector:selector];
        NSDragOperation outside = mask(receiver, selector, nil, NSDraggingContextOutsideApplication);
        NSDragOperation inside = mask(receiver, selector, nil, NSDraggingContextWithinApplication);
        check((outside & NSDragOperationCopy) != 0, @"Finder copies must remain available");
        check((outside & NSDragOperationGeneric) != 0, @"Application-specific opening must be negotiable");
        check((outside & (NSDragOperationDelete | NSDragOperationMove)) == 0, @"Managed files must not offer deletion/moving");
        check((inside & NSDragOperationMove) != 0, @"Internal ownership drop must negotiate Move");
        NSString *directory = [NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
        NSFileManager *fm = NSFileManager.defaultManager;
        [fm createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *file = [directory stringByAppendingPathComponent:@"analysis.md"];
        NSString *alias = [directory stringByAppendingPathComponent:@"visible-alias.md"];
        [@"# Generated test\n" writeToFile:file atomically:YES encoding:NSUTF8StringEncoding error:nil];
        [fm createSymbolicLinkAtPath:alias withDestinationPath:file error:nil];
        NSURL *url = [[NSURL fileURLWithPath:alias] URLByResolvingSymlinksInPath];
        NSDraggingItem *item = [[NSDraggingItem alloc] initWithPasteboardWriter:url];
        NSPasteboard *pasteboard = [NSPasteboard pasteboardWithUniqueName];
        check([pasteboard writeObjects:@[item.item]], @"File URL must be writable as a native drag item");
        NSArray *urls = [pasteboard readObjectsForClasses:@[NSURL.class]
            options:@{NSPasteboardURLReadingFileURLsOnlyKey: @YES}];
        check(urls.count == 1 && [[urls.firstObject path] isEqualToString:[file stringByResolvingSymlinksInPath]], @"Destination must receive the real canonical file URL");
        check([fm fileExistsAtPath:file] && [fm fileExistsAtPath:alias], @"Exporting a URL must preserve both file and placement");
        [pasteboard releaseGlobally];
        [fm removeItemAtPath:directory error:nil];
        NSDictionary *payload=@{@"type":@"paper-file",@"paper_id":@"fixture",@"resource_id":@7,@"token":@"gesture"};
        receiver.pendingLibraryDragPayload=payload;
        MoveInfo *info=[MoveInfo new];info.draggingSource=receiver;
        SEL drop=@selector(performDragOperation:);
        BOOL (*perform)(id,SEL,id)=(void *)[GewuInsightWebView instanceMethodForSelector:drop];
        check(perform(receiver,drop,info),@"Managed drop must be handled");
        check(receiver.scripts.count==1 && [receiver.scripts[0] containsString:@"handleNativeLibraryManagedDrop"],@"Internal files must use ownership routing, never Finder import");
        check([receiver.scripts[0] containsString:@"paper-file"] && [receiver.scripts[0] containsString:@"resource_id"],@"Keep the exact source resource identity");
        check(receiver.pendingLibraryDragPayload==nil,@"Consume the pending drag once");
        check(!perform(receiver,drop,info) && receiver.scripts.count==1,@"A consumed native drag must not become a Finder import");
        SEL end=@selector(draggingSession:endedAtPoint:operation:);
        void (*ended)(id,SEL,id,NSPoint,NSDragOperation)=(void *)[GewuInsightWebView instanceMethodForSelector:end];
        for(NSNumber *op in @[@(NSDragOperationNone),@(NSDragOperationCopy),@(NSDragOperationGeneric)]) {
            receiver.nativeFileDragActive=YES;
            receiver.pendingLibraryDragPayload=payload;[receiver.scripts removeAllObjects];
            ended(receiver,end,nil,NSZeroPoint,op.unsignedIntegerValue);
            check(receiver.scripts.count==1 && [receiver.scripts[0] containsString:@"clearNativeLibraryDrag"],@"Cancel and external exports must never move ownership");
            check(receiver.pendingLibraryDragPayload==nil,@"End clears stale source identity");
        }
        // The old implementation rejected this exact title/row-drop path.
        receiver.nativeFileDragActive=NO;[receiver.scripts removeAllObjects];
        Method method=class_getInstanceMethod(WKWebView.class,drop);
        IMP original=method_setImplementation(method,(IMP)webDrop);
        forwarded=0;
        check(perform(receiver,drop,info) && forwarded==1,@"WebKit DOM drop from the same view must reach its superclass");
        check(receiver.scripts.count==0,@"DOM drop must not trigger a second native ownership request");
        // A stale armed payload is not evidence that Gewu started the session.
        receiver.pendingLibraryDragPayload=payload;
        check(perform(receiver,drop,info) && forwarded==2 && receiver.scripts.count==0,@"Stale native payload cannot steal a DOM drop");
        method_setImplementation(method,original);
        for (NSString *name in @[@"draggingEntered:", @"draggingUpdated:"]) {
            SEL sel=NSSelectorFromString(name);method=class_getInstanceMethod(WKWebView.class,sel);
            original=method_setImplementation(method,(IMP)webEnter);forwarded=0;
            NSDragOperation (*call)(id,SEL,id)=(void *)[GewuInsightWebView instanceMethodForSelector:sel];
            check(call(receiver,sel,info)==NSDragOperationLink && forwarded==1,@"DOM hover must preserve WebKit operation negotiation");
            method_setImplementation(method,original);
        }
        SEL leave=@selector(draggingExited:);method=class_getInstanceMethod(WKWebView.class,leave);
        original=method_setImplementation(method,(IMP)webExit);forwarded=0;
        void (*exitDrag)(id,SEL,id)=(void *)[GewuInsightWebView instanceMethodForSelector:leave];
        exitDrag(receiver,leave,info);
        check(forwarded==1 && receiver.scripts.count==0,@"DOM exit stays with WebKit without native cleanup");
        method_setImplementation(method,original);
        method=class_getInstanceMethod(WKWebView.class,selector);
        original=method_setImplementation(method,(IMP)webMask);forwarded=0;
        check(mask(receiver,selector,nil,NSDraggingContextWithinApplication)==NSDragOperationLink && forwarded==1,@"DOM source operation mask stays with WebKit");
        method_setImplementation(method,original);
        SEL begin=@selector(draggingSession:willBeginAtPoint:);
        void (*began)(id,SEL,id,NSPoint)=(void *)[GewuInsightWebView instanceMethodForSelector:begin];
        if (![WKWebView instancesRespondToSelector:begin]) {
            began(receiver,begin,nil,NSZeroPoint);
            check(receiver.scripts.count==0,@"Older WebKit may omit the optional begin callback");
        }
        method=installOptionalWebMethod(begin,(IMP)webBegin);
        original=method_setImplementation(method,(IMP)webBegin);forwarded=0;
        began(receiver,begin,nil,NSZeroPoint);
        check(forwarded==1,@"WebKit must initialize its own DOM drag session");
        receiver.nativeFileDragActive=YES;began(receiver,begin,nil,NSZeroPoint);
        check(forwarded==1,@"Gewu file export must not initialize a WebKit DOM session");
        receiver.nativeFileDragActive=NO;method_setImplementation(method,original);
        if (![WKWebView instancesRespondToSelector:end]) {
            SEL legacy=NSSelectorFromString(@"draggedImage:endedAt:operation:");
            method=class_getInstanceMethod(WKWebView.class,legacy);
            original=method_setImplementation(method,(IMP)webEnd);forwarded=0;
            ended(receiver,end,nil,NSZeroPoint,NSDragOperationMove);
            check(forwarded==1 && receiver.scripts.count==0,@"Older WebKit must receive the legacy DOM dragend callback");
            method_setImplementation(method,original);
        }
        method=installOptionalWebMethod(end,(IMP)webEnd);
        original=method_setImplementation(method,(IMP)webEnd);forwarded=0;
        for (NSNumber *op in @[@(NSDragOperationNone),@(NSDragOperationMove),@(NSDragOperationCopy)]) {
            ended(receiver,end,nil,NSZeroPoint,op.unsignedIntegerValue);
        }
        check(forwarded==3 && receiver.scripts.count==0,@"WebKit must finish DOM drags and dispatch its own dragend");
        method_setImplementation(method,original);
        // The public sibling destination must forward the complete native file
        // handshake even when WebKit's internal scrolling view owns DOM hits.
        for (NSString *name in @[@"draggingEntered:", @"draggingUpdated:", @"performDragOperation:"]) {
            SEL sel=NSSelectorFromString(name);
            Method source=class_getInstanceMethod(GewuInsightWebView.class,sel);
            class_addMethod(MoveReceiver.class,sel,method_getImplementation(source),method_getTypeEncoding(source));
        }
        GewuFinderDropView *destination=[[GewuFinderDropView alloc] initWithFrame:NSMakeRect(0,0,500,500)];
        destination.destinationWebView=(id)receiver;
        check([destination hitTest:NSMakePoint(100,100)]==nil,@"The file destination must not intercept clicks or text selection");
        check([destination.registeredDraggedTypes isEqualToArray:@[NSPasteboardTypeFileURL]],@"Text, links and HTML row sorting must not enter the file destination");
        check(!destination.acceptsFirstResponder,@"The transparent destination must not add a keyboard focus stop");
        info.draggingSource=[NSObject new];
        info.draggingPasteboard=[NSPasteboard pasteboardWithUniqueName];
        receiver.nativeFileDragActive=NO;receiver.pendingLibraryDragPayload=nil;
        for (NSArray *paths in @[@[@"/private/tmp/fixture.md"], @[@"/private/tmp/folder"], @[@"/private/tmp/a.pdf",@"/private/tmp/b.md"]]) {
            [info.draggingPasteboard clearContents];
            NSMutableArray *fileURLs=[NSMutableArray new];
            for (NSString *path in paths) [fileURLs addObject:[NSURL fileURLWithPath:path]];
            [info.draggingPasteboard writeObjects:fileURLs];
            [receiver.scripts removeAllObjects];
            check([destination draggingEntered:(id)info]==NSDragOperationCopy,@"Files and folders must negotiate Copy");
            check([destination draggingUpdated:(id)info]==NSDragOperationCopy,@"Native hover remains accepted across the whole surface");
            check([destination prepareForDragOperation:(id)info],@"Accepted file URLs must survive the preparation phase");
            check([destination performDragOperation:(id)info],@"Files and folders must reach the product importer");
            check(receiver.scripts.count==3 && [receiver.scripts.lastObject containsString:@"handleNativeFinderDrop"],@"One gesture dispatches exactly one native import");
            for (NSString *path in paths) check([receiver.scripts.lastObject containsString:path.lastPathComponent],@"Preserve all dropped paths");
            [destination draggingExited:(id)info];
            check([receiver.scripts.lastObject containsString:@"clearNativeFinderDropTarget"],@"Leaving clears the destination highlight");
        }
        info.draggingSource=receiver;receiver.nativeFileDragActive=YES;receiver.pendingLibraryDragPayload=payload;
        [receiver.scripts removeAllObjects];
        check([destination draggingEntered:(id)info]==NSDragOperationMove,@"A managed native resource keeps ownership-move semantics");
        check([destination prepareForDragOperation:(id)info] && [destination performDragOperation:(id)info],@"Managed native drop passes the same destination");
        check([receiver.scripts.lastObject containsString:@"handleNativeLibraryManagedDrop"],@"Managed files must never become external imports");
        check(![destination prepareForDragOperation:(id)info] && ![destination performDragOperation:(id)info],@"Do not replay a consumed managed gesture");
        receiver.nativeFileDragActive=NO;receiver.pendingLibraryDragPayload=payload;
        check(![destination prepareForDragOperation:(id)info],@"A stale armed payload cannot steal a WebKit DOM gesture");
        info.draggingSource=[NSObject new];[info.draggingPasteboard clearContents];
        [info.draggingPasteboard setString:@"https://example.org/paper" forType:NSPasteboardTypeURL];
        check(![destination prepareForDragOperation:(id)info] && ![destination performDragOperation:(id)info],@"Ordinary web links are not imported as files");
        [info.draggingPasteboard releaseGlobally];
        printf("%lu native drag contract checks passed\n",(unsigned long)checks);
    }
}
