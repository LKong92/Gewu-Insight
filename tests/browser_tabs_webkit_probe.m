// Real WebKit popup/configuration smoke test. Generated documents only;
// ephemeral website data, no network, credentials, user profile or database.
#import "GewuBrowserController.m"

static NSInteger checks;
static void check(BOOL ok, const char *name) {
    if (!ok) { fprintf(stderr, "FAIL: %s\n", name); exit(1); }
    checks++;
}
static BOOL spin(BOOL (^done)(void)) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:12];
    while (!done() && deadline.timeIntervalSinceNow > 0)
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
    return done();
}
static BOOL js(WKWebView *view, NSString *script) {
    __block BOOL finished = NO, result = NO;
    [view evaluateJavaScript:script completionHandler:^(id value, NSError *error) {
        result = !error && [value respondsToSelector:@selector(boolValue)] && [value boolValue]; finished = YES;
    }];
    return spin(^BOOL { return finished; }) && result;
}
@interface EphemeralTabs : GewuBrowserController
@property(strong) WKWebsiteDataStore *testStore;
@property NSInteger popups;
@property BOOL exactConfiguration;
@end
@implementation EphemeralTabs
- (GewuBrowserPage *)makePage {
    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    if (!self.testStore) self.testStore = WKWebsiteDataStore.nonPersistentDataStore;
    configuration.websiteDataStore = self.testStore;
    // Test-only gesture stand-in: allows a generated anchor.click() to exercise
    // the same real WebKit create-web-view callback without desktop automation.
    configuration.preferences.javaScriptCanOpenWindowsAutomatically = YES;
    return [super makePageWithConfiguration:configuration];
}
- (WKWebView *)webView:(WKWebView *)view createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration forNavigationAction:(WKNavigationAction *)action windowFeatures:(WKWindowFeatures *)features {
    self.popups++;
    WKWebView *result = [super webView:view createWebViewWithConfiguration:configuration forNavigationAction:action windowFeatures:features];
    self.exactConfiguration = result && result.configuration.websiteDataStore == configuration.websiteDataStore;
    return result;
}
- (void)webView:(WKWebView *)view decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decision {
    NSURL *url = action.request.URL;
    if (!action.targetFrame) {
        // Only the generated test link can request a popup.
        if ([url.absoluteString isEqual:@"https://example.org/target"]) [super webView:view decidePolicyForNavigationAction:action decisionHandler:decision];
        else decision(WKNavigationActionPolicyCancel);
        return;
    }
    if ([url.absoluteString isEqual:@"https://example.org/target"]) {
        decision(WKNavigationActionPolicyCancel);
        [view loadHTMLString:@"<!doctype html><title>Target fixture</title><h1>Target fixture</h1>" baseURL:[NSURL URLWithString:@"https://example.org/target-fixture"]];
        return;
    }
    // Only explicit loadHTMLString fixture documents, never live URLs.
    if ([@[@"about:blank", @"https://example.org/start-fixture", @"https://example.org/target-fixture"] containsObject:url.absoluteString]) decision(WKNavigationActionPolicyAllow);
    else decision(WKNavigationActionPolicyCancel);
}
@end

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(40,40,800,500) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        window.title = @"Gewu synthetic tab verification";
        window.releasedWhenClosed = NO;
        WKWebViewConfiguration *local = [WKWebViewConfiguration new];
        local.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
        WKWebView *workspace = [[WKWebView alloc] initWithFrame:window.contentView.bounds configuration:local];
        [window.contentView addSubview:workspace];
        EphemeralTabs *browser = [[EphemeralTabs alloc] initWithWorkspace:workspace];
        [browser.favicons invalidate]; browser.favicons = nil;
        browser.active = YES; browser.visible = YES;
        [browser ensureWebView];
        browser.contentPage = [browser makePage];
        [browser activatePage:browser.contentPage];
        browser.webView.frame = workspace.frame;
        [window orderBack:nil];
        // Dispatch actual AppKit key events through the installed local monitor,
        // not just the controller method. Synthetic keys target this test window
        // only; no global input events or real user credentials are involved.
        __block NSInteger returns = 0;
        browser.onEvent = ^(NSDictionary *event) {
            if ([event[@"event"] isEqual:@"return-workspace"]) returns++;
        };
        for (NSString *characters in @[@"[", @"【", @"［"]) {
            for (WKWebView *focus in @[workspace, browser.webView]) {
                browser.canReturnToWorkspace = YES;
                [window makeFirstResponder:focus];
                NSInteger before = returns;
                NSEvent *key = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
                    modifierFlags:NSEventModifierFlagCommand timestamp:0 windowNumber:window.windowNumber
                    context:nil characters:characters charactersIgnoringModifiers:characters isARepeat:NO keyCode:33];
                [NSApp sendEvent:key];
                check(returns == before + 1, "AppKit monitor dispatches English/localized source-return key");
                check(window.firstResponder == workspace && !browser.canReturnToWorkspace,
                    "dispatched return restores workspace responder and consumes origin");
            }
        }
        browser.onEvent = nil;
        WKWebView *start = browser.webView;
        GewuBrowserTab *first = browser.selectedTab;
        [start loadHTMLString:@"<!doctype html><title>Start fixture</title><input id=draft value=synthetic-draft><a id=open target=_blank href=https://example.org/target>Open test tab</a>" baseURL:[NSURL URLWithString:@"https://example.org/start-fixture"]];
        check(spin(^BOOL { return [start.title isEqual:@"Start fixture"] && !start.loading; }), "start generated document");
        NSMenu *menu = [[NSMenu alloc] init];
        NSMenuItem *link = [[NSMenuItem alloc] initWithTitle:@"Open Link in New Window" action:nil keyEquivalent:@""];
        link.tag = WebMenuItemTagOpenLinkInNewWindow; [menu addItem:link];
        NSEvent *contextEvent = [NSEvent mouseEventWithType:NSEventTypeRightMouseDown location:NSMakePoint(30,30) modifierFlags:0 timestamp:0 windowNumber:window.windowNumber context:nil eventNumber:1 clickCount:1 pressure:1];
        [(GewuBrowserWebView *)start willOpenMenu:menu withEvent:contextEvent];
        check([link.title isEqual:@"Open Link in New Tab"], "native link menu describes a tab");
        check(js(start,@"window.fixtureIdentity = {}; document.getElementById('open').click(); true"), "generated link click");
        check(spin(^BOOL { return browser.tabs.count == 2 && [browser.webView.title isEqual:@"Target fixture"] && !browser.webView.loading; }), "real WebKit popup opens tracked destination");
        WKWebView *target = browser.webView;
        check(browser.popups == 1 && browser.exactConfiguration, "WebKit configuration accepted once");
        check(start.configuration.websiteDataStore == target.configuration.websiteDataStore && !target.configuration.websiteDataStore.persistent, "tabs share only ephemeral test profile");
        check(js(target,@"window.opener === null"), "target blank keeps WebKit's implicit noopener security");
        [browser selectTab:first];
        check(js(start,@"!!window.fixtureIdentity && document.getElementById('draft').value === 'synthetic-draft'"), "switch preserves original document and synthetic draft");
        [browser selectTab:browser.tabs.lastObject];
        [target evaluateJavaScript:@"window.close()" completionHandler:nil];
        check(spin(^BOOL { return browser.tabs.count == 1; }) && browser.selectedTab == first, "script closes only its own popup tab");
        check(js(start,@"document.getElementById('open').rel='opener'; document.getElementById('open').click(); true"), "explicit opener test link");
        check(spin(^BOOL { return browser.tabs.count == 2 && [browser.webView.title isEqual:@"Target fixture"] && !browser.webView.loading; }), "second native popup");
        check(js(browser.webView,@"window.opener !== null"), "explicit opener relationship remains WebKit-owned");
        [browser invalidate];
        check(browser.tabs.count == 0 && browser.webView == nil, "all surfaces disposed");
        [window close];
        printf("Real WebKit tabs: %ld checks passed; generated documents, zero network or credential requests.\n", (long)checks);
    }
}
