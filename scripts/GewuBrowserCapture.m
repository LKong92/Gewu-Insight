#import "GewuBrowserCapture.h"
#import "GewuBrowserNavigation.h"

@interface GewuBrowserCapture () <NSURLSessionTaskDelegate>
@property(nonatomic, strong) WKDownload *download;
@property(nonatomic, strong) NSURLSession *uploader;
@property(nonatomic, strong) NSURL *directory;
@property(nonatomic, strong) NSURL *file;
@property(nonatomic, strong) NSURL *endpoint;
@property(nonatomic, copy) NSString *uploadToken;
@property(nonatomic, copy) NSString *filename;
@property(nonatomic, copy) void (^completion)(NSString *error);
@property(nonatomic, strong) NSTimer *timer;
@end

@implementation GewuBrowserCapture
- (void)downloadURL:(NSURL *)url fromView:(WKWebView *)view workspaceURL:(NSURL *)workspaceURL
       uploadToken:(NSString *)token completion:(void (^)(NSString *error))completion {
    self.completion = completion;
    if (!GewuBrowserPublicURL(url) || ![workspaceURL.scheme isEqual:@"http"]
        || ![@[@"127.0.0.1", @"localhost", @"::1"] containsObject:workspaceURL.host]
        || token.length < 32 || token.length > 128) {
        [self finish:@"The capture request is invalid. Open Save to Gewu again."]; return;
    }
    self.endpoint = [NSURL URLWithString:@"/api/browser-capture-file" relativeToURL:workspaceURL].absoluteURL;
    self.uploadToken = token;
    __weak typeof(self) weakSelf = self;
    NSDate *started = NSDate.date;
    self.timer = [NSTimer scheduledTimerWithTimeInterval:0.5 repeats:YES block:^(NSTimer *timer) {
        NSNumber *size = weakSelf.file ? [NSFileManager.defaultManager attributesOfItemAtPath:weakSelf.file.path error:nil][NSFileSize] : nil;
        if (size.longLongValue > 64 * 1024 * 1024) [weakSelf finish:@"Choose a PDF up to 64 MB."];
        else if (-started.timeIntervalSinceNow > 90) [weakSelf finish:@"The PDF transfer timed out. Retry or choose a downloaded PDF."];
    }];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    // WebKit owns authentication and cookies; no credential export or replay.
    if (GewuBrowserPublicURL(view.URL)) {
        NSURLComponents *referrer = [NSURLComponents componentsWithURL:view.URL resolvingAgainstBaseURL:NO];
        referrer.query = nil; referrer.fragment = nil;
        if (![view.URL.host isEqual:url.host]) referrer.path = @"/";
        [request setValue:referrer.URL.absoluteString forHTTPHeaderField:@"Referer"];
    }
    [view startDownloadUsingRequest:request completionHandler:^(WKDownload *download) {
        typeof(self) self = weakSelf;
        if (!self.completion) { [download cancel:nil]; return; }
        self.download = download; download.delegate = self;
    }];
}
- (void)download:(WKDownload *)download willPerformHTTPRedirection:(NSHTTPURLResponse *)response
      newRequest:(NSURLRequest *)request decisionHandler:(void (^)(WKDownloadRedirectPolicy))decisionHandler {
    BOOL allowed = GewuBrowserPublicURL(request.URL);
    decisionHandler(allowed ? WKDownloadRedirectPolicyAllow : WKDownloadRedirectPolicyCancel);
    if (!allowed) [self finish:@"The PDF redirected to an unsupported address."];
}
- (void)download:(WKDownload *)download decideDestinationUsingResponse:(NSURLResponse *)response
 suggestedFilename:(NSString *)filename completionHandler:(void (^)(NSURL *))completionHandler {
    if (!self.completion) { completionHandler(nil); return; }
    if (!GewuBrowserPublicURL(response.URL)) { completionHandler(nil); [self finish:@"The PDF response has an unsupported address."]; return; }
    NSString *mime = response.MIMEType.lowercaseString;
    if (![mime isEqual:@"application/pdf"] && ![mime isEqual:@"application/octet-stream"] && ![mime isEqual:@"binary/octet-stream"]) {
        completionHandler(nil); [self finish:@"This link returned a web page instead of a PDF. Open the PDF or choose a local file."]; return;
    }
    if (response.expectedContentLength > 64 * 1024 * 1024) {
        completionHandler(nil); [self finish:@"Choose a PDF up to 64 MB."]; return;
    }
    self.filename = filename.lastPathComponent.length ? filename.lastPathComponent : @"Article.pdf";
    self.directory = [NSURL fileURLWithPath:[NSTemporaryDirectory() stringByAppendingPathComponent:[@"gewu-capture-native-" stringByAppendingString:NSUUID.UUID.UUIDString]] isDirectory:YES];
    NSError *error;
    if (![NSFileManager.defaultManager createDirectoryAtURL:self.directory withIntermediateDirectories:NO attributes:nil error:&error]) {
        completionHandler(nil); [self finish:@"Could not prepare a temporary PDF file."]; return;
    }
    self.file = [self.directory URLByAppendingPathComponent:@"capture.pdf"];
    completionHandler(self.file);
}
- (void)downloadDidFinish:(WKDownload *)download {
    if (!self.completion) return;
    NSNumber *size;
    [self.file getResourceValue:&size forKey:NSURLFileSizeKey error:nil];
    if (!size || size.longLongValue <= 0 || size.longLongValue > 64 * 1024 * 1024) {
        [self finish:@"Choose a readable PDF up to 64 MB."]; return;
    }
    NSURLSessionConfiguration *configuration = NSURLSessionConfiguration.ephemeralSessionConfiguration;
    configuration.HTTPCookieStorage = nil; configuration.URLCredentialStorage = nil;
    configuration.HTTPShouldSetCookies = NO;
    configuration.timeoutIntervalForRequest = 45;
    self.uploader = [NSURLSession sessionWithConfiguration:configuration delegate:self delegateQueue:nil];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:self.endpoint];
    request.HTTPMethod = @"POST";
    [request setValue:@"application/pdf" forHTTPHeaderField:@"Content-Type"];
    [request setValue:self.uploadToken forHTTPHeaderField:@"X-Gewu-Capture-Token"];
    [request setValue:[self.filename stringByAddingPercentEncodingWithAllowedCharacters:NSCharacterSet.URLPathAllowedCharacterSet] forHTTPHeaderField:@"X-Gewu-Filename"];
    [request setValue:size.stringValue forHTTPHeaderField:@"Content-Length"];
    __weak typeof(self) weakSelf = self;
    [[self.uploader uploadTaskWithRequest:request fromFile:self.file completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        id object = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        NSDictionary *body = [object isKindOfClass:NSDictionary.class] ? object : nil;
        NSString *message = nil;
        if (error || ![response isKindOfClass:NSHTTPURLResponse.class] || [(NSHTTPURLResponse *)response statusCode] != 200 || ![body isKindOfClass:NSDictionary.class] || ![body[@"ok"] boolValue])
            message = [body[@"error"] isKindOfClass:NSString.class] ? body[@"error"] : @"The PDF could not be delivered to Gewu Insight. Retry or choose a local file.";
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf finish:message]; });
    }] resume];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
 willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest *))completionHandler {
    // The upload capability and PDF bytes must never follow a redirect.
    completionHandler(nil);
}
- (void)download:(WKDownload *)download didFailWithError:(NSError *)error resumeData:(NSData *)resumeData {
    [self finish:@"The website did not provide the PDF. Retry after opening it, or choose a local file."];
}
- (void)finish:(NSString *)error {
    void (^completion)(NSString *) = self.completion;
    self.completion = nil;
    [self cancel];
    if (completion) completion(error);
}
- (void)cancel {
    self.completion = nil;
    [self.timer invalidate]; self.timer = nil;
    self.download.delegate = nil; [self.download cancel:nil]; self.download = nil;
    [self.uploader invalidateAndCancel]; self.uploader = nil;
    if (self.directory) [NSFileManager.defaultManager removeItemAtURL:self.directory error:nil];
    self.directory = nil;
}
@end
