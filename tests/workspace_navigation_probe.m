// Execute the actual App delegate with inert views/actions. No App launch,
// network, cookies, real window, clipboard or credential store is involved.
#define main GewuUnusedApplicationEntry
#import "PaperMonitorApp.m"
#undef main

@interface LinkProbeView : NSObject
@property(strong) NSMutableArray *scripts;
@end
@implementation LinkProbeView
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

static NSInteger checks;
static void check(BOOL ok, NSString *label) {
    if (!ok) { fprintf(stderr,"FAILED: %s\n",label.UTF8String); exit(1); }
    checks++;
}
int main(void) {
    @autoreleasepool {
        PaperMonitorDelegate *delegate = [PaperMonitorDelegate new];
        delegate.url = [NSURL URLWithString:@"http://127.0.0.1:8765/"];
        LinkProbeView *view = [LinkProbeView new]; view.scripts = [NSMutableArray array];
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
        printf("Workspace native routing: %ld checks passed\n",(long)checks);
    }
    return 0;
}
