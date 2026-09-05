#import "GewuBrowserFavicons.h"
#import "GewuBrowserNavigation.h"
#import <AppKit/AppKit.h>
#import <ImageIO/ImageIO.h>
#import <CommonCrypto/CommonDigest.h>

@interface GewuBrowserFavicons ()
@property(nonatomic, strong) NSURLSession *session;
@property(nonatomic, strong) NSURL *cache;
@property(nonatomic, strong) NSMutableArray<NSString *> *pending;
@property(nonatomic, strong) NSMutableSet<NSString *> *requested;
@property(nonatomic, strong) NSMutableDictionary<NSNumber *, NSMutableDictionary *> *tasks;
@property(nonatomic, strong) NSMutableDictionary<NSString *, NSURL *> *preferred;
@property(nonatomic) BOOL stopped;
@property(nonatomic) BOOL scheduled;
@end

@implementation GewuBrowserFavicons
- (instancetype)init {
    if ((self = [super init])) {
        _pending = [NSMutableArray array]; _requested = [NSMutableSet set];
        _tasks = [NSMutableDictionary dictionary]; _preferred = [NSMutableDictionary dictionary];
        NSURLSessionConfiguration *config = NSURLSessionConfiguration.ephemeralSessionConfiguration;
        config.HTTPCookieStorage = nil; config.URLCredentialStorage = nil;
        config.HTTPShouldSetCookies = NO; config.timeoutIntervalForRequest = 8;
        config.timeoutIntervalForResource = 12; config.HTTPMaximumConnectionsPerHost = 1;
        _session = [NSURLSession sessionWithConfiguration:config delegate:self delegateQueue:NSOperationQueue.mainQueue];
        NSURL *caches = [NSFileManager.defaultManager URLsForDirectory:NSCachesDirectory inDomains:NSUserDomainMask].firstObject;
        _cache = [caches URLByAppendingPathComponent:@"com.zhengranwu.gewuinsight/BrowserFavicons" isDirectory:YES];
        [NSFileManager.defaultManager createDirectoryAtURL:_cache withIntermediateDirectories:YES attributes:nil error:nil];
    }
    return self;
}
- (NSURL *)cacheURL:(NSString *)host {
    NSData *bytes = [host dataUsingEncoding:NSUTF8StringEncoding]; unsigned char hash[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(bytes.bytes, (CC_LONG)bytes.length, hash);
    NSMutableString *name = [NSMutableString string];
    for (NSUInteger i = 0; i < sizeof(hash); i++) [name appendFormat:@"%02x", hash[i]];
    return [self.cache URLByAppendingPathComponent:[name stringByAppendingString:@".png"]];
}
- (void)publish:(NSData *)png host:(NSString *)host {
    if (self.onIcon && !self.stopped) self.onIcon(host, png.length ? [@"data:image/png;base64," stringByAppendingString:[png base64EncodedStringWithOptions:0]] : @"");
}
- (void)setActive:(BOOL)active { _active = active; if (active) [self pump]; }
- (void)requestURL:(NSURL *)pageURL {
    if (self.stopped || !GewuBrowserPublicURL(pageURL)) return;
    NSString *host = pageURL.host.lowercaseString;
    if (pageURL.port || [self.requested containsObject:host]) return;
    NSURL *path = [self cacheURL:host];
    NSDictionary *attrs = [NSFileManager.defaultManager attributesOfItemAtPath:path.path error:nil];
    NSTimeInterval age = -[attrs[NSFileModificationDate] timeIntervalSinceNow];
    NSUInteger size = [attrs[NSFileSize] unsignedIntegerValue];
    if (attrs && size <= 65536 && age < (size ? 7 * 86400 : 6 * 3600)) {
        [self.requested addObject:host]; [self publish:[NSData dataWithContentsOfURL:path] host:host]; return;
    }
    if (self.pending.count >= 64) return;
    [self.requested addObject:host]; [self.pending addObject:host]; [self pump];
}
- (void)preferIcon:(NSURL *)iconURL forPage:(NSURL *)pageURL {
    if (!GewuBrowserPublicURL(iconURL) || !GewuBrowserPublicURL(pageURL) || ![iconURL.scheme isEqualToString:@"https"]
        || ![iconURL.host.lowercaseString isEqualToString:pageURL.host.lowercaseString] || iconURL.port) return;
    NSString *host = pageURL.host.lowercaseString;
    if ([self.preferred[host] isEqual:iconURL]) return;
    self.preferred[host] = iconURL;
    NSURL *path = [self cacheURL:host];
    NSDictionary *attrs = [NSFileManager.defaultManager attributesOfItemAtPath:path.path error:nil];
    // A newly visited page can supply the missing nonstandard icon. Retry a
    // cached miss once for this hint, but do not replace a useful cached image.
    BOOL inFlight = [self.pending containsObject:host];
    for (NSDictionary *task in self.tasks.allValues) if ([task[@"host"] isEqualToString:host]) inFlight = YES;
    if (attrs && [attrs[NSFileSize] unsignedIntegerValue] == 0 && !inFlight) {
        [NSFileManager.defaultManager removeItemAtURL:path error:nil];
        [self.requested removeObject:host]; [self requestURL:pageURL];
    }
}
- (void)pump {
    if (!self.active || self.stopped || self.scheduled || self.tasks.count >= 2 || !self.pending.count) return;
    NSString *host = self.pending.firstObject; [self.pending removeObjectAtIndex:0];
    NSURL *url = self.preferred[host] ?: [NSURL URLWithString:[NSString stringWithFormat:@"https://%@/favicon.ico", host]];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url]; request.HTTPShouldHandleCookies = NO;
    [request setValue:@"image/png,image/x-icon,image/*;q=0.8" forHTTPHeaderField:@"Accept"];
    NSURLSessionDataTask *task = [self.session dataTaskWithRequest:request];
    self.tasks[@(task.taskIdentifier)] = [@{@"host":host, @"data":[NSMutableData data], @"redirects":@0} mutableCopy];
    [task resume]; self.scheduled = YES;
    __weak typeof(self) weakSelf = self;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        weakSelf.scheduled = NO; [weakSelf pump];
    });
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveResponse:(NSURLResponse *)response completionHandler:(void (^)(NSURLSessionResponseDisposition))completion {
    BOOL valid = [response isKindOfClass:NSHTTPURLResponse.class] && [(NSHTTPURLResponse *)response statusCode] == 200
        && response.expectedContentLength <= 524288;
    completion(valid ? NSURLSessionResponseAllow : NSURLSessionResponseCancel);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    NSMutableData *buffer = self.tasks[@(task.taskIdentifier)][@"data"];
    if (buffer.length + data.length > 524288) [task cancel]; else [buffer appendData:data];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request completionHandler:(void (^)(NSURLRequest *))completion {
    NSMutableDictionary *context = self.tasks[@(task.taskIdentifier)];
    NSInteger redirects = [context[@"redirects"] integerValue] + 1; context[@"redirects"] = @(redirects);
    completion(redirects <= 3 && GewuBrowserPublicURL(request.URL) && [request.URL.scheme isEqualToString:@"https"] ? request : nil);
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didReceiveChallenge:(NSURLAuthenticationChallenge *)challenge completionHandler:(void (^)(NSURLSessionAuthChallengeDisposition, NSURLCredential *))completion {
    completion([challenge.protectionSpace.authenticationMethod isEqualToString:NSURLAuthenticationMethodServerTrust]
        ? NSURLSessionAuthChallengePerformDefaultHandling : NSURLSessionAuthChallengeCancelAuthenticationChallenge, nil);
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)error {
    NSDictionary *context = self.tasks[@(task.taskIdentifier)]; [self.tasks removeObjectForKey:@(task.taskIdentifier)];
    if (!context || self.stopped) return;
    NSData *png = nil;
    if (!error) {
        CGImageSourceRef source = CGImageSourceCreateWithData((__bridge CFDataRef)context[@"data"], NULL);
        if (source) {
            NSDictionary *properties = CFBridgingRelease(CGImageSourceCopyPropertiesAtIndex(source, 0, NULL));
            if ([properties[(NSString *)kCGImagePropertyPixelWidth] integerValue] <= 4096
                && [properties[(NSString *)kCGImagePropertyPixelHeight] integerValue] <= 4096) {
                CGImageRef thumb = CGImageSourceCreateThumbnailAtIndex(source, 0, (__bridge CFDictionaryRef)@{
                    (NSString *)kCGImageSourceCreateThumbnailFromImageAlways:@YES, (NSString *)kCGImageSourceThumbnailMaxPixelSize:@64});
                if (thumb) { png = [[[NSBitmapImageRep alloc] initWithCGImage:thumb] representationUsingType:NSBitmapImageFileTypePNG properties:@{}]; CGImageRelease(thumb); }
            }
            CFRelease(source);
        }
    }
    if (png.length > 65536) png = nil;
    [(png ?: NSData.data) writeToURL:[self cacheURL:context[@"host"]] options:NSDataWritingAtomic error:nil];
    [self publish:png host:context[@"host"]]; [self pump];
}
- (void)invalidate { self.stopped = YES; [self.pending removeAllObjects]; [self.session invalidateAndCancel]; self.onIcon = nil; }
@end
