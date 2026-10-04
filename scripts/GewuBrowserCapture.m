#import "GewuBrowserCapture.h"
#import "GewuBrowserNavigation.h"

static const int64_t GewuCapturePDFLimit = 128 * 1024 * 1024;

static BOOL GewuCompletePDF(NSData *data) {
    if (!data.length || data.length > GewuCapturePDFLimit) return NO;
    NSData *header = [@"%PDF-" dataUsingEncoding:NSASCIIStringEncoding];
    NSData *trailer = [@"%%EOF" dataUsingEncoding:NSASCIIStringEncoding];
    return [data rangeOfData:header options:0 range:NSMakeRange(0, MIN(data.length, 1024))].location != NSNotFound
        && [data rangeOfData:trailer options:0 range:NSMakeRange(data.length - MIN(data.length, 4096), MIN(data.length, 4096))].location != NSNotFound;
}

@implementation GewuBrowserPDFFile
+ (instancetype)fileWithData:(NSData *)data filename:(NSString *)filename {
    if (!GewuCompletePDF(data)) return nil;
    GewuBrowserPDFFile *file = [self new];
    NSURL *directory = [NSURL fileURLWithPath:[NSTemporaryDirectory() stringByAppendingPathComponent:[@"gewu-loaded-pdf-" stringByAppendingString:NSUUID.UUID.UUIDString]] isDirectory:YES];
    file->_URL = [directory URLByAppendingPathComponent:@"original.pdf"];
    NSString *name = filename.lastPathComponent;
    if (!name.length || [name isEqual:@"."] || [name isEqual:@".."]) name = @"Article.pdf";
    if (![name.pathExtension.lowercaseString isEqual:@"pdf"]) name = [name stringByAppendingString:@".pdf"];
    file->_filename = [name copy]; file->_size = data.length;
    if (![NSFileManager.defaultManager createDirectoryAtURL:directory withIntermediateDirectories:NO attributes:@{NSFilePosixPermissions:@0700} error:nil]
        || ![data writeToURL:file.URL options:NSDataWritingAtomic error:nil]) return nil;
    return file;
}
- (void)dealloc {
    if (_URL) [NSFileManager.defaultManager removeItemAtURL:_URL.URLByDeletingLastPathComponent error:nil];
}
@end

// Narrow optional WebKit SPI, present on supported macOS versions but not a
// public SDK guarantee. Failure is explicit; never replay a publisher request.
@interface WKWebView (GewuLoadedResource)
- (void)_getMainResourceDataWithCompletionHandler:(void (^)(NSData *, NSError *))completionHandler;
@end
void GewuReadLoadedBrowserPDF(WKWebView *view, NSString *filename,
    void (^completion)(GewuBrowserPDFFile *, NSString *)) {
    if (![view respondsToSelector:@selector(_getMainResourceDataWithCompletionHandler:)]) {
        completion(nil, @"This WebKit version cannot provide the loaded PDF. Choose a local PDF or explicitly download it again in Details."); return;
    }
    __block BOOL finished = NO;
    void (^finish)(GewuBrowserPDFFile *, NSString *) = ^(GewuBrowserPDFFile *file, NSString *error) {
        if (finished) return;
        finished = YES; completion(file, error);
    };
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        finish(nil, @"Reading the loaded PDF timed out. Wait for the PDF to finish loading and retry. No new download was started.");
    });
    [view _getMainResourceDataWithCompletionHandler:^(NSData *data, NSError *error) {
        if (finished) return;
        if (error || !data.length) { finish(nil, @"The loaded PDF is not available yet. Retry after it finishes loading. No new download was started."); return; }
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            GewuBrowserPDFFile *file = [GewuBrowserPDFFile fileWithData:data filename:filename];
            NSString *message = data.length > GewuCapturePDFLimit ? @"Choose a PDF up to 128 MB."
                : @"WebKit did not provide a complete original PDF. Retry or choose a local PDF. No new download was started.";
            dispatch_async(dispatch_get_main_queue(), ^{ finish(file, file ? nil : message); });
        });
    }];
}

