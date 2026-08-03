#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#include <string.h>

@interface GewuInsightWebView : WKWebView <NSDraggingDestination, NSDraggingSource>
@property(nonatomic, copy) NSString *nativeDragPath;
@property(nonatomic, copy) NSString *nativeDragName;
@property(nonatomic, copy) NSString *nativeDragCleanupPath;
@property(nonatomic) BOOL pdfQuickLookActive;
@property(nonatomic) CGFloat pdfMagnificationAccumulator;
@end

@implementation GewuInsightWebView

- (instancetype)initWithFrame:(NSRect)frame configuration:(WKWebViewConfiguration *)configuration {
    self = [super initWithFrame:frame configuration:configuration];
    if (self) {
        [self registerForDraggedTypes:@[NSPasteboardTypeFileURL, NSPasteboardTypeURL]];
    }
    return self;
}

- (NSDragOperation)draggingEntered:(id<NSDraggingInfo>)sender {
    if ([self finderDropPathsFromDraggingInfo:sender].count > 0) {
        [self updateFinderDropTargetForDraggingInfo:sender];
        return NSDragOperationCopy;
    }
    return [super draggingEntered:sender];
}

- (NSDragOperation)draggingUpdated:(id<NSDraggingInfo>)sender {
    if ([self finderDropPathsFromDraggingInfo:sender].count > 0) {
        [self updateFinderDropTargetForDraggingInfo:sender];
        return NSDragOperationCopy;
    }
    return [super draggingUpdated:sender];
}

- (void)draggingExited:(id<NSDraggingInfo>)sender {
    [self clearFinderDropTarget];
    [super draggingExited:sender];
}

- (BOOL)performDragOperation:(id<NSDraggingInfo>)sender {
    NSArray<NSString *> *paths = [self finderDropPathsFromDraggingInfo:sender];
    if (paths.count == 0) {
        return [super performDragOperation:sender];
    }
    NSError *error = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:paths options:0 error:&error];
    if (!data || error) {
        return NO;
    }
    NSString *json = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    NSPoint point = [self browserClientPointForDraggingInfo:sender];
    NSString *script = [NSString stringWithFormat:@"window.handleNativeFinderDrop && window.handleNativeFinderDrop(%@, {x:%0.2f,y:%0.2f})", json ?: @"[]", point.x, point.y];
    [self evaluateJavaScript:script completionHandler:nil];
    return YES;
}

- (NSPoint)browserClientPointForDraggingInfo:(id<NSDraggingInfo>)sender {
    NSPoint point = [self convertPoint:sender.draggingLocation fromView:nil];
    CGFloat clientX = point.x;
    CGFloat clientY = self.isFlipped ? point.y : self.bounds.size.height - point.y;
    return NSMakePoint(clientX, clientY);
}

- (void)updateFinderDropTargetForDraggingInfo:(id<NSDraggingInfo>)sender {
    NSPoint point = [self browserClientPointForDraggingInfo:sender];
    NSString *script = [NSString stringWithFormat:@"window.updateNativeFinderDropTarget && window.updateNativeFinderDropTarget({x:%0.2f,y:%0.2f})", point.x, point.y];
    [self evaluateJavaScript:script completionHandler:nil];
}

- (void)clearFinderDropTarget {
    [self evaluateJavaScript:@"window.clearNativeFinderDropTarget && window.clearNativeFinderDropTarget()" completionHandler:nil];
}

- (void)setPdfQuickLookActive:(BOOL)active {
    _pdfQuickLookActive = active;
    self.pdfMagnificationAccumulator = 0;
    if (active) {
        [self hidePDFHUDSubviews];
    }
}

- (void)didAddSubview:(NSView *)subview {
    [super didAddSubview:subview];
    if (self.pdfQuickLookActive) {
        [self hidePDFHUDSubviewsInView:subview];
    }
}

- (void)layout {
    [super layout];
    if (self.pdfQuickLookActive) {
        [self hidePDFHUDSubviews];
    }
}

- (void)hidePDFHUDSubviews {
    for (NSView *subview in self.subviews) {
        [self hidePDFHUDSubviewsInView:subview];
    }
}

- (void)hidePDFHUDSubviewsInView:(NSView *)view {
    if ([NSStringFromClass(view.class) containsString:@"WKPDFHUDView"]) {
        view.hidden = YES;
        return;
    }
    for (NSView *subview in view.subviews) {
        [self hidePDFHUDSubviewsInView:subview];
    }
}

- (void)collectPDFHUDSubviewsInView:(NSView *)view into:(NSMutableArray<NSView *> *)result {
    if ([NSStringFromClass(view.class) containsString:@"WKPDFHUDView"]) {
        [result addObject:view];
        return;
    }
    for (NSView *subview in view.subviews) {
        [self collectPDFHUDSubviewsInView:subview into:result];
    }
}

- (NSArray<NSView *> *)pdfHUDSubviews {
    NSMutableArray<NSView *> *result = [NSMutableArray array];
    for (NSView *subview in self.subviews) {
        [self collectPDFHUDSubviewsInView:subview into:result];
    }
    return result;
}

- (BOOL)performPDFHUDZoomIn:(BOOL)zoomIn {
    BOOL handled = NO;
    SEL directSelector = NSSelectorFromString(zoomIn ? @"performPDFZoomIn" : @"performPDFZoomOut");
    SEL legacyVisibleSelector = NSSelectorFromString(@"_setVisible:");
    SEL legacyActionSelector = NSSelectorFromString(@"_performActionForControl:");
    NSString *legacyControl = zoomIn ? @"plus.magnifyingglass" : @"minus.magnifyingglass";
    for (NSView *hud in [self pdfHUDSubviews]) {
        if ([hud respondsToSelector:directSelector]) {
            IMP implementation = [hud methodForSelector:directSelector];
            ((void (*)(id, SEL))implementation)(hud, directSelector);
            handled = YES;
            continue;
        }
        if (![hud respondsToSelector:legacyActionSelector]) continue;
        if ([hud respondsToSelector:legacyVisibleSelector]) {
            IMP visibleImplementation = [hud methodForSelector:legacyVisibleSelector];
            ((void (*)(id, SEL, BOOL))visibleImplementation)(hud, legacyVisibleSelector, YES);
        }
        IMP actionImplementation = [hud methodForSelector:legacyActionSelector];
        ((void (*)(id, SEL, id))actionImplementation)(hud, legacyActionSelector, legacyControl);
        handled = YES;
    }
    [self hidePDFHUDSubviews];
    return handled;
}

- (void)magnifyWithEvent:(NSEvent *)event {
    if (!self.pdfQuickLookActive) {
        [super magnifyWithEvent:event];
        return;
    }
    if (event.phase == NSEventPhaseBegan) {
        self.pdfMagnificationAccumulator = 0;
    }
    self.pdfMagnificationAccumulator += event.magnification;
    const CGFloat step = 0.045;
    NSInteger actionCount = 0;
    BOOL handled = NO;
    while (fabs(self.pdfMagnificationAccumulator) >= step && actionCount < 4) {
        BOOL zoomIn = self.pdfMagnificationAccumulator > 0;
        handled = [self performPDFHUDZoomIn:zoomIn] || handled;
        self.pdfMagnificationAccumulator += zoomIn ? -step : step;
        actionCount += 1;
    }
    if (!handled && actionCount > 0) {
        [super magnifyWithEvent:event];
    }
    if (event.phase == NSEventPhaseEnded || event.phase == NSEventPhaseCancelled) {
        self.pdfMagnificationAccumulator = 0;
    }
}

- (void)mouseDragged:(NSEvent *)event {
    if (self.nativeDragPath.length > 0) {
        NSString *path = self.nativeDragPath;
        self.nativeDragPath = nil;
        self.nativeDragName = nil;
        if ([[NSFileManager defaultManager] fileExistsAtPath:path]) {
            NSURL *fileURL = [NSURL fileURLWithPath:path];
            NSDraggingItem *draggingItem = [[NSDraggingItem alloc] initWithPasteboardWriter:fileURL];
            NSImage *icon = [[NSWorkspace sharedWorkspace] iconForFile:path];
            icon.size = NSMakeSize(48, 48);
            NSPoint point = [self convertPoint:event.locationInWindow fromView:nil];
            NSRect frame = NSMakeRect(point.x - 24, point.y - 24, 48, 48);
            [draggingItem setDraggingFrame:frame contents:icon];
            [self beginDraggingSessionWithItems:@[draggingItem] event:event source:self];
            return;
        }
    }
    [super mouseDragged:event];
}

- (void)scheduleNativeDragCleanup:(NSString *)path afterDelay:(NSTimeInterval)delay {
    if (path.length == 0) return;
    NSString *cleanupPath = [path copy];
    dispatch_after(
        dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)),
        dispatch_get_global_queue(QOS_CLASS_UTILITY, 0),
        ^{
            [[NSFileManager defaultManager] removeItemAtPath:cleanupPath error:nil];
        }
    );
}

- (void)mouseUp:(NSEvent *)event {
    if (self.nativeDragPath.length > 0 && self.nativeDragCleanupPath.length > 0) {
        [self scheduleNativeDragCleanup:self.nativeDragCleanupPath afterDelay:0.5];
    }
    self.nativeDragPath = nil;
    self.nativeDragName = nil;
    self.nativeDragCleanupPath = nil;
    [super mouseUp:event];
}

- (NSDragOperation)draggingSession:(NSDraggingSession *)session sourceOperationMaskForDraggingContext:(NSDraggingContext)context {
    return NSDragOperationCopy;
}

- (BOOL)ignoreModifierKeysForDraggingSession:(NSDraggingSession *)session {
    return YES;
}

- (void)draggingSession:(NSDraggingSession *)session
           endedAtPoint:(NSPoint)screenPoint
              operation:(NSDragOperation)operation {
    NSString *cleanupPath = self.nativeDragCleanupPath;
    self.nativeDragCleanupPath = nil;
    [self scheduleNativeDragCleanup:cleanupPath afterDelay:60.0];
}

- (NSArray<NSString *> *)finderDropPathsFromDraggingInfo:(id<NSDraggingInfo>)sender {
    NSPasteboard *pasteboard = sender.draggingPasteboard;
    NSMutableArray<NSString *> *paths = [NSMutableArray array];
    NSMutableSet<NSString *> *seen = [NSMutableSet set];

    NSDictionary *options = @{NSPasteboardURLReadingFileURLsOnlyKey: @YES};
    NSArray<NSURL *> *urls = [pasteboard readObjectsForClasses:@[[NSURL class]] options:options];
    for (NSURL *url in urls) {
        if (!url.isFileURL || !url.path) continue;
        if ([seen containsObject:url.path]) continue;
        [seen addObject:url.path];
        [paths addObject:url.path];
    }
    return paths;
}

