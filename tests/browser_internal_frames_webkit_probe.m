// Real WebKit with generated documents only. No challenge is loaded or solved;
// no live website, persistent profile, password, cookie export or database.
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
static BOOL evaluate(WKWebView *view, NSString *script) {
    __block BOOL finished = NO, result = NO;
    [view evaluateJavaScript:script completionHandler:^(id value, NSError *error) {
        result = !error && [value respondsToSelector:@selector(boolValue)] && [value boolValue]; finished = YES;
    }];
    return spin(^BOOL { return finished; }) && result;
}
static BOOL evaluateAsync(WKWebView *view, NSString *body) {
    __block BOOL finished = NO, result = NO;
    [view callAsyncJavaScript:body arguments:@{} inFrame:nil inContentWorld:WKContentWorld.pageWorld completionHandler:^(id value, NSError *error) {
        result = !error && [value respondsToSelector:@selector(boolValue)] && [value boolValue]; finished = YES;
    }];
    return spin(^BOOL { return finished; }) && result;
}
@interface FrameBrowser : GewuBrowserController
@property NSInteger srcdocActions, blankActions, childResponses, unexpectedRequests;
@end
@implementation FrameBrowser
- (GewuBrowserPage *)makePage {
    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    return [super makePageWithConfiguration:configuration];
}
- (void)webView:(WKWebView *)view decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decision {
    NSString *url = action.request.URL.absoluteString;
    BOOL internal = GewuBrowserInternalFrameURL(action.request.URL);
    if (!internal && ![url isEqual:@"https://example.org/generated-frame-fixture"]) {
        self.unexpectedRequests++; decision(WKNavigationActionPolicyCancel); return;
    }
    [super webView:view decidePolicyForNavigationAction:action decisionHandler:^(WKNavigationActionPolicy policy) {
        if (!action.targetFrame.isMainFrame && policy == WKNavigationActionPolicyAllow) {
            if ([url isEqual:@"about:srcdoc"]) self.srcdocActions++;
            if ([url isEqual:@"about:blank"]) self.blankActions++;
        }
        decision(policy);
    }];
}
- (void)webView:(WKWebView *)view decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decision {
    [super webView:view decidePolicyForNavigationResponse:response decisionHandler:^(WKNavigationResponsePolicy policy) {
        if (!response.forMainFrame && policy == WKNavigationResponsePolicyAllow) self.childResponses++;
        decision(policy);
    }];
}
@end
int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(40,40,800,500) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        window.title = @"Gewu generated internal-frame verification"; window.releasedWhenClosed = NO;
        WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
        configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
        WKWebView *workspace = [[WKWebView alloc] initWithFrame:window.contentView.bounds configuration:configuration];
        [window.contentView addSubview:workspace];
        FrameBrowser *browser = [[FrameBrowser alloc] initWithWorkspace:workspace];
        [browser.favicons invalidate]; browser.favicons = nil; browser.active = YES; browser.visible = YES;
        [browser ensureWebView]; browser.contentPage = [browser makePage]; [browser activatePage:browser.contentPage];
        WKWebView *view = browser.webView; view.frame = workspace.bounds;
        [window orderBack:nil];
        NSString *html = @"<!doctype html><title>Generated child documents</title><script>window.received=[];addEventListener('message',e=>received.push({data:e.data,origin:e.origin}));</script><iframe id='regular'></iframe><iframe id='sandboxed' sandbox='allow-scripts'></iframe><iframe id='blank' src='about:blank'></iframe>";
        [view loadHTMLString:html baseURL:[NSURL URLWithString:@"https://example.org/generated-frame-fixture"]];
        check(spin(^BOOL { return [view.title isEqual:@"Generated child documents"] && !view.loading; }), "generated parent loaded");
        check(evaluate(view, @"regular.srcdoc=\"<script>parent.postMessage('regular','*');<\\/script><p id='value'>Synthetic child</p>\";sandboxed.srcdoc=\"<script>parent.postMessage('sandboxed','*');<\\/script>\";true"), "generated regular and sandboxed srcdoc assigned");
        check(spin(^BOOL { return browser.srcdocActions >= 2; }), "real WebKit srcdoc actions reach and pass the product delegate");
        check(evaluateAsync(view, @"return new Promise(resolve=>{let n=0;let t=setInterval(()=>{if(received.length===2||++n===100){clearInterval(t);resolve(received.length===2)}},20)})"), "both child scripts execute and can postMessage to their parent");
        check(evaluate(view, @"regular.contentDocument.getElementById('value').textContent==='Synthetic child'"), "ordinary srcdoc inherits its embedding document access");
        check(evaluate(view, @"received.some(x=>x.data==='regular'&&x.origin==='https://example.org')&&received.some(x=>x.data==='sandboxed'&&x.origin==='null')"), "WebKit origin and sandbox isolation remain intact");
        check(evaluate(view, @"sandboxed.contentDocument===null"), "sandboxed child does not gain parent document access");
        check(evaluate(view, @"blank.contentDocument.body!==null"), "about blank child remains usable");
        check(browser.unexpectedRequests == 0 && browser.tabs.count == 1, "no network requests or extra tabs");
        check(!view.configuration.websiteDataStore.persistent, "fixture uses only an ephemeral profile");
        check(evaluate(view, @"!window.webkit?.messageHandlers?.browser && !window.webkit?.messageHandlers?.native"), "remote document has no trusted workspace bridge");
        [browser invalidate]; [window close];
        printf("Real WebKit internal frames: %ld checks passed; srcdoc actions=%ld, blank actions=%ld, child responses=%ld. No live challenge or credentials.\n", (long)checks, (long)browser.srcdocActions, (long)browser.blankActions, (long)browser.childResponses);
    }
}