// Optional WebKit frame SPI/C API. Resolve every symbol at runtime so an older
// WebKit fails explicitly instead of silently replaying a publisher request.
#import <dlfcn.h>
@interface WKWebView (GewuLoadedFrames)
- (const void *)_pageRefForTransitionToWKWebView;
- (void)_frameTrees:(void (^)(NSSet *))completion;
@end
@interface WKFrameInfo (GewuFrameHandle)
@property(nonatomic, readonly) id _handle;
@end
@protocol GewuFrameTree <NSObject>
@property(nonatomic, readonly) WKFrameInfo *info;
@property(nonatomic, readonly) NSArray *childFrames;
@end
static const void *(*GewuFrameLookup)(const void *, const void *);
static void (*GewuFrameRead)(const void *, void (*)(const void *, const void *, void *), void *);
static size_t (*GewuDataSize)(const void *);
static const unsigned char *(*GewuDataBytes)(const void *);
static BOOL GewuFrameAPI(WKWebView *view) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        GewuFrameLookup = dlsym(RTLD_DEFAULT, "WKPageLookUpFrameFromHandle");
        GewuFrameRead = dlsym(RTLD_DEFAULT, "WKFrameGetMainResourceData");
        GewuDataSize = dlsym(RTLD_DEFAULT, "WKDataGetSize");
        GewuDataBytes = dlsym(RTLD_DEFAULT, "WKDataGetBytes");
    });
    return GewuFrameLookup && GewuFrameRead && GewuDataSize && GewuDataBytes
        && [view respondsToSelector:@selector(_frameTrees:)]
        && [view respondsToSelector:@selector(_pageRefForTransitionToWKWebView)];
}
static WKContentWorld *GewuFrameWorld(void) {
    // WebKit's named world is weakly registered; retain the actual world, not
    // merely its name, so the document nonce survives separate evaluations.
    static WKContentWorld *world;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ world=[WKContentWorld worldWithName:@"GewuBrowserCapture"]; });
    return world;
}
static NSString *GewuFrameProbe(void) {
    return @"(() => ({mime:document.contentType,url:location.href,token:(globalThis.__gewuPDFDocumentToken ||= Array.from(crypto.getRandomValues(new Uint32Array(4)),x=>x.toString(16)).join('-'))}))()";
}
BOOL GewuBrowserScienceEPDFURL(NSURL *url) {
    return [@[@"science.org", @"www.science.org"] containsObject:url.host.lowercaseString]
        && [url.scheme.lowercaseString isEqual:@"https"] && [url.path hasPrefix:@"/doi/epdf/10.1126/"];
}
// Science's ePDF is an HTML/PDF.js reader, not a PDF main resource or frame.
// Bind its loaded document to the current DOI and fingerprint. Do not expose
// its signed pdfdirect URL or reconstruct a publisher download request.
static NSString *GewuSciencePDFProbe(void) {
    return @"(() => { const app=window.PDFViewerApplication, doc=app?.pdfDocument;"
        "const doi=decodeURIComponent(location.pathname).slice('/doi/epdf/'.length);"
        "if(!doc?.numPages || typeof doc.getData!=='function') return null;"
        "const source=new URL(app.url,location.href);"
        "if(source.origin!==location.origin || !['/doi/pdf/'+doi,'/doi/pdfdirect/'+doi].includes(decodeURIComponent(source.pathname))) return null;"
        "const token=doc.fingerprints?.[0] || doc.fingerprint; if(typeof token!=='string' || !token.length || token.length>256) return null;"
        "const link=[...document.querySelectorAll('a[href]')].slice(0,600).find(a=>{try{const u=new URL(a.href);return u.origin===location.origin && decodeURIComponent(u.pathname)==='/doi/pdf/'+doi;}catch(_){return false;}});"
        "return link ? {science:true,url:link.href,token} : null; })()";
}
static void GewuSciencePDFReference(WKWebView *view, void (^completion)(NSDictionary *)) {
    if (!GewuBrowserScienceEPDFURL(view.URL)) { completion(nil); return; }
    __block BOOL finished=NO;
    void (^finish)(NSDictionary *)=^(NSDictionary *value){if(!finished){finished=YES;completion(value);}};
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,8*NSEC_PER_SEC),dispatch_get_main_queue(),^{finish(nil);});
    [view evaluateJavaScript:GewuSciencePDFProbe() inFrame:nil inContentWorld:WKContentWorld.pageWorld completionHandler:^(id value,NSError *error){
        finish(!error && [value isKindOfClass:NSDictionary.class] ? value : nil);
    }];
}
static void GewuReadSciencePDF(WKWebView *view, NSDictionary *reference, void (^completion)(GewuBrowserPDFFile *, NSString *)) {
    __block BOOL finished=NO;
    void (^finish)(GewuBrowserPDFFile *,NSString *)=^(GewuBrowserPDFFile *file,NSString *error){if(!finished){finished=YES;completion(file,error);}};
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_SEC),dispatch_get_main_queue(),^{finish(nil,@"Reading the Science PDF timed out. Retry after it finishes loading.");});
    GewuSciencePDFReference(view,^(NSDictionary *current){
        if(finished)return;
        if(![current[@"url"] isEqual:reference[@"url"]] || ![current[@"token"] isEqual:reference[@"token"]]){finish(nil,@"The Science PDF changed. Reopen Save to Gewu.");return;}
        NSString *script=@"const app=window.PDFViewerApplication, doc=app?.pdfDocument;"
            "if((doc?.fingerprints?.[0] || doc?.fingerprint)!==token) throw Error('PDF changed');"
            "const bytes=await doc.getData();"
            "if(app.pdfDocument!==doc || !bytes?.length || bytes.length>134217728) throw Error('PDF unavailable or too large');"
            "const chunks=[];for(let i=0;i<bytes.length;i+=32768)chunks.push(String.fromCharCode(...bytes.subarray(i,i+32768)));"
            "return btoa(chunks.join(''));";
        [view callAsyncJavaScript:script arguments:@{@"token":reference[@"token"]} inFrame:nil inContentWorld:WKContentWorld.pageWorld completionHandler:^(id value,NSError *error){
            if(finished)return;
            if(error || ![value isKindOfClass:NSString.class] || [value length]>(GewuCapturePDFLimit+2)/3*4){finish(nil,@"The loaded Science PDF could not be read. Retry or choose a local PDF.");return;}
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
                NSData *bytes=[[NSData alloc] initWithBase64EncodedString:value options:0];
                NSString *name=[[NSURL URLWithString:reference[@"url"]].lastPathComponent stringByAppendingString:@".pdf"];
                GewuBrowserPDFFile *file=[GewuBrowserPDFFile fileWithData:bytes filename:name];
                dispatch_async(dispatch_get_main_queue(),^{
                    if(finished)return;
                    GewuSciencePDFReference(view,^(NSDictionary *last){
                        BOOL same=[last[@"url"] isEqual:reference[@"url"]] && [last[@"token"] isEqual:reference[@"token"]];
                        finish(same?file:nil, !same?@"The Science PDF changed. Reopen Save to Gewu.":file?nil:@"The Science reader did not provide a complete original PDF.");
                    });
                });
            });
        }];
    });
}
void GewuLoadedBrowserPDFFrames(WKWebView *view, void (^completion)(NSArray<NSDictionary *> *)) {
    if (GewuBrowserScienceEPDFURL(view.URL)) {
        GewuSciencePDFReference(view,^(NSDictionary *reference){completion(reference?@[reference]:@[]);}); return;
    }
    if (!GewuFrameAPI(view)) { completion(@[]); return; }
    __block BOOL finished = NO;
    void (^finish)(NSArray *) = ^(NSArray *frames) { if (!finished) { finished=YES; completion(frames); } };
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 8 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{ finish(@[]); });
    [view _frameTrees:^(NSSet *roots) {
        if (finished) return;
        NSMutableArray *queue = [roots.allObjects mutableCopy], *infos = [NSMutableArray array];
        for (NSUInteger i=0; i<queue.count && i<32; i++) {
            id<GewuFrameTree> node=queue[i];
            if (![node respondsToSelector:@selector(info)] || ![node respondsToSelector:@selector(childFrames)]) continue;
            WKFrameInfo *info=node.info;
            if (!info.mainFrame && [@[@"http", @"https"] containsObject:info.request.URL.scheme.lowercaseString]) [infos addObject:info];
            if (queue.count < 32) [queue addObjectsFromArray:[node.childFrames subarrayWithRange:NSMakeRange(0,MIN(node.childFrames.count,32-queue.count))]];
        }
        if (!infos.count) { finish(@[]); return; }
        __block NSUInteger pending=infos.count;
        NSMutableArray *found=[NSMutableArray array];
        for (WKFrameInfo *info in infos) [view evaluateJavaScript:GewuFrameProbe() inFrame:info inContentWorld:GewuFrameWorld() completionHandler:^(id result, NSError *error) {
            if (finished) return;
            if (!error && [result isKindOfClass:NSDictionary.class] && [result[@"mime"] isEqual:@"application/pdf"]
                && [result[@"url"] isKindOfClass:NSString.class] && [result[@"token"] isKindOfClass:NSString.class])
                [found addObject:@{@"frame":info, @"url":result[@"url"], @"token":result[@"token"]}];
            if (!--pending) finish(found);
        }];
    }];
}
void GewuBrowserPDFFrameIsCurrent(WKWebView *view, NSDictionary *reference, void (^completion)(BOOL)) {
    if ([reference[@"science"] boolValue]) {
        GewuSciencePDFReference(view,^(NSDictionary *current){completion([current[@"url"] isEqual:reference[@"url"]] && [current[@"token"] isEqual:reference[@"token"]]);});return;
    }
    WKFrameInfo *info=reference[@"frame"];
    if (!info) { completion(NO); return; }
    __block BOOL finished=NO;
    void (^finish)(BOOL)=^(BOOL current){if(!finished){finished=YES;completion(current);}};
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,8*NSEC_PER_SEC),dispatch_get_main_queue(),^{finish(NO);});
    [view evaluateJavaScript:GewuFrameProbe() inFrame:info inContentWorld:GewuFrameWorld() completionHandler:^(id result, NSError *error) {
        finish(!error && [result isKindOfClass:NSDictionary.class] && [result[@"mime"] isEqual:@"application/pdf"]
            && [result[@"url"] isEqual:reference[@"url"]] && [result[@"token"] isEqual:reference[@"token"]]);
    }];
}
static void GewuFrameDataReceived(const void *data, const void *error, void *context) {
    void (^done)(NSData *, NSString *) = CFBridgingRelease(context);
    size_t length=data ? GewuDataSize(data) : 0;
    NSData *bytes=(!error && length && length<=GewuCapturePDFLimit) ? [NSData dataWithBytes:GewuDataBytes(data) length:length] : nil;
    done(bytes, bytes ? nil : @"The embedded PDF is not completely available. No new download was started.");
}
void GewuReadLoadedBrowserPDFFrame(WKWebView *view, NSDictionary *reference, void (^completion)(GewuBrowserPDFFile *, NSString *)) {
    if ([reference[@"science"] boolValue]) { GewuReadSciencePDF(view,reference,completion); return; }
    if (!GewuFrameAPI(view)) { completion(nil,@"This WebKit version cannot read the loaded embedded PDF. Open the PDF itself or choose a local PDF."); return; }
    __block BOOL finished=NO;
    void (^finish)(GewuBrowserPDFFile *, NSString *)=^(GewuBrowserPDFFile *file,NSString *error){if(!finished){finished=YES;completion(file,error);}};
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_SEC),dispatch_get_main_queue(),^{finish(nil,@"Reading the embedded PDF timed out. No new download was started.");});
    GewuBrowserPDFFrameIsCurrent(view,reference,^(BOOL current){
        if(finished)return;
        WKFrameInfo *info=reference[@"frame"];
        const void *frame=current && [info respondsToSelector:@selector(_handle)] ? GewuFrameLookup([view _pageRefForTransitionToWKWebView],(__bridge const void *)info._handle) : NULL;
        if(!frame){finish(nil,@"The embedded document changed. Reopen Save to Gewu on the current PDF.");return;}
        void (^received)(NSData *,NSString *)=^(NSData *data,NSString *error){
            if(finished)return;
            if(!data){finish(nil,error);return;}
            GewuBrowserPDFFrameIsCurrent(view,reference,^(BOOL stillCurrent){
                if(finished)return;
                if(!stillCurrent){finish(nil,@"The embedded document changed. Reopen Save to Gewu on the current PDF.");return;}
                dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
                    GewuBrowserPDFFile *file=[GewuBrowserPDFFile fileWithData:data filename:[NSURL URLWithString:reference[@"url"]].lastPathComponent];
                    dispatch_async(dispatch_get_main_queue(),^{
                        if (finished) return;
                        GewuBrowserPDFFrameIsCurrent(view,reference,^(BOOL unchanged){
                            finish(unchanged ? file : nil, !unchanged ? @"The embedded document changed. Reopen Save to Gewu on the current PDF."
                                : file ? nil : @"WebKit did not provide the complete original PDF. No new download was started.");
                        });
                    });
                });
            });
        };
        GewuFrameRead(frame,GewuFrameDataReceived,(void *)CFBridgingRetain([received copy]));
    });
}

