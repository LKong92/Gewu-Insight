#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface PaperMonitorDelegate : NSObject <NSApplicationDelegate, WKUIDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSTask *ownedServerTask;
@property(nonatomic) NSInteger attempts;
@property(nonatomic, strong) NSURL *url;
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
                             NSWindowStyleMaskResizable)
                    backing:NSBackingStoreBuffered
                      defer:NO];
    self.window.title = @"Paper Monitor";
    self.window.minSize = NSMakeSize(980, 680);
    [self.window center];
    self.window.contentView = self.webView;
    [self.window makeKeyAndOrderFront:nil];
}

- (void)installMainMenu {
    NSMenu *mainMenu = [[NSMenu alloc] initWithTitle:@""];

    NSMenuItem *appMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:appMenuItem];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"Paper Monitor"];
    NSString *quitTitle = [NSString stringWithFormat:@"Quit %@", @"Paper Monitor"];
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
        "</style></head><body><div class='card'><strong>Starting Paper Monitor…</strong>Preparing the local reading workspace.</div></body></html>";
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
        BOOL available = (error == nil && [body containsString:@"Paper Monitor"]);
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
    alert.messageText = @"Paper Monitor could not start";
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
