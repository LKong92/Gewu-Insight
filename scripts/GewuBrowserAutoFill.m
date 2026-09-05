#import "GewuBrowserAutoFill.h"
#import "GewuBrowserNavigation.h"

static NSString *MenuTitle(id<NSAccessibility> item) {
    if (![item respondsToSelector:@selector(accessibilityTitle)]) return @"";
    return [[[item accessibilityTitle] stringByTrimmingCharactersInSet:
        [NSCharacterSet characterSetWithCharactersInString:@" \t\n.…"]] lowercaseString] ?: @"";
}
static NSArray *MenuChildren(id<NSAccessibility> item) {
    if (![item respondsToSelector:@selector(accessibilityChildren)]) return @[];
    NSArray *children = [item accessibilityChildren];
    return children.count <= 80 ? children : @[];
}
static id<NSAccessibility> FindPasswords(id<NSAccessibility> parent, NSUInteger depth, BOOL inAutoFill) {
    if (depth > 4) return nil;
    for (id<NSAccessibility> item in MenuChildren(parent)) {
        if (![item respondsToSelector:@selector(accessibilityRole)]) continue;
        NSString *role = [item accessibilityRole];
        // Never walk text fields, sheets, windows or password-picker contents.
        if (![role isEqual:NSAccessibilityMenuRole] && ![role isEqual:NSAccessibilityMenuItemRole]) continue;
        NSString *title = MenuTitle(item);
        BOOL autoFill = [@[@"autofill", @"自动填充", @"自動填寫", @"自動填充"] containsObject:title];
        BOOL password = [@[@"passwords", @"密码", @"密碼"] containsObject:title];
        if (inAutoFill && password && [role isEqual:NSAccessibilityMenuItemRole]
            && [item respondsToSelector:@selector(isAccessibilityEnabled)] && item.accessibilityEnabled
            && [item respondsToSelector:@selector(accessibilityPerformPress)]) return item;
        id<NSAccessibility> found = FindPasswords(item, depth + 1, inAutoFill || autoFill);
        if (found) return found;
    }
    return nil;
}
id<NSAccessibility> GewuBrowserPasswordMenuItem(NSMenu *menu) {
    return menu ? FindPasswords((id)menu, 0, NO) : nil;
}

