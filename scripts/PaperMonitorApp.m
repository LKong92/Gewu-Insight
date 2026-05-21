#import <Cocoa/Cocoa.h>
#import <PDFKit/PDFKit.h>
#import <WebKit/WebKit.h>

@interface PaperMonitorDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKScriptMessageHandler>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSTask *ownedServerTask;
@property(nonatomic) NSInteger attempts;
@property(nonatomic, strong) NSURL *url;
@property(nonatomic, strong) NSWindow *pdfWindow;
@property(nonatomic, strong) PDFView *pdfView;
@property(nonatomic, strong) PDFThumbnailView *pdfThumbnailView;
@property(nonatomic, strong) PDFDocument *pdfDocument;
@property(nonatomic, strong) NSURL *pdfURL;
@property(nonatomic, strong) NSColor *annotationColor;
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
    [self.webView.configuration.userContentController removeScriptMessageHandlerForName:@"openPdfAnnotator"];
    if (self.ownedServerTask && self.ownedServerTask.isRunning) {
        [self.ownedServerTask terminate];
    }
}

- (void)createWindow {
    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    WKUserContentController *userContentController = [[WKUserContentController alloc] init];
    [userContentController addScriptMessageHandler:self name:@"openPdfAnnotator"];
    configuration.userContentController = userContentController;
    self.webView = [[WKWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
    self.webView.UIDelegate = self;
    self.annotationColor = [NSColor colorWithCalibratedRed:1.0 green:0.94 blue:0.27 alpha:1.0];

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
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"Daico"];
    NSString *quitTitle = [NSString stringWithFormat:@"Quit %@", @"Daico"];
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

    NSApp.mainMenu = mainMenu;
}

- (void)showLoadingPage {
    NSString *html = @"<!doctype html>"
        "<html><head><meta charset='utf-8'><style>"
        "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f3ee;color:#231f1a;font:15px -apple-system,BlinkMacSystemFont,sans-serif;}"
        ".card{padding:28px 32px;border:1px solid rgba(35,31,26,.12);border-radius:18px;background:rgba(255,255,255,.72);box-shadow:0 18px 50px rgba(35,31,26,.08);}"
        "strong{display:block;margin-bottom:8px;font-size:18px;}"
        "</style></head><body><div class='card'><strong>Starting Daico...</strong>Preparing the local reading workspace.</div></body></html>";
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
}

- (void)presentStartupFailure:(NSString *)message {
    NSString *projectDir = [[[NSBundle mainBundle] bundleURL].URLByDeletingLastPathComponent path];
    NSString *logPath = [projectDir stringByAppendingPathComponent:@"logs/paper_monitor_launcher.log"];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Daico could not start";
    alert.informativeText = message ?: [NSString stringWithFormat:@"The local UI server did not become ready. Check the launcher log for details:\n\n%@", logPath];
    alert.alertStyle = NSAlertStyleWarning;
    [alert addButtonWithTitle:@"OK"];
    [alert runModal];
}

- (void)userContentController:(WKUserContentController *)userContentController didReceiveScriptMessage:(WKScriptMessage *)message {
    if (![message.name isEqualToString:@"openPdfAnnotator"]) return;
    id body = message.body;
    NSString *path = nil;
    BOOL toggle = NO;
    if ([body isKindOfClass:[NSString class]]) {
        path = (NSString *)body;
    } else if ([body isKindOfClass:[NSDictionary class]]) {
        NSDictionary *payload = (NSDictionary *)body;
        id rawPath = payload[@"path"];
        if ([rawPath isKindOfClass:[NSString class]]) path = rawPath;
        toggle = [payload[@"toggle"] boolValue];
    }
    if (path.length == 0) return;
    [self openPdfAnnotatorAtPath:path toggle:toggle];
}

- (void)openPdfAnnotatorAtPath:(NSString *)path toggle:(BOOL)toggle {
    NSURL *fileURL = [NSURL fileURLWithPath:path];
    if (toggle && self.pdfWindow.visible && [self.pdfURL.path isEqualToString:fileURL.path]) {
        [self.pdfWindow orderOut:nil];
        return;
    }
    PDFDocument *document = [[PDFDocument alloc] initWithURL:fileURL];
    if (!document) {
        [self showPdfAlert:@"Could not open this PDF for annotation."];
        return;
    }
    self.pdfURL = fileURL;
    self.pdfDocument = document;
    [self ensurePdfWindow];
    self.pdfView.document = document;
    self.pdfThumbnailView.PDFView = self.pdfView;
    self.pdfWindow.title = fileURL.lastPathComponent ?: @"PDF";
    [self.pdfWindow makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (void)ensurePdfWindow {
    if (self.pdfWindow) return;

    NSRect frame = NSMakeRect(120, 90, 1180, 820);
    self.pdfWindow = [[NSWindow alloc]
        initWithContentRect:frame
                  styleMask:(NSWindowStyleMaskTitled |
                             NSWindowStyleMaskClosable |
                             NSWindowStyleMaskMiniaturizable |
                             NSWindowStyleMaskResizable)
                    backing:NSBackingStoreBuffered
                      defer:NO];
    self.pdfWindow.minSize = NSMakeSize(860, 620);

    NSView *contentView = [[NSView alloc] initWithFrame:frame];
    contentView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;

    NSView *toolbar = [[NSView alloc] initWithFrame:NSMakeRect(0, frame.size.height - 42, frame.size.width, 42)];
    toolbar.autoresizingMask = NSViewWidthSizable | NSViewMinYMargin;
    toolbar.wantsLayer = YES;
    toolbar.layer.backgroundColor = [NSColor.windowBackgroundColor CGColor];

    NSButton *highlightButton = [self pdfToolButtonWithTitle:@"Highlight" action:@selector(highlightPdfSelection:)];
    highlightButton.frame = NSMakeRect(12, 8, 86, 26);
    [toolbar addSubview:highlightButton];

    NSButton *underlineButton = [self pdfToolButtonWithTitle:@"Underline" action:@selector(underlinePdfSelection:)];
    underlineButton.frame = NSMakeRect(104, 8, 86, 26);
    [toolbar addSubview:underlineButton];

    NSButton *textButton = [self pdfToolButtonWithTitle:@"Text Box" action:@selector(addPdfTextBox:)];
    textButton.frame = NSMakeRect(196, 8, 82, 26);
    [toolbar addSubview:textButton];

    NSArray<NSColor *> *colors = @[
        [NSColor colorWithCalibratedRed:1.0 green:0.94 blue:0.27 alpha:1.0],
        [NSColor colorWithCalibratedRed:0.65 green:0.95 blue:0.82 alpha:1.0],
        [NSColor colorWithCalibratedRed:0.75 green:0.86 blue:1.0 alpha:1.0],
        [NSColor colorWithCalibratedRed:0.98 green:0.81 blue:0.91 alpha:1.0]
    ];
    CGFloat colorX = 294;
    NSInteger colorTag = 0;
    for (NSColor *color in colors) {
        NSButton *button = [NSButton buttonWithTitle:@"" target:self action:@selector(selectPdfAnnotationColor:)];
        button.frame = NSMakeRect(colorX, 10, 22, 22);
        button.bezelStyle = NSBezelStyleTexturedRounded;
        button.wantsLayer = YES;
        button.layer.backgroundColor = [color CGColor];
        button.layer.cornerRadius = 5;
        button.tag = colorTag;
        [toolbar addSubview:button];
        colorX += 28;
        colorTag += 1;
    }

    NSButton *saveButton = [self pdfToolButtonWithTitle:@"Save" action:@selector(savePdfAnnotations:)];
    saveButton.frame = NSMakeRect(colorX + 10, 8, 64, 26);
    [toolbar addSubview:saveButton];

    NSSplitView *splitView = [[NSSplitView alloc] initWithFrame:NSMakeRect(0, 0, frame.size.width, frame.size.height - 42)];
    splitView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    splitView.dividerStyle = NSSplitViewDividerStyleThin;
    splitView.vertical = YES;

    NSScrollView *thumbScroll = [[NSScrollView alloc] initWithFrame:NSMakeRect(0, 0, 142, frame.size.height - 42)];
    thumbScroll.hasVerticalScroller = YES;
    self.pdfThumbnailView = [[PDFThumbnailView alloc] initWithFrame:thumbScroll.contentView.bounds];
    self.pdfThumbnailView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.pdfThumbnailView.thumbnailSize = NSMakeSize(92, 128);
    thumbScroll.documentView = self.pdfThumbnailView;

    self.pdfView = [[PDFView alloc] initWithFrame:NSMakeRect(0, 0, frame.size.width - 142, frame.size.height - 42)];
    self.pdfView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.pdfView.autoScales = YES;
    self.pdfView.displayMode = kPDFDisplaySinglePageContinuous;
    self.pdfView.displayDirection = kPDFDisplayDirectionVertical;

    [splitView addArrangedSubview:thumbScroll];
    [splitView addArrangedSubview:self.pdfView];
    [splitView setPosition:142 ofDividerAtIndex:0];

    [contentView addSubview:splitView];
    [contentView addSubview:toolbar];
    self.pdfWindow.contentView = contentView;
}

- (NSButton *)pdfToolButtonWithTitle:(NSString *)title action:(SEL)action {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:action];
    button.bezelStyle = NSBezelStyleRounded;
    button.font = [NSFont systemFontOfSize:12 weight:NSFontWeightSemibold];
    return button;
}

- (void)selectPdfAnnotationColor:(NSButton *)sender {
    NSArray<NSColor *> *colors = @[
        [NSColor colorWithCalibratedRed:1.0 green:0.94 blue:0.27 alpha:1.0],
        [NSColor colorWithCalibratedRed:0.65 green:0.95 blue:0.82 alpha:1.0],
        [NSColor colorWithCalibratedRed:0.75 green:0.86 blue:1.0 alpha:1.0],
        [NSColor colorWithCalibratedRed:0.98 green:0.81 blue:0.91 alpha:1.0]
    ];
    NSInteger index = MAX(0, MIN(sender.tag, (NSInteger)colors.count - 1));
    self.annotationColor = colors[index];
}

- (void)highlightPdfSelection:(id)sender {
    [self annotateCurrentSelectionWithSubtype:PDFAnnotationSubtypeHighlight];
}

- (void)underlinePdfSelection:(id)sender {
    [self annotateCurrentSelectionWithSubtype:PDFAnnotationSubtypeUnderline];
}

- (void)annotateCurrentSelectionWithSubtype:(PDFAnnotationSubtype)subtype {
    PDFSelection *selection = self.pdfView.currentSelection;
    if (!selection || selection.string.length == 0) {
        [self showPdfAlert:@"Select text in the PDF first."];
        return;
    }
    NSArray<PDFSelection *> *lineSelections = selection.selectionsByLine ?: @[selection];
    NSUInteger added = 0;
    for (PDFSelection *lineSelection in lineSelections) {
        for (PDFPage *page in lineSelection.pages) {
            NSRect bounds = [lineSelection boundsForPage:page];
            if (NSIsEmptyRect(bounds)) continue;
            PDFAnnotation *annotation = [[PDFAnnotation alloc] initWithBounds:bounds forType:subtype withProperties:nil];
            annotation.color = self.annotationColor ?: [NSColor yellowColor];
            [page addAnnotation:annotation];
            added += 1;
        }
    }
    if (added > 0) [self savePdfAnnotations:nil];
}

- (void)addPdfTextBox:(id)sender {
    if (!self.pdfDocument || !self.pdfView.currentPage) return;
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Text box";
    alert.informativeText = @"Enter text to place on the current page.";
    NSTextField *input = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 320, 26)];
    alert.accessoryView = input;
    [alert addButtonWithTitle:@"Add"];
    [alert addButtonWithTitle:@"Cancel"];
    if ([alert runModal] != NSAlertFirstButtonReturn || input.stringValue.length == 0) return;

    PDFPage *page = self.pdfView.currentPage;
    NSRect pageBounds = [page boundsForBox:kPDFDisplayBoxCropBox];
    NSRect textBounds = NSMakeRect(NSMidX(pageBounds) - 120, NSMidY(pageBounds) - 26, 240, 52);
    PDFAnnotation *annotation = [[PDFAnnotation alloc] initWithBounds:textBounds forType:PDFAnnotationSubtypeFreeText withProperties:nil];
    annotation.contents = input.stringValue;
    annotation.color = self.annotationColor ?: [NSColor systemBlueColor];
    annotation.font = [NSFont systemFontOfSize:13];
    annotation.fontColor = [NSColor blackColor];
    [page addAnnotation:annotation];
    [self savePdfAnnotations:nil];
}

- (void)savePdfAnnotations:(id)sender {
    if (!self.pdfDocument || !self.pdfURL) return;
    if (![self.pdfDocument writeToURL:self.pdfURL]) {
        [self showPdfAlert:@"Could not save annotations back to the PDF file."];
    }
}

- (void)showPdfAlert:(NSString *)message {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = message;
    alert.alertStyle = NSAlertStyleInformational;
    [alert addButtonWithTitle:@"OK"];
    [alert beginSheetModalForWindow:self.pdfWindow ?: self.window completionHandler:nil];
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