@end

@interface GewuInsightWindow : NSWindow
@property(nonatomic, copy) void (^titlebarDoubleClickHandler)(void);
@end

@implementation GewuInsightWindow

- (BOOL)handleTitlebarDoubleClickAction {
    NSEvent *event = NSApp.currentEvent;
    if (!event || event.clickCount != 2 || event.window != self) return NO;
    NSPoint point = event.locationInWindow;
    CGFloat distanceFromTop = NSHeight(self.frame) - point.y;
    if (point.x < 90.0 || distanceFromTop < 0.0 || distanceFromTop > 40.0) return NO;
    if (self.titlebarDoubleClickHandler) self.titlebarDoubleClickHandler();
    return YES;
}

- (void)sendEvent:(NSEvent *)event {
    if (event.type == NSEventTypeLeftMouseDown && event.clickCount == 2) {
        NSPoint point = event.locationInWindow;
        CGFloat distanceFromTop = NSHeight(self.frame) - point.y;
        if (point.x >= 90.0 && distanceFromTop >= 0.0 && distanceFromTop <= 40.0) {
            if (self.titlebarDoubleClickHandler) self.titlebarDoubleClickHandler();
            return;
        }
    }
    [super sendEvent:event];
}

- (void)performMiniaturize:(id)sender {
    if ([self handleTitlebarDoubleClickAction]) return;
    [super performMiniaturize:sender];
}

- (void)miniaturize:(id)sender {
    if ([self handleTitlebarDoubleClickAction]) return;
    [super miniaturize:sender];
}

- (void)performZoom:(id)sender {
    if ([self handleTitlebarDoubleClickAction]) return;
    [super performZoom:sender];
}

- (void)zoom:(id)sender {
    if ([self handleTitlebarDoubleClickAction]) return;
    [super zoom:sender];
}

@end

@interface PaperMonitorDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate, WKDownloadDelegate, WKScriptMessageHandler>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSWindow *loaderWindow;
@property(nonatomic, strong) WKWebView *loaderWebView;
@property(nonatomic, strong) NSWindow *userGuideWindow;
@property(nonatomic, strong) WKWebView *userGuideWebView;
@property(nonatomic, strong) WKWebView *hiddenPublisherWebView;
@property(nonatomic, strong) WKDownload *hiddenPublisherDownload;
@property(nonatomic, copy) NSDictionary *hiddenPublisherContext;
@property(nonatomic, copy) NSString *hiddenPublisherToken;
@property(nonatomic, copy) NSString *hiddenPublisherTemporaryPath;
@property(nonatomic, strong) NSTimer *hiddenPublisherTimeout;
@property(nonatomic) BOOL hiddenPublisherDownloadTransitionPending;
@property(nonatomic, strong) NSMutableSet<NSString *> *hiddenPublisherDiscoveryVisitedURLs;
@property(nonatomic) NSInteger hiddenPublisherDiscoveryDepth;
@property(nonatomic) NSInteger hiddenPublisherDiscoveryPageRetryCount;
@property(nonatomic, strong) NSTask *ownedServerTask;
@property(nonatomic) NSInteger attempts;
@property(nonatomic, strong) NSURL *url;
@property(nonatomic, strong) NSMenuItem *titleNamingItem;
@property(nonatomic, strong) NSMenuItem *citationNamingItem;
@property(nonatomic, strong) NSMenuItem *listViewItem;
@property(nonatomic, strong) NSMenuItem *tableViewItem;
@property(nonatomic) BOOL windowDragging;
@property(nonatomic) NSPoint windowDragStartPoint;
@property(nonatomic) NSRect windowDragStartFrame;
@property(nonatomic) NSRect windowRestoreFrame;
@property(nonatomic) BOOL recoverTitlebarDoubleClickMiniaturize;
- (void)toggleMainWindowFill;
- (NSRect)defaultRestoreFrameForScreen:(NSScreen *)screen;
- (void)showAuthorPhotoChooserForAuthorId:(NSNumber *)authorId;
@end

@implementation PaperMonitorDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSDictionary *environment = [[NSProcessInfo processInfo] environment];
    NSString *host = environment[@"PAPER_MONITOR_HOST"] ?: @"127.0.0.1";
    NSString *port = environment[@"PAPER_MONITOR_PORT"] ?: @"8765";
    self.url = [NSURL URLWithString:[NSString stringWithFormat:@"http://%@:%@", host, port]];

    // Gewu Insight owns the title-bar double-click gesture. Keep AppKit from applying
    // the user's global Fill/Zoom/Minimize choice before our window can toggle.
    [[NSUserDefaults standardUserDefaults] setObject:@"None" forKey:@"AppleActionOnDoubleClick"];

    [self createWindow];
    [self showLoadingPage];
    [self installMainMenu];
    [NSApp activateIgnoringOtherApps:YES];
    [self ensureServerThenLoad];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return NO;
}

- (BOOL)windowShouldClose:(NSWindow *)sender {
    [sender orderOut:nil];
    return NO;
}

- (void)windowWillMiniaturize:(NSNotification *)notification {
    NSEvent *event = NSApp.currentEvent;
    if (!event || event.clickCount != 2 || event.window != self.window) {
        self.recoverTitlebarDoubleClickMiniaturize = NO;
        return;
    }
    NSPoint point = event.locationInWindow;
    CGFloat distanceFromTop = NSHeight(self.window.frame) - point.y;
    self.recoverTitlebarDoubleClickMiniaturize = point.x >= 90.0
        && distanceFromTop >= 0.0
        && distanceFromTop <= 40.0;
}

- (void)windowDidMiniaturize:(NSNotification *)notification {
    if (!self.recoverTitlebarDoubleClickMiniaturize) return;
    self.recoverTitlebarDoubleClickMiniaturize = NO;
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.window deminiaturize:nil];
        [self toggleMainWindowFill];
    });
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    if (!flag) {
        if (self.window.isMiniaturized) [self.window deminiaturize:nil];
        [self.window makeKeyAndOrderFront:nil];
        [NSApp activateIgnoringOtherApps:YES];
    }
    return YES;
}

- (void)closeActiveWindow:(id)sender {
    NSWindow *activeWindow = NSApp.keyWindow ?: NSApp.mainWindow;
    if (!activeWindow || !activeWindow.isVisible) {
        return;
    }
    if (
        activeWindow == self.window
        && [self.webView isKindOfClass:[GewuInsightWebView class]]
        && ((GewuInsightWebView *)self.webView).pdfQuickLookActive
    ) {
        [self.webView evaluateJavaScript:
            @"window.closeGewuInsightPreviewFromNative && window.closeGewuInsightPreviewFromNative()"
            completionHandler:nil];
        return;
    }
    [activeWindow performClose:sender];
}

- (void)applicationWillTerminate:(NSNotification *)notification {
    if (self.ownedServerTask && self.ownedServerTask.isRunning) {
        [self.ownedServerTask terminate];
    }
}

- (void)createWindow {
    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    WKUserContentController *userContentController = [[WKUserContentController alloc] init];
    [userContentController addScriptMessageHandler:self name:@"windowDrag"];
    [userContentController addScriptMessageHandler:self name:@"nativeFileDrag"];
    [userContentController addScriptMessageHandler:self name:@"authorPhotoChooser"];
    [userContentController addScriptMessageHandler:self name:@"libraryLoaderWindow"];
    [userContentController addScriptMessageHandler:self name:@"pdfPreviewState"];
    [userContentController addScriptMessageHandler:self name:@"publisherPdfDownload"];
    configuration.userContentController = userContentController;
    self.webView = [[GewuInsightWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
    self.webView.UIDelegate = self;

    self.window = [[GewuInsightWindow alloc]
        initWithContentRect:NSMakeRect(0, 0, 1280, 860)
                  styleMask:(NSWindowStyleMaskTitled |
                             NSWindowStyleMaskClosable |
                             NSWindowStyleMaskMiniaturizable |
                             NSWindowStyleMaskResizable |
                             NSWindowStyleMaskFullSizeContentView)
                    backing:NSBackingStoreBuffered
                      defer:NO];
    self.window.title = @"";
    self.window.delegate = self;
    self.window.titleVisibility = NSWindowTitleHidden;
    self.window.titlebarAppearsTransparent = YES;
    self.window.minSize = NSMakeSize(980, 680);
    NSScreen *screen = [NSScreen mainScreen];
    if (screen) {
        self.windowRestoreFrame = [self defaultRestoreFrameForScreen:screen];
        [self.window setFrame:screen.visibleFrame display:YES];
    } else {
        [self.window center];
        self.windowRestoreFrame = self.window.frame;
    }
    self.window.contentView = self.webView;
    __weak PaperMonitorDelegate *weakSelf = self;
    ((GewuInsightWindow *)self.window).titlebarDoubleClickHandler = ^{
        PaperMonitorDelegate *strongSelf = weakSelf;
        if (!strongSelf) return;
        strongSelf.windowDragging = NO;
        [strongSelf toggleMainWindowFill];
    };
    if (self.window.isMiniaturized) [self.window deminiaturize:nil];
    [self.window makeKeyAndOrderFront:nil];
    [self positionTrafficLightButtons];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self positionTrafficLightButtons];
    });
}

