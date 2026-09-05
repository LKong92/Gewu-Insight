#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

// Inspects only the current native context menu's menu nodes. No window tree,
// accessibility permission request, password-provider API, or credential values.
id<NSAccessibility> GewuBrowserPasswordMenuItem(NSMenu *menu);

@interface GewuBrowserAutoFill : NSObject
- (instancetype)initWithProbeScript:(NSString *)script canUseView:(BOOL (^)(WKWebView *))canUseView;
- (void)noteInputEvent:(NSEvent *)event;
- (void)considerMouseUp:(NSEvent *)event inView:(WKWebView *)view;
- (void)cancelPending;
- (void)nativeMenuWillOpen:(NSMenu *)menu inView:(WKWebView *)view event:(NSEvent *)event;
// Separate dispatch seam for non-credential tests; production presses only the
// OS-owned Passwords menu item, never a credential row or authentication control.
- (BOOL)performPasswordMenuItem:(id<NSAccessibility>)item;
@end
