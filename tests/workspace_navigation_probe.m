// Execute the actual App delegate with inert views/actions. No App launch,
// network, cookies, real window, clipboard or credential store is involved.
#define main GewuUnusedApplicationEntry
#import "PaperMonitorApp.m"
#undef main

@interface LinkProbeView : NSObject
@property(strong) NSMutableArray *scripts;
@property(strong) NSMutableArray *requests;
@end
@implementation LinkProbeView
- (id)loadRequest:(NSURLRequest *)request { [self.requests addObject:request]; return nil; }
- (void)evaluateJavaScript:(NSString *)script completionHandler:(id)handler {
    [self.scripts addObject:script];
}
@end
@interface LinkProbeFrame : NSObject
@property(strong) NSURLRequest *request;
@property BOOL mainFrame;
@end
@implementation LinkProbeFrame
- (BOOL)isMainFrame { return self.mainFrame; }
@end
@interface LinkProbeAction : NSObject
@property(strong) NSURLRequest *request;
@property(strong) LinkProbeFrame *sourceFrame;
@property(strong) LinkProbeFrame *targetFrame;
@end
@implementation LinkProbeAction
@end

@interface RecoveryProbeDelegate : PaperMonitorDelegate
@property NSInteger recoveries;
@property NSInteger failures;
@end
@implementation RecoveryProbeDelegate
- (NSMutableURLRequest *)workspaceRequestForURL:(NSURL *)url {
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    [request setValue:@"synthetic-workspace-session" forHTTPHeaderField:@"X-Gewu-Workspace"];
    return request;
}
- (void)showLoadingPage {}
- (void)closeNativeQuickLookNotifyingWeb:(BOOL)notify {}
- (void)loadApp { self.recoveries++; }
- (void)appendLauncherLogMessage:(NSString *)message {}
- (void)presentStartupFailure:(NSString *)message { self.failures++; }
@end

static NSInteger checks;
static void check(BOOL ok, NSString *label) {
    if (!ok) { fprintf(stderr,"FAILED: %s\n",label.UTF8String); exit(1); }
    checks++;
}
int main(void) {
    @autoreleasepool {
        RecoveryProbeDelegate *delegate = [RecoveryProbeDelegate new];
        delegate.url = [NSURL URLWithString:@"http://127.0.0.1:8765/"];
        LinkProbeView *view = [LinkProbeView new]; view.scripts = [NSMutableArray array]; view.requests = [NSMutableArray array];
        delegate.webView = (id)view;
        LinkProbeFrame *frame = [LinkProbeFrame new]; frame.mainFrame = YES;
        frame.request = [NSURLRequest requestWithURL:delegate.url];
        LinkProbeAction *action = [LinkProbeAction new]; action.sourceFrame = frame;
        action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.org/paper.pdf?x=1&y=2#page=2"]];
        for (NSNumber *popup in @[@NO,@YES]) {
            action.targetFrame = popup.boolValue ? nil : frame;
            NSInteger before = view.scripts.count;
            __block NSInteger decisions = 0;
            [delegate webView:(id)view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy policy) {
                decisions++; check(policy == WKNavigationActionPolicyCancel,@"remote workspace navigation cancelled");
            }];
            check(decisions == 1 && view.scripts.count == before+1,@"one Browser request for either main-frame or target-blank link");
            check([view.scripts.lastObject containsString:@"window.openWebsite"] && [view.scripts.lastObject containsString:@"paper.pdf?x=1&y=2#page=2"],@"exact destination passed as JSON, no parameter loss");
        }
        NSInteger before = view.scripts.count;
        check([delegate webView:(id)view createWebViewWithConfiguration:nil forNavigationAction:(id)action windowFeatures:nil] == nil,@"workspace popup creates no privileged remote view");
        check(view.scripts.count == before+1,@"popup delegate fallback uses the same router");
        for (NSString *url in @[@"http://127.0.0.1:8765/api/file?path=paper.pdf", @"blob:http://127.0.0.1:8765/example"]) {
            action.request = [NSURLRequest requestWithURL:[NSURL URLWithString:url]];
            before = view.scripts.count;
            [delegate webView:(id)view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy policy) {
                check(policy == WKNavigationActionPolicyAllow,@"local file/export navigation unchanged");
            }];
            check(before == view.scripts.count,@"local request creates no Browser tab");
        }
        NSMutableURLRequest *post = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"https://example.org/form"]];
        post.HTTPMethod = @"POST"; action.request = post; before = view.scripts.count;
        [delegate webView:(id)view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy policy) {
            check(policy == WKNavigationActionPolicyCancel,@"remote form cannot replace workspace");
        }];
        check(before == view.scripts.count,@"form is not replayed");
        action.targetFrame = frame;
        action.request = [NSURLRequest requestWithURL:delegate.url];
        [delegate webView:(id)view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy policy) {
            check(policy == WKNavigationActionPolicyCancel,@"credential-free workspace reload is replaced");
        }];
        check(view.requests.count == 1,@"one authenticated replacement request");
        check([[view.requests.lastObject valueForHTTPHeaderField:@"X-Gewu-Workspace"] isEqual:@"synthetic-workspace-session"],@"replacement includes private credential");
        action.request = view.requests.lastObject;
        [delegate webView:(id)view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy policy) {
            check(policy == WKNavigationActionPolicyAllow,@"authenticated reload proceeds without a loop");
        }];
        frame.mainFrame = NO;
        action.request = [NSURLRequest requestWithURL:delegate.url];
        [delegate webView:(id)view decidePolicyForNavigationAction:(id)action decisionHandler:^(WKNavigationActionPolicy policy) {
            check(policy == WKNavigationActionPolicyAllow,@"subframe does not receive credential injection");
        }];
        check(view.requests.count == 1,@"subframe does not create credential request");
        [delegate webViewWebContentProcessDidTerminate:(id)[LinkProbeView new]];
        check(delegate.recoveries == 0,@"unrelated webview cannot trigger workspace recovery");
        for (int i=0; i<4; i++) [delegate webViewWebContentProcessDidTerminate:(id)view];
        check(delegate.recoveries == 3 && delegate.failures == 1,@"workspace recovery is bounded without restarting jobs");
        delegate.workspaceRecoveryWindow = [NSDate dateWithTimeIntervalSinceNow:-61];
        [delegate webViewWebContentProcessDidTerminate:(id)view];
        check(delegate.recoveries == 4,@"later independent crash can recover");
        printf("Workspace native routing: %ld checks passed\n",(long)checks);
    }
    return 0;
}