- (void)userContentController:(WKUserContentController *)userContentController
      didReceiveScriptMessage:(WKScriptMessage *)message {
    if ([message.name isEqualToString:@"publisherPdfDownload"]) {
        if (![message.body isKindOfClass:[NSDictionary class]]) return;
        [self startHiddenPublisherDownload:(NSDictionary *)message.body];
        return;
    }
    if ([message.name isEqualToString:@"pdfPreviewState"]) {
        if (![self.webView isKindOfClass:[GewuInsightWebView class]]) return;
        BOOL active = NO;
        if ([message.body isKindOfClass:[NSDictionary class]]) {
            id value = ((NSDictionary *)message.body)[@"active"];
            if ([value respondsToSelector:@selector(boolValue)]) active = [value boolValue];
        }
        ((GewuInsightWebView *)self.webView).pdfQuickLookActive = active;
        return;
    }
    if ([message.name isEqualToString:@"libraryLoaderWindow"]) {
        NSString *type = @"close";
        if ([message.body isKindOfClass:[NSDictionary class]]) {
            NSDictionary *payload = (NSDictionary *)message.body;
            type = [payload[@"type"] isKindOfClass:[NSString class]] ? payload[@"type"] : type;
        }
        if ([type isEqualToString:@"open"]) {
            [self showLibraryLoaderWindow];
        } else {
            [self.loaderWindow orderOut:nil];
        }
        return;
    }
    if ([message.name isEqualToString:@"nativeFileDrag"]) {
        if (![message.body isKindOfClass:[NSDictionary class]] || ![self.webView isKindOfClass:[GewuInsightWebView class]]) {
            return;
        }
        NSDictionary *payload = (NSDictionary *)message.body;
        NSString *path = [payload[@"path"] isKindOfClass:[NSString class]] ? payload[@"path"] : @"";
        NSString *name = [payload[@"name"] isKindOfClass:[NSString class]] ? payload[@"name"] : @"";
        NSString *cleanupPath = [payload[@"cleanup_path"] isKindOfClass:[NSString class]] ? payload[@"cleanup_path"] : @"";
        GewuInsightWebView *webView = (GewuInsightWebView *)self.webView;
        webView.nativeDragPath = path;
        webView.nativeDragName = name;
        webView.nativeDragCleanupPath = cleanupPath;
        return;
    }
    if ([message.name isEqualToString:@"authorPhotoChooser"]) {
        if (![message.body isKindOfClass:[NSDictionary class]]) return;
        id value = ((NSDictionary *)message.body)[@"author_id"];
        NSNumber *authorId = [value isKindOfClass:[NSNumber class]] ? value : nil;
        if (!authorId || authorId.integerValue <= 0) return;
        [self showAuthorPhotoChooserForAuthorId:authorId];
        return;
    }
    if (![message.name isEqualToString:@"windowDrag"] || ![message.body isKindOfClass:[NSDictionary class]]) {
        return;
    }
    NSDictionary *payload = (NSDictionary *)message.body;
    NSString *type = [payload[@"type"] isKindOfClass:[NSString class]] ? payload[@"type"] : @"";
    NSNumber *screenXNumber = [payload[@"screenX"] isKindOfClass:[NSNumber class]] ? payload[@"screenX"] : nil;
    NSNumber *screenYNumber = [payload[@"screenY"] isKindOfClass:[NSNumber class]] ? payload[@"screenY"] : nil;
    if (!screenXNumber || !screenYNumber) {
        return;
    }
    NSPoint point = NSMakePoint(screenXNumber.doubleValue, screenYNumber.doubleValue);
    if ([type isEqualToString:@"toggleFill"]) {
        self.windowDragging = NO;
        [self toggleMainWindowFill];
        return;
    }
    if ([type isEqualToString:@"begin"]) {
        self.windowDragging = YES;
        self.windowDragStartPoint = point;
        self.windowDragStartFrame = self.window.frame;
        return;
    }
    if ([type isEqualToString:@"end"] || [type isEqualToString:@"cancel"]) {
        self.windowDragging = NO;
        return;
    }
    if (![type isEqualToString:@"move"] || !self.windowDragging) {
        return;
    }
    CGFloat dx = point.x - self.windowDragStartPoint.x;
    CGFloat dy = point.y - self.windowDragStartPoint.y;
    NSRect frame = self.windowDragStartFrame;
    frame.origin.x += dx;
    frame.origin.y -= dy;
    [self.window setFrame:frame display:YES];
}

- (void)showAuthorPhotoChooserForAuthorId:(NSNumber *)authorId {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.title = @"Choose Author Photo";
    panel.message = @"Choose a PNG, JPEG, or WebP image.";
    panel.prompt = @"Choose Photo";
    panel.canChooseFiles = YES;
    panel.canChooseDirectories = NO;
    panel.allowsMultipleSelection = NO;
    panel.resolvesAliases = YES;
    panel.allowedFileTypes = @[@"png", @"jpg", @"jpeg", @"webp"];
    __weak typeof(self) weakSelf = self;
    [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse result) {
        PaperMonitorDelegate *strongSelf = weakSelf;
        if (!strongSelf) return;
        NSMutableDictionary *payload = [@{
            @"author_id": authorId,
            @"cancelled": @(result != NSModalResponseOK)
        } mutableCopy];
        if (result == NSModalResponseOK && panel.URL.path.length > 0) {
            payload[@"path"] = panel.URL.path;
        }
        NSData *jsonData = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
        NSString *json = jsonData
            ? [[NSString alloc] initWithData:jsonData encoding:NSUTF8StringEncoding]
            : @"{}";
        NSString *script = [NSString stringWithFormat:
            @"window.handleNativeAuthorPhotoSelection && "
             "window.handleNativeAuthorPhotoSelection(%@);",
            json
        ];
        [strongSelf.webView evaluateJavaScript:script completionHandler:nil];
    }];
}

