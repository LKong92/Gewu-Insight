// Real WebKit + AppKit trigger, synthetic page only. Never opens Passwords:
// the final OS menu press is replaced by a counter. No credential is requested.
#import "GewuBrowserAutoFill.m"
@interface DryTrigger : GewuBrowserAutoFill
@property NSInteger dispatches;
@end
@implementation DryTrigger
- (BOOL)performPasswordMenuItem:(id<NSAccessibility>)item { self.dispatches++; return NO; }
- (void)considerMouseUp:(NSEvent *)event inView:(WKWebView *)view {
    fprintf(stdout,"TEST_CLICK eligible=%d key=%d loading=%d\n", self.clickEligible, view.window.isKeyWindow, view.loading);
    [super considerMouseUp:event inView:view];
    fprintf(stdout,"TEST_QUERY pending=%d\n", self.pendingView != nil); fflush(stdout);
}
- (void)nativeMenuWillOpen:(NSMenu *)menu inView:(WKWebView *)view event:(NSEvent *)event {
    fprintf(stdout,"TEST_MENU pending=%d available=%d\n", self.menuEvent != nil, GewuBrowserPasswordMenuItem(menu) != nil); fflush(stdout);
    [super nativeMenuWillOpen:menu inView:view event:event];
}
@end
@interface TriggerView : WKWebView
@property(strong) DryTrigger *trigger;
@end
@implementation TriggerView
- (void)callAsyncJavaScript:(NSString *)script arguments:(NSDictionary *)arguments inFrame:(WKFrameInfo *)frame inContentWorld:(WKContentWorld *)world completionHandler:(void (^)(id, NSError *))completion {
    [super callAsyncJavaScript:script arguments:arguments inFrame:frame inContentWorld:world completionHandler:^(id result, NSError *error) {
        if (arguments[@"mode"]) { fprintf(stdout,"TEST_SEMANTICS eligible=%d error=%d\n", [@[@"username",@"current-password"] containsObject:result ?: NSNull.null], error != nil); fflush(stdout); }
        completion(result,error);
    }];
}
- (void)willOpenMenu:(NSMenu *)menu withEvent:(NSEvent *)event {
    [self.window makeFirstResponder:self];
    [super willOpenMenu:menu withEvent:event];
    [self.trigger nativeMenuWillOpen:menu inView:self event:event];
}
@end
@interface Probe : NSObject <WKNavigationDelegate>
@property(strong) NSWindow *window;
@property(strong) TriggerView *view;
@property NSInteger step;
- (void)next;
@end
@implementation Probe
- (void)webView:(WKWebView *)view didFinishNavigation:(WKNavigation *)navigation { [self next]; }
- (void)next {
    NSArray *ids = @[@"username", @"username", @"username", @"username", @"username", @"username", @"username", @"search", @"ordinary", @"password", @"password"];
    NSArray *expected = @[@0, @0, @0, @0, @0, @1, @1, @1, @1, @2, @2];
    if (self.step >= ids.count) { puts("11 native trigger checks passed; zero credential requests"); fflush(stdout); [NSApp terminate:nil]; return; }
    // A test-dispatched mouse event does not activate the app like a physical
    // user click; restore only this isolated fixture window for each step.
    [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
    NSString *identifier = ids[self.step]; NSInteger expectedCount = [expected[self.step] integerValue];
    [self.view callAsyncJavaScript:@"const r=document.getElementById(identifier).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};"
        arguments:@{@"identifier":identifier} inFrame:nil inContentWorld:WKContentWorld.defaultClientWorld completionHandler:^(id result, NSError *error) {
        if (error || ![result isKindOfClass:NSDictionary.class]) { fprintf(stderr,"FAIL: fixture geometry\n"); exit(1); }
        NSPoint point = NSMakePoint([result[@"x"] doubleValue], self.view.bounds.size.height - [result[@"y"] doubleValue]);
        NSEvent *(^event)(NSEventType) = ^NSEvent *(NSEventType type) {
            return [NSEvent mouseEventWithType:type location:point modifierFlags:self.step == 0 ? NSEventModifierFlagCommand : 0 timestamp:NSProcessInfo.processInfo.systemUptime
                windowNumber:self.window.windowNumber context:nil eventNumber:1 clickCount:self.step == 1 ? 2 : 1 pressure:0];
        };
        NSEvent *down = event(NSEventTypeLeftMouseDown);
        [self.view.trigger noteInputEvent:down]; [self.window sendEvent:down];
        if (self.step == 2) [self.view.trigger noteInputEvent:event(NSEventTypeLeftMouseDragged)];
        if (self.step == 3) [self.view.trigger cancelPending];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_MSEC * 100), dispatch_get_main_queue(), ^{
            NSEvent *up = event(NSEventTypeLeftMouseUp); [self.window sendEvent:up];
            [self.view.trigger considerMouseUp:up inView:self.view];
            if (self.step == 4) [self.view.trigger cancelPending];
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_MSEC * 600), dispatch_get_main_queue(), ^{
                if (self.view.trigger.dispatches != expectedCount) {
                    fprintf(stderr,"FAIL: step %ld dispatch count %ld expected %ld\n", (long)self.step, (long)self.view.trigger.dispatches, (long)expectedCount); exit(1);
                }
                self.step++; [self next];
            });
        });
    }];
}
@end
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
        Probe *probe = [Probe new];
        probe.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100,100,650,450) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        probe.window.title = @"Gewu — synthetic AutoFill trigger checks (no passwords)";
        WKWebViewConfiguration *config = [WKWebViewConfiguration new]; config.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
        probe.view = [[TriggerView alloc] initWithFrame:probe.window.contentView.bounds configuration:config];
        NSString *script = [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[1]] encoding:NSUTF8StringEncoding error:nil];
        probe.view.trigger = [[DryTrigger alloc] initWithProbeScript:script canUseView:^BOOL(WKWebView *view) { return YES; }];
        probe.view.navigationDelegate = probe; [probe.window.contentView addSubview:probe.view];
        [probe.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
        [probe.view loadHTMLString:@"<!doctype html><style>input{display:block;margin:10px;width:300px;height:45px}</style><form id=login><input id=username autocomplete=username><input id=password type=password autocomplete=current-password></form><input id=search type=search><input id=ordinary type=email>" baseURL:[NSURL URLWithString:@"https://example.org/login"]];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 20*NSEC_PER_SEC), dispatch_get_main_queue(), ^{ fprintf(stderr,"FAIL: trigger test timeout\n"); exit(1); });
        [NSApp run];
    }
}
