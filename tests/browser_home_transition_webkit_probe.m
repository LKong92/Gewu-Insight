// Real WebKit lifecycle, but only generated HTML and an ephemeral profile.
// loadRequest is mapped to a test-only scheme handler; no live URL is fetched.
#import "GewuBrowserController.m"

static NSInteger checks;
static void check(BOOL ok, const char *label) {
    if (!ok) { fprintf(stderr, "FAIL: %s\n", label); exit(1); } checks++;
}
static BOOL spin(BOOL (^done)(void)) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:12];
    while (!done() && deadline.timeIntervalSinceNow > 0)
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
    return done();
}
static NSString *fixtureHTML(NSURL *url) {
    BOOL home = GewuBrowserGoogleHome(url);
    NSString *title = home ? @"Google fixture" : [url.path isEqual:@"/old"] ? @"Old article fixture" : @"New result fixture";
    return [NSString stringWithFormat:@"<!doctype html><title>%@</title><body style='background:%@'><h1>%@</h1><form action='https://example.org/new'><input name=q value=synthetic><button>Search</button></form></body>", title, home ? @"white" : [url.path isEqual:@"/old"] ? @"red" : @"#cfe8ff", title];
}
@interface FixtureDocuments : NSObject <WKURLSchemeHandler>
@end
@implementation FixtureDocuments
- (void)webView:(WKWebView *)view startURLSchemeTask:(id<WKURLSchemeTask>)task {
    NSData *body = [fixtureHTML(task.request.URL) dataUsingEncoding:NSUTF8StringEncoding];
    [task didReceiveResponse:[[NSURLResponse alloc] initWithURL:task.request.URL MIMEType:@"text/html" expectedContentLength:body.length textEncodingName:@"utf-8"]];
    [task didReceiveData:body]; [task didFinish];
}
- (void)webView:(WKWebView *)view stopURLSchemeTask:(id<WKURLSchemeTask>)task {}
@end
@interface FixtureHomeView : WKWebView
@property NSInteger requests;
@end
@implementation FixtureHomeView
- (WKNavigation *)loadRequest:(NSURLRequest *)request {
    self.requests++;
    if (GewuBrowserGoogleHome(request.URL)) return [self loadHTMLString:fixtureHTML(request.URL) baseURL:request.URL];
    NSURLComponents *url = [NSURLComponents componentsWithURL:request.URL resolvingAgainstBaseURL:NO];
    url.scheme = @"gewu-fixture";
    return [super loadRequest:[NSURLRequest requestWithURL:url.URL]];
}
@end
@interface TransitionBrowser : GewuBrowserController
@property(strong) WKWebsiteDataStore *testStore;
@property(copy) void (^heldDecision)(WKNavigationActionPolicy);
@property BOOL commitRevealed, provisionalKeptHome;
@end
@implementation TransitionBrowser
- (GewuBrowserPage *)makePage {
    if (!self.testStore) self.testStore = WKWebsiteDataStore.nonPersistentDataStore;
    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    configuration.websiteDataStore = self.testStore;
    [configuration setURLSchemeHandler:[FixtureDocuments new] forURLScheme:@"gewu-fixture"];
    GewuBrowserPage *page = [GewuBrowserPage new];
    page.view = [[FixtureHomeView alloc] initWithFrame:NSMakeRect(0,0,800,500) configuration:configuration];
    page.view.navigationDelegate = self; page.view.UIDelegate = self; page.view.hidden = YES;
    for (NSString *key in @[@"URL", @"title", @"loading", @"estimatedProgress", @"canGoBack", @"canGoForward"])
        [page.view addObserver:self forKeyPath:key options:NSKeyValueObservingOptionNew context:NULL];
    [self.workspace.superview addSubview:page.view positioned:NSWindowAbove relativeTo:self.workspace];
    return page;
}
- (void)webView:(WKWebView *)view decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decision {
    NSURL *url = action.request.URL;
    if ([url.scheme isEqual:@"gewu-fixture"] && [url.host isEqual:@"example.org"] && [@[@"/old", @"/new"] containsObject:url.path]) {
        if ([url.path isEqual:@"/new"] && self.selectedTab.contentPendingFromHome) self.heldDecision = decision;
        else decision(WKNavigationActionPolicyAllow);
        return;
    }
    if (!(GewuBrowserGoogleHome(url) || ([url.host isEqual:@"example.org"] && [@[@"/old", @"/new"] containsObject:url.path]))) {
        decision(WKNavigationActionPolicyCancel); return;
    }
    [super webView:view decidePolicyForNavigationAction:action decisionHandler:^(WKNavigationActionPolicy policy) {
        // Delay only the generated destination's commit, not the Home GET
        // interception. This deterministically exposes the original regression.
        if (view == self.contentPage.view && [url.path isEqual:@"/new"] && policy == WKNavigationActionPolicyAllow)
            self.heldDecision = decision;
        else decision(policy);
    }];
}
- (void)webView:(WKWebView *)view decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decision {
    if ([response.response.URL.scheme isEqual:@"gewu-fixture"]) decision(WKNavigationResponsePolicyAllow);
    else [super webView:view decidePolicyForNavigationResponse:response decisionHandler:decision];
}
- (void)webView:(WKWebView *)view didStartProvisionalNavigation:(WKNavigation *)navigation {
    [super webView:view didStartProvisionalNavigation:navigation];
    if (self.selectedTab.contentPendingFromHome)
        self.provisionalKeptHome = !self.homePage.view.hidden && view.hidden;
}
- (void)webView:(WKWebView *)view didCommitNavigation:(WKNavigation *)navigation {
    BOOL pending = self.selectedTab.contentPendingFromHome;
    [super webView:view didCommitNavigation:navigation];
    if (pending && [view.URL.path isEqual:@"/new"])
        self.commitRevealed = self.homePage.view.hidden && !view.hidden && !self.selectedTab.contentPendingFromHome;
}
@end

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(40,40,800,500) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        window.title = @"Gewu synthetic Home transition verification"; window.releasedWhenClosed = NO;
        WKWebViewConfiguration *config = [WKWebViewConfiguration new]; config.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
        WKWebView *workspace = [[WKWebView alloc] initWithFrame:window.contentView.bounds configuration:config];
        [window.contentView addSubview:workspace];
        TransitionBrowser *browser = [[TransitionBrowser alloc] initWithWorkspace:workspace];
        [browser.favicons invalidate]; browser.favicons = nil; browser.active = YES; browser.visible = YES;
        [window orderBack:nil];
        [browser handleCommand:@{@"action":@"home"}];
        check(spin(^BOOL { return browser.homePage.ready && !browser.webView.loading; }), "generated Home loaded");
        FixtureHomeView *home = (id)browser.webView;
        [browser handleCommand:@{@"action":@"navigate", @"url":@"https://example.org/old"}];
        check(spin(^BOOL { return [browser.webView.title isEqual:@"Old article fixture"] && browser.currentPage.ready && !browser.webView.loading; }), "old article loaded and visible");
        FixtureHomeView *content = (id)browser.webView;
        [browser handleCommand:@{@"action":@"home"}];
        check(!home.hidden && content.hidden && home.requests == 1, "Home reuses document without reload");
        __block BOOL chromeStayedHome = YES;
        browser.onEvent = ^(NSDictionary *event) {
            if ([event[@"event"] isEqual:@"state"] && browser.selectedTab.contentPendingFromHome)
                chromeStayedHome &= GewuBrowserGoogleHome([NSURL URLWithString:event[@"url"]]) && ![event[@"title"] isEqual:@"Old article fixture"];
        };
        // Generated non-credential form, owned entirely by this fixture.
        [home evaluateJavaScript:@"document.querySelector('form').requestSubmit()" completionHandler:nil];
        check(spin(^BOOL { return browser.heldDecision != nil; }), "Home search enters native pending destination");
        check(browser.webView == content && browser.selectedTab.contentPendingFromHome, "logical destination retains original content surface");
        check([content.title isEqual:@"Old article fixture"] && content.hidden && !home.hidden, "old document demonstrably exists but is not presented");
        [browser handleCommand:@{@"action":@"layout", @"active":@YES, @"visible":@YES, @"viewportWidth":@800, @"x":@0, @"y":@0, @"width":@800, @"height":@500}];
        check(content.hidden && !home.hidden && chromeStayedHome, "layout and loading events cannot unhide old content");
        void (^release)(WKNavigationActionPolicy) = browser.heldDecision; browser.heldDecision = nil;
        release(WKNavigationActionPolicyAllow);
        check(spin(^BOOL { return [content.title isEqual:@"New result fixture"] && browser.currentPage.ready && !content.loading; }), "new generated result completes");
        check(browser.provisionalKeptHome && browser.commitRevealed, "Home survives provisional start and switches only at destination commit");
        check(home.requests == 1 && content.requests == 2 && browser.tabs.count == 1, "no added Home reload, duplicate request or third surface");
        [browser handleCommand:@{@"action":@"back"}];
        check(browser.webView == home && !home.hidden && content.hidden, "Back restores Home");
        [browser handleCommand:@{@"action":@"forward"}];
        check(browser.webView == content && !content.hidden && [content.title isEqual:@"New result fixture"] && content.requests == 2, "Forward restores new result without replay");
        browser.onEvent = nil;
        [browser invalidate]; [window close];
        printf("Real WebKit Home transition: %ld checks passed; generated HTML, zero live network or credential requests.\n", (long)checks);
    }
}
