#import <WebKit/WebKit.h>

// A scoped, disk-backed copy of one complete PDF. It deletes only its own
// temporary directory when the last capture/page reference is released.
@interface GewuBrowserPDFFile : NSObject
@property(nonatomic, readonly) NSURL *URL;
@property(nonatomic, readonly) NSString *filename;
@property(nonatomic, readonly) NSUInteger size;
+ (instancetype)fileWithData:(NSData *)data filename:(NSString *)filename;
@end

// Reads the current main resource without creating a network request. WebKit's
// optional loaded-resource SPI is capability checked; no private cache paths,
// regenerated PDF, archive HTML or network fallback may substitute for it.
void GewuReadLoadedBrowserPDF(WKWebView *view, NSString *filename,
    void (^completion)(GewuBrowserPDFFile *file, NSString *error));

// Discover original PDF documents in child frames, including cross-origin
// publisher readers. References bind to an isolated-world document token.
void GewuLoadedBrowserPDFFrames(WKWebView *view, void (^completion)(NSArray<NSDictionary *> *frames));
void GewuReadLoadedBrowserPDFFrame(WKWebView *view, NSDictionary *frame,
    void (^completion)(GewuBrowserPDFFile *file, NSString *error));
void GewuBrowserPDFFrameIsCurrent(WKWebView *view, NSDictionary *frame, void (^completion)(BOOL current));

// One explicit PDF transfer using the source WebView's existing session.
// The only NSURLSession request uploads bytes to the trusted local workspace.
@interface GewuBrowserCapture : NSObject <WKDownloadDelegate>
@property(nonatomic, copy) void (^progress)(NSString *message);
@property(nonatomic, copy) void (^receivedPDF)(GewuBrowserPDFFile *file);
- (void)uploadPDFFile:(GewuBrowserPDFFile *)file sourceURL:(NSURL *)url
        workspaceURL:(NSURL *)workspaceURL uploadToken:(NSString *)token completion:(void (^)(NSString *error))completion;
- (void)downloadURL:(NSURL *)url fromView:(WKWebView *)view workspaceURL:(NSURL *)workspaceURL
       uploadToken:(NSString *)token completion:(void (^)(NSString *error))completion;
// Reuse bytes already displayed by the native Browser; no publisher GET replay.
- (void)uploadPDFData:(NSData *)data filename:(NSString *)filename sourceURL:(NSURL *)url
        workspaceURL:(NSURL *)workspaceURL uploadToken:(NSString *)token completion:(void (^)(NSString *error))completion;
- (void)cancel;
@end
