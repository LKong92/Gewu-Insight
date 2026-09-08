// Actual native source contract and file-URL pasteboard, no visible window or
// real drag gesture, and no user's general clipboard or Library file writes.
#define main GewuUnusedApplicationEntry
#import "PaperMonitorApp.m"
#undef main

static void check(BOOL ok, NSString *message) {
    if (!ok) { fprintf(stderr, "%s\n", message.UTF8String); exit(1); }
}
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
        check(inside == NSDragOperationCopy, @"Internal drop policy must remain unchanged");
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
        puts("7 native drag contract checks passed");
    }
}