- (NSString *)publisherNameForContext:(NSDictionary *)context {
    NSString *publisher = [context[@"publisher_download_name"] isKindOfClass:[NSString class]]
        ? [context[@"publisher_download_name"] lowercaseString]
        : @"";
    NSString *kind = [context[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? context[@"publisher_download_kind"]
        : @"";
    if (publisher.length == 0 && [kind hasPrefix:@"aaas-"]) return @"aaas";
    return publisher;
}

- (BOOL)isAllowedPublisherURL:(NSURL *)url publisher:(NSString *)publisher {
    if (!url || ![url.scheme.lowercaseString isEqualToString:@"https"]) return NO;
    NSString *host = url.host.lowercaseString ?: @"";
    if ([publisher isEqualToString:@"aaas"]) {
        return [host isEqualToString:@"science.org"]
            || [host hasSuffix:@".science.org"]
            || [host isEqualToString:@"sciencemag.org"]
            || [host hasSuffix:@".sciencemag.org"];
    }
    if ([publisher isEqualToString:@"acs"]) {
        return [host isEqualToString:@"pubs.acs.org"]
            || [host isEqualToString:@"acs.figshare.com"];
    }
    if ([publisher isEqualToString:@"aps"]) {
        return [host hasSuffix:@".aps.org"]
            || [host isEqualToString:@"aps.org"];
    }
    if ([publisher isEqualToString:@"wiley"]) {
        return [host isEqualToString:@"onlinelibrary.wiley.com"]
            || [host hasSuffix:@".onlinelibrary.wiley.com"];
    }
    if ([publisher isEqualToString:@"cpl"]) {
        return [host isEqualToString:@"cpl.iphy.ac.cn"]
            || [host isEqualToString:@"iopscience.iop.org"];
    }
    if ([publisher isEqualToString:@"cpb"]) {
        return [host isEqualToString:@"cpb.iphy.ac.cn"]
            || [host isEqualToString:@"iopscience.iop.org"];
    }
    if ([publisher isEqualToString:@"elsevier"]) {
        return [host isEqualToString:@"www.sciencedirect.com"]
            || [host isEqualToString:@"sciencedirect.com"]
            || [host isEqualToString:@"linkinghub.elsevier.com"]
            || [host isEqualToString:@"reader.elsevier.com"]
            || [host isEqualToString:@"ars.els-cdn.com"]
            || [host hasSuffix:@".sciencedirectassets.com"];
    }
    if ([publisher isEqualToString:@"oup"]) {
        return [host isEqualToString:@"academic.oup.com"]
            || [host isEqualToString:@"preview.academic.oup.com"]
            || [host isEqualToString:@"watermark.silverchair.com"]
            || [host hasSuffix:@".silverchair-cdn.com"];
    }
    return NO;
}

- (void)startHiddenPublisherDownload:(NSDictionary *)payload {
    NSString *token = [payload[@"token"] isKindOfClass:[NSString class]] ? payload[@"token"] : @"";
    NSString *urlString = [payload[@"url"] isKindOfClass:[NSString class]] ? payload[@"url"] : @"";
    NSDictionary *context = [payload[@"context"] isKindOfClass:[NSDictionary class]] ? payload[@"context"] : @{};
    NSURL *publisherURL = [NSURL URLWithString:urlString];
    NSString *publisher = [self publisherNameForContext:context];
    NSString *path = publisherURL.path.lowercaseString ?: @"";
    BOOL sciencePath = [path hasPrefix:@"/doi/pdf/"]
        || [path hasPrefix:@"/doi/epdf/"]
        || [path hasPrefix:@"/doi/suppl/"]
        || [path hasPrefix:@"/doi/"]
        || [path hasSuffix:@".pdf"];
    BOOL allowedPath = [publisher isEqualToString:@"aaas"] ? sciencePath : path.length > 0;
    if (token.length == 0 || !publisherURL || ![self isAllowedPublisherURL:publisherURL publisher:publisher] || !allowedPath) {
        [self notifyHiddenPublisherDownloadToken:token success:NO data:nil error:@"Invalid published PDF download request."];
        return;
    }
    if (self.hiddenPublisherWebView || self.hiddenPublisherDownload) {
        [self notifyHiddenPublisherDownloadToken:token success:NO data:nil error:@"Another published PDF is already downloading."];
        return;
    }

    self.hiddenPublisherToken = token;
    self.hiddenPublisherContext = [context copy];
    self.hiddenPublisherDiscoveryVisitedURLs = [NSMutableSet set];
    self.hiddenPublisherDiscoveryDepth = 0;
    self.hiddenPublisherDiscoveryPageRetryCount = 0;
    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    configuration.websiteDataStore = [WKWebsiteDataStore defaultDataStore];
    // Publisher pages often hide their desktop PDF controls in a 1x1 responsive
    // viewport. The web view remains off-screen, but uses a normal desktop layout.
    self.hiddenPublisherWebView = [[WKWebView alloc] initWithFrame:NSMakeRect(0, 0, 1280, 900) configuration:configuration];
    self.hiddenPublisherWebView.navigationDelegate = self;

    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:publisherURL];
    [request setValue:@"application/pdf,application/octet-stream;q=0.9,text/html;q=0.8,*/*;q=0.5" forHTTPHeaderField:@"Accept"];
    NSString *referer = [context[@"publisher_download_referer"] isKindOfClass:[NSString class]]
        ? context[@"publisher_download_referer"]
        : @"";
    NSURL *refererURL = [NSURL URLWithString:referer];
    if (referer.length == 0 && [publisher isEqualToString:@"aaas"]) {
        NSString *refererPath = [publisherURL.path stringByReplacingOccurrencesOfString:@"/doi/pdf/" withString:@"/doi/"];
        refererPath = [refererPath stringByReplacingOccurrencesOfString:@"/doi/epdf/" withString:@"/doi/"];
        if ([publisherURL.path hasPrefix:@"/doi/suppl/"]) {
            NSString *supplementPath = [publisherURL.path substringFromIndex:@"/doi/suppl/".length];
            NSRange fileRange = [supplementPath rangeOfString:@"/suppl_file/"];
            if (fileRange.location != NSNotFound) {
                supplementPath = [supplementPath substringToIndex:fileRange.location];
            }
            refererPath = [@"/doi/" stringByAppendingString:supplementPath];
        }
        referer = [NSString stringWithFormat:@"https://www.science.org%@", refererPath ?: @""];
        refererURL = [NSURL URLWithString:referer];
    }
    if (refererURL && [self isAllowedPublisherURL:refererURL publisher:publisher]) {
        [request setValue:referer forHTTPHeaderField:@"Referer"];
    }

    self.hiddenPublisherTimeout = [NSTimer scheduledTimerWithTimeInterval:80.0
                                                                   target:self
                                                                 selector:@selector(hiddenPublisherDownloadTimedOut:)
                                                                 userInfo:nil
                                                                  repeats:NO];
    [self.hiddenPublisherWebView loadRequest:request];
}

- (BOOL)isAllowedScienceSupplementURL:(NSURL *)url {
    NSString *host = url.host.lowercaseString ?: @"";
    NSString *path = url.path.lowercaseString ?: @"";
    BOOL allowedHost = [host isEqualToString:@"science.org"]
        || [host hasSuffix:@".science.org"]
        || [host isEqualToString:@"sciencemag.org"]
        || [host hasSuffix:@".sciencemag.org"];
    BOOL allowedPath = [path hasPrefix:@"/doi/"]
        || [path hasPrefix:@"/content/suppl/"]
        || [path hasPrefix:@"/cgi/content/full/"]
        || [path hasSuffix:@".pdf"]
        || [path hasSuffix:@".doc"]
        || [path hasSuffix:@".docx"];
    return [url.scheme.lowercaseString isEqualToString:@"https"] && allowedHost && allowedPath;
}

- (BOOL)isHiddenPublisherSupplementDiscovery {
    NSString *kind = [self.hiddenPublisherContext[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? self.hiddenPublisherContext[@"publisher_download_kind"]
        : @"";
    return [kind isEqualToString:@"aaas-supplement-discovery"];
}

- (BOOL)isHiddenGenericSupplementDiscovery {
    NSString *kind = [self.hiddenPublisherContext[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? self.hiddenPublisherContext[@"publisher_download_kind"]
        : @"";
    return [kind isEqualToString:@"publisher-supplement-discovery"];
}

- (BOOL)isHiddenPublisherMainDownload {
    NSString *kind = [self.hiddenPublisherContext[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? self.hiddenPublisherContext[@"publisher_download_kind"]
        : @"";
    return [kind isEqualToString:@"publisher-main-pdf"]
        || [kind isEqualToString:@"aaas-published-pdf"];
}

- (void)completeHiddenPublisherSupplementDiscoveryWithURLs:(NSArray<NSString *> *)urls {
    NSString *token = self.hiddenPublisherToken ?: @"";
    [self notifyHiddenPublisherDownloadToken:token
                                     success:YES
                                        data:@{@"supplement_urls": urls ?: @[]}
                                       error:nil];
    [self clearHiddenPublisherDownload];
}

- (void)inspectHiddenPublisherSupplementPage {
    if (![self isHiddenPublisherSupplementDiscovery] || !self.hiddenPublisherWebView) return;
    NSString *script =
        @"(() => {"
         "const acceptedHost = h => h === 'science.org' || h.endsWith('.science.org') || h === 'sciencemag.org' || h.endsWith('.sciencemag.org');"
         "const pagePath = location.pathname.toLowerCase();"
         "const pageIsSupplement = pagePath.includes('/doi/suppl/') || pagePath.includes('/content/suppl/') || /\\/dc\\d+(?:$|[/?#])/.test(pagePath);"
         "const pdfs = [], landings = [];"
         "for (const a of document.querySelectorAll('a[href], iframe[src], embed[src]')) {"
           "const raw = a.getAttribute('href') || a.getAttribute('src') || '';"
           "let u; try { u = new URL(raw, location.href); } catch (_) { continue; }"
           "if (u.protocol === 'http:') u.protocol = 'https:';"
           "if (!acceptedHost(u.hostname.toLowerCase())) continue;"
           "const path = u.pathname.toLowerCase();"
           "const label = `${a.textContent || ''} ${a.getAttribute('title') || ''} ${a.getAttribute('type') || ''}`.toLowerCase();"
           "const supplementMarker = pageIsSupplement || path.includes('/suppl') || path.includes('/supplement') || /(?:^|[/.])dc\\d+(?:$|[/?#])/.test(path) || label.includes('supplement') || label.includes('supporting information');"
           "const explicitPdf = /\\.(pdf|docx?)$/i.test(path) || /pdf|msword|wordprocessingml/.test(String(a.getAttribute('type') || '').toLowerCase()) || /\\b(pdf|word|docx?)\\b/.test(label);"
           "const likelyMainPdf = path.includes('/doi/pdf/') || label.includes('full text pdf') || label.includes('article pdf');"
           "if (supplementMarker && explicitPdf && !likelyMainPdf) pdfs.push(u.href);"
           "else if (path.includes('/doi/suppl/') || path.includes('/content/suppl/') || path.includes('/cgi/content/full/') && /\\/dc\\d+/.test(path)) landings.push(u.href);"
         "}"
         "return {pdfs: [...new Set(pdfs)], landings: [...new Set(landings)], page: location.href};"
        "})()";
    __weak PaperMonitorDelegate *weakSelf = self;
    [self.hiddenPublisherWebView evaluateJavaScript:script completionHandler:^(id result, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            PaperMonitorDelegate *strongSelf = weakSelf;
            if (!strongSelf || !strongSelf.hiddenPublisherWebView || ![strongSelf isHiddenPublisherSupplementDiscovery]) return;
            NSDictionary *payload = [result isKindOfClass:[NSDictionary class]] ? result : @{};
            NSArray *rawPDFs = [payload[@"pdfs"] isKindOfClass:[NSArray class]] ? payload[@"pdfs"] : @[];
            NSMutableArray<NSString *> *pdfs = [NSMutableArray array];
            for (id value in rawPDFs) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                if ([strongSelf isAllowedScienceSupplementURL:url]) [pdfs addObject:url.absoluteString];
            }
            if (pdfs.count > 0) {
                [strongSelf completeHiddenPublisherSupplementDiscoveryWithURLs:pdfs];
                return;
            }
            NSArray *landings = [payload[@"landings"] isKindOfClass:[NSArray class]] ? payload[@"landings"] : @[];
            for (id value in landings) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                NSString *absolute = url.absoluteString ?: @"";
                if (![strongSelf isAllowedScienceSupplementURL:url] || [strongSelf.hiddenPublisherDiscoveryVisitedURLs containsObject:absolute]) continue;
                if (strongSelf.hiddenPublisherDiscoveryDepth >= 4) break;
                [strongSelf.hiddenPublisherDiscoveryVisitedURLs addObject:absolute];
                strongSelf.hiddenPublisherDiscoveryDepth += 1;
                strongSelf.hiddenPublisherDiscoveryPageRetryCount = 0;
                [strongSelf.hiddenPublisherWebView loadRequest:[NSURLRequest requestWithURL:url]];
                return;
            }
            if (!error && strongSelf.hiddenPublisherDiscoveryPageRetryCount < 2) {
                strongSelf.hiddenPublisherDiscoveryPageRetryCount += 1;
                dispatch_after(
                    dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.0 * NSEC_PER_SEC)),
                    dispatch_get_main_queue(),
                    ^{
                        [strongSelf inspectHiddenPublisherSupplementPage];
                    }
                );
                return;
            }
            NSString *message = error.localizedDescription ?: @"Science did not list any PDF supplementary files.";
            [strongSelf failHiddenPublisherDownload:message];
        });
    }];
}

- (void)inspectHiddenGenericSupplementPage {
    if (![self isHiddenGenericSupplementDiscovery] || !self.hiddenPublisherWebView) return;
    NSString *script =
        @"(() => {"
         "const files = [], landings = [];"
         "for (const el of document.querySelectorAll('a[href], iframe[src], embed[src]')) {"
           "const raw = el.getAttribute('href') || el.getAttribute('src') || '';"
           "let u; try { u = new URL(raw, location.href); } catch (_) { continue; }"
           "if (u.protocol === 'http:') u.protocol = 'https:';"
           "const path = u.pathname.toLowerCase();"
           "const label = `${el.textContent || ''} ${el.getAttribute('title') || ''} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('type') || ''}`.toLowerCase();"
           "const marker = `${path} ${u.search.toLowerCase()} ${label}`;"
           "const supplementary = /supplement|supporting information|suppl_file|supinfo|suppinfo|suppdata|additional file|appendix|attachment|mmc\\d|figshare/.test(marker);"
           "const supported = /\\.(pdf|docx?)(?:$|[?#])/.test(`${path}${u.search}`) || /\\b(pdf|word|docx?)\\b/.test(label);"
           "const mainPdf = /article-pdf|\\/doi\\/(pdf|epdf)\\//.test(path) && !supplementary;"
           "if (supplementary && supported && !mainPdf) files.push(u.href);"
           "else if (supplementary && !supported) landings.push(u.href);"
         "}"
         "return {files: [...new Set(files)], landings: [...new Set(landings)], page: location.href};"
        "})()";
    __weak PaperMonitorDelegate *weakSelf = self;
    [self.hiddenPublisherWebView evaluateJavaScript:script completionHandler:^(id result, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            PaperMonitorDelegate *strongSelf = weakSelf;
            if (!strongSelf || !strongSelf.hiddenPublisherWebView || ![strongSelf isHiddenGenericSupplementDiscovery]) return;
            NSDictionary *payload = [result isKindOfClass:[NSDictionary class]] ? result : @{};
            NSString *publisher = [strongSelf publisherNameForContext:strongSelf.hiddenPublisherContext ?: @{}];
            NSArray *rawFiles = [payload[@"files"] isKindOfClass:[NSArray class]] ? payload[@"files"] : @[];
            NSMutableArray<NSString *> *files = [NSMutableArray array];
            for (id value in rawFiles) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                if ([strongSelf isAllowedPublisherURL:url publisher:publisher]) {
                    [files addObject:url.absoluteString];
                }
            }
            if (files.count > 0) {
                [strongSelf completeHiddenPublisherSupplementDiscoveryWithURLs:files];
                return;
            }
            NSArray *landings = [payload[@"landings"] isKindOfClass:[NSArray class]] ? payload[@"landings"] : @[];
            for (id value in landings) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                NSString *absolute = url.absoluteString ?: @"";
                if (![strongSelf isAllowedPublisherURL:url publisher:publisher]
                    || [strongSelf.hiddenPublisherDiscoveryVisitedURLs containsObject:absolute]) {
                    continue;
                }
                if (strongSelf.hiddenPublisherDiscoveryDepth >= 5) break;
                [strongSelf.hiddenPublisherDiscoveryVisitedURLs addObject:absolute];
                strongSelf.hiddenPublisherDiscoveryDepth += 1;
                strongSelf.hiddenPublisherDiscoveryPageRetryCount = 0;
                [strongSelf.hiddenPublisherWebView loadRequest:[NSURLRequest requestWithURL:url]];
                return;
            }
            if (!error && strongSelf.hiddenPublisherDiscoveryPageRetryCount < 5) {
                strongSelf.hiddenPublisherDiscoveryPageRetryCount += 1;
                dispatch_after(
                    dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.0 * NSEC_PER_SEC)),
                    dispatch_get_main_queue(),
                    ^{
                        [strongSelf inspectHiddenGenericSupplementPage];
                    }
                );
                return;
            }
            if (error) {
                [strongSelf failHiddenPublisherDownload:error.localizedDescription ?: @"Supplement discovery failed."];
            } else {
                [strongSelf completeHiddenPublisherSupplementDiscoveryWithURLs:@[]];
            }
        });
    }];
}

