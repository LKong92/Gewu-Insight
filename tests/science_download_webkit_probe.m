// Product delegates + real ephemeral WebKit DOM; every navigation is intercepted.
#define main GewuScienceProductMain
#import "PaperMonitorApp.m"
#undef main
#import <objc/runtime.h>

@interface GewuBrowserController (SessionProbe)
- (id)makePage;
- (void)disposePage:(id)page;
@end

@interface ScienceProbeView : WKWebView
@property NSURL *fixtureURL;
@property NSMutableArray<NSURLRequest *> *requests;
@property NSDictionary *payload;
@end
@implementation ScienceProbeView
- (NSURL *)URL { return self.fixtureURL ?: super.URL; }
- (WKNavigation *)loadRequest:(NSURLRequest *)request { [self.requests addObject:request]; return nil; }
- (void)evaluateJavaScript:(NSString *)script completionHandler:(void (^)(id, NSError *))completion {
    NSString *wrapped = [NSString stringWithFormat:@"((location) => (%@))(new URL('%@'))", script, self.fixtureURL.absoluteString];
    [super evaluateJavaScript:wrapped completionHandler:^(id result, NSError *error) {
        if ([result isKindOfClass:NSDictionary.class]) self.payload = result;
        if (completion) completion(result, error);
    }];
}
@end

@interface ScienceProbeDelegate : PaperMonitorDelegate
@property NSString *failure;
@property NSArray *discovered;
@end
@implementation ScienceProbeDelegate
- (void)failHiddenPublisherDownload:(NSString *)message { self.failure = message; }
- (void)appendLauncherLogMessage:(NSString *)message {}
- (void)completeHiddenPublisherSupplementDiscoveryWithURLs:(NSArray *)urls { self.discovered = urls; }
@end

static NSUInteger checks = 0;
static void check(BOOL ok, const char *label) { if (!ok) { fprintf(stderr, "FAIL: %s\n", label); exit(1); } checks++; }
static BOOL spin(BOOL (^done)(void)) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:12];
    while (!done() && deadline.timeIntervalSinceNow > 0) [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
    return done();
}
static ScienceProbeView *page(NSString *html) {
    WKWebViewConfiguration *config = [WKWebViewConfiguration new];
    config.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    ScienceProbeView *view = [[ScienceProbeView alloc] initWithFrame:NSMakeRect(0, 0, 1280, 900) configuration:config];
    view.fixtureURL = [NSURL URLWithString:@"https://www.science.org/doi/10.1126/science.fixture"];
    view.requests = [NSMutableArray array];
    [view loadHTMLString:html baseURL:nil];
    check(spin(^BOOL { return !view.loading; }), "fixture loaded");
    return view;
}
static void inspect(ScienceProbeDelegate *d, ScienceProbeView *view, NSString *target) {
    d.hiddenPublisherWebView = view;
    d.hiddenPublisherContext = @{@"publisher_download_kind": @"aaas-published-pdf", @"publisher_download_target_url": target};
    d.hiddenPublisherDiscoveryVisitedURLs = [NSMutableSet set];
    d.hiddenPublisherDiscoveryPageRetryCount = 0;
    d.hiddenPublisherDiscoveryDepth = 0;
    [d inspectHiddenPublisherMainPage];
    check(spin(^BOOL { return view.payload != nil; }), "product page inspection completed");
}

static void inspectNature(ScienceProbeDelegate *d, ScienceProbeView *view, NSString *kind) {
    d.failure = nil;
    d.discovered = nil;
    view.fixtureURL = [NSURL URLWithString:@"https://www.nature.com/articles/s41563-026-02522-9"];
    d.hiddenPublisherWebView = view;
    d.hiddenPublisherContext = @{@"publisher_download_kind": kind, @"publisher_download_name": @"nature",
        @"publisher_download_target_url": @"https://www.nature.com/articles/s41563-026-02522-9.pdf"};
    d.hiddenPublisherDiscoveryVisitedURLs = [NSMutableSet set];
    d.hiddenPublisherDiscoveryPageRetryCount = 0;
    d.hiddenPublisherDiscoveryDepth = 0;
    if ([kind isEqual:@"publisher-main-pdf"]) [d inspectHiddenPublisherMainPage];
    else [d inspectHiddenGenericSupplementPage];
    check(spin(^BOOL { return view.payload != nil; }), "Nature DOM inspected by product delegate");
}

