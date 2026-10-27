#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

// Only the trusted workspace owns this controller. External pages have no
// script-message handlers and never inherit GewuInsightWebView file bridges.
@interface GewuBrowserController : NSObject <WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate>
@property(nonatomic, weak) WKWebView *workspace;
@property(nonatomic, strong, readonly) WKWebView *webView;
@property(nonatomic, readonly) BOOL hasPendingFileOperations;
@property(nonatomic) BOOL preparingUpdate;
@property(nonatomic, copy) void (^onEvent)(NSDictionary *event);
// External Browser pages and authorized Science downloads share website state,
// but always receive fresh configurations with no trusted workspace bridges.
+ (WKWebsiteDataStore *)externalWebsiteDataStore;
+ (WKWebViewConfiguration *)externalPageConfiguration;
// Retain this wrapper while the external view uses it as its weak delegate.
+ (id<WKNavigationDelegate>)externalNavigationDelegate:(id<WKNavigationDelegate>)delegate;
- (instancetype)initWithWorkspace:(WKWebView *)workspace;
- (void)handleCommand:(NSDictionary *)command;
- (void)invalidate;
@end