- (void)inspectHiddenPublisherMainPage {
    if (![self isHiddenPublisherMainDownload] || !self.hiddenPublisherWebView) return;
    NSString *publisher = [self publisherNameForContext:self.hiddenPublisherContext ?: @{}];
    NSString *current = self.hiddenPublisherWebView.URL.absoluteString ?: @"";
    NSString *targetString =
        [self.hiddenPublisherContext[@"publisher_download_target_url"] isKindOfClass:[NSString class]]
            ? self.hiddenPublisherContext[@"publisher_download_target_url"]
            : @"";
    NSURL *targetURL = [NSURL URLWithString:targetString];
    NSString *targetAbsolute = targetURL.absoluteString ?: @"";
    if (targetAbsolute.length > 0
        && ![targetAbsolute isEqualToString:current]
        && [self isAllowedPublisherURL:targetURL publisher:publisher]
        && ![self.hiddenPublisherDiscoveryVisitedURLs containsObject:targetAbsolute]) {
        [self.hiddenPublisherDiscoveryVisitedURLs addObject:targetAbsolute];
        self.hiddenPublisherDiscoveryDepth += 1;
        self.hiddenPublisherDiscoveryPageRetryCount = 0;
        NSMutableURLRequest *targetRequest = [NSMutableURLRequest requestWithURL:targetURL];
        if (current.length > 0) [targetRequest setValue:current forHTTPHeaderField:@"Referer"];
        [targetRequest setValue:@"application/pdf,application/octet-stream;q=0.9,text/html;q=0.8,*/*;q=0.5"
             forHTTPHeaderField:@"Accept"];
        [self.hiddenPublisherWebView loadRequest:targetRequest];
        return;
    }
    NSString *script =
        @"(() => {"
         "const urls = [];"
         "for (const meta of document.querySelectorAll('meta[name=\"citation_pdf_url\"], meta[property=\"citation_pdf_url\"]')) {"
           "const raw = meta.getAttribute('content') || '';"
           "try { if (raw) urls.push(new URL(raw, location.href).href); } catch (_) {}"
         "}"
         "for (const el of document.querySelectorAll('a[href], iframe[src], embed[src]')) {"
           "const raw = el.getAttribute('href') || el.getAttribute('src') || '';"
           "let u; try { u = new URL(raw, location.href); } catch (_) { continue; }"
           "const path = u.pathname.toLowerCase();"
           "const label = `${el.textContent || ''} ${el.getAttribute('title') || ''} ${el.getAttribute('aria-label') || ''}`.toLowerCase();"
           "const supplementary = /supplement|supporting information|appendix/.test(`${path} ${label}`);"
           "const pdfRoute = /\\.pdf$/i.test(path) || path.includes('/doi/pdf') || path.includes('/doi/epdf') || path.includes('/article-pdf/') || path.includes('/pdfft') || path.includes('downloadarticlefile.do');"
           "const pdfLabel = /(^|\\s)(download\\s+|view\\s+|open\\s+)?pdf(\\s|$)/.test(label);"
           "if (!supplementary && (pdfRoute || pdfLabel)) urls.push(u.href);"
         "}"
         "let clicked = false;"
         "if (!urls.length) {"
           "for (const el of document.querySelectorAll('button, [role=\"button\"], a')) {"
             "const label = `${el.textContent || ''} ${el.getAttribute('title') || ''} ${el.getAttribute('aria-label') || ''}`.trim().toLowerCase();"
             "if (!/supplement|supporting information/.test(label) && /(^|\\s)(download\\s+|view\\s+|open\\s+)?pdf(\\s|$)/.test(label)) {"
               "try { el.click(); clicked = true; } catch (_) {}"
               "break;"
             "}"
           "}"
         "}"
         "return {urls: [...new Set(urls)], clicked, page: location.href};"
        "})()";
    __weak PaperMonitorDelegate *weakSelf = self;
    [self.hiddenPublisherWebView evaluateJavaScript:script completionHandler:^(id result, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            PaperMonitorDelegate *strongSelf = weakSelf;
            if (!strongSelf || !strongSelf.hiddenPublisherWebView || ![strongSelf isHiddenPublisherMainDownload]) return;
            NSDictionary *payload = [result isKindOfClass:[NSDictionary class]] ? result : @{};
            NSArray *rawURLs = [payload[@"urls"] isKindOfClass:[NSArray class]] ? payload[@"urls"] : @[];
            NSString *publisher = [strongSelf publisherNameForContext:strongSelf.hiddenPublisherContext ?: @{}];
            NSString *current = strongSelf.hiddenPublisherWebView.URL.absoluteString ?: @"";
            for (id value in rawURLs) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                NSString *absolute = url.absoluteString ?: @"";
                if (![strongSelf isAllowedPublisherURL:url publisher:publisher]
                    || [absolute isEqualToString:current]
                    || [strongSelf.hiddenPublisherDiscoveryVisitedURLs containsObject:absolute]) {
                    continue;
                }
                if (strongSelf.hiddenPublisherDiscoveryDepth >= 6) break;
                [strongSelf.hiddenPublisherDiscoveryVisitedURLs addObject:absolute];
                strongSelf.hiddenPublisherDiscoveryDepth += 1;
                strongSelf.hiddenPublisherDiscoveryPageRetryCount = 0;
                NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
                if (current.length > 0) [request setValue:current forHTTPHeaderField:@"Referer"];
                [request setValue:@"application/pdf,application/octet-stream;q=0.9,text/html;q=0.8,*/*;q=0.5" forHTTPHeaderField:@"Accept"];
                [strongSelf.hiddenPublisherWebView loadRequest:request];
                return;
            }
            BOOL clicked = [payload[@"clicked"] respondsToSelector:@selector(boolValue)]
                && [payload[@"clicked"] boolValue];
            if (!error && strongSelf.hiddenPublisherDiscoveryPageRetryCount < 160) {
                strongSelf.hiddenPublisherDiscoveryPageRetryCount += 1;
                NSTimeInterval delay = clicked ? 1.5 : 1.0;
                dispatch_after(
                    dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)),
                    dispatch_get_main_queue(),
                    ^{
                        [strongSelf inspectHiddenPublisherMainPage];
                    }
                );
                return;
            }
            NSString *message = error.localizedDescription
                ?: @"The publisher page did not expose a downloadable PDF.";
            [strongSelf failHiddenPublisherDownload:message];
        });
    }];
}

- (void)hiddenPublisherDownloadTimedOut:(NSTimer *)timer {
    [self failHiddenPublisherDownload:@"The publisher did not provide a PDF before the background download timed out."];
}

- (void)webView:(WKWebView *)webView
decidePolicyForNavigationResponse:(WKNavigationResponse *)navigationResponse
decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler {
    if (webView != self.hiddenPublisherWebView) {
        decisionHandler(WKNavigationResponsePolicyAllow);
        return;
    }
    NSString *mimeType = navigationResponse.response.MIMEType.lowercaseString ?: @"";
    NSString *disposition = @"";
    if ([navigationResponse.response isKindOfClass:[NSHTTPURLResponse class]]) {
        id value = ((NSHTTPURLResponse *)navigationResponse.response).allHeaderFields[@"Content-Disposition"];
        if ([value isKindOfClass:[NSString class]]) disposition = [value lowercaseString];
    }
    BOOL isPDF = [mimeType containsString:@"pdf"] || [disposition containsString:@".pdf"];
    if (isPDF || !navigationResponse.canShowMIMEType) {
        self.hiddenPublisherDownloadTransitionPending = YES;
        decisionHandler(WKNavigationResponsePolicyDownload);
    } else {
        decisionHandler(WKNavigationResponsePolicyAllow);
    }
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    if (webView != self.hiddenPublisherWebView) return;
    NSString *absolute = webView.URL.absoluteString ?: @"";
    if (absolute.length > 0) [self.hiddenPublisherDiscoveryVisitedURLs addObject:absolute];
    self.hiddenPublisherDiscoveryPageRetryCount = 0;
    if ([self isHiddenPublisherSupplementDiscovery]) {
        [self inspectHiddenPublisherSupplementPage];
    } else if ([self isHiddenGenericSupplementDiscovery]) {
        [self inspectHiddenGenericSupplementPage];
    } else if ([self isHiddenPublisherMainDownload]) {
        [self inspectHiddenPublisherMainPage];
    }
}

- (void)webView:(WKWebView *)webView
navigationAction:(WKNavigationAction *)navigationAction
didBecomeDownload:(WKDownload *)download {
    if (webView != self.hiddenPublisherWebView) return;
    self.hiddenPublisherDownloadTransitionPending = NO;
    self.hiddenPublisherDownload = download;
    download.delegate = self;
}

- (void)webView:(WKWebView *)webView
navigationResponse:(WKNavigationResponse *)navigationResponse
didBecomeDownload:(WKDownload *)download {
    if (webView != self.hiddenPublisherWebView) return;
    self.hiddenPublisherDownloadTransitionPending = NO;
    self.hiddenPublisherDownload = download;
    download.delegate = self;
}

- (void)download:(WKDownload *)download
decideDestinationUsingResponse:(NSURLResponse *)response
suggestedFilename:(NSString *)suggestedFilename
completionHandler:(void (^)(NSURL * _Nullable destination))completionHandler {
    if (download != self.hiddenPublisherDownload) {
        completionHandler(nil);
        return;
    }
    NSString *extension = suggestedFilename.pathExtension.lowercaseString ?: @"";
    NSString *mimeType = response.MIMEType.lowercaseString ?: @"";
    if (![extension isEqualToString:@"pdf"] && ![extension isEqualToString:@"doc"] && ![extension isEqualToString:@"docx"]) {
        if ([mimeType containsString:@"wordprocessingml"]) extension = @"docx";
        else if ([mimeType containsString:@"msword"]) extension = @"doc";
        else extension = @"pdf";
    }
    NSString *temporaryName = [NSString stringWithFormat:@"daiqo-published-%@.%@", NSUUID.UUID.UUIDString, extension];
    NSString *temporaryPath = [NSTemporaryDirectory() stringByAppendingPathComponent:temporaryName];
    self.hiddenPublisherTemporaryPath = temporaryPath;
    completionHandler([NSURL fileURLWithPath:temporaryPath]);
}

