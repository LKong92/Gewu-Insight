// Execute the real controller with inert surfaces. No WebKit process, website,
// profile, credential store, bookmark database, or system network is opened.
#import "GewuBrowserController.m"

static NSInteger checks;
static void check(BOOL ok, NSString *label) {
    if (!ok) { fprintf(stderr, "FAILED: %s\n", label.UTF8String); exit(1); }
    checks++;
}
@interface ReturnWindow : NSObject
@property(strong) id attachedSheet, firstResponder;
@end
@implementation ReturnWindow
- (BOOL)makeFirstResponder:(id)responder { self.firstResponder = responder; return YES; }
@end
@interface ReturnWorkspace : NSObject
@property(strong) ReturnWindow *window;
@end
@implementation ReturnWorkspace
@end
@interface ReturnKey : NSObject
@property NSEventType type;
@property NSEventModifierFlags modifierFlags;
@property(copy) NSString *charactersIgnoringModifiers;
@property unsigned short keyCode;
@property(strong) id window;
@property BOOL isARepeat;
@end
@implementation ReturnKey
@end
static void workspaceReturnChecks(void) {
    GewuBrowserController *browser = [GewuBrowserController alloc];
    ReturnWorkspace *workspace = [ReturnWorkspace new]; workspace.window = [ReturnWindow new];
    browser.workspace = (id)workspace; browser.active = YES; browser.visible = YES;
    ReturnKey *key = [ReturnKey new]; key.type = NSEventTypeKeyDown; key.window = workspace.window;
    key.modifierFlags = NSEventModifierFlagCommand; key.charactersIgnoringModifiers = @"[";
    __block NSInteger events = 0;
    browser.onEvent = ^(NSDictionary *event) { check([event[@"event"] isEqual:@"return-workspace"], @"only trusted return event"); events++; };
    check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"no origin leaves ordinary Browser key handling alone");
    browser.canReturnToWorkspace = YES;
    for (NSNumber *extra in @[@(NSEventModifierFlagShift), @(NSEventModifierFlagControl), @(NSEventModifierFlagOption)]) {
        key.modifierFlags = NSEventModifierFlagCommand | extra.unsignedLongLongValue;
        check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"modified bracket is not the return command");
    }
    key.modifierFlags = 0;
    check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"plain bracket still types");
    key.modifierFlags = NSEventModifierFlagCommand; key.charactersIgnoringModifiers = @"]";
    check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"right bracket is untouched");
    key.charactersIgnoringModifiers = @"["; key.window = [ReturnWindow new];
    check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"another window is excluded");
    key.window = workspace.window; workspace.window.attachedSheet = [NSObject new];
    check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"sheet cannot be dismissed by workspace return");
    workspace.window.attachedSheet = nil; browser.visible = NO;
    check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"covered Browser cannot return");
    browser.visible = YES; browser.active = NO;
    check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"inactive Browser cannot return");
    browser.active = YES; key.isARepeat = YES;
    check([browser handleWorkspaceReturnKeyEvent:(id)key] && events == 0, @"held key cannot repeat the return action");
    key.isARepeat = NO;
    for (id responder in @[[NSObject new], workspace]) {
        browser.canReturnToWorkspace = YES; workspace.window.firstResponder = responder;
        check([browser handleWorkspaceReturnKeyEvent:(id)key], @"return works from webpage or workspace focus");
        check(workspace.window.firstResponder == workspace && !browser.canReturnToWorkspace, @"native focus returns to workspace once");
    }
    check(events == 2 && !browser.webView, @"return neither loads nor creates nor closes any webpage");
    for (NSString *localized in @[@"【", @"［", @"「", @""]) {
        key.keyCode = 33; key.charactersIgnoringModifiers = localized;
        browser.canReturnToWorkspace = YES;
        check([browser handleWorkspaceReturnKeyEvent:(id)key], @"physical bracket works with localized input methods");
        check(!browser.canReturnToWorkspace, @"localized shortcut consumes the source exactly once");
    }
    browser.canReturnToWorkspace = YES; key.keyCode = 30; key.charactersIgnoringModifiers = @"】";
    check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"physical right bracket cannot return");
    key.keyCode = 33; key.modifierFlags |= NSEventModifierFlagShift;
    check(![browser handleWorkspaceReturnKeyEvent:(id)key], @"localized bracket retains modifier boundaries");
    browser.workspace = nil;
}
@interface FakeHistory : NSObject
@property(strong) id currentItem;
@property(copy) NSArray *backList;
@property(copy) NSArray *forwardList;
@end
@implementation FakeHistory
@end
@interface FakeSurface : NSObject
@property(strong) NSURL *URL;
@property(copy) NSString *title;
@property BOOL loading, hidden;
@property double estimatedProgress, pageZoom;
@property NSRect frame;
@property(strong) FakeHistory *backForwardList;
@property NSInteger loads, reloads, traversals;
@end
@implementation FakeSurface
- (instancetype)init {
    if ((self = [super init])) {
        _backForwardList = [[FakeHistory alloc] init];
        _backForwardList.backList = @[]; _backForwardList.forwardList = @[];
        _frame = NSMakeRect(0, 0, 900, 600); _pageZoom = 1;
    }
    return self;
}
- (id)loadRequest:(NSURLRequest *)request { self.loads++; self.loading = YES; self.URL = request.URL; return nil; }
- (void)stopLoading { self.loading = NO; }
- (BOOL)isLoading { return self.loading; }
- (id)reload { self.reloads++; return nil; }
- (id)goToBackForwardListItem:(id)item { self.traversals++; self.backForwardList.currentItem = item; return nil; }
- (void)evaluateJavaScript:(NSString *)script completionHandler:(id)handler {}
@end
@interface FakeFrame : NSObject
- (BOOL)isMainFrame;
@end
@implementation FakeFrame
- (BOOL)isMainFrame { return YES; }
@end
@interface FakeAction : NSObject
@property(strong) NSURLRequest *request;
@property(strong) FakeFrame *targetFrame;
@property BOOL shouldPerformDownload;
@property WKNavigationType navigationType;
@property NSEventModifierFlags modifierFlags;
@property NSInteger buttonNumber;
@end
@implementation FakeAction
@end
@interface FakeChildFrame : FakeFrame
@end
@implementation FakeChildFrame
- (BOOL)isMainFrame { return NO; }
@end
@interface FakeNavigationResponse : NSObject
@property(strong) NSURLResponse *response;
@property(getter=isForMainFrame) BOOL forMainFrame;
@property BOOL canShowMIMEType;
@end
@implementation FakeNavigationResponse
@end
@interface TestBrowser : GewuBrowserController
@property NSInteger surfaces;
@property NSInteger disposed;
@property(strong) WKWebViewConfiguration *popupConfiguration;
@end
@implementation TestBrowser
- (GewuBrowserPage *)makePage {
    self.surfaces++;
    GewuBrowserPage *page = [[GewuBrowserPage alloc] init];
    page.view = (id)[[FakeSurface alloc] init]; return page;
}
- (GewuBrowserPage *)makePageWithConfiguration:(WKWebViewConfiguration *)configuration {
    self.popupConfiguration = configuration;
    return [self makePage];
}
- (void)disposePage:(GewuBrowserPage *)page { if (page) self.disposed++; }
@end
static void commit(TestBrowser *browser, NSString *url) {
    FakeSurface *view = (id)browser.webView;
    NSMutableArray *past = [view.backForwardList.backList mutableCopy];
    if (view.backForwardList.currentItem) [past addObject:view.backForwardList.currentItem];
    view.backForwardList.backList = past; view.backForwardList.forwardList = @[];
    view.backForwardList.currentItem = [[NSObject alloc] init];
    view.URL = [NSURL URLWithString:url]; view.loading = NO;
    [browser webView:browser.webView didCommitNavigation:nil];
    browser.currentPage.ready = YES;
}
static void internalFrameChecks(void) {
    TestBrowser *browser = [TestBrowser alloc]; browser.active = YES; browser.visible = YES;
    [browser handleCommand:@{@"action":@"navigate", @"url":@"https://example.org/document"}];
    GewuBrowserPage *content = browser.currentPage;
    NSURLRequest *originalRequest = content.mainNavigationRequest;
    FakeAction *action = [FakeAction new]; action.navigationType = WKNavigationTypeOther;
    FakeNavigationResponse *response = [FakeNavigationResponse new]; response.canShowMIMEType = YES;
    for (NSString *url in @[@"about:blank", @"about:srcdoc", @"https://challenges.cloudflare.com/"]) {
        action.targetFrame = [FakeChildFrame new];
        action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:url]];
        __block WKNavigationActionPolicy decision;
        [browser webView:content.view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy p) { decision = p; }];
        check(decision == WKNavigationActionPolicyAllow, @"internal documents and public challenge hosts load as subframes");
        response.response = [[NSURLResponse alloc] initWithURL:action.request.URL MIMEType:@"text/html" expectedContentLength:0 textEncodingName:@"utf-8"];
        response.forMainFrame = NO;
        __block WKNavigationResponsePolicy result;
        [browser webView:content.view decidePolicyForNavigationResponse:(id)response decisionHandler:^(WKNavigationResponsePolicy p) { result = p; }];
        check(result == WKNavigationResponsePolicyAllow, @"internal child response is not rejected after its action was allowed");
        check(content.mainNavigationRequest == originalRequest && browser.tabs.count == 1, @"subframe callbacks do not change main navigation or create tabs");
    }
    for (NSString *url in @[@"about:config", @"about:srcdoc?file=/tmp/a", @"file:///tmp/a", @"data:text/html,test", @"http://127.0.0.1:8765/"]) {
        action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:url]];
        __block WKNavigationActionPolicy decision;
        [browser webView:content.view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy p) { decision = p; }];
        check(decision == WKNavigationActionPolicyCancel, @"unrelated schemes and local/private child destinations remain blocked");
        response.response = [[NSURLResponse alloc] initWithURL:action.request.URL MIMEType:@"text/html" expectedContentLength:0 textEncodingName:@"utf-8"];
        __block WKNavigationResponsePolicy result;
        [browser webView:content.view decidePolicyForNavigationResponse:(id)response decisionHandler:^(WKNavigationResponsePolicy p) { result = p; }];
        check(result == WKNavigationResponsePolicyCancel, @"response policy keeps local and unrelated schemes blocked");
    }
    action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:@"about:srcdoc"]];
    for (id frame in @[[FakeFrame new], NSNull.null]) {
        action.targetFrame = frame == NSNull.null ? nil : frame;
        __block WKNavigationActionPolicy decision;
        [browser webView:content.view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy p) { decision = p; }];
        check(decision == WKNavigationActionPolicyCancel, @"srcdoc cannot become a top-level or popup destination");
    }
    response.response = [[NSURLResponse alloc] initWithURL:action.request.URL MIMEType:@"text/html" expectedContentLength:0 textEncodingName:@"utf-8"];
    response.forMainFrame = YES;
    __block WKNavigationResponsePolicy result;
    [browser webView:content.view decidePolicyForNavigationResponse:(id)response decisionHandler:^(WKNavigationResponsePolicy p) { result = p; }];
    check(result == WKNavigationResponsePolicyCancel, @"top-level srcdoc response is blocked");
    response.forMainFrame = NO;
    response.canShowMIMEType = NO;
    [browser webView:content.view decidePolicyForNavigationResponse:(id)response decisionHandler:^(WKNavigationResponsePolicy p) { result = p; }];
    check(result == WKNavigationResponsePolicyCancel, @"internal child exceptions never initiate a download");
    response.canShowMIMEType = YES;
    action.targetFrame = [FakeChildFrame new];
    __block WKNavigationActionPolicy decision;
    [browser webView:browser.homePage.view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy p) { decision = p; }];
    check(decision == WKNavigationActionPolicyCancel, @"Home anchor cannot start internal child navigation");
    [browser webView:(id)[FakeSurface new] decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy p) { decision = p; }];
    check(decision == WKNavigationActionPolicyCancel, @"unknown views cannot start internal child navigation");
    [browser webView:browser.homePage.view decidePolicyForNavigationResponse:(id)response decisionHandler:^(WKNavigationResponsePolicy p) { result = p; }];
    check(result == WKNavigationResponsePolicyCancel, @"local Home anchor cannot load internal documents");
    [browser webView:(id)[FakeSurface new] decidePolicyForNavigationResponse:(id)response decisionHandler:^(WKNavigationResponsePolicy p) { result = p; }];
    check(result == WKNavigationResponsePolicyCancel, @"unknown or disposed views cannot use the child-document exception");
}
static void presentationChecks(void) {
    TestBrowser *browser = [TestBrowser alloc]; browser.active = YES; browser.visible = YES;
    [browser handleCommand:@{@"action":@"home"}];
    FakeSurface *home = (id)browser.webView;
    [browser openContentRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.org/old"]]];
    commit(browser, @"https://example.org/old");
    FakeSurface *old = (id)browser.webView; old.title = @"Old article";
    [browser handleCommand:@{@"action":@"home"}];
    GewuBrowserTab *tab = browser.selectedTab;
    NSInteger historyCount = tab.session.entries.count;
    __block NSDictionary *state;
    browser.onEvent = ^(NSDictionary *event) { if ([event[@"event"] isEqual:@"state"]) state = event; };
    NSURLRequest *search = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://www.google.com/search?q=new"]];
    [browser openContentRequest:search];
    check(home.hidden && old.hidden && tab.contentPendingFromHome, @"Home search never reveals previous content while provisional");
    check([state[@"home"] boolValue] && [state[@"url"] isEqual:@""] && [state[@"title"] isEqual:@"Favorites"] && [state[@"loading"] boolValue], @"local Home chrome stays stable with a working loading/stop indicator");
    [browser webView:(id)old didStartProvisionalNavigation:nil];
    [browser recordCurrentHistory];
    check(old.hidden && tab.session.entries.count == historyCount, @"start and old history cannot cause a stale-page flash or history entry");
    [browser handleCommand:@{@"action":@"reload"}];
    check(old.reloads == 0 && [old.URL isEqual:search.URL] && old.hidden, @"reload during transition reloads the new request, never old document");
    [browser addTabWithRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.net/"]] configuration:nil];
    GewuBrowserTab *other = browser.selectedTab;
    check(home.hidden && old.hidden, @"switch away hides both transition surfaces");
    [browser selectTab:tab];
    check(home.hidden && old.hidden, @"switch back keeps Home visible until destination commits");
    [browser handleCommand:@{@"action":@"stop"}];
    check(browser.webView == (id)home && home.hidden && old.hidden && !tab.contentPendingFromHome, @"Stop restores retained Home without revealing old content");
    [browser openContentRequest:search];
    old.loading = NO;
    [browser navigationFailed:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorTimedOut userInfo:nil] inPage:tab.currentPage];
    check(home.hidden && old.hidden && [state[@"error"] length] && ![state[@"loading"] boolValue], @"failed provisional request keeps Home and displays an error, not old article");
    [browser handleCommand:@{@"action":@"home"}];
    check(home.loads == 0, @"Home cancellation never loads a remote document");
    [browser openContentRequest:search];
    id staleNavigation = [NSObject new];
    id currentNavigation = [NSObject new];
    tab.pendingHomeNavigation = currentNavigation;
    [browser webView:(id)old didCommitNavigation:staleNavigation];
    [browser webView:(id)old didFailProvisionalNavigation:staleNavigation withError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorCancelled userInfo:nil]];
    check(tab.contentPendingFromHome && old.hidden, @"superseded callbacks cannot reveal or cancel a newer request");
    tab.pendingHomeNavigation = nil;
    commit(browser, search.URL.absoluteString);
    check(home.hidden && !old.hidden && !tab.contentPendingFromHome, @"only destination commit reveals content");
    check(tab.session.entries.count == historyCount + 1, @"new destination adds exactly one history entry");
    [browser handleCommand:@{@"action":@"back"}];
    check(browser.webView == (id)home && home.hidden, @"Back from committed result restores Home");
    [browser handleCommand:@{@"action":@"forward"}];
    check(browser.webView == (id)old && !old.hidden, @"Forward still reveals retained result without requests");
    [browser handleCommand:@{@"action":@"home"}];
    [browser openContentRequest:search];
    FakeAction *action = [FakeAction new]; action.targetFrame = [FakeFrame new]; action.navigationType = WKNavigationTypeFormSubmitted;
    action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://www.google.com/search?q=replacement"]];
    __block WKNavigationActionPolicy policy;
    [browser openContentRequest:action.request];
    [browser webView:(id)home decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy p) { policy = p; }];
    check(policy == WKNavigationActionPolicyCancel && [old.URL isEqual:action.request.URL] && old.hidden, @"second Home search replaces pending request without showing prior page");
    [browser selectTab:other];
    [browser webView:(id)old didCommitNavigation:nil];
    check(home.hidden && old.hidden && !tab.contentPendingFromHome && browser.selectedTab == other, @"background commit never shows another tab's content");
    [browser selectTab:tab];
    check(!old.hidden && home.hidden, @"completed background destination appears when selected");
    [browser handleCommand:@{@"action":@"home"}]; [browser openContentRequest:search];
    [browser returnToRetainedHomeInTab:tab];
    check(home.hidden && old.hidden && browser.webView == (id)home, @"download hand-off keeps Home rather than the old document");
}
int main(void) {
    @autoreleasepool {
        // Deliberately skip AppKit initialization: no event monitor or cache IO.
        TestBrowser *browser = [TestBrowser alloc];
        browser.session = [[GewuBrowserSession alloc] init]; browser.active = YES;
        [browser handleCommand:@{@"action":@"home"}];
        FakeSurface *home = (id)browser.webView;
        check(home.loads == 0 && browser.surfaces == 1 && !home.URL, @"first Home is local, with no Google load");
        [browser handleCommand:@{@"action":@"home"}];
        check(home.loads == 0, @"repeated Home does not create a request");
        for (int i = 0; i < 10; i++) [browser handleCommand:@{@"action":@"home"}];
        check(home.loads == 0 && home.reloads == 0 && browser.session.entries.count == 1, @"warm Home is request-free and does not duplicate history");

        FakeAction *action = [[FakeAction alloc] init]; action.targetFrame = [[FakeFrame alloc] init];
        action.navigationType = WKNavigationTypeFormSubmitted;
        action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://www.google.com/search?q=physics"]];
        __block WKNavigationActionPolicy policy = WKNavigationActionPolicyAllow;
        [browser webView:browser.webView decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy value) { policy = value; }];
        check(policy == WKNavigationActionPolicyCancel && home.loads == 0, @"unloaded Home anchor rejects webpage navigation");
        [browser handleCommand:@{@"action":@"navigate", @"url":action.request.URL.absoluteString}];
        FakeSurface *content = (id)browser.webView;
        check(content != home && content.loads == 1 && home.loads == 0, @"address-bar search opens content without loading Google Home");
        commit(browser, @"https://www.google.com/search?q=physics");
        check(browser.session.index == 1 && browser.surfaces == 2, @"Home and result share a bounded two-surface session");
        [browser handleCommand:@{@"action":@"back"}];
        check(browser.webView == (id)home && home.loads == 0, @"Back from first search restores local Home");
        [browser handleCommand:@{@"action":@"forward"}];
        check(browser.webView == (id)content && content.loads == 1 && content.traversals == 0, @"Forward restores retained result without reloading");
        [browser handleCommand:@{@"action":@"home"}];
        [browser handleCommand:@{@"action":@"back"}];
        check(browser.webView == (id)content && content.loads == 1, @"Home button keeps the previous webpage accessible");
        [browser handleCommand:@{@"action":@"forward"}];
        [browser handleCommand:@{@"action":@"reload"}];
        check(home.reloads == 0 && home.loads == 0, @"Home Reload cannot request Google");
        [browser handleCommand:@{@"action":@"back"}];
        [browser handleCommand:@{@"action":@"reload"}];
        check(content.reloads == 1, @"ordinary webpage Reload remains a real refresh");

        NSMutableURLRequest *post = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"https://accounts.google.com/"]];
        post.HTTPMethod = @"POST"; action.request = post;
        [browser webView:browser.webView decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy value) { policy = value; }];
        check(policy == WKNavigationActionPolicyAllow && browser.webView == (id)content, @"POST stays with WebKit; never replay form data in a different view");
        post.HTTPMethod = @"GET"; post.HTTPBody = [@"synthetic" dataUsingEncoding:NSUTF8StringEncoding];
        check(!GewuBrowserCanRetainHomeForRequest(post), @"requests with a body are not transferred");
        post.HTTPBody = nil; post.HTTPBodyStream = [NSInputStream inputStreamWithData:NSData.data];
        check(!GewuBrowserCanRetainHomeForRequest(post), @"streams are not transferred");
        [browser webViewWebContentProcessDidTerminate:(id)home];
        [browser handleCommand:@{@"action":@"home"}];
        check(home.loads == 0 && browser.homePage.ready, @"local Home survives process termination without network");
        [browser handleCommand:@{@"action":@"navigate", @"url":@"https://example.org/"}];
        commit(browser, @"https://example.org/");
        NSInteger before = browser.session.index;
        [browser webView:(id)home didStartProvisionalNavigation:nil];
        [browser webView:(id)home didCommitNavigation:nil];
        check(browser.webView == (id)content && browser.session.index == before, @"hidden Home callbacks cannot corrupt active history");
        [browser handleCommand:@{@"action":@"home"}];
        check(home.loads == 0 && browser.surfaces == 2, @"subsequent Home still reuses the same two surfaces");

        GewuBrowserTab *first = browser.selectedTab;
        NSInteger originalHistoryCount = first.session.entries.count;
        home.loading = YES;
        [browser handleCommand:@{@"action":@"new-tab", @"url":@"https://example.net/article"}];
        GewuBrowserTab *second = browser.selectedTab;
        FakeSurface *secondView = (id)browser.webView;
        check(browser.tabs.count == 2 && first != second && secondView.loads == 1 && home.loading, @"new tab loads once without interrupting previous tab");
        commit(browser, @"https://example.net/article");
        check(second.session.entries.count == 1 && first.session.entries.count == originalHistoryCount, @"tabs own independent native history");
        [browser selectTab:first];
        check(browser.webView == (id)home && home.loads == 0 && secondView.loads == 1, @"selecting tabs never reloads either document");
        __block NSDictionary *lastState;
        browser.onEvent = ^(NSDictionary *event) { if ([event[@"event"] isEqual:@"state"]) lastState = event; };
        [browser emitState];
        NSString *firstURL = lastState[@"url"];
        secondView.backForwardList.backList = @[secondView.backForwardList.currentItem];
        secondView.backForwardList.currentItem = [[NSObject alloc] init];
        secondView.URL = [NSURL URLWithString:@"https://example.net/next"];
        [browser webView:(id)secondView didStartProvisionalNavigation:nil];
        [browser webView:(id)secondView didCommitNavigation:nil];
        [browser webView:(id)secondView didFinishNavigation:nil];
        check(second.session.entries.count == 2 && [lastState[@"url"] isEqual:firstURL], @"background completion updates its own history, not active chrome");
        action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.net/redirect"]];
        action.navigationType = WKNavigationTypeOther;
        [browser webView:(id)secondView decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy p) { policy=p; }];
        check(policy == WKNavigationActionPolicyAllow && second.contentPage.mainNavigationRequest == action.request, @"background redirects remain scoped to their tab");
        NSString *priorError = first.currentPage.errorMessage;
        [browser navigationFailed:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorTimedOut userInfo:nil] inPage:second.currentPage];
        check(second.currentPage.errorMessage.length && first.currentPage.errorMessage == priorError, @"background errors are not assigned to visible tab");
        [browser closeTab:second];
        check(browser.tabs.count == 1 && browser.selectedTab == first && browser.disposed == 1, @"close background tab frees its surfaces without disturbing selection");

        browser.visible = YES; home.loading = NO;
        [browser activatePage:browser.contentPage];
        action.targetFrame = nil;
        action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.org/popup"]];
        WKWebViewConfiguration *configuration = (id)[[NSObject alloc] init];
        WKWebView *popup = [browser webView:(id)content createWebViewWithConfiguration:configuration forNavigationAction:(id)action windowFeatures:nil];
        check(popup && browser.popupConfiguration == configuration && ((FakeSurface *)popup).loads == 0, @"popup returns supplied-configuration view; WebKit loads it, no GET/POST replay");
        check(browser.tabs.count == 2 && browser.selectedTab.currentPage.view == popup, @"target blank selects a tracked tab");
        [browser webViewDidClose:popup];
        check(browser.tabs.count == 1 && browser.selectedTab == first, @"window.close closes only script-opened tab");
        [browser webViewDidClose:(id)home];
        check(browser.tabs.count == 1, @"website cannot script-close user-created Home tab");
        action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:@"http://127.0.0.1:8765/"]];
        check(![browser webView:(id)content createWebViewWithConfiguration:configuration forNavigationAction:(id)action windowFeatures:nil], @"popup cannot reach private workspace addresses");
        action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.org/linked.pdf"]];
        action.targetFrame = [[FakeFrame alloc] init]; action.navigationType = WKNavigationTypeLinkActivated;
        action.modifierFlags = NSEventModifierFlagCommand;
        [browser webView:(id)content decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy p) { policy=p; }];
        check(policy == WKNavigationActionPolicyCancel && browser.tabs.count == 2 && browser.selectedTab != first, @"Command-click link opens another tab");
        [browser handleCommand:@{@"action":@"close-tab",@"tab_id":browser.selectedTab.identifier}];
        [browser handleCommand:@{@"action":@"close-tab",@"tab_id":first.identifier}];
        check(browser.tabs.count == 1 && browser.selectedTab != first && browser.currentPage == browser.homePage, @"closing final tab keeps Browser open with a new Home");
        check(((FakeSurface *)browser.webView).loads == 0, @"replacement Home creates no remote load");
        [browser handleCommand:@{@"action":@"select-tab",@"tab_id":first.identifier}];
        check(browser.selectedTab != first, @"stale closed-tab commands are ignored");
        while (browser.tabs.count < 32) [browser handleCommand:@{@"action":@"new-tab"}];
        GewuBrowserTab *last = browser.selectedTab;
        NSInteger surfacesBeforeLimit = browser.surfaces;
        [browser handleCommand:@{@"action":@"new-tab"}];
        check(browser.tabs.count == 32 && browser.selectedTab == last && browser.surfaces == surfacesBeforeLimit, @"tab limit never evicts existing documents or preloads extra views");

        GewuBrowserSession *session = [[GewuBrowserSession alloc] init];
        NSObject *surface = [[NSObject alloc] init], *a = [[NSObject alloc] init], *b = [[NSObject alloc] init], *c = [[NSObject alloc] init];
        [session recordSurface:surface item:nil home:YES traversal:NO];
        [session recordSurface:surface item:a home:NO traversal:NO];
        [session recordSurface:surface item:nil home:YES traversal:NO];
        [session recordSurface:surface item:b home:NO traversal:NO];
        [session move:-2];
        [session recordSurface:surface item:c home:NO traversal:NO];
        check(session.entries.count == 3 && session.current.item == c && ![session move:1], @"new navigation discards the forward branch");
        [session recordSurface:surface item:a home:NO traversal:YES];
        check(session.index == 1, @"native history traversal selects existing item");
        [session pruneSurface:surface validItems:@[c]];
        check(session.entries.count == 2 && session.index == 0 && session.current.home, @"evicted native history items are removed, never URL-replayed");
        for (int i = 0; i < 300; i++) [session recordSurface:surface item:[[NSObject alloc] init] home:NO traversal:NO];
        check(session.entries.count == 256 && session.index == 255, @"session metadata is bounded");
        presentationChecks();
        workspaceReturnChecks();
        internalFrameChecks();
        printf("Retained Browser Home: %ld checks passed\n", (long)checks);
    }
}
