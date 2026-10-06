#import <Foundation/Foundation.h>
#import <WebKit/WebKit.h>
#import <arpa/inet.h>
#import <math.h>

// Home fitting must never affect search results, account pages, or publishers.
static inline BOOL GewuBrowserGoogleHome(NSURL *url) {
    if (![url.scheme.lowercaseString isEqualToString:@"https"] || url.user.length || url.password.length
        || (url.port && url.port.integerValue != 443)
        || ![@[@"google.com", @"www.google.com"] containsObject:url.host.lowercaseString]
        || ![@[@"", @"/", @"/webhp"] containsObject:url.path]) return NO;
    for (NSURLQueryItem *item in [NSURLComponents componentsWithURL:url resolvingAgainstBaseURL:NO].queryItems)
        if ([item.name isEqualToString:@"q"]) return NO;
    return YES;
}

static inline double GewuBrowserHomeFitZoom(double zoom, double width, double height, double contentWidth, double contentHeight) {
    if (!isfinite(zoom) || !isfinite(width) || !isfinite(height) || !isfinite(contentWidth) || !isfinite(contentHeight)
        || zoom <= 0 || width <= 2 || height <= 2 || contentWidth <= 0 || contentHeight <= 0) return zoom;
    if (contentWidth <= width && contentHeight <= height) return zoom;
    return MAX(.25, zoom * MIN((width - 2) / MAX(width, contentWidth), (height - 2) / MAX(height, contentHeight)));
}

static inline BOOL GewuBrowserCanRetainHomeForRequest(NSURLRequest *request) {
    return [request.HTTPMethod isEqualToString:@"GET"] && !request.HTTPBody.length && !request.HTTPBodyStream;
}

// WebKit-owned child documents inherit their embedding page's security context.
// They are not public addresses and must never become address-bar destinations.
static inline BOOL GewuBrowserInternalFrameURL(NSURL *url) {
    return [url.absoluteString isEqualToString:@"about:blank"]
        || [url.absoluteString isEqualToString:@"about:srcdoc"];
}

static inline BOOL GewuBrowserPublicURL(NSURL *url) {
    if (!url || ![@[@"http", @"https"] containsObject:url.scheme.lowercaseString]
        || url.user.length || url.password.length || url.absoluteString.length > 8192) return NO;
    NSString *host = url.host.lowercaseString;
    while ([host hasSuffix:@"."]) host = [host substringToIndex:host.length - 1];
    if (!host.length || [host isEqualToString:@"localhost"] || [host hasSuffix:@".localhost"]
        || [host hasSuffix:@".local"] || [host hasSuffix:@".internal"]) return NO;
    NSString *bare = [[host stringByReplacingOccurrencesOfString:@"[" withString:@""] stringByReplacingOccurrencesOfString:@"]" withString:@""];
    struct in_addr v4;
    if (inet_aton(bare.UTF8String, &v4)) {
        uint32_t ip = ntohl(v4.s_addr);
        return !((ip >> 24) == 0 || (ip >> 24) == 10 || (ip >> 24) == 127
            || (ip >> 16) == 0xA9FE || (ip >> 20) == 0xAC1 || (ip >> 16) == 0xC0A8
            || (ip >> 22) == 0x191 || (ip >> 24) >= 224);
    }
    struct in6_addr v6;
    if (inet_pton(AF_INET6, bare.UTF8String, &v6) == 1) {
        return !IN6_IS_ADDR_LOOPBACK(&v6) && !IN6_IS_ADDR_UNSPECIFIED(&v6)
            && !IN6_IS_ADDR_LINKLOCAL(&v6) && !IN6_IS_ADDR_MULTICAST(&v6)
            && !IN6_IS_ADDR_V4MAPPED(&v6) && (v6.s6_addr[0] & 0xFE) != 0xFC;
    }
    return [host containsString:@"."];
}

// Blob URLs are accepted only from their public creating origin, never from the
// address bar, opaque origins or a local workspace. WebKit still enforces access.
static inline BOOL GewuBrowserBlobURL(NSURL *url, NSURL *source) {
    if (![url.scheme.lowercaseString isEqual:@"blob"] || !GewuBrowserPublicURL(source)) return NO;
    NSURL *origin = [NSURL URLWithString:[url.absoluteString substringFromIndex:5]];
    if (!GewuBrowserPublicURL(origin)) return NO;
    NSNumber *originPort = origin.port ?: @([origin.scheme.lowercaseString isEqual:@"https"] ? 443 : 80);
    NSNumber *sourcePort = source.port ?: @([source.scheme.lowercaseString isEqual:@"https"] ? 443 : 80);
    return [origin.scheme.lowercaseString isEqual:source.scheme.lowercaseString]
        && [origin.host.lowercaseString isEqual:source.host.lowercaseString] && [originPort isEqual:sourcePort];
}