- (void)downloadDidFinish:(WKDownload *)download {
    if (download != self.hiddenPublisherDownload) return;
    [self.hiddenPublisherTimeout invalidate];
    self.hiddenPublisherTimeout = nil;
    [self acceptHiddenPublisherFileAtPath:self.hiddenPublisherTemporaryPath ?: @""];
}

- (void)acceptHiddenPublisherFileAtPath:(NSString *)path {
    NSDictionary *attributes = path.length > 0
        ? [[NSFileManager defaultManager] attributesOfItemAtPath:path error:nil]
        : nil;
    unsigned long long fileSize = [attributes fileSize];
    NSFileHandle *handle = path.length > 0 ? [NSFileHandle fileHandleForReadingAtPath:path] : nil;
    NSData *prefix = [handle readDataOfLength:1024];
    [handle closeFile];
    NSString *prefixText = prefix ? [[NSString alloc] initWithData:prefix encoding:NSISOLatin1StringEncoding] : @"";
    NSString *extension = path.pathExtension.lowercaseString ?: @"";
    BOOL isPDF = [prefixText rangeOfString:@"%PDF-"].location != NSNotFound;
    const unsigned char *bytes = prefix.bytes;
    BOOL isDOCX = prefix.length >= 4 && bytes[0] == 'P' && bytes[1] == 'K' && bytes[2] == 3 && bytes[3] == 4;
    const unsigned char oleHeader[] = {0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1};
    BOOL isDOC = prefix.length >= sizeof(oleHeader)
        && memcmp(bytes, oleHeader, sizeof(oleHeader)) == 0;
    NSString *kind = [self.hiddenPublisherContext[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? self.hiddenPublisherContext[@"publisher_download_kind"]
        : @"";
    BOOL supplementFile = [kind isEqualToString:@"publisher-supplement-file"]
        || [kind isEqualToString:@"aaas-supplement-pdf"];
    BOOL validSupplementDocument = supplementFile && (isDOCX || isDOC);
    if (path.length == 0 || fileSize < 1024 || (!isPDF && !validSupplementDocument)) {
        [self failHiddenPublisherDownload:@"The publisher returned a page instead of a supported PDF, DOC, or DOCX file."];
        return;
    }
    NSString *acceptedPath = path;
    if (!isPDF && validSupplementDocument) {
        NSString *wantedExtension = isDOCX ? @"docx" : @"doc";
        if (![extension isEqualToString:wantedExtension]) {
            acceptedPath = [[path stringByDeletingPathExtension] stringByAppendingPathExtension:wantedExtension];
            [[NSFileManager defaultManager] removeItemAtPath:acceptedPath error:nil];
            NSError *moveError = nil;
            if (![[NSFileManager defaultManager] moveItemAtPath:path toPath:acceptedPath error:&moveError]) {
                [self failHiddenPublisherDownload:moveError.localizedDescription ?: @"Could not prepare the Word supplement."];
                return;
            }
            self.hiddenPublisherTemporaryPath = acceptedPath;
        }
    }
    [self attachHiddenPublisherPDFAtPath:acceptedPath];
}

- (void)download:(WKDownload *)download didFailWithError:(NSError *)error resumeData:(NSData *)resumeData {
    if (download != self.hiddenPublisherDownload) return;
    NSString *message = error.localizedDescription.length > 0 ? error.localizedDescription : @"Published PDF download failed.";
    [self failHiddenPublisherDownload:message];
}

- (BOOL)isExpectedHiddenPublisherDownloadTransitionError:(NSError *)error {
    if (!self.hiddenPublisherDownloadTransitionPending || !error) return NO;
    NSString *domain = error.domain ?: @"";
    // WebKit still reports legacy policy-change code 102 when a navigation is
    // deliberately converted into a WKDownload, although the named constant
    // itself has been deprecated since macOS 10.14.
    const NSInteger frameLoadInterruptedByPolicyChange = 102;
    return error.code == frameLoadInterruptedByPolicyChange
        && ([domain isEqualToString:@"WebKitErrorDomain"] || [domain isEqualToString:WKErrorDomain]);
}

- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    if (webView != self.hiddenPublisherWebView || self.hiddenPublisherDownload) return;
    if ([self isExpectedHiddenPublisherDownloadTransitionError:error]) return;
    [self failHiddenPublisherDownload:error.localizedDescription ?: @"The publisher page could not be loaded."];
}

- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    if (webView != self.hiddenPublisherWebView || self.hiddenPublisherDownload) return;
    if ([self isExpectedHiddenPublisherDownloadTransitionError:error]) return;
    [self failHiddenPublisherDownload:error.localizedDescription ?: @"The publisher page could not be loaded."];
}

- (void)attachHiddenPublisherPDFAtPath:(NSString *)path {
    NSMutableDictionary *payload = [NSMutableDictionary dictionaryWithDictionary:self.hiddenPublisherContext ?: @{}];
    BOOL wasScienceSupplementDiscovery = [self isHiddenPublisherSupplementDiscovery];
    BOOL wasGenericSupplementDiscovery = [self isHiddenGenericSupplementDiscovery];
    BOOL wasSupplementDiscovery = wasScienceSupplementDiscovery || wasGenericSupplementDiscovery;
    if (wasScienceSupplementDiscovery) {
        payload[@"publisher_download_kind"] = @"aaas-supplement-pdf";
    } else if (wasGenericSupplementDiscovery) {
        payload[@"publisher_download_kind"] = @"publisher-supplement-file";
    }
    payload[@"source_path"] = path;
    payload[@"preserve_filename"] = @NO;
    NSError *jsonError = nil;
    NSData *body = [NSJSONSerialization dataWithJSONObject:payload options:0 error:&jsonError];
    if (!body || jsonError) {
        [self failHiddenPublisherDownload:@"Could not prepare the downloaded PDF for the Library."];
        return;
    }
    NSURL *endpoint = [self.url URLByAppendingPathComponent:@"api/manual-pdf-path"];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:endpoint];
    request.HTTPMethod = @"POST";
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    request.HTTPBody = body;
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSDictionary *responsePayload = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        NSInteger statusCode = [response isKindOfClass:[NSHTTPURLResponse class]]
            ? ((NSHTTPURLResponse *)response).statusCode
            : 0;
        dispatch_async(dispatch_get_main_queue(), ^{
            if (error || statusCode < 200 || statusCode >= 300 || ![responsePayload isKindOfClass:[NSDictionary class]]) {
                NSString *serverError = [responsePayload[@"error"] isKindOfClass:[NSString class]] ? responsePayload[@"error"] : nil;
                [self failHiddenPublisherDownload:serverError ?: error.localizedDescription ?: @"Could not add the published PDF to Gewu Insight."];
                return;
            }
            NSString *token = self.hiddenPublisherToken ?: @"";
            NSMutableDictionary *resultPayload = [NSMutableDictionary dictionaryWithDictionary:responsePayload];
            if (wasSupplementDiscovery) resultPayload[@"supplement_attached"] = @YES;
            [self notifyHiddenPublisherDownloadToken:token success:YES data:resultPayload error:nil];
            [self clearHiddenPublisherDownload];
        });
    }] resume];
}

- (void)failHiddenPublisherDownload:(NSString *)message {
    NSString *token = self.hiddenPublisherToken ?: @"";
    [self notifyHiddenPublisherDownloadToken:token success:NO data:nil error:message ?: @"Published PDF download failed."];
    [self clearHiddenPublisherDownload];
}

- (void)notifyHiddenPublisherDownloadToken:(NSString *)token
                                   success:(BOOL)success
                                      data:(NSDictionary *)data
                                     error:(NSString *)error {
    NSMutableDictionary *payload = [NSMutableDictionary dictionary];
    payload[@"token"] = token ?: @"";
    payload[@"success"] = @(success);
    if (data) payload[@"data"] = data;
    if (error.length > 0) payload[@"error"] = error;
    NSData *jsonData = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
    NSString *json = jsonData ? [[NSString alloc] initWithData:jsonData encoding:NSUTF8StringEncoding] : @"{}";
    NSString *script = [NSString stringWithFormat:@"window.handleNativePublisherDownloadResult && window.handleNativePublisherDownloadResult(%@)", json];
    [self.webView evaluateJavaScript:script completionHandler:nil];
}

- (void)clearHiddenPublisherDownload {
    [self.hiddenPublisherTimeout invalidate];
    self.hiddenPublisherTimeout = nil;
    [self.hiddenPublisherWebView stopLoading];
    self.hiddenPublisherWebView.navigationDelegate = nil;
    self.hiddenPublisherWebView = nil;
    self.hiddenPublisherDownload.delegate = nil;
    self.hiddenPublisherDownload = nil;
    if (self.hiddenPublisherTemporaryPath.length > 0) {
        [[NSFileManager defaultManager] removeItemAtPath:self.hiddenPublisherTemporaryPath error:nil];
    }
    self.hiddenPublisherTemporaryPath = nil;
    self.hiddenPublisherContext = nil;
    self.hiddenPublisherToken = nil;
    self.hiddenPublisherDownloadTransitionPending = NO;
    self.hiddenPublisherDiscoveryVisitedURLs = nil;
    self.hiddenPublisherDiscoveryDepth = 0;
    self.hiddenPublisherDiscoveryPageRetryCount = 0;
}

- (NSRect)defaultRestoreFrameForScreen:(NSScreen *)screen {
    NSRect visibleFrame = screen.visibleFrame;
    CGFloat width = MIN(NSWidth(visibleFrame) - 40.0, MAX(980.0, floor(NSWidth(visibleFrame) * 0.82)));
    CGFloat height = MIN(NSHeight(visibleFrame) - 40.0, MAX(680.0, floor(NSHeight(visibleFrame) * 0.84)));
    width = MAX(640.0, width);
    height = MAX(480.0, height);
    return NSMakeRect(
        round(NSMidX(visibleFrame) - width / 2.0),
        round(NSMidY(visibleFrame) - height / 2.0),
        width,
        height
    );
}

