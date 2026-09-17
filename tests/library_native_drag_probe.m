// Actual native source contract and file-URL pasteboard, no visible window or
// real drag gesture, and no user's general clipboard or Library file writes.
#define main GewuUnusedApplicationEntry
#import "PaperMonitorApp.m"
#undef main

static void check(BOOL ok, NSString *message) {
    if (!ok) { fprintf(stderr, "%s\n", message.UTF8String); exit(1); }
}
// Execute the production destination/lifecycle methods with deterministic
// coordinates and a recording JavaScript sink. No live Library is opened.
@interface MoveReceiver : NSObject
@property NSDictionary *pendingLibraryDragPayload;
@property NSInteger pendingLibraryItemDragId;
@property NSString *nativeDragCleanupPath;
@property NSWindow *window;
@property NSMutableArray *scripts;
@property NSRect bounds;
- (void)evaluateJavaScript:(NSString *)script completionHandler:(id)handler;
- (NSPoint)browserClientPointForDraggingInfo:(id)sender;
- (NSPoint)browserClientPointForViewPoint:(NSPoint)point;
- (NSPoint)convertPoint:(NSPoint)point fromView:(NSView *)view;
- (void)scheduleNativeDragCleanup:(NSString *)path afterDelay:(NSTimeInterval)delay;
- (void)dispatchPendingLibraryItemDropAtClientPoint:(NSPoint)point;
@end
@implementation MoveReceiver
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
@end
@implementation MoveInfo
@end

int main(void) {
    @autoreleasepool {
        SEL selector = @selector(draggingSession:sourceOperationMaskForDraggingContext:);
        NSDragOperation (*mask)(id, SEL, NSDraggingSession *, NSDraggingContext) =
            (void *)[GewuInsightWebView instanceMethodForSelector:selector];
        NSDragOperation outside = mask(nil, selector, nil, NSDraggingContextOutsideApplication);
        NSDragOperation inside = mask(nil, selector, nil, NSDraggingContextWithinApplication);
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
        MoveReceiver *receiver=[MoveReceiver new];receiver.scripts=[NSMutableArray new];receiver.bounds=NSMakeRect(0,0,500,500);
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
            receiver.pendingLibraryDragPayload=payload;[receiver.scripts removeAllObjects];
            ended(receiver,end,nil,NSZeroPoint,op.unsignedIntegerValue);
            check(receiver.scripts.count==1 && [receiver.scripts[0] containsString:@"clearNativeLibraryDrag"],@"Cancel and external exports must never move ownership");
            check(receiver.pendingLibraryDragPayload==nil,@"End clears stale source identity");
        }
        puts("18 native drag contract checks passed");
    }
}
