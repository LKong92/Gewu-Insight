#define main GewuUnusedApplicationEntry
#import "PaperMonitorApp.m"
#undef main

static NSUInteger checks;
static void check(BOOL value, NSString *message) {
    checks++;
    if (!value) { fprintf(stderr, "%s\n", message.UTF8String); exit(1); }
}
@interface DragProbeWindow : GewuInsightWindow
@property NSEvent *handedOffEvent;
@property NSUInteger handoffs;
@property BOOL pretendFullScreen;
@end
@implementation DragProbeWindow
- (void)performWindowDragWithEvent:(NSEvent *)event { self.handedOffEvent = event; self.handoffs++; }
- (NSWindowStyleMask)styleMask {
    return [super styleMask] | (self.pretendFullScreen ? NSWindowStyleMaskFullScreen : 0);
}
@end
@interface FlippedDragProbeView : NSView
@end
@implementation FlippedDragProbeView
- (BOOL)isFlipped { return YES; }
@end
static NSEvent *mouseEvent(NSWindow *window, NSEventType type, NSPoint point) {
    return [NSEvent mouseEventWithType:type location:point modifierFlags:0
        timestamp:NSProcessInfo.processInfo.systemUptime windowNumber:window.windowNumber
        context:nil eventNumber:1 clickCount:1 pressure:1];
}
int main(void) { @autoreleasepool {
    [NSApplication sharedApplication];
    DragProbeWindow *window = [[DragProbeWindow alloc] initWithContentRect:NSMakeRect(40,40,800,600)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    NSView *view = window.contentView;
    NSPoint down = NSMakePoint(400, 580), client = NSMakePoint(400, 20);
    NSEvent *event = mouseEvent(window, NSEventTypeLeftMouseDown, down);
    NSRect before = window.frame;
    window.pendingWindowDragMouseDown = event;
    [window beginNativeWindowDragAtClientPoint:client inView:view];
    check(window.handoffs == 1 && window.handedOffEvent == event,
        [NSString stringWithFormat:@"Hand off original NSEvent unchanged (window=%ld eventWindow=%@ view=%@ bounds=%@ origin=%@)",
            (long)window.windowNumber, event.window, view.window, NSStringFromRect(view.bounds),
            NSStringFromPoint([view convertPoint:event.locationInWindow fromView:nil])]);
    check(NSEqualRects(before, window.frame), @"Application must not move the frame itself");
    check(window.pendingWindowDragMouseDown == nil, @"No stale state if Window Server consumes mouse-up");
    [window beginNativeWindowDragAtClientPoint:client inView:view];
    check(window.handoffs == 1, @"Duplicate begin must not restart the drag");
    for (NSValue *value in @[[NSValue valueWithPoint:NSMakePoint(50,20)],
                              [NSValue valueWithPoint:NSMakePoint(NAN,20)]]) {
        window.pendingWindowDragMouseDown = event;
        [window beginNativeWindowDragAtClientPoint:value.pointValue inView:view];
        check(window.handoffs == 1, @"Reject mismatched/nonfinite DOM origin");
    }
    for (NSNumber *type in @[@(NSEventTypeLeftMouseUp), @(NSEventTypeRightMouseDown)]) {
        window.pendingWindowDragMouseDown = mouseEvent(window, type.unsignedIntegerValue, down);
        [window beginNativeWindowDragAtClientPoint:client inView:view];
        check(window.handoffs == 1, @"Only genuine left mouse-down can start a window drag");
    }
    window.pendingWindowDragMouseDown = event;
    window.pretendFullScreen = YES;
    [window beginNativeWindowDragAtClientPoint:client inView:view];
    check(window.handoffs == 1, @"Leave fullscreen handling to the system");
    window.pretendFullScreen = NO;
    NSView *detached = [[NSView alloc] initWithFrame:view.bounds];
    window.pendingWindowDragMouseDown = event;
    [window beginNativeWindowDragAtClientPoint:client inView:detached];
    check(window.handoffs == 1, @"Reject another view/window");
    window.pendingWindowDragMouseDown = event;
    [window sendEvent:mouseEvent(window, NSEventTypeLeftMouseUp, down)];
    [window beginNativeWindowDragAtClientPoint:client inView:view];
    check(window.handoffs == 1 && window.pendingWindowDragMouseDown == nil, @"Released mouse cancels delayed bridge request");
    FlippedDragProbeView *flipped = [[FlippedDragProbeView alloc] initWithFrame:view.bounds];
    [view addSubview:flipped];
    window.pendingWindowDragMouseDown = event;
    [window beginNativeWindowDragAtClientPoint:client inView:flipped];
    check(window.handoffs == 2 && window.handedOffEvent == event, @"Support WebKit's flipped coordinates");
    printf("%lu native window handoff checks passed\n", (unsigned long)checks);
} return 0; }
