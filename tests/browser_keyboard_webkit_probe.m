// Generated documents and ephemeral WebKit only; no real browser profiles.
#import "GewuBrowserController.m"
static NSInteger checks;
static void check(BOOL ok, const char *label) { if (!ok) { fprintf(stderr,"FAIL: %s\n",label); exit(1); } checks++; }
static void spin(NSTimeInterval seconds) {
    NSDate *end = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while (end.timeIntervalSinceNow > 0) [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
}
static BOOL js(WKWebView *view, NSString *script) {
    __block BOOL done = NO, result = NO;
    [view evaluateJavaScript:script completionHandler:^(id value, NSError *error) { result = !error && [value respondsToSelector:@selector(boolValue)] && [value boolValue]; done = YES; }];
    for (NSInteger i=0; i<600 && !done; i++) spin(.01);
    return done && result;
}
@interface KeyboardFixture : GewuBrowserController
@end
@implementation KeyboardFixture
- (GewuBrowserPage *)makePage {
    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    return [super makePageWithConfiguration:configuration];
}
- (void)webView:(WKWebView *)view decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decision {
    decision([@[@"about:blank", @"https://example.org/keyboard-fixture"] containsObject:action.request.URL.absoluteString] ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}
@end
static void arrow(NSWindow *window, unsigned short key, NSEventModifierFlags flags) {
    unichar character = key == 126 ? NSUpArrowFunctionKey : NSLeftArrowFunctionKey;
    NSString *text = [NSString stringWithCharacters:&character length:1];
    [NSApp sendEvent:[NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:flags timestamp:NSProcessInfo.processInfo.systemUptime windowNumber:window.windowNumber context:nil characters:text charactersIgnoringModifiers:text isARepeat:NO keyCode:key]];
    spin(.3);
}
int main(int argc, const char **argv) {
    @autoreleasepool {
        [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(60,60,700,450) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        window.title = @"Gewu synthetic arrow verification"; window.releasedWhenClosed = NO;
        WKWebViewConfiguration *configuration = [WKWebViewConfiguration new]; configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
        WKWebView *workspace = [[WKWebView alloc] initWithFrame:window.contentView.bounds configuration:configuration];
        [window.contentView addSubview:workspace];
        KeyboardFixture *browser = [[KeyboardFixture alloc] initWithWorkspace:workspace];
        [browser.favicons invalidate]; browser.favicons = nil;
        browser.navigationProbe = [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[1]] encoding:NSUTF8StringEncoding error:nil];
        browser.active = YES; browser.visible = YES; browser.sidebarVisible = YES;
        [browser ensureWebView]; browser.contentPage = [browser makePage]; [browser activatePage:browser.contentPage];
        browser.webView.frame = workspace.frame;
        // A background/fully occluded WebKit document correctly reports hidden
        // and is excluded by the product probe. Show only this synthetic window.
        [window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
        [browser.webView loadHTMLString:@"<!doctype html><title>Keyboard fixture</title><main style='height:2000px'><input id='login' autocomplete='username'><textarea id='text'></textarea><div id='widget' role='listbox' tabindex='0'>Widget</div></main>" baseURL:[NSURL URLWithString:@"https://example.org/keyboard-fixture"]];
        for (NSInteger i=0;i<300 && ![browser.webView.title isEqual:@"Keyboard fixture"];i++) spin(.02);
        spin(.3);
        check(js(browser.webView,@"!!document.getElementById('login')"),"fixture loaded");
        check(js(browser.webView,@"document.visibilityState === 'visible'"),"fixture visible");
        __block NSInteger handoffs = 0; __block NSString *destination = nil;
        browser.onEvent = ^(NSDictionary *event) { if ([event[@"event"] isEqual:@"focus-chrome"]) { handoffs++; destination = event[@"destination"]; } };
        [window makeFirstResponder:browser.webView];
        check(js(browser.webView,@"document.activeElement.blur(); scrollTo(0,0); true"),"focus ordinary document");
        arrow(window,126,0);
        check(handoffs == 1 && [destination isEqual:@"tabs"],"real AppKit Up reaches tabs at document top");
        check(window.firstResponder == workspace,"native handoff restores trusted workspace responder");
        [window makeFirstResponder:browser.webView];
        check(js(browser.webView,@"document.activeElement.blur();scrollTo(0,0);true"),"restore ordinary document, not a remembered form control");
        arrow(window,123,0);
        check(handoffs == 2 && [destination isEqual:@"sidebar"],"real AppKit Left enters visible sidebar");
        browser.sidebarVisible = NO; [window makeFirstResponder:browser.webView]; arrow(window,123,0);
        check(handoffs == 2,"hidden sidebar cannot receive focus");
        arrow(window,126,NSEventModifierFlagShift); check(handoffs == 2,"modified arrows remain native");
        for (NSString *field in @[@"login", @"text", @"widget"]) {
            [window makeFirstResponder:browser.webView];
            check(js(browser.webView,[NSString stringWithFormat:@"document.getElementById('%@').focus(); true",field]),"focus generated control");
            arrow(window,126,0); check(handoffs == 2,"form and widget arrows cannot escape to chrome");
        }
        [window makeFirstResponder:browser.webView];
        check(js(browser.webView,@"document.activeElement.blur();scrollTo(0,800);true"),"scroll ordinary page");
        arrow(window,126,0); check(handoffs == 2,"Up away from page top does not leave webpage");
        check(js(browser.webView,@"scrollY > 0"),"ordinary page remains scrolled");
        [browser invalidate]; [window orderOut:nil];
        printf("%ld native Browser arrow checks passed\n",(long)checks);
    }
}
