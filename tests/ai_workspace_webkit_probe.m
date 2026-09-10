// Synthetic loopback fixture only; no original App, library or browser profile.
#define main GewuProductMain
#import "PaperMonitorApp.m"
#undef main
static NSInteger checks;
static void check(BOOL ok, const char *label) {
    if (!ok) { fprintf(stderr, "FAIL: %s\n", label); exit(1); } checks++;
}
static BOOL spin(BOOL (^done)(void)) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:20];
    while (!done() && deadline.timeIntervalSinceNow > 0)
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
    return done();
}
static BOOL js(WKWebView *view, NSString *body) {
    __block BOOL finished = NO, result = NO;
    [view callAsyncJavaScript:body arguments:@{} inFrame:nil inContentWorld:WKContentWorld.pageWorld completionHandler:^(id value, NSError *error) {
        result = !error && [value respondsToSelector:@selector(boolValue)] && [value boolValue]; finished = YES;
    }];
    return spin(^BOOL { return finished; }) && result;
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        check(argc == 2, "provide a synthetic fixture JSON path");
        NSDictionary *fixture = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[1])] options:0 error:nil];
        NSString *dataRoot = [fixture[@"root"] stringByAppendingPathComponent:@"data"];
        setenv("GEWU_DATA_ROOT", dataRoot.UTF8String, 1);
        [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        PaperMonitorDelegate *delegate = [PaperMonitorDelegate new];
        delegate.url = [NSURL URLWithString:fixture[@"url"]];
        NSURLRequest *request = [delegate workspaceRequestForURL:delegate.url];
        check([[request valueForHTTPHeaderField:@"X-Gewu-Workspace"] isEqual:fixture[@"token"]], "native App supplies only its private workspace credential");
        check(![[delegate workspaceRequestForURL:[NSURL URLWithString:@"https://example.org/paper"]] valueForHTTPHeaderField:@"X-Gewu-Workspace"], "publisher URL receives no workspace credential");
        check(![[delegate workspaceRequestForURL:[NSURL URLWithString:@"http://127.0.0.1:1/"]] valueForHTTPHeaderField:@"X-Gewu-Workspace"], "different local port receives no workspace credential");
        WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
        configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
        WKWebView *view = [[WKWebView alloc] initWithFrame:NSMakeRect(0,0,1100,750) configuration:configuration];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:view.bounds styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        window.releasedWhenClosed = NO; [window.contentView addSubview:view]; [window orderBack:nil];
        [view loadRequest:request];
        check(spin(^BOOL { return !view.loading && view.URL != nil; }), "workspace loaded in real WebKit");
        check(js(view, @"for(let i=0;i<100;i++){if(document.getElementById('libraryShell') && typeof openAIAccessSettings === 'function')return true;await new Promise(r=>setTimeout(r,50));}return false"), "full authenticated UI and settings script loaded");
        check(js(view, @"return (await fetch('/api/paper?paper_id=one')).ok && (await fetch('/api/paper-files?paper_id=one')).ok"), "WebKit automatically reuses private cookie for normal paper/file APIs");
        check(js(view, @"return !(document.cookie.includes('gewu_workspace_'))"), "workspace cookie inaccessible to page JavaScript");
        check(js(view, @"openAIAccessSettings(); await new Promise(r=>setTimeout(r,300)); return document.getElementById('aiAccessBackdrop').classList.contains('open') && !!document.getElementById('aiAccessState').textContent"), "native settings action opens authenticated AI Access");
        NSURLRequest *guide = [delegate workspaceRequestForURL:[delegate.url URLByAppendingPathComponent:@"user-guide"]];
        [view loadRequest:guide]; check(spin(^BOOL { return !view.loading && [view.URL.path isEqual:@"/user-guide"]; }), "guide loaded");
        check(js(view, @"return !!document.getElementById('ai-access')"), "updated Guide available through native authenticated request");
        [window close];
        printf("Native workspace authentication: %ld checks passed with an ephemeral WebKit profile.\n", (long)checks);
    }
}
