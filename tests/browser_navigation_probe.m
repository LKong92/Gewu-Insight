#import "GewuBrowserNavigation.h"

static NSInteger checks = 0;
static void check(BOOL condition, NSString *name) {
    if (!condition) { fprintf(stderr, "FAILED: %s\n", name.UTF8String); exit(1); }
    checks++;
}

static NSHTTPURLResponse *response(NSString *mime, NSString *disposition) {
    NSMutableDictionary *headers = [@{@"Content-Type": mime} mutableCopy];
    if (disposition) headers[@"Content-Disposition"] = disposition;
    return [[NSHTTPURLResponse alloc] initWithURL:[NSURL URLWithString:@"https://example.org/document?id=123"]
        statusCode:200 HTTPVersion:@"HTTP/1.1" headerFields:headers];
}

int main(void) {
    @autoreleasepool {
        for (NSString *url in @[@"https://www.google.com/", @"https://google.com/webhp?hl=en", @"https://www.google.com/?authuser=0"])
            check(GewuBrowserGoogleHome([NSURL URLWithString:url]), @"only the real Google homepage can be fitted");
        for (NSString *url in @[@"https://www.google.com/search?q=paper", @"https://www.google.com/?q=", @"https://accounts.google.com/", @"https://www.google.com.evil.example/", @"http://www.google.com/", @"https://user@www.google.com/", @"https://www.google.com:8765/", @"https://www.nature.com/a.pdf"])
            check(!GewuBrowserGoogleHome([NSURL URLWithString:url]), @"search, sign-in, publishers and unrelated pages keep normal zoom");
        check(GewuBrowserHomeFitZoom(1, 1000, 520, 1000, 600) < .87, @"fit the complete homepage without hiding overflow");
        check(GewuBrowserHomeFitZoom(.85, 1000, 610, 1000, 610) == .85, @"a fitted page stays stable");
        check(GewuBrowserHomeFitZoom(1, 1000, 700, 1000, 600) == 1, @"no unnecessary magnification");
        check(GewuBrowserHomeFitZoom(1, 0, 0, 0, 0) == 1, @"ignore unavailable geometry");
        check(GewuBrowserHomeFitZoom(1, 1000, NAN, 1000, 600) == 1, @"ignore nonfinite geometry");
        check(GewuBrowserResponsePolicy(response(@"application/pdf", nil), YES, NO) == WKNavigationResponsePolicyAllow, @"inline PDF");
        check(GewuBrowserResponsePolicy(response(@"application/pdf", @"attachment; filename=paper.pdf"), YES, NO) == WKNavigationResponsePolicyAllow, @"attachment PDF stays inline");
        check(GewuBrowserResponsePolicy(response(@"application/pdf", @"attachment"), YES, YES) == WKNavigationResponsePolicyAllow, @"download attribute PDF stays inline after MIME is known");
        check(GewuBrowserResponsePolicy(response(@"application/pdf; charset=binary", nil), YES, YES) == WKNavigationResponsePolicyAllow, @"extensionless PDF with MIME parameters");
        check(GewuBrowserResponsePolicy(response(@"application/x-pdf", @"attachment"), YES, NO) == WKNavigationResponsePolicyAllow, @"viewable PDF alias");
        check(GewuBrowserResponsePolicy(response(@"application/pdf", nil), NO, NO) == WKNavigationResponsePolicyDownload, @"unsupported PDF remains downloadable");
        check(GewuBrowserResponsePolicy(response(@"application/zip", @"attachment"), NO, NO) == WKNavigationResponsePolicyDownload, @"archive download preserved");
        check(GewuBrowserResponsePolicy(response(@"text/html", nil), YES, NO) == WKNavigationResponsePolicyAllow, @"HTML navigation preserved");
        check(GewuBrowserResponsePolicy(response(@"text/plain", @" Attachment; filename=notes.txt"), YES, NO) == WKNavigationResponsePolicyDownload, @"non-PDF attachment preserved");
        check(GewuBrowserResponsePolicy(response(@"text/plain", nil), YES, YES) == WKNavigationResponsePolicyDownload, @"non-PDF explicit link download preserved");

        NSURL *http = [NSURL URLWithString:@"http://example.org/cgi-bin/main.plex?return=paper#top"];
        NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"https://example.org/"]];
        NSError *ats = [NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorAppTransportSecurityRequiresSecureConnection userInfo:@{NSURLErrorFailingURLErrorKey:http}];
        check([GewuBrowserHTTPSRecoveryURL(ats, request, NO).absoluteString isEqualToString:@"https://example.org/cgi-bin/main.plex?return=paper#top"], @"legacy redirect upgrades preserving path query and fragment");
        check(GewuBrowserHTTPSRecoveryURL(ats, request, YES) == nil, @"only one secure retry");
        request.HTTPMethod = @"POST";
        check(GewuBrowserHTTPSRecoveryURL(ats, request, NO) == nil, @"no POST replay");
        request.HTTPMethod = @"GET"; request.HTTPBody = [@"private form" dataUsingEncoding:NSUTF8StringEncoding];
        check(GewuBrowserHTTPSRecoveryURL(ats, request, NO) == nil, @"no body replay");
        request.HTTPBody = nil;
        request.URL = [NSURL URLWithString:@"https://other.example/"];
        check(GewuBrowserHTTPSRecoveryURL(ats, request, NO) == nil, @"no cross-host retry");
        request.URL = [NSURL URLWithString:@"http://example.org/cgi-bin/main.plex"];
        check(GewuBrowserHTTPSRecoveryURL(ats, request, NO) != nil, @"old HTTP bookmark can upgrade");
        for (NSString *url in @[@"https://example.org/", @"http://example.org:8080/", @"http://user:password@example.org/"]) {
            NSError *blocked = [NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorAppTransportSecurityRequiresSecureConnection userInfo:@{NSURLErrorFailingURLErrorKey:[NSURL URLWithString:url]}];
            check(GewuBrowserHTTPSRecoveryURL(blocked, request, NO) == nil, @"no invalid recovery or certificate downgrade");
        }
        for (NSNumber *code in @[@(NSURLErrorServerCertificateUntrusted), @(NSURLErrorTimedOut), @(NSURLErrorCannotFindHost)]) {
            NSError *failure = [NSError errorWithDomain:NSURLErrorDomain code:code.integerValue userInfo:@{NSURLErrorFailingURLErrorKey:http, NSLocalizedDescriptionKey:@"private-secret-value"}];
            check(GewuBrowserHTTPSRecoveryURL(failure, request, NO) == nil, @"no automatic security or network bypass");
            NSString *message = GewuBrowserNavigationErrorMessage(failure);
            check([message containsString:code.stringValue] && ![message containsString:@"private-secret-value"] && ![message containsString:@"return=paper"], @"specific error code without secrets or full URL");
        }
        printf("Native browser navigation policy: %ld checks passed\n", (long)checks);
    }
    return 0;
}