@interface GewuBrowserAutoFill ()
@property(copy) NSString *script;
@property(copy) BOOL (^canUseView)(WKWebView *);
@property(strong) WKContentWorld *world;
@property(strong) NSMutableSet<NSString *> *attempted;
@property NSUInteger generation;
@property(weak) WKWebView *pendingView;
@property(copy) NSURL *pendingURL;
@property(strong) NSEvent *menuEvent;
@property(weak) NSMenu *pendingMenu;
@property NSTimeInterval deadline;
@property BOOL clickEligible;
@property NSPoint mouseDownPoint;
@property NSInteger mouseDownWindow;
@property NSTimeInterval mouseDownTime;
@end
@implementation GewuBrowserAutoFill
- (instancetype)initWithProbeScript:(NSString *)script canUseView:(BOOL (^)(WKWebView *))canUseView {
    if ((self = [super init])) {
        _script = [script copy]; _canUseView = [canUseView copy]; _attempted = [NSMutableSet set];
        _world = [WKContentWorld worldWithName:@"GewuLoginTriggerSemantics"];
    }
    return self;
}
- (void)cancelPending {
    self.generation++;
    self.clickEligible = NO;
    NSMenu *menu = self.pendingMenu;
    self.pendingMenu = nil; self.pendingView = nil; self.pendingURL = nil; self.menuEvent = nil;
    [menu cancelTrackingWithoutAnimation];
}
- (BOOL)current:(WKWebView *)view generation:(NSUInteger)generation {
    return generation == self.generation && view == self.pendingView && self.canUseView(view)
        && !view.loading && [view.URL isEqual:self.pendingURL] && !view.hidden
        && view.window.isKeyWindow && !view.window.attachedSheet
        && NSProcessInfo.processInfo.systemUptime <= self.deadline;
}
- (void)noteInputEvent:(NSEvent *)event {
    [self cancelPending];
    self.clickEligible = event.type == NSEventTypeLeftMouseDown && event.clickCount == 1;
    if (self.clickEligible) {
        self.mouseDownPoint = event.locationInWindow; self.mouseDownWindow = event.windowNumber;
        self.mouseDownTime = event.timestamp;
    }
}
- (void)considerMouseUp:(NSEvent *)event inView:(WKWebView *)view {
    BOOL clicked = self.clickEligible && event.windowNumber == self.mouseDownWindow
        && event.timestamp >= self.mouseDownTime && event.timestamp - self.mouseDownTime < 2
        && hypot(event.locationInWindow.x - self.mouseDownPoint.x, event.locationInWindow.y - self.mouseDownPoint.y) < 4;
    self.clickEligible = NO;
    [self cancelPending];
    if (!clicked || !self.script.length || !view || !self.canUseView(view) || view.hidden || view.loading
        || event.type != NSEventTypeLeftMouseUp || event.clickCount != 1
        || (event.modifierFlags & (NSEventModifierFlagCommand | NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagShift))
        || event.window != view.window || !view.window.isKeyWindow || view.window.attachedSheet
        || ![view.URL.scheme.lowercaseString isEqual:@"https"] || !GewuBrowserPublicURL(view.URL)) return;
    NSPoint point = [view convertPoint:event.locationInWindow fromView:nil];
    if (!NSPointInRect(point, view.bounds) || !isfinite(view.pageZoom) || view.pageZoom <= 0) return;
    NSView *hit = [view.window.contentView hitTest:[view.window.contentView convertPoint:event.locationInWindow fromView:nil]];
    if (hit != view && ![hit isDescendantOf:view]) return;
    NSURLComponents *parts = [NSURLComponents componentsWithURL:view.URL resolvingAgainstBaseURL:NO];
    NSString *origin = [NSString stringWithFormat:@"https://%@%@", parts.host.lowercaseString,
        parts.port && parts.port.integerValue != 443 ? [@":" stringByAppendingString:parts.port.stringValue] : @""];
    // At most once per kind and HTTPS origin per App session, including cancel
    // and unavailable menu. Never evict old entries and accidentally re-prompt.
    if (self.attempted.count >= 128 || ([self.attempted containsObject:[origin stringByAppendingString:@"|username"]]
        && [self.attempted containsObject:[origin stringByAppendingString:@"|current-password"]])) return;
    self.pendingView = view; self.pendingURL = view.URL;
    self.deadline = NSProcessInfo.processInfo.systemUptime + 0.8;
    NSUInteger generation = self.generation;
    NSDictionary *arguments = @{@"clickX":@(point.x / view.pageZoom),
        @"clickY":@((view.isFlipped ? point.y : view.bounds.size.height - point.y) / view.pageZoom),
        @"expectedOrigin":origin, @"mode":@"inspect", @"token":@(generation)};
    __weak typeof(self) weakSelf = self;
    [view callAsyncJavaScript:self.script arguments:arguments inFrame:nil
        inContentWorld:self.world completionHandler:^(id result, NSError *error) {
        typeof(self) self = weakSelf;
        if (!self || error || ![self current:view generation:generation]
            || ![result isKindOfClass:NSString.class] || ![@[@"username", @"current-password"] containsObject:result]) return;
        NSString *key = [origin stringByAppendingFormat:@"|%@", result];
        if ([self.attempted containsObject:key]) return;
        NSMutableDictionary *confirmation = [arguments mutableCopy]; confirmation[@"mode"] = @"confirm";
        [view callAsyncJavaScript:self.script arguments:confirmation inFrame:nil
            inContentWorld:self.world completionHandler:^(id confirmed, NSError *confirmError) {
        typeof(self) self = weakSelf;
        if (!self || confirmError || ![confirmed isEqual:result] || ![self current:view generation:generation]
            || [self.attempted containsObject:key]) return;
        [self.attempted addObject:key];
        // Ask WebKit/AppKit to construct its real input context menu. Do not
        // invent private selectors, manufacture a credential target, or focus
        // any other view. The existing WebView menu behavior remains in charge.
        self.menuEvent = [NSEvent mouseEventWithType:NSEventTypeRightMouseDown location:event.locationInWindow
            modifierFlags:0 timestamp:NSProcessInfo.processInfo.systemUptime windowNumber:view.window.windowNumber
            context:nil eventNumber:event.eventNumber clickCount:1 pressure:0];
        [view.window sendEvent:self.menuEvent];
        }];
    }];
}
- (void)nativeMenuWillOpen:(NSMenu *)menu inView:(WKWebView *)view event:(NSEvent *)event {
    NSUInteger generation = self.generation;
    // WebKit normalizes its menu event into an OS-defined event (window 0),
    // rather than returning the original mouse event. Bind to our one issued
    // request, originating view and generation; every intervening real click,
    // key, drag, scroll or navigation cancels it before reaching this callback.
    if (!self.menuEvent || view != self.pendingView) return;
    if (![self current:view generation:generation]) { dispatch_async(dispatch_get_main_queue(), ^{ [menu cancelTrackingWithoutAnimation]; }); return; }
    self.pendingMenu = menu;
    __weak typeof(self) weakSelf = self;
    dispatch_async(dispatch_get_main_queue(), ^{
        typeof(self) self = weakSelf;
        if (!self || ![self current:view generation:generation] || self.pendingMenu != menu) {
            [menu cancelTrackingWithoutAnimation]; return;
        }
        id<NSAccessibility> item = GewuBrowserPasswordMenuItem(menu);
        // Clear our pending operation BEFORE the OS opens its own panel. App
        // deactivation, authentication and text delivery belong entirely to it.
        self.pendingMenu = nil; self.pendingView = nil; self.pendingURL = nil; self.menuEvent = nil;
        if (!item || ![self performPasswordMenuItem:item]) [menu cancelTrackingWithoutAnimation];
    });
}
- (BOOL)performPasswordMenuItem:(id<NSAccessibility>)item {
    return [item accessibilityPerformPress];
}
@end