@interface GewuBrowserCapture () <NSURLSessionTaskDelegate>
@property(nonatomic, strong) WKDownload *download;
@property(nonatomic, strong) GewuBrowserPDFFile *retainedPDF;
@property(nonatomic, strong) NSURLSession *uploader;
@property(nonatomic, strong) NSURL *directory;
@property(nonatomic, strong) NSURL *file;
@property(nonatomic, strong) NSURL *endpoint;
@property(nonatomic, copy) NSString *uploadToken;
@property(nonatomic, copy) NSString *filename;
@property(nonatomic, copy) NSString *sourceURL;
@property(nonatomic, copy) void (^completion)(NSString *error);
@property(nonatomic, strong) NSTimer *timer;
@end

@implementation GewuBrowserCapture
- (void)uploadPDFData:(NSData *)data filename:(NSString *)filename sourceURL:(NSURL *)url
        workspaceURL:(NSURL *)workspaceURL uploadToken:(NSString *)token completion:(void (^)(NSString *error))completion {
    self.completion = completion;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        GewuBrowserPDFFile *file = [GewuBrowserPDFFile fileWithData:data filename:filename];
        dispatch_async(dispatch_get_main_queue(), ^{
            if (!self.completion) return;
            [self uploadPDFFile:file sourceURL:url workspaceURL:workspaceURL uploadToken:token completion:completion];
        });
    });
}
- (void)uploadPDFFile:(GewuBrowserPDFFile *)file sourceURL:(NSURL *)url
        workspaceURL:(NSURL *)workspaceURL uploadToken:(NSString *)token completion:(void (^)(NSString *error))completion {
    self.completion = completion;
    if (!file || !GewuBrowserPublicURL(url) || ![workspaceURL.scheme isEqual:@"http"]
        || ![@[@"127.0.0.1", @"localhost", @"::1"] containsObject:workspaceURL.host]
        || token.length < 32 || token.length > 128) {
        [self finish:@"Choose a complete PDF up to 128 MB and reopen Save to Gewu."]; return;
    }
    self.endpoint = [NSURL URLWithString:@"/api/browser-capture-file" relativeToURL:workspaceURL].absoluteURL;
    self.uploadToken = token; self.sourceURL = url.absoluteString;
    self.retainedPDF = file; self.file = file.URL; self.filename = file.filename;
    [self uploadPreparedPDF];
}
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
    self.sourceURL = url.absoluteString;
    __weak typeof(self) weakSelf = self;
    NSDate *started = NSDate.date;
    __block NSDate *lastProgress = started;
    __block long long lastBytes = 0;
    self.timer = [NSTimer scheduledTimerWithTimeInterval:0.5 repeats:YES block:^(NSTimer *timer) {
        NSNumber *size = weakSelf.file ? [NSFileManager.defaultManager attributesOfItemAtPath:weakSelf.file.path error:nil][NSFileSize] : nil;
        if (size.longLongValue > GewuCapturePDFLimit) [weakSelf finish:@"Choose a PDF up to 128 MB."];
        else {
            long long bytes = MAX(size.longLongValue, weakSelf.download.progress.completedUnitCount);
            if (bytes > lastBytes) { lastBytes = bytes; lastProgress = NSDate.date; }
            if (-lastProgress.timeIntervalSinceNow > 90 || -started.timeIntervalSinceNow > 15 * 60) {
                [weakSelf finish:@"The PDF download stopped making progress or exceeded its time limit. Retry or choose a local PDF."]; return;
            }
            if (weakSelf.progress) weakSelf.progress([NSString stringWithFormat:@"Downloading PDF… %.1f MB received", bytes / (1024.0 * 1024.0)]);
        }
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
    if (response.expectedContentLength > GewuCapturePDFLimit) {
        completionHandler(nil); [self finish:@"Choose a PDF up to 128 MB."]; return;
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
    [self.timer invalidate]; self.timer = nil;
    if (self.progress) self.progress(@"Preparing downloaded PDF…");
    NSURL *fileURL = self.file;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        GewuBrowserPDFFile *file = [GewuBrowserPDFFile fileWithData:[NSData dataWithContentsOfURL:fileURL options:NSDataReadingMappedIfSafe error:nil] filename:self.filename];
        dispatch_async(dispatch_get_main_queue(), ^{
            if (!self.completion) return;
            if (!file) { [self finish:@"The download did not contain a complete PDF up to 128 MB."]; return; }
            self.retainedPDF = file; self.file = file.URL;
            if (self.receivedPDF) self.receivedPDF(file);
            [self uploadPreparedPDF];
        });
    });
}
- (void)uploadPreparedPDF {
    if (!self.completion) return;
    NSNumber *size;
    [self.file getResourceValue:&size forKey:NSURLFileSizeKey error:nil];
    if (!size || size.longLongValue <= 0 || size.longLongValue > GewuCapturePDFLimit) {
        [self finish:@"Choose a readable PDF up to 128 MB."]; return;
    }
    NSURLSessionConfiguration *configuration = NSURLSessionConfiguration.ephemeralSessionConfiguration;
    configuration.HTTPCookieStorage = nil; configuration.URLCredentialStorage = nil;
    configuration.HTTPShouldSetCookies = NO;
    configuration.timeoutIntervalForRequest = 180;
    configuration.timeoutIntervalForResource = 300;
    if (self.progress) self.progress(@"Reading PDF information…");
    self.uploader = [NSURLSession sessionWithConfiguration:configuration delegate:self delegateQueue:nil];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:self.endpoint];
    request.HTTPMethod = @"POST";
    [request setValue:@"application/pdf" forHTTPHeaderField:@"Content-Type"];
    [request setValue:self.uploadToken forHTTPHeaderField:@"X-Gewu-Capture-Token"];
    [request setValue:[self.filename stringByAddingPercentEncodingWithAllowedCharacters:NSCharacterSet.URLPathAllowedCharacterSet] forHTTPHeaderField:@"X-Gewu-Filename"];
    [request setValue:[self.sourceURL stringByAddingPercentEncodingWithAllowedCharacters:NSCharacterSet.URLPathAllowedCharacterSet] forHTTPHeaderField:@"X-Gewu-PDF-Source"];
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
    self.directory = nil; self.retainedPDF = nil;
    self.progress = nil; self.receivedPDF = nil;
}
@end
