// A disposable nonpersistent WebKit page; never connects to the running App.
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
@interface MarkdownProbe : NSObject <WKNavigationDelegate, WKScriptMessageHandler>
@property WKWebView *view;
@property BOOL done;
@property BOOL passed;
@end
@implementation MarkdownProbe
- (void)webView:(WKWebView *)view didFinishNavigation:(WKNavigation *)navigation {
    [view evaluateJavaScript:@"runChecks().then(r=>window.webkit.messageHandlers.result.postMessage({ok:true,result:r}),e=>window.webkit.messageHandlers.result.postMessage({ok:false,error:String(e)}));void(0)" completionHandler:^(id value, NSError *error) {
        if (error) { fprintf(stderr,"WebKit evaluation: %s\n",error.description.UTF8String); self.done=YES; }
    }];
}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    NSDictionary *body=message.body;
    self.passed=[body[@"ok"] boolValue];
    NSData *data=[NSJSONSerialization dataWithJSONObject:body options:0 error:nil];
    printf("WebKit Markdown: %s\n",[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
    self.done=YES;
}
- (void)webView:(WKWebView *)view didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    fprintf(stderr,"WebKit navigation: %s\n",error.description.UTF8String);self.done=YES;
}
@end
int main(int argc,const char *argv[]) { @autoreleasepool {
    if(argc!=2)return 2;
    [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    MarkdownProbe *probe=[MarkdownProbe new];
    WKWebViewConfiguration *config=[WKWebViewConfiguration new];config.websiteDataStore=[WKWebsiteDataStore nonPersistentDataStore];
    [config.userContentController addScriptMessageHandler:probe name:@"result"];
    probe.view=[[WKWebView alloc] initWithFrame:NSMakeRect(0,0,1100,800) configuration:config];probe.view.navigationDelegate=probe;
    NSWindow *window=[[NSWindow alloc] initWithContentRect:NSMakeRect(-3000,-3000,1100,800) styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
    window.contentView=probe.view;[window orderBack:nil];
    [probe.view loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:[NSString stringWithUTF8String:argv[1]]]]];
    NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:30];
    while(!probe.done&&deadline.timeIntervalSinceNow>0)[NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
    [window orderOut:nil];[config.userContentController removeScriptMessageHandlerForName:@"result"];
    return probe.done&&probe.passed?0:1;
} }