int main(void) { @autoreleasepool {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    ScienceProbeDelegate *d = [ScienceProbeDelegate new];
    // Redirect only the profile provider to ephemeral storage. Exercise the
    // actual Browser and download configuration callers without user cookies.
    WKWebsiteDataStore *store = WKWebsiteDataStore.nonPersistentDataStore;
    Method storeMethod = class_getClassMethod(GewuBrowserController.class, @selector(externalWebsiteDataStore));
    IMP oldStore = method_setImplementation(storeMethod, imp_implementationWithBlock(^WKWebsiteDataStore *(id cls) { return store; }));
    Method loadMethod = class_getInstanceMethod(WKWebView.class, @selector(loadRequest:));
    IMP oldLoad = method_setImplementation(loadMethod, imp_implementationWithBlock(^WKNavigation *(id view, NSURLRequest *request) { return nil; }));
    NSDictionary *context = @{@"publisher_download_kind":@"aaas-published-pdf"};
    NSDictionary *request = @{@"token":@"fixture", @"url":@"https://www.science.org/doi/10.1126/science.fixture", @"context":context};
    [d startHiddenPublisherDownload:request];
    WKWebView *downloadView = d.hiddenPublisherWebView;
    check(downloadView.configuration.websiteDataStore == store, "download before first Browser tab uses its external profile");
    GewuBrowserController *browser = [GewuBrowserController new];
    id browserPage = [browser makePage];
    WKWebView *browserView = [browserPage valueForKey:@"view"];
    check(browserView.configuration.websiteDataStore == store, "Browser and download share the same website store");
    check([browserView.configuration.applicationNameForUserAgent isEqual:downloadView.configuration.applicationNameForUserAgent], "Browser and download use the same WebKit identity");
    check(browserView.configuration.userContentController != downloadView.configuration.userContentController, "external configurations have independent script controllers");
    check(downloadView.configuration.userContentController.userScripts.count == 0, "download imports no workspace scripts");
    NSHTTPCookie *cookie = [NSHTTPCookie cookieWithProperties:@{NSHTTPCookieDomain:@"science.fixture.invalid", NSHTTPCookiePath:@"/", NSHTTPCookieName:@"fixture-session", NSHTTPCookieValue:@"synthetic-only"}];
    __block BOOL cookieWritten = NO;
    [browserView.configuration.websiteDataStore.httpCookieStore setCookie:cookie completionHandler:^{ cookieWritten = YES; }];
    check(spin(^BOOL { return cookieWritten; }), "synthetic Browser session stored");
    __block NSArray *cookies;
    [downloadView.configuration.websiteDataStore.httpCookieStore getAllCookies:^(NSArray *values) { cookies = values; }];
    check(spin(^BOOL { return cookies != nil; }) && cookies.count == 1 && [((NSHTTPCookie *)cookies[0]).value isEqual:@"synthetic-only"], "background download observes Browser session cookie");
    __block NSArray *separateCookies;
    WKWebsiteDataStore *workspaceStore = WKWebsiteDataStore.nonPersistentDataStore;
    [workspaceStore.httpCookieStore getAllCookies:^(NSArray *values) { separateCookies = values; }];
    check(spin(^BOOL { return separateCookies != nil; }) && separateCookies.count == 0, "trusted workspace store stays separate");
    [d clearHiddenPublisherDownload];
    [d startHiddenPublisherDownload:@{@"token": @"nature-fixture", @"url": @"https://www.nature.com/articles/s41563-026-02522-9",
        @"context": @{@"publisher_download_kind": @"publisher-main-pdf", @"publisher_download_name": @"nature"}}];
    check(d.hiddenPublisherWebView.configuration.websiteDataStore == store, "Nature shares Browser session");
    check(d.hiddenPublisherWebView.configuration.userContentController.userScripts.count == 0, "Nature imports no workspace scripts");
    [d clearHiddenPublisherDownload];
    for (NSString *publisher in @[@"aps", @"acs", @"wiley", @"cpl", @"cpb", @"elsevier", @"oup"]) {
        NSDictionary *hosts = @{@"aps": @"journals.aps.org", @"acs": @"pubs.acs.org", @"wiley": @"onlinelibrary.wiley.com", @"cpl": @"cpl.iphy.ac.cn", @"cpb": @"cpb.iphy.ac.cn", @"elsevier": @"www.sciencedirect.com", @"oup": @"academic.oup.com"};
        [d startHiddenPublisherDownload:@{@"token": @"session-fixture", @"url": [NSString stringWithFormat:@"https://%@/article", hosts[publisher]], @"context": @{@"publisher_download_kind": @"publisher-main-pdf", @"publisher_download_name": publisher}}];
        check(d.hiddenPublisherWebView.configuration.websiteDataStore == store, "every supported publisher shares Browser session");
        check([d.hiddenPublisherWebView.configuration.applicationNameForUserAgent isEqual:browserView.configuration.applicationNameForUserAgent], "every publisher shares Browser identity");
        check(d.hiddenPublisherWebView.configuration.userContentController.userScripts.count == 0, "external pages never inherit workspace scripts");
        [d clearHiddenPublisherDownload];
    }
    [browser disposePage:browserPage];
    method_setImplementation(loadMethod, oldLoad);
    method_setImplementation(storeMethod, oldStore);
    NSString *mainURL = @"https://www.science.org/doi/pdf/10.1126/science.fixture?download=true";
    NSString *smURL = @"https://www.science.org/doi/suppl/10.1126/science.fixture/suppl_file/science.fixture_sm.pdf";
    NSString *html = [NSString stringWithFormat:@"<title>Article</title><meta name='citation_pdf_url' content='%@'><a href='%@'>View PDF</a><a href='%@'>PDF</a><a href='/x/science.fixture_mdar_reproducibility_checklist.pdf'>PDF</a>", smURL, mainURL, smURL];
    ScienceProbeView *view = page(html);
    inspect(d, view, mainURL);
    check([view.payload[@"urls"] isEqual:@[mainURL]], "main discovery excludes supplement metadata, SM and MDAR");
    check([view.requests.firstObject.URL.absoluteString isEqual:mainURL], "article session requests the main PDF");
    check([view.requests.firstObject.allHTTPHeaderFields[@"Referer"] isEqual:view.fixtureURL.absoluteString], "article referer retained");
    d.hiddenPublisherWebView = nil;

    view = page([NSString stringWithFormat:@"<title>Article</title><a href='%@'>PDF</a>", smURL]);
    inspect(d, view, mainURL);
    check([view.payload[@"urls"] count] == 0 && ![view.payload[@"clicked"] boolValue], "supplement-only page never clicks its PDF button as main");
    d.hiddenPublisherWebView = nil;

    view = page(@"<title>Just a moment...</title><div id='challenge-stage'></div>");
    inspect(d, view, mainURL);
    check([view.payload[@"blocked"] boolValue] && view.requests.count == 0, "verification page is not bypassed or used for supplement fallback");
    check(spin(^BOOL { return d.failure != nil; }), "verification stops after bounded checks instead of the full timeout");
    check([d.failure containsString:@"Open Website in Gewu Browser"] && [d.failure containsString:@"retry Download"], "verification guidance names the shared Browser session");
    d.hiddenPublisherWebView = nil;

    for (NSNumber *restricted in @[@YES, @NO]) {
        d.failure = nil;
        view = page(restricted.boolValue
            ? @"<h1>Authorization Required</h1><p>We need you to provide your credentials before accessing this content.</p><a href='/login'>Sign in</a>"
            : @"<h1>Research article</h1><a href='/login'>Sign in</a><footer>Authorization Required for other services</footer>");
        view.fixtureURL = [NSURL URLWithString:@"https://journals.aps.org/prl/abstract/10.1103/fixture"];
        d.hiddenPublisherWebView = view;
        d.hiddenPublisherContext = @{@"publisher_download_kind": @"publisher-main-pdf", @"publisher_download_name": @"aps",
            @"publisher_download_target_url": @"https://journals.aps.org/prl/pdf/10.1103/fixture"};
        d.hiddenPublisherDiscoveryVisitedURLs = [NSMutableSet set];
        d.hiddenPublisherDiscoveryPageRetryCount = 0;
        d.hiddenPublisherDiscoveryDepth = 0;
        [d inspectHiddenPublisherMainPage];
        if (restricted.boolValue) {
            check(spin(^BOOL { return d.failure != nil; }), "APS authorization page stops without timeout");
            check([d.failure containsString:@"institutional or personal subscription"] && view.requests.count == 0,
                  "APS authorization failure gives access guidance and does not chase links");
        } else {
            check(spin(^BOOL { return view.requests.count > 0; }) && d.failure == nil,
                  "ordinary sign-in links do not mark an accessible APS article as restricted");
        }
        d.hiddenPublisherWebView = nil;
    }

    d.hiddenPublisherDownload = (id)[NSObject new];
    d.hiddenPublisherContext = @{@"publisher_download_kind": @"aaas-published-pdf"};
    NSURLResponse *response = [[NSURLResponse alloc] initWithURL:[NSURL URLWithString:smURL] MIMEType:@"application/pdf" expectedContentLength:4096 textEncodingName:nil];
    __block NSURL *destination = [NSURL URLWithString:@"file:///not-used"];
    [d download:d.hiddenPublisherDownload decideDestinationUsingResponse:response suggestedFilename:@"science.fixture_sm.pdf" completionHandler:^(NSURL *url) { destination = url; }];
    check(destination == nil && [d.failure containsString:@"instead of the main"], "redirected supplement is rejected before attachment");

    d.failure = nil;
    d.hiddenPublisherContext = @{@"publisher_download_kind": @"aaas-published-pdf"};
    response = [[NSURLResponse alloc] initWithURL:[NSURL URLWithString:mainURL] MIMEType:@"application/pdf" expectedContentLength:4096 textEncodingName:nil];
    [d download:d.hiddenPublisherDownload decideDestinationUsingResponse:response suggestedFilename:@"science.fixture.pdf" completionHandler:^(NSURL *url) { destination = url; }];
    check(destination != nil && [destination.lastPathComponent hasPrefix:@"gewu-publisher-"], "native temporary name uses Gewu");
    check([d.hiddenPublisherContext[@"publisher_download_filename"] isEqual:@"science.fixture.pdf"], "publisher filename retained separately");
    check([d.hiddenPublisherContext[@"publisher_download_final_url"] isEqual:mainURL], "actual PDF response URL retained");

    d.hiddenPublisherContext = @{@"publisher_download_kind": @"aaas-supplement-pdf"};
    response = [[NSURLResponse alloc] initWithURL:[NSURL URLWithString:smURL] MIMEType:@"application/pdf" expectedContentLength:4096 textEncodingName:nil];
    [d download:d.hiddenPublisherDownload decideDestinationUsingResponse:response suggestedFilename:@"science.fixture_sm.pdf" completionHandler:^(NSURL *url) { destination = url; }];
    check(destination != nil && d.failure == nil, "supplement download remains allowed in its own stage");
    d.hiddenPublisherContext = @{@"publisher_download_kind": @"aaas-published-pdf", @"publisher_download_response_detail": @"HTTP 403 at www.science.org/doi/pdf/10.1126/science.fixture."};
    [d hiddenPublisherDownloadTimedOut:nil];
    check([d.failure containsString:@"main PDF was not obtained"] && [d.failure containsString:@"HTTP 403"], "main failure reports access guidance and actual response status");
    d.hiddenPublisherDownload = nil;
    NSString *natureMain = @"https://www.nature.com/articles/s41563-026-02522-9.pdf";
    NSString *natureReference = @"https://www.nature.com/articles/s41563-026-02522-9_reference.pdf";
    NSString *natureSM = @"https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41563-026-02522-9/MediaObjects/41563_2026_2522_MOESM1_ESM.pdf";
    NSString *peerReview = @"https://static-content.springer-cdn.com/esm/art%3A10.1038%2Fs41563-026-02522-9/MediaObjects/41563_2026_2522_MOESM2_ESM.pdf";
    view = page([NSString stringWithFormat:@"<title>Nature article</title><meta name='citation_pdf_url' content='%@'><a href='%@'>PDF</a><a href='%@'>Supplementary information</a><a href='%@'>Peer Review File (PDF)</a><a href='/articles/unrelated.pdf'>PDF</a>", natureReference, natureMain, natureSM, peerReview]);
    inspectNature(d, view, @"publisher-main-pdf");
    check([view.requests.firstObject.URL.absoluteString isEqual:natureMain], "Nature published PDF precedes accepted reference version");
    check([view.payload[@"urls"] containsObject:natureReference] && ![view.payload[@"urls"] containsObject:natureSM] && ![view.payload[@"urls"] containsObject:peerReview], "Nature main discovery excludes secondary metadata and links");
    check(![d isNatureMainURL:[NSURL URLWithString:@"https://www.nature.com/articles/unrelated.pdf"]], "related article cannot replace requested main");
    check([d isNatureMainURL:[NSURL URLWithString:natureReference]], "explicit accepted reference remains eligible");
    d.hiddenPublisherWebView = nil;

    view = page([NSString stringWithFormat:@"<title>Nature article</title><a href='%@'>Supplementary information (PDF)</a><a href='%@'>Peer Review File (PDF)</a><a href='%@'>Download PDF</a><a href='https://example.invalid/moesm1_esm.pdf'>Supplementary PDF</a>", natureSM, peerReview, natureMain]);
    inspectNature(d, view, @"publisher-supplement-discovery");
    check(spin(^BOOL { return d.discovered != nil; }) && [d.discovered isEqual:@[natureSM]], "Nature supplement finds official CDN file and excludes peer review, main and foreign host");
    check(![d isAllowedPublisherURL:[NSURL URLWithString:@"https://media.springernature.com.evil.invalid/a.pdf"] publisher:@"nature"], "lookalike CDN rejected");
    check(![d isAllowedPublisherURL:[NSURL URLWithString:@"http://www.nature.com/articles/a.pdf"] publisher:@"nature"], "insecure Nature request rejected");
    check([d isAllowedPublisherURL:[NSURL URLWithString:peerReview] publisher:@"nature"], "legacy official supplement CDN accepted");
    d.hiddenPublisherWebView = nil;

    view = page(@"<title>Just a moment...</title><div id='challenge-stage'></div>");
    inspectNature(d, view, @"publisher-main-pdf");
    check(view.requests.count == 0 && [view.payload[@"blocked"] boolValue], "Nature verification does not navigate to PDF");
    check(spin(^BOOL { return d.failure != nil; }) && [d.failure containsString:@"Nature requires browser verification"], "Nature verification fails with bounded actionable guidance");
    d.hiddenPublisherWebView = nil;

    view = page(@"<title>Nature article</title><a href='#supplementary-information'>Supplementary information</a><a href='https://media.springernature.com/esm/MOESM2_ESM.mp4'>Supplementary Movie PDF</a><a href='https://media.springernature.com/esm/MOESM3_ESM.zip'>Supplementary Data</a><a href='https://media.springernature.com/esm/MOESM4_ESM.docx'>Supplementary Word</a>");
    inspectNature(d, view, @"publisher-supplement-discovery");
    check(spin(^BOOL { return d.discovered != nil; }) && d.discovered.count == 0 && view.requests.count == 0 && d.failure == nil, "non-PDF attachments are skipped without navigation or download failure");
    d.hiddenPublisherWebView = nil;

    view = page(@"<title>Access denied</title>");
    inspectNature(d, view, @"publisher-supplement-discovery");
    check(spin(^BOOL { return d.failure != nil; }) && d.discovered == nil, "blocked Nature supplementary page is not an empty success");
    d.hiddenPublisherWebView = nil;

    d.failure = nil;
    d.hiddenPublisherDownload = (id)[NSObject new];
    d.hiddenPublisherContext = @{@"publisher_download_kind": @"publisher-main-pdf", @"publisher_download_name": @"nature", @"publisher_download_target_url": natureMain};
    response = [[NSURLResponse alloc] initWithURL:[NSURL URLWithString:natureSM] MIMEType:@"application/pdf" expectedContentLength:4096 textEncodingName:nil];
    [d download:d.hiddenPublisherDownload decideDestinationUsingResponse:response suggestedFilename:@"41563_2026_2522_MOESM1_ESM.pdf" completionHandler:^(NSURL *url) { destination = url; }];
    check(destination == nil && [d.failure containsString:@"instead of the main"], "Nature supplement redirect cannot attach as main");
    d.failure = nil;
    response = [[NSURLResponse alloc] initWithURL:[NSURL URLWithString:natureMain] MIMEType:@"application/pdf" expectedContentLength:4096 textEncodingName:nil];
    [d download:d.hiddenPublisherDownload decideDestinationUsingResponse:response suggestedFilename:@"s41563-026-02522-9.pdf" completionHandler:^(NSURL *url) { destination = url; }];
    check(destination != nil && d.failure == nil, "Nature main PDF response allowed");
    d.hiddenPublisherDownload = nil;
    printf("Science native/WebKit probe: %lu checks passed; no live App, user data or external requests.\n", (unsigned long)checks);
} return 0; }
