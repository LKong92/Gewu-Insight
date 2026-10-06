// Full product-page startup, with an ephemeral profile and synthetic server.
#import <AppKit/AppKit.h>
#import <WebKit/WebKit.h>
@interface StartupProbe : NSObject <WKScriptMessageHandler, WKNavigationDelegate>
@property NSString *status;
@property NSMutableArray *errors;
@property NSURL *base;
@end
@implementation StartupProbe
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    if ([message.name isEqual:@"appReady"]) self.status = message.body[@"status"];
    else [self.errors addObject:message.body ?: @"Unknown JS error"];
}
- (void)webView:(WKWebView *)view decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))handler {
    NSURL *url = action.request.URL;
    handler([url.host isEqual:self.base.host] && [url.port isEqual:self.base.port] ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}
@end
static BOOL spin(BOOL (^done)(void)) {
    NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:20];
    while (!done() && deadline.timeIntervalSinceNow>0) [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.02]];
    return done();
}
static void check(BOOL condition, const char *label) { if (!condition) {fprintf(stderr,"FAIL: %s\n",label);exit(1);} }
static BOOL js(WKWebView *view, NSString *script) {
    __block BOOL done=NO,result=NO;
    [view evaluateJavaScript:script completionHandler:^(id value,NSError *error){result=!error && [value respondsToSelector:@selector(boolValue)] && [value boolValue];done=YES;}];
    return spin(^BOOL{return done;}) && result;
}
int main(int argc,const char *argv[]) { @autoreleasepool {
    check(argc==2,"fixture required");
    NSDictionary *fixture=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[1])] options:0 error:nil];
    [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    StartupProbe *probe=[StartupProbe new];probe.errors=[NSMutableArray new];probe.base=[NSURL URLWithString:fixture[@"url"]];
    WKWebViewConfiguration *config=[WKWebViewConfiguration new];config.websiteDataStore=WKWebsiteDataStore.nonPersistentDataStore;
    [config.userContentController addScriptMessageHandler:probe name:@"appReady"];
    [config.userContentController addScriptMessageHandler:probe name:@"qaError"];
    [config.userContentController addUserScript:[[WKUserScript alloc] initWithSource:@"window.addEventListener('error',e=>{if(e.error)window.webkit.messageHandlers.qaError.postMessage(String(e.error));});window.addEventListener('unhandledrejection',e=>window.webkit.messageHandlers.qaError.postMessage(String(e.reason)));" injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:YES]];
    WKWebView *view=[[WKWebView alloc] initWithFrame:NSMakeRect(0,0,1100,750) configuration:config];view.navigationDelegate=probe;
    NSWindow *window=[[NSWindow alloc] initWithContentRect:view.bounds styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];window.releasedWhenClosed=NO;[window.contentView addSubview:view];[window orderFront:nil];
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:probe.base];[request setValue:fixture[@"token"] forHTTPHeaderField:@"X-Gewu-Workspace"];
    [view loadRequest:request];
    if (!spin(^BOOL{return probe.status!=nil;})) {
        fprintf(stderr,"Startup timeout; URL=%s; loading=%d; JS errors=%s\n",view.URL.absoluteString.UTF8String,view.loading,probe.errors.description.UTF8String);
        __block BOOL inspected=NO;
        [view evaluateJavaScript:@"JSON.stringify({ready:document.readyState,hidden:document.hidden,cover:document.getElementById('appStartupCover')?.innerText,body:document.body?.innerText.slice(0,600)})" completionHandler:^(id value,NSError *error){fprintf(stderr,"Page state: %s; evaluation: %s\n",[value description].UTF8String,error.description.UTF8String);inspected=YES;}];
        spin(^BOOL{return inspected;});
        check(NO,"full page must send a native ready/error result");
    }
    if (![probe.status isEqual:@"ready"] || probe.errors.count) {fprintf(stderr,"Startup status %s; errors %s\n",probe.status.UTF8String,probe.errors.description.UTF8String);return 1;}
    check(js(view,@"appBootCompleted && !document.getElementById('appStartupCover') && document.getElementById('libraryDetail').textContent.includes('Folder')"),"startup cover removed and default folder rendered");
    NSString *select=[NSString stringWithFormat:@"state.librarySelection={type:'folder',id:%@};renderLibraryDetail();document.getElementById('libraryDetail').textContent.includes('Nested fixture')",fixture[@"folder_id"]];
    check(js(view,select),"nested folder selection renders without paper metadata");
    check(js(view,@"state.librarySelection=null;renderLibraryDetail();document.getElementById('libraryDetail').textContent.includes('Select a folder or paper')"),"empty selection renders normally");
    check(probe.errors.count==0,"no runtime JS errors after folder transitions");
    [window close];printf("Full product WebKit startup: native ready, removed cover, default/nested/empty selections, zero JS errors passed.\n");
}return 0;}
