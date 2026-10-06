// Actual navigation/recovery delegates, private ephemeral WebKit and loopback fixture.
#define main GewuRecoveryProductMain
#import "PaperMonitorApp.m"
#undef main
@interface RecoveryDelegate : PaperMonitorDelegate
@end
@implementation RecoveryDelegate
- (void)appendLauncherLogMessage:(NSString *)message {}
- (void)refreshLibraryNamingRuleMenu {}
- (void)closeNativeQuickLookNotifyingWeb:(BOOL)notify {}
@end
static void check(BOOL ok,const char *label){if(!ok){fprintf(stderr,"FAIL: %s\n",label);exit(1);}}
static BOOL spin(BOOL (^done)(void)) {
    NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:15];
    while(!done()&&deadline.timeIntervalSinceNow>0) [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
    return done();
}
static BOOL authenticated(WKWebView *view) {
    __block BOOL done=NO,ok=NO;
    [view evaluateJavaScript:@"!!document.getElementById('authenticated')" completionHandler:^(id value,NSError *error){ok=!error&&[value boolValue];done=YES;}];
    return spin(^BOOL{return done;})&&ok;
}
int main(int argc,const char *argv[]){@autoreleasepool{
    check(argc==2,"fixture path required");
    NSDictionary *f=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[1])] options:0 error:nil];
    setenv("GEWU_DATA_ROOT",[f[@"data"] UTF8String],1);
    [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    RecoveryDelegate *d=[RecoveryDelegate new];d.url=[NSURL URLWithString:f[@"url"]];
    WKWebViewConfiguration *c=[WKWebViewConfiguration new];c.websiteDataStore=WKWebsiteDataStore.nonPersistentDataStore;
    d.webView=[[WKWebView alloc] initWithFrame:NSMakeRect(0,0,1000,700) configuration:c];d.webView.navigationDelegate=d;
    d.window=[[NSWindow alloc] initWithContentRect:d.webView.bounds styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];d.window.releasedWhenClosed=NO;[d.window.contentView addSubview:d.webView];[d.window orderBack:nil];
    [d.webView loadRequest:[d workspaceRequestForURL:d.url]];
    check(spin(^BOOL{return !d.webView.loading&&d.webView.URL!=nil;})&&authenticated(d.webView),"initial authenticated document");
    __block BOOL cleared=NO;
    [c.websiteDataStore removeDataOfTypes:[NSSet setWithObject:WKWebsiteDataTypeCookies] modifiedSince:NSDate.distantPast completionHandler:^{cleared=YES;}];
    check(spin(^BOOL{return cleared;}),"synthetic cookies cleared");
    [d.webView loadRequest:[NSURLRequest requestWithURL:d.url]];
    check(spin(^BOOL{return !d.webView.loading;})&&authenticated(d.webView),"cookie-free same-origin navigation recovers credential");
    [d webViewWebContentProcessDidTerminate:d.webView];
    check(spin(^BOOL{return !d.webView.loading;})&&authenticated(d.webView),"process termination callback reloads authenticated document");
    check(!d.ownedServerTask&&d.serverRestartAttempts==0,"recovery never starts/restarts server");
    [d.window close];printf("Real WebKit recovery: authenticated initial load, lost-cookie navigation, termination recovery, no server restart passed.\n");
}return 0;}