- (void)toggleMainWindowFill {
    NSScreen *screen = self.window.screen ?: [NSScreen mainScreen];
    if (!screen) return;
    NSRect visibleFrame = screen.visibleFrame;
    NSRect currentFrame = self.window.frame;
    BOOL fillsVisibleFrame = fabs(NSMinX(currentFrame) - NSMinX(visibleFrame)) <= 2.0
        && fabs(NSMinY(currentFrame) - NSMinY(visibleFrame)) <= 2.0
        && fabs(NSWidth(currentFrame) - NSWidth(visibleFrame)) <= 2.0
        && fabs(NSHeight(currentFrame) - NSHeight(visibleFrame)) <= 2.0;
    NSRect targetFrame;
    if (fillsVisibleFrame) {
        targetFrame = self.windowRestoreFrame;
        NSRect intersection = NSIntersectionRect(targetFrame, visibleFrame);
        BOOL restoreIsUsable = !NSIsEmptyRect(targetFrame)
            && NSWidth(intersection) >= MIN(240.0, NSWidth(targetFrame))
            && NSHeight(intersection) >= MIN(160.0, NSHeight(targetFrame));
        BOOL restoreIsAlsoFilled = fabs(NSMinX(targetFrame) - NSMinX(visibleFrame)) <= 2.0
            && fabs(NSMinY(targetFrame) - NSMinY(visibleFrame)) <= 2.0
            && fabs(NSWidth(targetFrame) - NSWidth(visibleFrame)) <= 2.0
            && fabs(NSHeight(targetFrame) - NSHeight(visibleFrame)) <= 2.0;
        if (!restoreIsUsable || restoreIsAlsoFilled) {
            targetFrame = [self defaultRestoreFrameForScreen:screen];
        }
        targetFrame.size.width = MIN(NSWidth(targetFrame), NSWidth(visibleFrame));
        targetFrame.size.height = MIN(NSHeight(targetFrame), NSHeight(visibleFrame));
        targetFrame.origin.x = MIN(MAX(NSMinX(targetFrame), NSMinX(visibleFrame)), NSMaxX(visibleFrame) - NSWidth(targetFrame));
        targetFrame.origin.y = MIN(MAX(NSMinY(targetFrame), NSMinY(visibleFrame)), NSMaxY(visibleFrame) - NSHeight(targetFrame));
    } else {
        self.windowRestoreFrame = currentFrame;
        targetFrame = visibleFrame;
    }
    [self.window setFrame:targetFrame display:YES animate:YES];
}

- (void)positionTrafficLightButtons {
    CGFloat tabBarHeight = 38.0;
    NSArray *windowButtons = @[
        [self.window standardWindowButton:NSWindowCloseButton],
        [self.window standardWindowButton:NSWindowMiniaturizeButton],
        [self.window standardWindowButton:NSWindowZoomButton]
    ];
    for (NSButton *button in windowButtons) {
        if (!button) continue;
        NSView *container = button.superview;
        NSRect frame = button.frame;
        CGFloat containerHeight = container ? NSHeight(container.bounds) : tabBarHeight;
        frame.origin.y = round(containerHeight - tabBarHeight + ((tabBarHeight - NSHeight(frame)) / 2.0));
        button.frame = frame;
    }
}

- (void)installMainMenu {
    NSMenu *mainMenu = [[NSMenu alloc] initWithTitle:@""];

    NSMenuItem *appMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:appMenuItem];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"Gewu Insight"];
    NSString *quitTitle = [NSString stringWithFormat:@"Quit %@", @"Gewu Insight"];
    [appMenu addItemWithTitle:quitTitle action:@selector(terminate:) keyEquivalent:@"q"];
    appMenuItem.submenu = appMenu;

    NSMenuItem *fileMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:fileMenuItem];
    NSMenu *fileMenu = [[NSMenu alloc] initWithTitle:@"File"];
    NSMenuItem *closeWindowItem = [fileMenu addItemWithTitle:@"Close Window" action:@selector(closeActiveWindow:) keyEquivalent:@"w"];
    closeWindowItem.target = self;
    closeWindowItem.keyEquivalentModifierMask = NSEventModifierFlagCommand;
    fileMenuItem.submenu = fileMenu;

    NSMenuItem *editMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:editMenuItem];
    NSMenu *editMenu = [[NSMenu alloc] initWithTitle:@"Edit"];
    [editMenu addItemWithTitle:@"Undo" action:@selector(undo:) keyEquivalent:@"z"];
    [editMenu addItemWithTitle:@"Redo" action:@selector(redo:) keyEquivalent:@"Z"];
    [editMenu addItem:[NSMenuItem separatorItem]];
    [editMenu addItemWithTitle:@"Cut" action:@selector(cut:) keyEquivalent:@"x"];
    [editMenu addItemWithTitle:@"Copy" action:@selector(copy:) keyEquivalent:@"c"];
    [editMenu addItemWithTitle:@"Paste" action:@selector(paste:) keyEquivalent:@"v"];
    [editMenu addItemWithTitle:@"Select All" action:@selector(selectAll:) keyEquivalent:@"a"];
    editMenuItem.submenu = editMenu;

    NSMenuItem *viewMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:viewMenuItem];
    NSMenu *viewMenu = [[NSMenu alloc] initWithTitle:@"View"];
    self.listViewItem = [viewMenu addItemWithTitle:@"List View" action:@selector(useListLibraryView:) keyEquivalent:@""];
    self.listViewItem.target = self;
    self.listViewItem.state = NSControlStateValueOn;
    self.tableViewItem = [viewMenu addItemWithTitle:@"Table View" action:@selector(useTableLibraryView:) keyEquivalent:@""];
    self.tableViewItem.target = self;
    [viewMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *toggleViewItem = [viewMenu addItemWithTitle:@"Toggle List/Table" action:@selector(toggleLibraryContentView:) keyEquivalent:@"v"];
    toggleViewItem.target = self;
    toggleViewItem.keyEquivalentModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagShift;
    viewMenuItem.submenu = viewMenu;

    NSMenuItem *loaderMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:loaderMenuItem];
    NSMenu *loaderMenu = [[NSMenu alloc] initWithTitle:@"Loader"];
    NSMenuItem *openLoaderItem = [loaderMenu addItemWithTitle:@"Open Loader" action:@selector(openLibraryLoader:) keyEquivalent:@"l"];
    openLoaderItem.target = self;
    NSMenuItem *refreshMetadataItem = [loaderMenu addItemWithTitle:@"Refresh All Metadata" action:@selector(openMetadataRefresh:) keyEquivalent:@""];
    refreshMetadataItem.target = self;
    NSMenuItem *findMissingIdentifiersItem = [loaderMenu addItemWithTitle:@"Find All Missing Identifiers" action:@selector(openIdentifierRecovery:) keyEquivalent:@""];
    findMissingIdentifiersItem.target = self;
    loaderMenuItem.submenu = loaderMenu;

    NSMenuItem *settingMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:settingMenuItem];
    NSMenu *settingMenu = [[NSMenu alloc] initWithTitle:@"Setting"];
    NSMenuItem *namingRuleMenuItem = [[NSMenuItem alloc] initWithTitle:@"Naming Rule" action:nil keyEquivalent:@""];
    NSMenu *namingRuleMenu = [[NSMenu alloc] initWithTitle:@"Naming Rule"];
    self.titleNamingItem = [namingRuleMenu addItemWithTitle:@"Use Title" action:@selector(useTitleNamingRule:) keyEquivalent:@""];
    self.titleNamingItem.target = self;
    self.citationNamingItem = [namingRuleMenu addItemWithTitle:@"Use Citation" action:@selector(useCitationNamingRule:) keyEquivalent:@""];
    self.citationNamingItem.target = self;
    self.citationNamingItem.state = NSControlStateValueOn;
    namingRuleMenuItem.submenu = namingRuleMenu;
    [settingMenu addItem:namingRuleMenuItem];
    NSMenuItem *pdfRenameSettingsItem = [settingMenu addItemWithTitle:@"PDF Rename Settings" action:@selector(openPdfRenameSettings:) keyEquivalent:@""];
    pdfRenameSettingsItem.target = self;
    NSMenuItem *citationSettingsItem = [settingMenu addItemWithTitle:@"Citation Settings" action:@selector(openCitationSettings:) keyEquivalent:@","];
    citationSettingsItem.target = self;
    [settingMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *clearCacheItem = [settingMenu addItemWithTitle:@"Clear Web Cache" action:@selector(clearWebCache:) keyEquivalent:@""];
    clearCacheItem.target = self;
    settingMenuItem.submenu = settingMenu;

    NSMenuItem *helpMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:helpMenuItem];
    NSMenu *helpMenu = [[NSMenu alloc] initWithTitle:@"Help"];
    NSMenuItem *userGuideItem = [helpMenu addItemWithTitle:@"User Guide" action:@selector(openUserGuide:) keyEquivalent:@"?"];
    userGuideItem.target = self;
    helpMenuItem.submenu = helpMenu;

    NSApp.mainMenu = mainMenu;
}

- (void)showLoadingPage {
    NSString *html = @"<!doctype html>"
        "<html><head><meta charset='utf-8'><style>"
        "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f3ee;color:#231f1a;font:15px -apple-system,BlinkMacSystemFont,sans-serif;}"
        ".card{display:flex;align-items:center;gap:16px;width:430px;box-sizing:border-box;padding:28px 32px;border:1px solid rgba(35,31,26,.12);border-radius:18px;background:rgba(255,255,255,.72);box-shadow:0 18px 50px rgba(35,31,26,.08);}"
        ".icon{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(135deg,#0f6b6e,#d7b46a);color:white;font-size:22px;font-weight:800;box-shadow:0 10px 22px rgba(15,107,110,.22);}"
        ".copy{min-width:0;flex:1;}.message{min-height:22px;}"
        "strong{display:block;margin-bottom:8px;font-size:18px;}"
        "</style></head><body><div class='card'><div class='icon'>G</div><div class='copy'><strong>Starting Gewu Insight</strong><div class='message'>Preparing the local reading workspace.</div></div></div></body></html>";
    [self.webView loadHTMLString:html baseURL:nil];
}

- (void)ensureServerThenLoad {
    [self checkServerWithCompletion:^(BOOL available) {
        if (available) {
            [self loadApp];
        } else {
            [self startServerIfNeeded];
            [self pollUntilReady];
        }
    }];
}

- (void)startServerIfNeeded {
    if (self.ownedServerTask) {
        return;
    }

    NSURL *helperURL = [[[[[NSBundle mainBundle] bundleURL]
        URLByAppendingPathComponent:@"Contents"]
        URLByAppendingPathComponent:@"MacOS"]
        URLByAppendingPathComponent:@"Gewu Insight Server"];

    NSTask *task = [[NSTask alloc] init];
    task.executableURL = helperURL;
    __weak typeof(self) weakSelf = self;
    task.terminationHandler = ^(NSTask *terminatedTask) {
        dispatch_async(dispatch_get_main_queue(), ^{
            PaperMonitorDelegate *strongSelf = weakSelf;
            if (!strongSelf) {
                return;
            }
            if (terminatedTask.terminationStatus != 0) {
                [strongSelf presentStartupFailure:nil];
            }
        });
    };

    NSError *error = nil;
    if (![task launchAndReturnError:&error]) {
        [self presentStartupFailure:[NSString stringWithFormat:@"Could not launch the local server helper: %@", error.localizedDescription]];
        return;
    }
    self.ownedServerTask = task;
}

