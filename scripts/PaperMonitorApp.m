#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface DaiqoWebView : WKWebView <NSDraggingDestination, NSDraggingSource>
@property(nonatomic, copy) NSString *nativeDragPath;
@property(nonatomic, copy) NSString *nativeDragName;
@end

@implementation DaiqoWebView

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

- (void)mouseUp:(NSEvent *)event {
    self.nativeDragPath = nil;
    self.nativeDragName = nil;
    [super mouseUp:event];
}

- (NSDragOperation)draggingSession:(NSDraggingSession *)session sourceOperationMaskForDraggingContext:(NSDraggingContext)context {
    return NSDragOperationCopy;
}

- (BOOL)ignoreModifierKeysForDraggingSession:(NSDraggingSession *)session {
    return YES;
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

@interface PaperMonitorDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKScriptMessageHandler>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSWindow *loaderWindow;
@property(nonatomic, strong) WKWebView *loaderWebView;
@property(nonatomic, strong) NSWindow *userGuideWindow;
@property(nonatomic, strong) WKWebView *userGuideWebView;
@property(nonatomic, strong) NSWindow *aboutDeepSurveyWindow;
@property(nonatomic, strong) WKWebView *aboutDeepSurveyWebView;
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
@end

@implementation PaperMonitorDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSDictionary *environment = [[NSProcessInfo processInfo] environment];
    NSString *host = environment[@"PAPER_MONITOR_HOST"] ?: @"127.0.0.1";
    NSString *port = environment[@"PAPER_MONITOR_PORT"] ?: @"8765";
    self.url = [NSURL URLWithString:[NSString stringWithFormat:@"http://%@:%@", host, port]];

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

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    if (!flag) {
        [self.window makeKeyAndOrderFront:nil];
        [NSApp activateIgnoringOtherApps:YES];
    }
    return YES;
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
    [userContentController addScriptMessageHandler:self name:@"libraryLoaderWindow"];
    configuration.userContentController = userContentController;
    self.webView = [[DaiqoWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
    self.webView.UIDelegate = self;

    self.window = [[NSWindow alloc]
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
        [self.window setFrame:screen.visibleFrame display:YES];
    } else {
        [self.window center];
    }
    self.window.contentView = self.webView;
    [self.window makeKeyAndOrderFront:nil];
    [self positionTrafficLightButtons];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self positionTrafficLightButtons];
    });
}

- (void)userContentController:(WKUserContentController *)userContentController
      didReceiveScriptMessage:(WKScriptMessage *)message {
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
        if (![message.body isKindOfClass:[NSDictionary class]] || ![self.webView isKindOfClass:[DaiqoWebView class]]) {
            return;
        }
        NSDictionary *payload = (NSDictionary *)message.body;
        NSString *path = [payload[@"path"] isKindOfClass:[NSString class]] ? payload[@"path"] : @"";
        NSString *name = [payload[@"name"] isKindOfClass:[NSString class]] ? payload[@"name"] : @"";
        DaiqoWebView *webView = (DaiqoWebView *)self.webView;
        webView.nativeDragPath = path;
        webView.nativeDragName = name;
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
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"Daiqo"];
    NSString *quitTitle = [NSString stringWithFormat:@"Quit %@", @"Daiqo"];
    [appMenu addItemWithTitle:quitTitle action:@selector(terminate:) keyEquivalent:@"q"];
    appMenuItem.submenu = appMenu;

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
    NSMenuItem *pdfRenameSettingsItem = [settingMenu addItemWithTitle:@"PDF Rename Settings..." action:@selector(openPdfRenameSettings:) keyEquivalent:@""];
    pdfRenameSettingsItem.target = self;
    NSMenuItem *citationSettingsItem = [settingMenu addItemWithTitle:@"Citation Settings..." action:@selector(openCitationSettings:) keyEquivalent:@","];
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
    NSMenuItem *aboutDeepSurveyItem = [helpMenu addItemWithTitle:@"About Deep Survey" action:@selector(openAboutDeepSurvey:) keyEquivalent:@""];
    aboutDeepSurveyItem.target = self;
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
        "</style></head><body><div class='card'><div class='icon'>D</div><div class='copy'><strong>Starting Daiqo</strong><div class='message'>Preparing the local reading workspace.</div></div></div></body></html>";
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
        URLByAppendingPathComponent:@"Paper Monitor Server"];

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
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:self.url];
    request.timeoutInterval = 0.7;
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSString *body = data ? [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] : @"";
        BOOL available = (error == nil && [body containsString:@"Journal Monitor"]);
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

- (NSURL *)aboutDeepSurveyURL {
    return [self.url URLByAppendingPathComponent:@"about-deep-survey"];
}

- (void)openUserGuide:(id)sender {
    [self showUserGuideWindow];
}

- (void)openAboutDeepSurvey:(id)sender {
    [self showAboutDeepSurveyWindow];
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
        self.userGuideWindow.title = @"User Guide";
        self.userGuideWindow.delegate = self;
        self.userGuideWindow.minSize = NSMakeSize(760, 560);
        self.userGuideWindow.contentView = self.userGuideWebView;
        [self.userGuideWindow center];
    }
    [self.userGuideWebView loadRequest:[NSURLRequest requestWithURL:[self userGuideURL]]];
    [self.userGuideWindow makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (void)showAboutDeepSurveyWindow {
    if (!self.aboutDeepSurveyWindow) {
        WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
        self.aboutDeepSurveyWebView = [[WKWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
        self.aboutDeepSurveyWebView.UIDelegate = self;

        self.aboutDeepSurveyWindow = [[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, 980, 760)
                      styleMask:(NSWindowStyleMaskTitled |
                                 NSWindowStyleMaskClosable |
                                 NSWindowStyleMaskMiniaturizable |
                                 NSWindowStyleMaskResizable)
                        backing:NSBackingStoreBuffered
                          defer:NO];
        self.aboutDeepSurveyWindow.title = @"About Deep Survey";
        self.aboutDeepSurveyWindow.delegate = self;
        self.aboutDeepSurveyWindow.minSize = NSMakeSize(760, 560);
        self.aboutDeepSurveyWindow.contentView = self.aboutDeepSurveyWebView;
        [self.aboutDeepSurveyWindow center];
    }
    [self.aboutDeepSurveyWebView loadRequest:[NSURLRequest requestWithURL:[self aboutDeepSurveyURL]]];
    [self.aboutDeepSurveyWindow makeKeyAndOrderFront:nil];
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
    alert.messageText = @"Daiqo could not start";
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
