#import <WebKit/WebKit.h>

// One explicit PDF transfer using the source WebView's existing session.
// The only NSURLSession request uploads bytes to the trusted local workspace.
@interface GewuBrowserCapture : NSObject <WKDownloadDelegate>
- (void)downloadURL:(NSURL *)url fromView:(WKWebView *)view workspaceURL:(NSURL *)workspaceURL
       uploadToken:(NSString *)token completion:(void (^)(NSString *error))completion;
- (void)cancel;
@end