- (void)pollUntilReady {
    self.attempts += 1;
    [self checkServerWithCompletion:^(BOOL available) {
        if (available) {
            [self loadApp];
            return;
        }
        if (self.attempts >= 80) {
            [self presentStartupFailure:nil];
            return;
        }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.25 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            [self pollUntilReady];
        });
    }];
}

- (void)checkServerWithCompletion:(void (^)(BOOL available))completion {
    NSURL *healthURL = [self.url URLByAppendingPathComponent:@"api/health"];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:healthURL];
    request.timeoutInterval = 0.7;
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSHTTPURLResponse *httpResponse = [response isKindOfClass:[NSHTTPURLResponse class]] ? (NSHTTPURLResponse *)response : nil;
        BOOL available = (error == nil && httpResponse.statusCode == 200 && data.length > 0);
        dispatch_async(dispatch_get_main_queue(), ^{
            completion(available);
        });
    }] resume];
}

- (void)loadApp {
    [self.webView loadRequest:[NSURLRequest requestWithURL:self.url]];
    [self refreshLibraryNamingRuleMenu];
}

- (void)useTitleNamingRule:(id)sender {
    [self setLibraryNamingRule:@"title"];
}

- (void)useCitationNamingRule:(id)sender {
    [self setLibraryNamingRule:@"citation"];
}

- (void)openCitationSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openCitationSettings && window.openCitationSettings()" completionHandler:nil];
}

- (void)openPdfRenameSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openPdfRenameSettings && window.openPdfRenameSettings()" completionHandler:nil];
}

- (void)openLibraryLoader:(id)sender {
    [self showLibraryLoaderWindow];
}

- (void)openMetadataRefresh:(id)sender {
    [self.webView evaluateJavaScript:@"window.openMetadataRefreshWindow && window.openMetadataRefreshWindow()" completionHandler:nil];
}

- (void)openIdentifierRecovery:(id)sender {
    [self.webView evaluateJavaScript:@"window.openIdentifierRecoveryWindow && window.openIdentifierRecoveryWindow()" completionHandler:nil];
}

- (void)setNativeLibraryViewMenuState:(NSString *)viewMode {
    BOOL table = [viewMode isEqualToString:@"table"];
    self.listViewItem.state = table ? NSControlStateValueOff : NSControlStateValueOn;
    self.tableViewItem.state = table ? NSControlStateValueOn : NSControlStateValueOff;
}

- (void)useListLibraryView:(id)sender {
    [self setNativeLibraryViewMenuState:@"list"];
    [self.webView evaluateJavaScript:@"window.setLibraryContentView && window.setLibraryContentView('list')" completionHandler:nil];
}

- (void)useTableLibraryView:(id)sender {
    [self setNativeLibraryViewMenuState:@"table"];
    [self.webView evaluateJavaScript:@"window.setLibraryContentView && window.setLibraryContentView('table')" completionHandler:nil];
}

- (void)toggleLibraryContentView:(id)sender {
    [self.webView evaluateJavaScript:@"window.toggleLibraryContentView && window.toggleLibraryContentView()" completionHandler:^(id result, NSError *error) {
        if ([result isKindOfClass:[NSString class]]) {
            [self setNativeLibraryViewMenuState:(NSString *)result];
        }
    }];
}

- (NSURL *)userGuideURL {
    return [self.url URLByAppendingPathComponent:@"user-guide"];
}

- (void)openUserGuide:(id)sender {
    [self showUserGuideWindow];
}

- (void)showUserGuideWindow {
    if (!self.userGuideWindow) {
        WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
        self.userGuideWebView = [[WKWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
        self.userGuideWebView.UIDelegate = self;

        self.userGuideWindow = [[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, 980, 760)
                      styleMask:(NSWindowStyleMaskTitled |
                                 NSWindowStyleMaskClosable |
                                 NSWindowStyleMaskMiniaturizable |
                                 NSWindowStyleMaskResizable)
                        backing:NSBackingStoreBuffered
                          defer:NO];
        self.userGuideWindow.title = @"Gewu Insight User Guide";
        self.userGuideWindow.delegate = self;
        self.userGuideWindow.minSize = NSMakeSize(760, 560);
        self.userGuideWindow.contentView = self.userGuideWebView;
        [self.userGuideWindow center];
    }
    [self.userGuideWebView loadRequest:[NSURLRequest requestWithURL:[self userGuideURL]]];
    [self.userGuideWindow makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (NSURL *)loaderURL {
    NSURLComponents *components = [NSURLComponents componentsWithURL:self.url resolvingAgainstBaseURL:NO];
    components.queryItems = @[[[NSURLQueryItem alloc] initWithName:@"standalone" value:@"loader"]];
    return components.URL ?: self.url;
}

- (void)showLibraryLoaderWindow {
    if (!self.loaderWindow) {
        WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
        WKUserContentController *userContentController = [[WKUserContentController alloc] init];
        [userContentController addScriptMessageHandler:self name:@"libraryLoaderWindow"];
        configuration.userContentController = userContentController;

        self.loaderWebView = [[WKWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
        self.loaderWebView.UIDelegate = self;

        self.loaderWindow = [[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, 1220, 780)
                      styleMask:(NSWindowStyleMaskTitled |
                                 NSWindowStyleMaskClosable |
                                 NSWindowStyleMaskMiniaturizable |
                                 NSWindowStyleMaskResizable)
                        backing:NSBackingStoreBuffered
                          defer:NO];
        self.loaderWindow.title = @"Folder Loader";
        self.loaderWindow.delegate = self;
        self.loaderWindow.minSize = NSMakeSize(940, 620);
        self.loaderWindow.contentView = self.loaderWebView;
        [self.loaderWindow center];
    }
    [self.loaderWebView loadRequest:[NSURLRequest requestWithURL:[self loaderURL]]];
    [self.loaderWindow makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (void)updateLibraryNamingRuleMenu:(NSString *)rule {
    BOOL useTitle = [rule isEqualToString:@"title"];
    self.titleNamingItem.state = useTitle ? NSControlStateValueOn : NSControlStateValueOff;
    self.citationNamingItem.state = useTitle ? NSControlStateValueOff : NSControlStateValueOn;
}

- (void)setLibraryNamingRule:(NSString *)rule {
    [self updateLibraryNamingRuleMenu:rule];
    NSURL *endpoint = [self.url URLByAppendingPathComponent:@"api/settings/library-naming"];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:endpoint];
    request.HTTPMethod = @"POST";
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    request.HTTPBody = [[NSString stringWithFormat:@"{\"rule\":\"%@\"}", rule] dataUsingEncoding:NSUTF8StringEncoding];
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        if (error) {
            return;
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            [self updateLibraryNamingRuleMenu:rule];
        });
    }] resume];
}

- (void)refreshLibraryNamingRuleMenu {
    NSURL *endpoint = [self.url URLByAppendingPathComponent:@"api/settings/library-naming"];
    NSURLRequest *request = [NSURLRequest requestWithURL:endpoint];
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        if (error || !data) {
            return;
        }
        NSDictionary *payload = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        NSString *rule = [payload isKindOfClass:[NSDictionary class]] ? payload[@"rule"] : nil;
        if (![rule isKindOfClass:[NSString class]]) {
            return;
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            [self updateLibraryNamingRuleMenu:rule];
        });
    }] resume];
}

- (void)clearWebCache:(id)sender {
    NSURL *endpoint = [self.url URLByAppendingPathComponent:@"api/cache/clear-web"];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:endpoint];
    request.HTTPMethod = @"POST";
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    request.HTTPBody = [@"{}" dataUsingEncoding:NSUTF8StringEncoding];
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSString *message = @"Could not clear the WebKit cache.";
        if (!error && data) {
            NSDictionary *payload = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
            if ([payload isKindOfClass:[NSDictionary class]]) {
                long long removed = [payload[@"removed_bytes"] longLongValue];
                NSInteger files = [payload[@"removed_files"] integerValue];
                message = [NSString stringWithFormat:@"Removed %@ from %ld cache files.", [self humanSize:removed], (long)files];
            }
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            NSAlert *alert = [[NSAlert alloc] init];
            alert.messageText = @"Web cache cleared";
            alert.informativeText = message;
            alert.alertStyle = error ? NSAlertStyleWarning : NSAlertStyleInformational;
            [alert addButtonWithTitle:@"OK"];
            [alert beginSheetModalForWindow:self.window completionHandler:nil];
        });
    }] resume];
}

- (NSString *)humanSize:(long long)bytes {
    double value = (double)bytes;
    NSArray<NSString *> *units = @[@"B", @"KB", @"MB", @"GB", @"TB"];
    NSInteger index = 0;
    while (value >= 1024.0 && index < (NSInteger)units.count - 1) {
        value /= 1024.0;
        index += 1;
    }
    if (index == 0) {
        return [NSString stringWithFormat:@"%lld %@", bytes, units[index]];
    }
    return [NSString stringWithFormat:@"%.1f %@", value, units[index]];
}

- (void)presentStartupFailure:(NSString *)message {
    NSString *projectDir = [[[NSBundle mainBundle] bundleURL].URLByDeletingLastPathComponent path];
    NSString *logPath = [projectDir stringByAppendingPathComponent:@"logs/paper_monitor_launcher.log"];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Gewu Insight could not start";
    alert.informativeText = message ?: [NSString stringWithFormat:@"The local UI server did not become ready. Check the launcher log for details:\n\n%@", logPath];
    alert.alertStyle = NSAlertStyleWarning;
    [alert addButtonWithTitle:@"OK"];
    [alert runModal];
}

- (WKWebView *)webView:(WKWebView *)webView
createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration
   forNavigationAction:(WKNavigationAction *)navigationAction
        windowFeatures:(WKWindowFeatures *)windowFeatures {
    if (!navigationAction.targetFrame.isMainFrame && navigationAction.request.URL) {
        [[NSWorkspace sharedWorkspace] openURL:navigationAction.request.URL];
    }
    return nil;
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *application = [NSApplication sharedApplication];
        PaperMonitorDelegate *delegate = [[PaperMonitorDelegate alloc] init];
        application.delegate = delegate;
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        [application run];
    }
    return 0;
}