static inline BOOL GewuBrowserPDFResponse(NSURLResponse *response) {
    NSString *mime = [[response.MIMEType componentsSeparatedByString:@";"].firstObject.lowercaseString stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
    return [@[@"application/pdf", @"application/x-pdf"] containsObject:mime ?: @""];
}

// Keep normal inline documents streaming in WebKit. Attachment/download PDFs
// use that same WebKit request's download, then the controller displays its bytes.
static inline WKNavigationResponsePolicy GewuBrowserResponsePolicy(NSURLResponse *response, BOOL canShowMIMEType, BOOL requestedDownload) {
    NSString *disposition = [response isKindOfClass:NSHTTPURLResponse.class]
        ? [(NSHTTPURLResponse *)response valueForHTTPHeaderField:@"Content-Disposition"] : @"";
    BOOL attachment = [[disposition.lowercaseString stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet] hasPrefix:@"attachment"];
    if (canShowMIMEType && [response.MIMEType.lowercaseString isEqual:@"text/html"] && !attachment)
        return WKNavigationResponsePolicyAllow; // The download may lead to sign-in or consent first.
    return (!canShowMIMEType || attachment || requestedDownload) ? WKNavigationResponsePolicyDownload : WKNavigationResponsePolicyAllow;
}

// Recover an ATS-blocked HTTP hop with one same-host HTTPS GET, never an HTTP
// fallback, POST replay, certificate exception, or cross-host header transfer.
static inline NSURL *GewuBrowserHTTPSRecoveryURL(NSError *error, NSURLRequest *request, BOOL alreadyRetried) {
    if (alreadyRetried || ![error.domain isEqualToString:NSURLErrorDomain]
        || error.code != NSURLErrorAppTransportSecurityRequiresSecureConnection
        || ![request.HTTPMethod isEqualToString:@"GET"] || request.HTTPBody.length || request.HTTPBodyStream) return nil;
    id value = error.userInfo[NSURLErrorFailingURLErrorKey];
    NSURL *failed = [value isKindOfClass:NSURL.class] ? value : nil;
    if (!failed || ![failed.scheme.lowercaseString isEqualToString:@"http"]
        || ![failed.host.lowercaseString isEqualToString:request.URL.host.lowercaseString]
        || failed.user.length || failed.password.length || (failed.port && failed.port.integerValue != 80)) return nil;
    NSURLComponents *secure = [NSURLComponents componentsWithURL:failed resolvingAgainstBaseURL:NO];
    secure.scheme = @"https"; secure.port = nil;
    return secure.URL;
}

static inline NSString *GewuBrowserNavigationErrorMessage(NSError *error) {
    NSString *reason = @"The webpage could not load. Retry, or use Open in Safari if the site requires another browser.";
    if ([error.domain isEqualToString:NSURLErrorDomain]) {
        switch (error.code) {
            case NSURLErrorAppTransportSecurityRequiresSecureConnection:
                reason = @"The website redirected to an unencrypted HTTP address. A secure HTTPS page could not be opened; the app's connection protections remain enabled."; break;
            case NSURLErrorSecureConnectionFailed:
            case NSURLErrorServerCertificateHasBadDate:
            case NSURLErrorServerCertificateUntrusted:
            case NSURLErrorServerCertificateHasUnknownRoot:
            case NSURLErrorServerCertificateNotYetValid:
                reason = @"The website's secure connection or certificate could not be verified. Certificate checks have not been bypassed."; break;
            case NSURLErrorTimedOut: reason = @"The website took too long to respond. Retry and check this site's network route if the problem continues."; break;
            case NSURLErrorCannotFindHost:
            case NSURLErrorDNSLookupFailed: reason = @"The website's address could not be resolved. Check the address and your DNS or network route."; break;
            case NSURLErrorNotConnectedToInternet: reason = @"The network connection is offline. Reconnect, then retry."; break;
            case NSURLErrorNetworkConnectionLost:
            case NSURLErrorCannotConnectToHost: reason = @"The connection to this website failed. Retry and check this site's network route if needed."; break;
            case NSURLErrorHTTPTooManyRedirects: reason = @"The website redirected too many times. The site's sign-in or redirect flow could not finish."; break;
        }
    }
    // Do not expose NSError.userInfo/localizedDescription: either can contain
    // private URLs, authorization parameters, cookies, or other website data.
    return [NSString stringWithFormat:@"%@ (%@ %ld)", reason, error.domain, (long)error.code];
}
