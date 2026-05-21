#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface PaperMonitorDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate, WKUIDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSTask *ownedServerTask;
@property(nonatomic) NSInteger attempts;
@property(nonatomic, strong) NSURL *url;
@property(nonatomic, strong) NSMenuItem *titleNamingItem;
@property(nonatomic, strong) NSMenuItem *citationNamingItem;
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
    self.webView = [[WKWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
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
    [settingMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *clearCacheItem = [settingMenu addItemWithTitle:@"Clear Web Cache" action:@selector(clearWebCache:) keyEquivalent:@""];
    clearCacheItem.target = self;
    settingMenuItem.submenu = settingMenu;

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
    [self refreshLibraryNamingRuleMenu];
}

- (void)useTitleNamingRule:(id)sender {
    [self setLibraryNamingRule:@"title"];
}

- (void)useCitationNamingRule:(id)sender {
    [self setLibraryNamingRule:@"citation"];
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
    alert.messageText = @"Daico could not start";
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
