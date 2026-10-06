// Product delegates + real ephemeral WebKit DOM; every navigation is intercepted.
#define main GewuScienceProductMain
#import "PaperMonitorApp.m"
#undef main

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
@end
@implementation ScienceProbeDelegate
- (void)failHiddenPublisherDownload:(NSString *)message { self.failure = message; }
- (void)appendLauncherLogMessage:(NSString *)message {}
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

int main(void) { @autoreleasepool {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    ScienceProbeDelegate *d = [ScienceProbeDelegate new];
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
    d.hiddenPublisherWebView = nil;

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
    printf("Science native/WebKit probe: %lu checks passed; no live App, user data or external requests.\n", (unsigned long)checks);
} return 0; }
