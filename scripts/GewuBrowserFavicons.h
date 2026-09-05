#import <Foundation/Foundation.h>

// Disposable, bounded icon cache. No cookies, passwords, analytics services, or
// article-page crawling; at most two visible-site icon requests at a time.
@interface GewuBrowserFavicons : NSObject <NSURLSessionDataDelegate, NSURLSessionTaskDelegate>
@property(nonatomic, copy) void (^onIcon)(NSString *host, NSString *dataURL);
@property(nonatomic) BOOL active;
- (void)requestURL:(NSURL *)pageURL;
- (void)preferIcon:(NSURL *)iconURL forPage:(NSURL *)pageURL;
- (void)invalidate;
@end
