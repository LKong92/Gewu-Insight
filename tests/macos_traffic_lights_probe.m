// Exercise the actual launcher layout with AppKit windows, without launching
// the product, starting its server, or opening any Library data.
#define main GewuUnusedApplicationEntry
#import "PaperMonitorApp.m"
#undef main

static NSUInteger checks = 0;
static void check(BOOL ok, NSString *message) {
    checks++;
    if (!ok) { fprintf(stderr, "%s\n", message.UTF8String); exit(1); }
}

@interface LayoutProbeWindow : GewuInsightWindow
@property BOOL pretendFullScreen;
@end
@implementation LayoutProbeWindow
- (NSWindowStyleMask)styleMask {
    return [super styleMask] | (self.pretendFullScreen ? NSWindowStyleMaskFullScreen : 0);
}
@end

static NSRect buttonRect(PaperMonitorDelegate *delegate, NSButton *button) {
    return [button convertRect:button.bounds toView:delegate.webView];
}

static void verifyAlignment(PaperMonitorDelegate *delegate) {
    NSView *root = delegate.window.contentView.superview;
    for (NSNumber *kind in @[@(NSWindowCloseButton), @(NSWindowMiniaturizeButton), @(NSWindowZoomButton)]) {
        NSButton *button = [delegate.window standardWindowButton:kind.unsignedIntegerValue];
        NSRect rect = buttonRect(delegate, button);
        CGFloat top = NSMaxY(delegate.webView.bounds) - NSMidY(rect);
        check(fabs(top - 23.0) <= 0.5, [NSString stringWithFormat:@"Button %@ is %.2f pt from top", kind, top]);
        // The entire visible button must remain inside its native ancestors;
        // checking only its center would miss the lower-half click regression.
        for (NSView *parent = button.superview; parent; parent = parent.superview) {
            NSRect inside = [button convertRect:button.bounds toView:parent];
            check(NSContainsRect(parent.bounds, inside), @"Button clipped by native titlebar");
        }
        for (NSNumber *fraction in @[@0.15, @0.5, @0.85]) {
            NSPoint point = [button convertPoint:NSMakePoint(NSMidX(button.bounds), NSHeight(button.bounds) * fraction.doubleValue) toView:root];
            NSView *hit = [root hitTest:point];
            check(hit == button || [hit isDescendantOf:button], @"Native button hit target lost");
        }
    }
}

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        PaperMonitorDelegate *delegate = [PaperMonitorDelegate new];
        LayoutProbeWindow *window = [[LayoutProbeWindow alloc] initWithContentRect:NSMakeRect(0, 0, 1280, 860)
            styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
                | NSWindowStyleMaskResizable | NSWindowStyleMaskFullSizeContentView
            backing:NSBackingStoreBuffered defer:NO];
        window.releasedWhenClosed = NO;
        window.titleVisibility = NSWindowTitleHidden;
        window.titlebarAppearsTransparent = YES;
        delegate.window = window;
        window.delegate = delegate;
        // Layout only uses NSView geometry. Avoid creating any WebKit process.
        NSView *workspace = [[NSView alloc] initWithFrame:window.contentView.bounds];
        workspace.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
        [window.contentView addSubview:workspace];
        delegate.webView = (WKWebView *)workspace;
        [window layoutIfNeeded];
        NSButton *close = [window standardWindowButton:NSWindowCloseButton];
        NSRect originalButton = close.frame;
        NSView *titlebarContainer = close.superview.superview;
        NSRect originalContainer = titlebarContainer.frame;
        [delegate positionTrafficLightButtons];
        verifyAlignment(delegate);

        // Reproduce a native reset AFTER the initial/queued resize correction.
        // There is no resize notification here to rescue the old implementation.
        titlebarContainer.frame = originalContainer;
        close.frame = originalButton;
        check(fabs(NSMaxY(workspace.bounds) - NSMidY(buttonRect(delegate, close)) - 23.0) > 1.0,
            @"Fixture must first reproduce the higher native position");
        [window update];
        verifyAlignment(delegate);

        NSRect stable = buttonRect(delegate, close);
        __block NSUInteger changes = 0;
        close.postsFrameChangedNotifications = YES;
        id observer = [NSNotificationCenter.defaultCenter addObserverForName:NSViewFrameDidChangeNotification
            object:close queue:nil usingBlock:^(NSNotification *note) { changes++; }];
        for (NSUInteger i = 0; i < 100; i++) [window update];
        check(changes == 0 && NSEqualRects(stable, buttonRect(delegate, close)), @"Idle updates must not cause layout churn");
        [NSNotificationCenter.defaultCenter removeObserver:observer];

        for (NSNumber *height in @[@680, @940, @760]) {
            [window setContentSize:NSMakeSize(1100, height.doubleValue)];
            [window.contentView.superview setNeedsLayout:YES];
            [window layoutIfNeeded];
            [window update];
            verifyAlignment(delegate);
        }

        NSWindow *other = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 300, 200)
            styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        other.releasedWhenClosed = NO;
        NSRect shifted = close.frame;
        shifted.origin.y += 6;
        close.frame = shifted;
        [delegate windowDidUpdate:[NSNotification notificationWithName:NSWindowDidUpdateNotification object:other]];
        check(NSEqualRects(close.frame, shifted), @"Other windows must not reposition the main buttons");
        [window update];
        verifyAlignment(delegate);

        NSNotification *transition = [NSNotification notificationWithName:NSWindowWillEnterFullScreenNotification object:window];
        [delegate windowWillEnterFullScreen:transition];
        shifted = close.frame; shifted.origin.y += 6; close.frame = shifted;
        [window update];
        [delegate positionTrafficLightButtons];
        check(NSEqualRects(close.frame, shifted), @"Leave entering-fullscreen animation to AppKit");
        [delegate windowDidFailToEnterFullScreen:window];
        verifyAlignment(delegate);

        window.pretendFullScreen = YES;
        [delegate windowDidEnterFullScreen:transition];
        shifted = close.frame; shifted.origin.y += 6; close.frame = shifted;
        [window update];
        check(NSEqualRects(close.frame, shifted), @"Leave fullscreen toolbar placement to AppKit");
        [delegate windowWillExitFullScreen:transition];
        window.pretendFullScreen = NO;
        [window update];
        check(NSEqualRects(close.frame, shifted), @"Do not reposition during the exit animation");
        [delegate windowDidExitFullScreen:transition];
        [window update];
        verifyAlignment(delegate);
        [other close];
        [window close];
        printf("%lu traffic-light layout checks passed\n", (unsigned long)checks);
    }
    return 0;
}
