#import <Cocoa/Cocoa.h>
#import <Quartz/Quartz.h>
#import <WebKit/WebKit.h>
#import "GewuBrowserController.h"
#import "GewuWorkspaceNavigation.h"
#include <string.h>

static const NSTimeInterval GewuInsightServerStartupTimeout = 120.0;
static const NSTimeInterval GewuInsightServerPollInterval = 0.25;
static const NSTimeInterval GewuInsightServerRecoveryDelay = 0.75;
static const NSInteger GewuInsightServerMaxRestartAttempts = 3;

static void GewuConfigureConfirmationDetails(NSAlert *alert, NSString *message, NSWindow *parentWindow) {
    NSString *text = message.length ? message : @"Delete this file?";
    // Keep short confirmations compact; long file lists get a fixed viewport.
    if (text.length <= 600 && [text componentsSeparatedByString:@"\n"].count <= 8) {
        alert.informativeText = text;
        return;
    }
    NSRange paragraph = [text rangeOfString:@"\n\n"];
    if (paragraph.location != NSNotFound && paragraph.location <= 240) {
        alert.informativeText = [text substringToIndex:paragraph.location];
        text = [text substringFromIndex:NSMaxRange(paragraph)];
    } else {
        alert.informativeText = @"Review the details below before deleting.";
    }
    NSScreen *screen = parentWindow.screen ?: NSScreen.mainScreen;
    NSSize available = screen ? screen.visibleFrame.size : NSMakeSize(1024, 768);
    if (parentWindow) {
        available.width = MIN(available.width, NSWidth(parentWindow.frame));
        available.height = MIN(available.height, NSHeight(parentWindow.frame));
    }
    CGFloat width = MAX(180, MIN(520, available.width - 180));
    CGFloat height = MAX(80, MIN(320, available.height - 260));
    NSScrollView *scroll = [[NSScrollView alloc] initWithFrame:NSMakeRect(0, 0, width, height)];
    scroll.hasVerticalScroller = YES;
    scroll.hasHorizontalScroller = NO;
    scroll.autohidesScrollers = NO;
    scroll.borderType = NSBezelBorder;
    scroll.accessibilityLabel = @"Deletion details and files";
    NSSize contentSize = scroll.contentSize;
    NSTextView *details = [[NSTextView alloc] initWithFrame:NSMakeRect(0, 0, contentSize.width, contentSize.height)];
    details.editable = NO;
    details.selectable = YES;
    details.richText = NO;
    details.font = [NSFont systemFontOfSize:13];
    details.textColor = NSColor.labelColor;
    details.backgroundColor = NSColor.textBackgroundColor;
    details.textContainerInset = NSMakeSize(8, 8);
    details.verticallyResizable = YES;
    details.horizontallyResizable = NO;
    details.autoresizingMask = NSViewWidthSizable;
    details.minSize = NSMakeSize(0, contentSize.height);
    details.maxSize = NSMakeSize(CGFLOAT_MAX, CGFLOAT_MAX);
    details.textContainer.containerSize = NSMakeSize(contentSize.width - 16, CGFLOAT_MAX);
    details.textContainer.widthTracksTextView = YES;
    NSMutableParagraphStyle *style = [[NSMutableParagraphStyle alloc] init];
    style.lineBreakMode = NSLineBreakByCharWrapping;
    details.defaultParagraphStyle = style;
    details.string = text;
    details.accessibilityLabel = @"Files and deletion effects";
    scroll.documentView = details;
    [details.layoutManager ensureLayoutForTextContainer:details.textContainer];
    [details sizeToFit];
    [details scrollRangeToVisible:NSMakeRange(0, 0)];
    alert.accessoryView = scroll;
}

// This view paints synchronously with the window's first frame. A second
// WKWebView would itself need an asynchronous first paint before showing this art.
@interface GewuStartupView : NSView
@property(nonatomic, strong) NSImage *icon;
@property(nonatomic, strong) NSImage *brandArt;
@end

@implementation GewuStartupView
- (instancetype)initWithFrame:(NSRect)frame {
    self = [super initWithFrame:frame];
    if (self) {
        self.wantsLayer = YES;
        self.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
        NSURL *iconURL = [[NSBundle mainBundle] URLForResource:@"GewuInsightAppIcon" withExtension:@"png"];
        NSURL *artURL = [[NSBundle mainBundle] URLForResource:@"GewuSealGlyphs" withExtension:@"png"];
        self.icon = iconURL ? [[NSImage alloc] initWithContentsOfURL:iconURL] : nil;
        self.brandArt = artURL ? [[NSImage alloc] initWithContentsOfURL:artURL] : nil;
        self.accessibilityElement = YES;
        self.accessibilityRole = NSAccessibilityGroupRole;
        self.accessibilityLabel = @"Starting Gewu Insight. Preparing the local reading workspace.";
    }
    return self;
}
- (void)setBrandArt:(NSImage *)source {
    // The packaged seal has light glyphs. Match the startup page's black tint
    // while retaining the PNG's alpha, without waiting for a web CSS filter.
    _brandArt = source ? [NSImage imageWithSize:NSMakeSize(236, 236) flipped:NO drawingHandler:^BOOL(NSRect rect) {
        [source drawInRect:rect fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:1];
        [NSColor.blackColor setFill];
        NSRectFillUsingOperation(rect, NSCompositingOperationSourceIn);
        return YES;
    }] : nil;
}
- (BOOL)isFlipped { return YES; }
- (BOOL)isOpaque { return YES; }
- (void)setFrameSize:(NSSize)size {
    [super setFrameSize:size];
    self.needsDisplay = YES;
}
- (void)drawRect:(NSRect)dirtyRect {
    [[NSColor colorWithRed:244.0/255.0 green:242.0/255.0 blue:237.0/255.0 alpha:1.0] setFill];
    NSRectFill(self.bounds);
    NSRect card = NSMakeRect((NSWidth(self.bounds) - 460.0) / 2.0,
                             (NSHeight(self.bounds) - 116.0) / 2.0, 460.0, 116.0);
    NSBezierPath *outline = [NSBezierPath bezierPathWithRoundedRect:card xRadius:18 yRadius:18];
    [NSGraphicsContext saveGraphicsState];
    NSShadow *shadow = [NSShadow new];
    shadow.shadowColor = [NSColor colorWithWhite:0 alpha:0.08];
    shadow.shadowBlurRadius = 32;
    shadow.shadowOffset = NSMakeSize(0, -12);
    [shadow set];
    [[NSColor colorWithWhite:1 alpha:0.78] setFill];
    [outline fill];
    [NSGraphicsContext restoreGraphicsState];
    [NSGraphicsContext saveGraphicsState];
    [outline addClip];
    [self.brandArt drawInRect:NSMakeRect(NSMaxX(card) - 208, NSMinY(card) - 66, 236, 236)
                    fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:0.075
              respectFlipped:YES hints:nil];
    [NSGraphicsContext restoreGraphicsState];
    [[NSColor colorWithRed:35.0/255.0 green:31.0/255.0 blue:26.0/255.0 alpha:0.12] setStroke];
    [outline stroke];
    [self.icon drawInRect:NSMakeRect(NSMinX(card) + 33, NSMinY(card) + 29, 58, 58)
                fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:1
          respectFlipped:YES hints:nil];
    [@"Starting Gewu Insight" drawAtPoint:NSMakePoint(NSMinX(card) + 111, NSMinY(card) + 33)
                         withAttributes:@{NSFontAttributeName:[NSFont boldSystemFontOfSize:19],
                                          NSForegroundColorAttributeName:[NSColor colorWithWhite:0.13 alpha:1]}];
    [@"Preparing the local reading workspace." drawAtPoint:NSMakePoint(NSMinX(card) + 111, NSMinY(card) + 60)
                         withAttributes:@{NSFontAttributeName:[NSFont systemFontOfSize:13],
                                          NSForegroundColorAttributeName:[NSColor colorWithWhite:0.36 alpha:1]}];
}
@end

// WKWebView implements these public AppKit callbacks for its own DOM drags.
@interface WKWebView (GewuDragLifecycle) <NSDraggingSource>
@end

@interface GewuInsightWebView : WKWebView <NSDraggingDestination, NSDraggingSource>
@property(nonatomic, copy) NSString *nativeDragPath;
@property(nonatomic, copy) NSString *nativeDragName;
@property(nonatomic, copy) NSString *nativeDragCleanupPath;
@property(nonatomic) BOOL nativeFileDragActive;
@property(nonatomic) BOOL pdfQuickLookActive;
@property(nonatomic) CGFloat pdfMagnificationAccumulator;
@property(nonatomic) NSInteger pendingLibraryItemDragId;
@property(nonatomic, copy) NSDictionary *pendingLibraryDragPayload;
@end

@implementation GewuInsightWebView

- (instancetype)initWithFrame:(NSRect)frame configuration:(WKWebViewConfiguration *)configuration {
    self = [super initWithFrame:frame configuration:configuration];
    if (self) {
        [self registerForDraggedTypes:@[NSPasteboardTypeFileURL, NSPasteboardTypeURL]];
    }
    return self;
}

- (NSDragOperation)draggingEntered:(id<NSDraggingInfo>)sender {
    if ([sender draggingSource] == self && !self.nativeFileDragActive) {
        return [super draggingEntered:sender];
    }
    if ([self finderDropPathsFromDraggingInfo:sender].count > 0) {
        [self updateFinderDropTargetForDraggingInfo:sender];
        return [sender draggingSource] == self ? (self.pendingLibraryDragPayload ? NSDragOperationMove : NSDragOperationNone) : NSDragOperationCopy;
    }
    return [super draggingEntered:sender];
}

- (NSDragOperation)draggingUpdated:(id<NSDraggingInfo>)sender {
    if ([sender draggingSource] == self && !self.nativeFileDragActive) {
        return [super draggingUpdated:sender];
    }
    if ([self finderDropPathsFromDraggingInfo:sender].count > 0) {
        [self updateFinderDropTargetForDraggingInfo:sender];
        return [sender draggingSource] == self ? (self.pendingLibraryDragPayload ? NSDragOperationMove : NSDragOperationNone) : NSDragOperationCopy;
    }
    return [super draggingUpdated:sender];
}

- (void)draggingExited:(id<NSDraggingInfo>)sender {
    if ([sender draggingSource] == self && !self.nativeFileDragActive) {
        [super draggingExited:sender];
        return;
    }
    [self clearFinderDropTarget];
    [super draggingExited:sender];
}

- (BOOL)performDragOperation:(id<NSDraggingInfo>)sender {
    if ([sender draggingSource] == self) {
        // WebKit also uses this view as the source when dragging a row/title.
        // Only sessions we started from a file icon use the native payload.
        // Rejecting a DOM session here prevents its JavaScript drop entirely.
        if (!self.nativeFileDragActive) return [super performDragOperation:sender];
        if (!self.pendingLibraryDragPayload) return NO;
        [self dispatchPendingLibraryItemDropAtClientPoint:[self browserClientPointForDraggingInfo:sender]];
        return YES;
    }
    NSArray<NSString *> *paths = [self finderDropPathsFromDraggingInfo:sender];
    if (paths.count == 0) {
        return [super performDragOperation:sender];
    }
    NSError *error = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:paths options:0 error:&error];
    if (!data || error) {
        return NO;
    }
    NSString *json = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    NSPoint point = [self browserClientPointForDraggingInfo:sender];
    NSString *script = [NSString stringWithFormat:@"window.handleNativeFinderDrop && window.handleNativeFinderDrop(%@, {x:%0.2f,y:%0.2f})", json ?: @"[]", point.x, point.y];
    [self evaluateJavaScript:script completionHandler:nil];
    return YES;
}

- (NSPoint)browserClientPointForDraggingInfo:(id<NSDraggingInfo>)sender {
    NSPoint point = [self convertPoint:sender.draggingLocation fromView:nil];
    return [self browserClientPointForViewPoint:point];
}

- (NSPoint)browserClientPointForViewPoint:(NSPoint)point {
    CGFloat clientX = point.x;
    CGFloat clientY = self.isFlipped ? point.y : self.bounds.size.height - point.y;
    return NSMakePoint(clientX, clientY);
}

- (void)dispatchPendingLibraryItemDropAtClientPoint:(NSPoint)point {
    NSDictionary *payload = self.pendingLibraryDragPayload;
    self.pendingLibraryDragPayload = nil;
    self.pendingLibraryItemDragId = 0;
    if (!payload) return;
    NSData *data = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
    if (!data) return;
    NSString *json = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    NSString *script = [NSString stringWithFormat:
        @"window.handleNativeLibraryManagedDrop && window.handleNativeLibraryManagedDrop(%@, {x:%0.2f,y:%0.2f})",
        json, point.x, point.y];
    [self evaluateJavaScript:script completionHandler:nil];
}

- (void)updateFinderDropTargetForDraggingInfo:(id<NSDraggingInfo>)sender {
    NSPoint point = [self browserClientPointForDraggingInfo:sender];
    NSString *script = [NSString stringWithFormat:@"window.updateNativeFinderDropTarget && window.updateNativeFinderDropTarget({x:%0.2f,y:%0.2f})", point.x, point.y];
    [self evaluateJavaScript:script completionHandler:nil];
}

- (void)clearFinderDropTarget {
    [self evaluateJavaScript:@"window.clearNativeFinderDropTarget && window.clearNativeFinderDropTarget()" completionHandler:nil];
}

- (void)setPdfQuickLookActive:(BOOL)active {
    _pdfQuickLookActive = active;
    self.pdfMagnificationAccumulator = 0;
    if (active) {
        [self hidePDFHUDSubviews];
    }
}

- (void)didAddSubview:(NSView *)subview {
    [super didAddSubview:subview];
    if (self.pdfQuickLookActive) {
        [self hidePDFHUDSubviewsInView:subview];
    }
}

- (void)layout {
    [super layout];
    if (self.pdfQuickLookActive) {
        [self hidePDFHUDSubviews];
    }
}

- (void)hidePDFHUDSubviews {
    for (NSView *subview in self.subviews) {
        [self hidePDFHUDSubviewsInView:subview];
    }
}

- (void)hidePDFHUDSubviewsInView:(NSView *)view {
    if ([NSStringFromClass(view.class) containsString:@"WKPDFHUDView"]) {
        view.hidden = YES;
        return;
    }
    for (NSView *subview in view.subviews) {
        [self hidePDFHUDSubviewsInView:subview];
    }
}

- (void)collectPDFHUDSubviewsInView:(NSView *)view into:(NSMutableArray<NSView *> *)result {
    if ([NSStringFromClass(view.class) containsString:@"WKPDFHUDView"]) {
        [result addObject:view];
        return;
    }
    for (NSView *subview in view.subviews) {
        [self collectPDFHUDSubviewsInView:subview into:result];
    }
}

- (NSArray<NSView *> *)pdfHUDSubviews {
    NSMutableArray<NSView *> *result = [NSMutableArray array];
    for (NSView *subview in self.subviews) {
        [self collectPDFHUDSubviewsInView:subview into:result];
    }
    return result;
}

- (BOOL)performPDFHUDZoomIn:(BOOL)zoomIn {
    BOOL handled = NO;
    SEL directSelector = NSSelectorFromString(zoomIn ? @"performPDFZoomIn" : @"performPDFZoomOut");
    SEL legacyVisibleSelector = NSSelectorFromString(@"_setVisible:");
    SEL legacyActionSelector = NSSelectorFromString(@"_performActionForControl:");
    NSString *legacyControl = zoomIn ? @"plus.magnifyingglass" : @"minus.magnifyingglass";
    for (NSView *hud in [self pdfHUDSubviews]) {
        if ([hud respondsToSelector:directSelector]) {
            IMP implementation = [hud methodForSelector:directSelector];
            ((void (*)(id, SEL))implementation)(hud, directSelector);
            handled = YES;
            continue;
        }
        if (![hud respondsToSelector:legacyActionSelector]) continue;
        if ([hud respondsToSelector:legacyVisibleSelector]) {
            IMP visibleImplementation = [hud methodForSelector:legacyVisibleSelector];
            ((void (*)(id, SEL, BOOL))visibleImplementation)(hud, legacyVisibleSelector, YES);
        }
        IMP actionImplementation = [hud methodForSelector:legacyActionSelector];
        ((void (*)(id, SEL, id))actionImplementation)(hud, legacyActionSelector, legacyControl);
        handled = YES;
    }
    [self hidePDFHUDSubviews];
    return handled;
}

- (void)magnifyWithEvent:(NSEvent *)event {
    if (!self.pdfQuickLookActive) {
        [super magnifyWithEvent:event];
        return;
    }
    if (event.phase == NSEventPhaseBegan) {
        self.pdfMagnificationAccumulator = 0;
    }
    self.pdfMagnificationAccumulator += event.magnification;
    const CGFloat step = 0.045;
    NSInteger actionCount = 0;
    BOOL handled = NO;
    while (fabs(self.pdfMagnificationAccumulator) >= step && actionCount < 4) {
        BOOL zoomIn = self.pdfMagnificationAccumulator > 0;
        handled = [self performPDFHUDZoomIn:zoomIn] || handled;
        self.pdfMagnificationAccumulator += zoomIn ? -step : step;
        actionCount += 1;
    }
    if (!handled && actionCount > 0) {
        [super magnifyWithEvent:event];
    }
    if (event.phase == NSEventPhaseEnded || event.phase == NSEventPhaseCancelled) {
        self.pdfMagnificationAccumulator = 0;
    }
}

- (void)mouseDragged:(NSEvent *)event {
    if (self.nativeDragPath.length > 0) {
        NSString *path = self.nativeDragPath;
        self.nativeDragPath = nil;
        self.nativeDragName = nil;
        if ([[NSFileManager defaultManager] fileExistsAtPath:path]) {
            NSURL *fileURL = [[NSURL fileURLWithPath:path] URLByResolvingSymlinksInPath];
            NSDraggingItem *draggingItem = [[NSDraggingItem alloc] initWithPasteboardWriter:fileURL];
            NSImage *icon = [[NSWorkspace sharedWorkspace] iconForFile:path];
            icon.size = NSMakeSize(48, 48);
            NSPoint point = [self convertPoint:event.locationInWindow fromView:nil];
            NSRect frame = NSMakeRect(point.x - 24, point.y - 24, 48, 48);
            [draggingItem setDraggingFrame:frame contents:icon];
            self.nativeFileDragActive = YES;
            NSDraggingSession *session = [self beginDraggingSessionWithItems:@[draggingItem] event:event source:self];
            if (!session) {
                self.nativeFileDragActive = NO;
                self.pendingLibraryDragPayload = nil;
                self.pendingLibraryItemDragId = 0;
            }
            return;
        }
    }
    [super mouseDragged:event];
}

- (void)scheduleNativeDragCleanup:(NSString *)path afterDelay:(NSTimeInterval)delay {
    if (path.length == 0) return;
    NSString *cleanupPath = [path copy];
    dispatch_after(
        dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)),
        dispatch_get_global_queue(QOS_CLASS_UTILITY, 0),
        ^{
            [[NSFileManager defaultManager] removeItemAtPath:cleanupPath error:nil];
        }
    );
}

- (void)mouseUp:(NSEvent *)event {
    if (self.nativeDragPath.length > 0 && self.nativeDragCleanupPath.length > 0) {
        [self scheduleNativeDragCleanup:self.nativeDragCleanupPath afterDelay:0.5];
    }
    self.nativeDragPath = nil;
    self.nativeDragName = nil;
    self.nativeDragCleanupPath = nil;
    [super mouseUp:event];
    if (!self.nativeFileDragActive) {
        self.pendingLibraryDragPayload = nil;
        self.pendingLibraryItemDragId = 0;
    }
}

- (NSDragOperation)draggingSession:(NSDraggingSession *)session sourceOperationMaskForDraggingContext:(NSDraggingContext)context {
    if (!self.nativeFileDragActive) {
        return [super draggingSession:session sourceOperationMaskForDraggingContext:context];
    }
    // Finder copies the file; application icons can negotiate opening it.
    // Moves within Gewu use managed ownership transitions; outside exports stay copies.
    return context == NSDraggingContextOutsideApplication
        ? (NSDragOperationCopy | NSDragOperationGeneric)
        : (NSDragOperationCopy | NSDragOperationMove);
}

- (BOOL)ignoreModifierKeysForDraggingSession:(NSDraggingSession *)session {
    return YES;
}

- (void)draggingSession:(NSDraggingSession *)session willBeginAtPoint:(NSPoint)screenPoint {
    if (!self.nativeFileDragActive && [WKWebView instancesRespondToSelector:_cmd]) {
        [super draggingSession:session willBeginAtPoint:screenPoint];
    }
}

- (void)draggingSession:(NSDraggingSession *)session
           endedAtPoint:(NSPoint)screenPoint
              operation:(NSDragOperation)operation {
    if (!self.nativeFileDragActive) {
        if ([WKWebView instancesRespondToSelector:_cmd]) {
            [super draggingSession:session endedAtPoint:screenPoint operation:operation];
        } else {
            // Older WebKit (including macOS 15) ends DOM drags through this
            // public legacy callback. It dispatches dragend to the web page.
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
            [super draggedImage:nil endedAt:screenPoint operation:operation];
#pragma clang diagnostic pop
        }
        return;
    }
    NSPoint windowPoint = [self.window convertPointFromScreen:screenPoint];
    NSPoint viewPoint = [self convertPoint:windowPoint fromView:nil];
    NSPoint clientPoint = [self browserClientPointForViewPoint:viewPoint];
    NSString *cleanupPath = self.nativeDragCleanupPath;
    self.nativeDragCleanupPath = nil;
    [self scheduleNativeDragCleanup:cleanupPath afterDelay:60.0];
    if ((operation & NSDragOperationMove) && NSPointInRect(viewPoint, self.bounds)) {
        [self dispatchPendingLibraryItemDropAtClientPoint:clientPoint];
    }
    self.pendingLibraryDragPayload = nil;
    self.pendingLibraryItemDragId = 0;
    self.nativeFileDragActive = NO;
    [self evaluateJavaScript:@"window.clearNativeLibraryDrag && window.clearNativeLibraryDrag()" completionHandler:nil];
}

- (NSArray<NSString *> *)finderDropPathsFromDraggingInfo:(id<NSDraggingInfo>)sender {
    NSPasteboard *pasteboard = sender.draggingPasteboard;
    NSMutableArray<NSString *> *paths = [NSMutableArray array];
    NSMutableSet<NSString *> *seen = [NSMutableSet set];

    NSDictionary *options = @{NSPasteboardURLReadingFileURLsOnlyKey: @YES};
    NSArray<NSURL *> *urls = [pasteboard readObjectsForClasses:@[[NSURL class]] options:options];
    for (NSURL *url in urls) {
        if (!url.isFileURL || !url.path) continue;
        if ([seen containsObject:url.path]) continue;
        [seen addObject:url.path];
        [paths addObject:url.path];
    }
    return paths;
}

@end

// macOS WebKit may route file drags to an internal scrolling view instead of
// the WKWebView subclass. A sibling destination covers the complete workspace
// without depending on the DOM's composited hit regions. It only registers
// native file URLs; ordinary clicks and HTML row/sort drags stay with WebKit.
@interface GewuFinderDropView : NSView <NSDraggingDestination>
@property(nonatomic, weak) GewuInsightWebView *destinationWebView;
@end

@implementation GewuFinderDropView

- (instancetype)initWithFrame:(NSRect)frame {
    self = [super initWithFrame:frame];
    if (self) {
        self.wantsLayer = YES;
        [self registerForDraggedTypes:@[NSPasteboardTypeFileURL]];
    }
    return self;
}

- (NSView *)hitTest:(NSPoint)point { return nil; }

- (NSDragOperation)draggingEntered:(id<NSDraggingInfo>)sender {
    return [self.destinationWebView draggingEntered:sender];
}

- (NSDragOperation)draggingUpdated:(id<NSDraggingInfo>)sender {
    return [self.destinationWebView draggingUpdated:sender];
}

- (void)draggingExited:(id<NSDraggingInfo>)sender {
    [self.destinationWebView clearFinderDropTarget];
}

- (BOOL)prepareForDragOperation:(id<NSDraggingInfo>)sender {
    GewuInsightWebView *webView = self.destinationWebView;
    if (!webView || [webView finderDropPathsFromDraggingInfo:sender].count == 0) return NO;
    if (sender.draggingSource == webView) {
        return webView.nativeFileDragActive && webView.pendingLibraryDragPayload != nil;
    }
    return YES;
}

- (BOOL)performDragOperation:(id<NSDraggingInfo>)sender {
    if (![self prepareForDragOperation:sender]) return NO;
    return [self.destinationWebView performDragOperation:sender];
}

@end

@interface GewuInsightWindow : NSWindow
@property(nonatomic, strong) NSEvent *pendingWindowDragMouseDown;
- (void)beginNativeWindowDragAtClientPoint:(NSPoint)point inView:(NSView *)view;
@end

@implementation GewuInsightWindow

- (void)sendEvent:(NSEvent *)event {
    // WebKit's message arrives asynchronously. Retain the original AppKit
    // mouse-down, while leaving all event dispatch and hit testing unchanged.
    if (event.type == NSEventTypeLeftMouseDown) self.pendingWindowDragMouseDown = event;
    else if (event.type == NSEventTypeLeftMouseUp) self.pendingWindowDragMouseDown = nil;
    [super sendEvent:event];
}

- (void)beginNativeWindowDragAtClientPoint:(NSPoint)point inView:(NSView *)view {
    NSEvent *event = self.pendingWindowDragMouseDown;
    self.pendingWindowDragMouseDown = nil;
    if (!event || event.window != self || view.window != self
        || event.type != NSEventTypeLeftMouseDown
        || (self.styleMask & NSWindowStyleMaskFullScreen)) return;
    NSPoint origin = [view convertPoint:event.locationInWindow fromView:nil];
    NSPoint clientOrigin = NSMakePoint(origin.x,
        view.isFlipped ? origin.y : NSHeight(view.bounds) - origin.y);
    if (!NSPointInRect(origin, view.bounds) || !isfinite(point.x) || !isfinite(point.y)
        || hypot(clientOrigin.x - point.x, clientOrigin.y - point.y) > 2.0) return;
    // Window Server owns the drag, including edge tiling and Spaces switching.
    // It may consume mouse-up, so no application drag loop remains to stop.
    [self performWindowDragWithEvent:event];
}

@end

@interface PaperMonitorDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate, WKDownloadDelegate, WKScriptMessageHandler, QLPreviewPanelDataSource, QLPreviewPanelDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) GewuBrowserController *browserController;
@property(nonatomic, strong) GewuStartupView *startupView;
@property(nonatomic, strong) NSWindow *loaderWindow;
@property(nonatomic, strong) WKWebView *loaderWebView;
@property(nonatomic, strong) NSWindow *userGuideWindow;
@property(nonatomic, strong) WKWebView *userGuideWebView;
@property(nonatomic, strong) NSWindow *aboutWindow;
@property(nonatomic, strong) WKWebView *hiddenPublisherWebView;
@property(nonatomic, strong) WKDownload *hiddenPublisherDownload;
@property(nonatomic, copy) NSDictionary *hiddenPublisherContext;
@property(nonatomic, copy) NSString *hiddenPublisherToken;
@property(nonatomic, copy) NSString *hiddenPublisherTemporaryPath;
@property(nonatomic, strong) NSTimer *hiddenPublisherTimeout;
@property(nonatomic) BOOL hiddenPublisherDownloadTransitionPending;
@property(nonatomic, strong) NSMutableSet<NSString *> *hiddenPublisherDiscoveryVisitedURLs;
@property(nonatomic) NSInteger hiddenPublisherDiscoveryDepth;
@property(nonatomic) NSInteger hiddenPublisherDiscoveryPageRetryCount;
@property(nonatomic, strong) NSTask *ownedServerTask;
@property(nonatomic, strong) NSDate *serverStartupDeadline;
@property(nonatomic) BOOL serverReadinessPollActive;
@property(nonatomic) BOOL applicationIsTerminating;
@property(nonatomic) BOOL mainAppHasLoaded;
@property(nonatomic) BOOL startupFailurePresented;
@property(nonatomic, strong) NSAlert *startupFailureAlert;
@property(nonatomic) NSInteger serverRestartAttempts;
@property(nonatomic, strong) NSDate *workspaceRecoveryWindow;
@property(nonatomic) NSInteger workspaceRecoveryAttempts;
@property(nonatomic, strong) NSURL *url;
@property(nonatomic, strong) NSMenuItem *titleNamingItem;
@property(nonatomic, strong) NSMenuItem *citationNamingItem;
@property(nonatomic, strong) NSMenuItem *listViewItem;
@property(nonatomic, strong) NSMenuItem *tableViewItem;
@property(nonatomic) NSRect windowRestoreFrame;
@property(nonatomic) BOOL trafficLightLayoutScheduled;
@property(nonatomic) BOOL trafficLightLayoutInProgress;
@property(nonatomic) BOOL trafficLightFullScreenTransition;
@property(nonatomic, strong) NSURL *nativeQuickLookURL;
@property(nonatomic) BOOL nativeQuickLookActive;
@property(nonatomic) BOOL nativeQuickLookClosingProgrammatically;
@property(nonatomic, strong) id nativeQuickLookKeyMonitor;
@property(nonatomic) BOOL nativeQuickLookKeyDispatchInFlight;
@property(nonatomic, copy) NSString *nativeQuickLookPendingKey;
@property(nonatomic) NSInteger nativeQuickLookKeyDispatchGeneration;
@property(nonatomic) BOOL nativeQuickLookReloadScheduled;
- (NSMutableURLRequest *)workspaceRequestForURL:(NSURL *)url;
- (void)toggleMainWindowFill;
- (NSRect)defaultRestoreFrameForScreen:(NSScreen *)screen;
- (void)showAuthorPhotoChooserForAuthorId:(NSNumber *)authorId;
- (void)showPaperFileChooserWithPayload:(NSDictionary *)payload;
- (void)dismissStartupOverlay;
- (BOOL)showNativeQuickLookForPath:(NSString *)path;
- (void)closeNativeQuickLookNotifyingWeb:(BOOL)notifyWeb;
- (void)restoreMainWindowFocusForNativeQuickLook;
- (void)installNativeQuickLookKeyMonitor;
- (void)removeNativeQuickLookKeyMonitor;
- (void)dispatchNativeQuickLookKey:(NSString *)key;
- (void)scheduleNativeQuickLookReload;
- (void)beginServerReadinessPolling;
- (void)recoverServerAfterUnexpectedExit;
- (BOOL)restartServerForCurrentOutageIfPossible;
- (void)appendLauncherLogMessage:(NSString *)message;
- (void)dismissStartupFailureAlert;
- (void)recheckServerWhileStartupFailureIsVisible;
@end

@implementation PaperMonitorDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSString *applicationIconName = [[NSBundle mainBundle] objectForInfoDictionaryKey:@"CFBundleIconFile"];
    NSURL *applicationIconURL = [[NSBundle mainBundle] URLForResource:applicationIconName
                                                        withExtension:@"png"];
    NSImage *applicationIcon = applicationIconURL
        ? [[NSImage alloc] initWithContentsOfURL:applicationIconURL]
        : nil;
    if (applicationIcon) {
        applicationIcon.template = NO;
        NSApp.applicationIconImage = applicationIcon;
    }

    NSDictionary *environment = [[NSProcessInfo processInfo] environment];
    NSString *host = environment[@"PAPER_MONITOR_HOST"] ?: @"127.0.0.1";
    NSString *port = environment[@"PAPER_MONITOR_PORT"] ?: @"8765";
    self.url = [NSURL URLWithString:[NSString stringWithFormat:@"http://%@:%@", host, port]];

    // Gewu Insight owns the title-bar double-click gesture. Keep AppKit from applying
    // the user's global Fill/Zoom/Minimize choice before our window can toggle.
    [[NSUserDefaults standardUserDefaults] setObject:@"None" forKey:@"AppleActionOnDoubleClick"];

    [self createWindow];
    [self installMainMenu];
    [NSApp activateIgnoringOtherApps:YES];
    [self ensureServerThenLoad];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return NO;
}

- (BOOL)windowShouldClose:(NSWindow *)sender {
    [sender orderOut:nil];
    return NO;
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    if (!flag) {
        if (self.window.isMiniaturized) [self.window deminiaturize:nil];
        [self.window makeKeyAndOrderFront:nil];
        [NSApp activateIgnoringOtherApps:YES];
    }
    return YES;
}

- (void)closeActiveWindow:(id)sender {
    NSWindow *activeWindow = NSApp.keyWindow ?: NSApp.mainWindow;
    if (!activeWindow || !activeWindow.isVisible) {
        return;
    }
    if (
        activeWindow == self.window
        && self.nativeQuickLookActive
    ) {
        [self closeNativeQuickLookNotifyingWeb:YES];
        return;
    }
    if (
        activeWindow == self.window
        && [self.webView isKindOfClass:[GewuInsightWebView class]]
        && ((GewuInsightWebView *)self.webView).pdfQuickLookActive
    ) {
        [self.webView evaluateJavaScript:
            @"window.closeGewuInsightPreviewFromNative && window.closeGewuInsightPreviewFromNative()"
            completionHandler:nil];
        return;
    }
    [activeWindow performClose:sender];
}

- (void)applicationWillTerminate:(NSNotification *)notification {
    self.applicationIsTerminating = YES;
    [self.browserController invalidate];
    [self closeNativeQuickLookNotifyingWeb:NO];
    if (self.ownedServerTask && self.ownedServerTask.isRunning) {
        [self.ownedServerTask terminate];
    }
}

- (NSInteger)numberOfPreviewItemsInPreviewPanel:(QLPreviewPanel *)panel {
    return self.nativeQuickLookURL ? 1 : 0;
}

- (id<QLPreviewItem>)previewPanel:(QLPreviewPanel *)panel previewItemAtIndex:(NSInteger)index {
    return index == 0 ? self.nativeQuickLookURL : nil;
}

- (BOOL)showNativeQuickLookForPath:(NSString *)path {
    if (path.length == 0 || !path.isAbsolutePath) return NO;
    BOOL isDirectory = NO;
    if (![[NSFileManager defaultManager] fileExistsAtPath:path isDirectory:&isDirectory] || isDirectory) {
        return NO;
    }
    BOOL wasActive = self.nativeQuickLookActive;
    self.nativeQuickLookURL = [NSURL fileURLWithPath:path isDirectory:NO];
    self.nativeQuickLookActive = YES;
    QLPreviewPanel *panel = [QLPreviewPanel sharedPreviewPanel];
    panel.dataSource = self;
    panel.delegate = self;
    panel.hidesOnDeactivate = NO;
    panel.becomesKeyOnlyIfNeeded = YES;
    if (!wasActive || !panel.isVisible) {
        [panel reloadData];
        [panel orderFront:nil];
    } else {
        [self scheduleNativeQuickLookReload];
    }
    [self installNativeQuickLookKeyMonitor];
    [self restoreMainWindowFocusForNativeQuickLook];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self restoreMainWindowFocusForNativeQuickLook];
    });
    return YES;
}

- (void)scheduleNativeQuickLookReload {
    if (self.nativeQuickLookReloadScheduled) return;
    self.nativeQuickLookReloadScheduled = YES;
    __weak typeof(self) weakSelf = self;
    dispatch_async(dispatch_get_main_queue(), ^{
        typeof(self) strongSelf = weakSelf;
        if (!strongSelf) return;
        strongSelf.nativeQuickLookReloadScheduled = NO;
        if (!strongSelf.nativeQuickLookActive || !strongSelf.nativeQuickLookURL) return;
        QLPreviewPanel *panel = [QLPreviewPanel sharedPreviewPanel];
        [panel reloadData];
        if (!panel.isVisible) [panel orderFront:nil];
        [strongSelf restoreMainWindowFocusForNativeQuickLook];
    });
}

- (void)restoreMainWindowFocusForNativeQuickLook {
    if (!self.nativeQuickLookActive || !self.window || !self.webView) return;
    [self.window makeKeyWindow];
    [self.window makeFirstResponder:self.webView];
}

- (void)installNativeQuickLookKeyMonitor {
    if (self.nativeQuickLookKeyMonitor) return;
    __weak typeof(self) weakSelf = self;
    self.nativeQuickLookKeyMonitor = [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown
        handler:^NSEvent *(NSEvent *event) {
            typeof(self) strongSelf = weakSelf;
            if (!strongSelf || !strongSelf.nativeQuickLookActive) return event;
            NSString *key = nil;
            switch (event.keyCode) {
                case 123: key = @"ArrowLeft"; break;
                case 124: key = @"ArrowRight"; break;
                case 125: key = @"ArrowDown"; break;
                case 126: key = @"ArrowUp"; break;
                case 49: key = @" "; break;
                case 53: key = @"Escape"; break;
                default: return event;
            }
            [strongSelf dispatchNativeQuickLookKey:key];
            [strongSelf restoreMainWindowFocusForNativeQuickLook];
            return nil;
        }];
}

- (void)dispatchNativeQuickLookKey:(NSString *)key {
    if (!self.nativeQuickLookActive || key.length == 0) return;
    if (self.nativeQuickLookKeyDispatchInFlight) {
        self.nativeQuickLookPendingKey = key;
        return;
    }
    self.nativeQuickLookKeyDispatchInFlight = YES;
    NSInteger generation = self.nativeQuickLookKeyDispatchGeneration;
    NSData *keyData = [NSJSONSerialization dataWithJSONObject:key options:NSJSONWritingFragmentsAllowed error:nil];
    NSString *keyJSON = keyData
        ? [[NSString alloc] initWithData:keyData encoding:NSUTF8StringEncoding]
        : @"null";
    NSString *script = [NSString stringWithFormat:
        @"window.handleGewuInsightNativeQuickLookKey && window.handleGewuInsightNativeQuickLookKey(%@)",
        keyJSON
    ];
    __weak typeof(self) weakSelf = self;
    [self.webView evaluateJavaScript:script completionHandler:^(id result, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            typeof(self) strongSelf = weakSelf;
            if (!strongSelf || generation != strongSelf.nativeQuickLookKeyDispatchGeneration) return;
            strongSelf.nativeQuickLookKeyDispatchInFlight = NO;
            NSString *pendingKey = error ? nil : strongSelf.nativeQuickLookPendingKey;
            strongSelf.nativeQuickLookPendingKey = nil;
            if (!strongSelf.nativeQuickLookActive) return;
            [strongSelf restoreMainWindowFocusForNativeQuickLook];
            if (pendingKey.length) [strongSelf dispatchNativeQuickLookKey:pendingKey];
        });
    }];
}

- (void)removeNativeQuickLookKeyMonitor {
    if (!self.nativeQuickLookKeyMonitor) return;
    [NSEvent removeMonitor:self.nativeQuickLookKeyMonitor];
    self.nativeQuickLookKeyMonitor = nil;
}

- (void)closeNativeQuickLookNotifyingWeb:(BOOL)notifyWeb {
    if (!self.nativeQuickLookActive && !self.nativeQuickLookURL) return;
    self.nativeQuickLookClosingProgrammatically = YES;
    self.nativeQuickLookActive = NO;
    self.nativeQuickLookURL = nil;
    self.nativeQuickLookKeyDispatchGeneration += 1;
    self.nativeQuickLookKeyDispatchInFlight = NO;
    self.nativeQuickLookPendingKey = nil;
    [self removeNativeQuickLookKeyMonitor];
    QLPreviewPanel *panel = [QLPreviewPanel sharedPreviewPanel];
    [panel reloadData];
    [panel orderOut:nil];
    dispatch_async(dispatch_get_main_queue(), ^{
        self.nativeQuickLookClosingProgrammatically = NO;
    });
    if (notifyWeb) {
        [self.webView evaluateJavaScript:
            @"window.closeGewuInsightNativeQuickLookFromNative && window.closeGewuInsightNativeQuickLookFromNative()"
            completionHandler:nil];
    }
}

- (void)previewPanelWillClose:(QLPreviewPanel *)panel {
    if (self.nativeQuickLookClosingProgrammatically) {
        self.nativeQuickLookClosingProgrammatically = NO;
        return;
    }
    BOOL wasActive = self.nativeQuickLookActive || self.nativeQuickLookURL != nil;
    self.nativeQuickLookActive = NO;
    self.nativeQuickLookURL = nil;
    self.nativeQuickLookKeyDispatchGeneration += 1;
    self.nativeQuickLookKeyDispatchInFlight = NO;
    self.nativeQuickLookPendingKey = nil;
    [self removeNativeQuickLookKeyMonitor];
    if (wasActive) {
        [self.webView evaluateJavaScript:
            @"window.closeGewuInsightNativeQuickLookFromNative && window.closeGewuInsightNativeQuickLookFromNative()"
            completionHandler:nil];
    }
}

- (void)createWindow {
    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    WKUserContentController *userContentController = [[WKUserContentController alloc] init];
    [userContentController addScriptMessageHandler:self name:@"windowDrag"];
    [userContentController addScriptMessageHandler:self name:@"nativeFileDrag"];
    [userContentController addScriptMessageHandler:self name:@"libraryItemDrag"];
    [userContentController addScriptMessageHandler:self name:@"authorPhotoChooser"];
    [userContentController addScriptMessageHandler:self name:@"paperFileChooser"];
    [userContentController addScriptMessageHandler:self name:@"libraryLoaderWindow"];
    [userContentController addScriptMessageHandler:self name:@"pdfPreviewState"];
    [userContentController addScriptMessageHandler:self name:@"nativeQuickLook"];
    [userContentController addScriptMessageHandler:self name:@"publisherPdfDownload"];
    [userContentController addScriptMessageHandler:self name:@"appReady"];
    [userContentController addScriptMessageHandler:self name:@"browser"];
    configuration.userContentController = userContentController;
    self.webView = [[GewuInsightWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
    self.webView.UIDelegate = self;
    self.webView.navigationDelegate = self;

    self.window = [[GewuInsightWindow alloc]
        initWithContentRect:NSMakeRect(0, 0, 1280, 860)
                  styleMask:(NSWindowStyleMaskTitled |
                             NSWindowStyleMaskClosable |
                             NSWindowStyleMaskMiniaturizable |
                             NSWindowStyleMaskResizable |
                             NSWindowStyleMaskFullSizeContentView)
                    backing:NSBackingStoreBuffered
                      defer:NO];
    self.window.title = @"";
    self.window.delegate = self;
    self.window.titleVisibility = NSWindowTitleHidden;
    self.window.titlebarAppearsTransparent = YES;
    self.window.minSize = NSMakeSize(980, 680);
    NSScreen *screen = [NSScreen mainScreen];
    if (screen) {
        self.windowRestoreFrame = [self defaultRestoreFrameForScreen:screen];
        [self.window setFrame:screen.visibleFrame display:YES];
    } else {
        [self.window center];
        self.windowRestoreFrame = self.window.frame;
    }
    NSView *contentView = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 1280, 860)];
    contentView.wantsLayer = YES;
    contentView.layer.backgroundColor = [NSColor colorWithRed:244.0/255.0
                                                       green:242.0/255.0
                                                        blue:237.0/255.0
                                                       alpha:1.0].CGColor;
    self.webView.frame = contentView.bounds;
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    if (@available(macOS 12.0, *)) {
        self.webView.underPageBackgroundColor = [NSColor colorWithRed:244.0/255.0
                                                                green:242.0/255.0
                                                                 blue:237.0/255.0
                                                                alpha:1.0];
    }
    [contentView addSubview:self.webView];
    GewuFinderDropView *finderDropView = [[GewuFinderDropView alloc] initWithFrame:contentView.bounds];
    finderDropView.destinationWebView = (GewuInsightWebView *)self.webView;
    finderDropView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    [contentView addSubview:finderDropView];
    self.window.contentView = contentView;
    self.window.backgroundColor = [NSColor colorWithRed:244.0/255.0 green:242.0/255.0 blue:237.0/255.0 alpha:1.0];
    [self showLoadingPage];
    if (self.window.isMiniaturized) [self.window deminiaturize:nil];
    [self.window makeKeyAndOrderFront:nil];
    [self positionTrafficLightButtons];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self positionTrafficLightButtons];
    });
}

- (void)userContentController:(WKUserContentController *)userContentController
      didReceiveScriptMessage:(WKScriptMessage *)message {
    if ([message.name isEqualToString:@"browser"]) {
        NSURL *frameURL = message.frameInfo.request.URL;
        if (message.webView != self.webView || !message.frameInfo.isMainFrame
            || ![frameURL.scheme isEqualToString:@"http"]
            || ![frameURL.host isEqualToString:self.url.host]
            || ![frameURL.port isEqual:self.url.port]
            || ![message.body isKindOfClass:NSDictionary.class]) return;
        if (!self.browserController) {
            self.browserController = [[GewuBrowserController alloc] initWithWorkspace:self.webView];
            __weak typeof(self) weakSelf = self;
            self.browserController.onEvent = ^(NSDictionary *event) {
                NSData *data = [NSJSONSerialization dataWithJSONObject:event options:0 error:nil];
                if (!data) return;
                NSString *json = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
                NSString *script = [NSString stringWithFormat:@"window.gewuBrowserNativeEvent && window.gewuBrowserNativeEvent(%@)", json];
                [weakSelf.webView evaluateJavaScript:script completionHandler:nil];
            };
        }
        [self.browserController handleCommand:message.body];
        return;
    }
    if ([message.name isEqualToString:@"openUserGuidePDF"]) {
        [self openUserGuidePDF];
        return;
    }
    if ([message.name isEqualToString:@"appReady"]) {
        [self dismissStartupOverlay];
        return;
    }
    if ([message.name isEqualToString:@"libraryItemDrag"]) {
        if (![message.body isKindOfClass:[NSDictionary class]] || ![self.webView isKindOfClass:[GewuInsightWebView class]]) {
            return;
        }
        id value = ((NSDictionary *)message.body)[@"item_id"];
        NSInteger itemId = [value respondsToSelector:@selector(integerValue)] ? [value integerValue] : 0;
        GewuInsightWebView *webView = (GewuInsightWebView *)self.webView;
        webView.pendingLibraryItemDragId = itemId > 0 ? itemId : 0;
        webView.pendingLibraryDragPayload = itemId > 0 ? @{ @"type": @"item", @"id": @(itemId), @"token": NSUUID.UUID.UUIDString } : nil;
        return;
    }
    if ([message.name isEqualToString:@"publisherPdfDownload"]) {
        if (![message.body isKindOfClass:[NSDictionary class]]) return;
        [self startHiddenPublisherDownload:(NSDictionary *)message.body];
        return;
    }
    if ([message.name isEqualToString:@"pdfPreviewState"]) {
        if (![self.webView isKindOfClass:[GewuInsightWebView class]]) return;
        BOOL active = NO;
        if ([message.body isKindOfClass:[NSDictionary class]]) {
            id value = ((NSDictionary *)message.body)[@"active"];
            if ([value respondsToSelector:@selector(boolValue)]) active = [value boolValue];
        }
        ((GewuInsightWebView *)self.webView).pdfQuickLookActive = active;
        return;
    }
    if ([message.name isEqualToString:@"nativeQuickLook"]) {
        if (![message.body isKindOfClass:[NSDictionary class]]) return;
        NSDictionary *payload = (NSDictionary *)message.body;
        NSString *action = [payload[@"action"] isKindOfClass:[NSString class]] ? payload[@"action"] : @"";
        NSString *path = [payload[@"path"] isKindOfClass:[NSString class]] ? payload[@"path"] : @"";
        if ([action isEqualToString:@"close"]) {
            [self closeNativeQuickLookNotifyingWeb:NO];
            return;
        }
        if ([action isEqualToString:@"open"] || [action isEqualToString:@"update"]) {
            if (![self showNativeQuickLookForPath:path]) {
                [self.webView evaluateJavaScript:
                    @"window.handleGewuInsightNativeQuickLookFailure && window.handleGewuInsightNativeQuickLookFailure()"
                    completionHandler:nil];
            }
        }
        return;
    }
    if ([message.name isEqualToString:@"libraryLoaderWindow"]) {
        NSString *type = @"close";
        if ([message.body isKindOfClass:[NSDictionary class]]) {
            NSDictionary *payload = (NSDictionary *)message.body;
            type = [payload[@"type"] isKindOfClass:[NSString class]] ? payload[@"type"] : type;
            if ([type isEqualToString:@"show-paper"] && message.webView == self.loaderWebView) {
                [self showLoaderPaperInLibrary:payload];
                return;
            }
        }
        if ([type isEqualToString:@"open"]) {
            [self showLibraryLoaderWindow];
        } else {
            [self.loaderWindow orderOut:nil];
        }
        return;
    }
    if ([message.name isEqualToString:@"nativeFileDrag"]) {
        if (![message.body isKindOfClass:[NSDictionary class]] || ![self.webView isKindOfClass:[GewuInsightWebView class]]) {
            return;
        }
        NSDictionary *payload = (NSDictionary *)message.body;
        NSString *path = [payload[@"path"] isKindOfClass:[NSString class]] ? payload[@"path"] : @"";
        NSString *name = [payload[@"name"] isKindOfClass:[NSString class]] ? payload[@"name"] : @"";
        NSString *cleanupPath = [payload[@"cleanup_path"] isKindOfClass:[NSString class]] ? payload[@"cleanup_path"] : @"";
        GewuInsightWebView *webView = (GewuInsightWebView *)self.webView;
        webView.nativeDragPath = path;
        webView.nativeDragName = name;
        webView.nativeDragCleanupPath = cleanupPath;
        webView.pendingLibraryDragPayload = [payload[@"library_payload"] isKindOfClass:NSDictionary.class] ? payload[@"library_payload"] : nil;
        return;
    }
    if ([message.name isEqualToString:@"authorPhotoChooser"]) {
        if (![message.body isKindOfClass:[NSDictionary class]]) return;
        id value = ((NSDictionary *)message.body)[@"author_id"];
        NSNumber *authorId = [value isKindOfClass:[NSNumber class]] ? value : nil;
        if (!authorId || authorId.integerValue <= 0) return;
        [self showAuthorPhotoChooserForAuthorId:authorId];
        return;
    }
    if ([message.name isEqualToString:@"paperFileChooser"]) {
        if (![message.body isKindOfClass:[NSDictionary class]]) return;
        [self showPaperFileChooserWithPayload:(NSDictionary *)message.body];
        return;
    }
    if (![message.name isEqualToString:@"windowDrag"] || ![message.body isKindOfClass:[NSDictionary class]]) {
        return;
    }
    if (message.webView != self.webView || !message.frameInfo.isMainFrame) return;
    NSDictionary *payload = (NSDictionary *)message.body;
    NSString *type = [payload[@"type"] isKindOfClass:[NSString class]] ? payload[@"type"] : @"";
    if ([type isEqualToString:@"toggleFill"]) {
        [self toggleMainWindowFill];
        return;
    }
    if ([type isEqualToString:@"begin"] && [self.window isKindOfClass:GewuInsightWindow.class]) {
        NSNumber *x = [payload[@"clientX"] isKindOfClass:NSNumber.class] ? payload[@"clientX"] : nil;
        NSNumber *y = [payload[@"clientY"] isKindOfClass:NSNumber.class] ? payload[@"clientY"] : nil;
        if (!x || !y) return;
        [(GewuInsightWindow *)self.window beginNativeWindowDragAtClientPoint:NSMakePoint(x.doubleValue, y.doubleValue)
            inView:self.webView];
    }
}

- (void)showAuthorPhotoChooserForAuthorId:(NSNumber *)authorId {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.title = @"Choose Author Photo";
    panel.message = @"Choose a PNG, JPEG, or WebP image.";
    panel.prompt = @"Choose Photo";
    panel.canChooseFiles = YES;
    panel.canChooseDirectories = NO;
    panel.allowsMultipleSelection = NO;
    panel.resolvesAliases = YES;
    panel.allowedFileTypes = @[@"png", @"jpg", @"jpeg", @"webp"];
    __weak typeof(self) weakSelf = self;
    [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse result) {
        PaperMonitorDelegate *strongSelf = weakSelf;
        if (!strongSelf) return;
        NSMutableDictionary *payload = [@{
            @"author_id": authorId,
            @"cancelled": @(result != NSModalResponseOK)
        } mutableCopy];
        if (result == NSModalResponseOK && panel.URL.path.length > 0) {
            payload[@"path"] = panel.URL.path;
        }
        NSData *jsonData = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
        NSString *json = jsonData
            ? [[NSString alloc] initWithData:jsonData encoding:NSUTF8StringEncoding]
            : @"{}";
        NSString *script = [NSString stringWithFormat:
            @"window.handleNativeAuthorPhotoSelection && "
             "window.handleNativeAuthorPhotoSelection(%@);",
            json
        ];
        [strongSelf.webView evaluateJavaScript:script completionHandler:nil];
    }];
}

- (void)showPaperFileChooserWithPayload:(NSDictionary *)payload {
    NSString *paperId = [payload[@"paper_id"] isKindOfClass:[NSString class]] ? payload[@"paper_id"] : @"";
    if (paperId.length == 0) return;
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.title = @"Add Files to Paper";
    panel.message = @"Choose one or more files to associate with this paper.";
    panel.prompt = @"Add Files";
    panel.canChooseFiles = YES;
    panel.canChooseDirectories = NO;
    panel.allowsMultipleSelection = YES;
    panel.resolvesAliases = YES;
    __weak typeof(self) weakSelf = self;
    [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse result) {
        PaperMonitorDelegate *strongSelf = weakSelf;
        if (!strongSelf) return;
        NSMutableArray<NSString *> *paths = [NSMutableArray array];
        if (result == NSModalResponseOK) {
            for (NSURL *url in panel.URLs) {
                if (url.path.length > 0) [paths addObject:url.path];
            }
        }
        NSMutableDictionary *response = [NSMutableDictionary dictionaryWithDictionary:payload];
        response[@"paths"] = paths;
        response[@"cancelled"] = @(result != NSModalResponseOK);
        NSData *jsonData = [NSJSONSerialization dataWithJSONObject:response options:0 error:nil];
        NSString *json = jsonData
            ? [[NSString alloc] initWithData:jsonData encoding:NSUTF8StringEncoding]
            : @"{}";
        NSString *script = [NSString stringWithFormat:
            @"window.handleNativePaperFileSelection && window.handleNativePaperFileSelection(%@);",
            json
        ];
        [strongSelf.webView evaluateJavaScript:script completionHandler:nil];
    }];
}

- (void)webView:(WKWebView *)webView
    runJavaScriptConfirmPanelWithMessage:(NSString *)message
                        initiatedByFrame:(WKFrameInfo *)frame
                       completionHandler:(void (^)(BOOL result))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.alertStyle = NSAlertStyleWarning;
    alert.messageText = @"Delete File";
    NSWindow *parentWindow = webView.window ?: self.window;
    GewuConfigureConfirmationDetails(alert, message, parentWindow);
    [alert addButtonWithTitle:@"Delete"];
    [alert addButtonWithTitle:@"Cancel"];
    if (parentWindow) {
        [alert beginSheetModalForWindow:parentWindow completionHandler:^(NSModalResponse response) {
            completionHandler(response == NSAlertFirstButtonReturn);
        }];
        return;
    }
    completionHandler([alert runModal] == NSAlertFirstButtonReturn);
}

- (NSString *)publisherNameForContext:(NSDictionary *)context {
    NSString *publisher = [context[@"publisher_download_name"] isKindOfClass:[NSString class]]
        ? [context[@"publisher_download_name"] lowercaseString]
        : @"";
    NSString *kind = [context[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? context[@"publisher_download_kind"]
        : @"";
    if (publisher.length == 0 && [kind hasPrefix:@"aaas-"]) return @"aaas";
    return publisher;
}

- (BOOL)isAllowedPublisherURL:(NSURL *)url publisher:(NSString *)publisher {
    if (!url || ![url.scheme.lowercaseString isEqualToString:@"https"]) return NO;
    NSString *host = url.host.lowercaseString ?: @"";
    if ([publisher isEqualToString:@"aaas"]) {
        return [host isEqualToString:@"science.org"]
            || [host hasSuffix:@".science.org"]
            || [host isEqualToString:@"sciencemag.org"]
            || [host hasSuffix:@".sciencemag.org"];
    }
    if ([publisher isEqualToString:@"nature"]) {
        return [host isEqualToString:@"nature.com"] || [host hasSuffix:@".nature.com"]
            || [host isEqualToString:@"media.springernature.com"]
            || [host isEqualToString:@"static-content.springer-cdn.com"];
    }
    if ([publisher isEqualToString:@"acs"]) {
        return [host isEqualToString:@"pubs.acs.org"]
            || [host isEqualToString:@"acs.figshare.com"];
    }
    if ([publisher isEqualToString:@"aps"]) {
        return [host hasSuffix:@".aps.org"]
            || [host isEqualToString:@"aps.org"];
    }
    if ([publisher isEqualToString:@"wiley"]) {
        return [host isEqualToString:@"onlinelibrary.wiley.com"]
            || [host hasSuffix:@".onlinelibrary.wiley.com"];
    }
    if ([publisher isEqualToString:@"cpl"]) {
        return [host isEqualToString:@"cpl.iphy.ac.cn"]
            || [host isEqualToString:@"iopscience.iop.org"];
    }
    if ([publisher isEqualToString:@"cpb"]) {
        return [host isEqualToString:@"cpb.iphy.ac.cn"]
            || [host isEqualToString:@"iopscience.iop.org"];
    }
    if ([publisher isEqualToString:@"elsevier"]) {
        return [host isEqualToString:@"www.sciencedirect.com"]
            || [host isEqualToString:@"sciencedirect.com"]
            || [host isEqualToString:@"linkinghub.elsevier.com"]
            || [host isEqualToString:@"reader.elsevier.com"]
            || [host isEqualToString:@"ars.els-cdn.com"]
            || [host hasSuffix:@".sciencedirectassets.com"];
    }
    if ([publisher isEqualToString:@"oup"]) {
        return [host isEqualToString:@"academic.oup.com"]
            || [host isEqualToString:@"preview.academic.oup.com"]
            || [host isEqualToString:@"watermark.silverchair.com"]
            || [host hasSuffix:@".silverchair-cdn.com"];
    }
    return NO;
}

- (void)startHiddenPublisherDownload:(NSDictionary *)payload {
    NSString *token = [payload[@"token"] isKindOfClass:[NSString class]] ? payload[@"token"] : @"";
    NSString *urlString = [payload[@"url"] isKindOfClass:[NSString class]] ? payload[@"url"] : @"";
    NSDictionary *context = [payload[@"context"] isKindOfClass:[NSDictionary class]] ? payload[@"context"] : @{};
    NSURL *publisherURL = [NSURL URLWithString:urlString];
    NSString *publisher = [self publisherNameForContext:context];
    NSString *path = publisherURL.path.lowercaseString ?: @"";
    BOOL sciencePath = [path hasPrefix:@"/doi/pdf/"]
        || [path hasPrefix:@"/doi/epdf/"]
        || [path hasPrefix:@"/doi/suppl/"]
        || [path hasPrefix:@"/doi/"]
        || [path hasSuffix:@".pdf"];
    BOOL allowedPath = [publisher isEqualToString:@"aaas"] ? sciencePath : path.length > 0;
    if (token.length == 0 || !publisherURL || ![self isAllowedPublisherURL:publisherURL publisher:publisher] || !allowedPath) {
        [self notifyHiddenPublisherDownloadToken:token success:NO data:nil error:@"Invalid published PDF download request."];
        return;
    }
    if (self.hiddenPublisherWebView || self.hiddenPublisherDownload) {
        [self notifyHiddenPublisherDownloadToken:token success:NO data:nil error:@"Another published PDF is already downloading."];
        return;
    }

    self.hiddenPublisherToken = token;
    self.hiddenPublisherContext = [context copy];
    self.hiddenPublisherDiscoveryVisitedURLs = [NSMutableSet set];
    self.hiddenPublisherDiscoveryDepth = 0;
    self.hiddenPublisherDiscoveryPageRetryCount = 0;
    // These article-first downloads must see sign-in completed in Gewu Browser.
    // Use only its external configuration, never the trusted workspace's.
    WKWebViewConfiguration *configuration = [GewuBrowserController externalPageConfiguration];
    // Publisher pages often hide their desktop PDF controls in a 1x1 responsive
    // viewport. The web view remains off-screen, but uses a normal desktop layout.
    self.hiddenPublisherWebView = [[WKWebView alloc] initWithFrame:NSMakeRect(0, 0, 1280, 900) configuration:configuration];
    self.hiddenPublisherWebView.navigationDelegate = self;

    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:publisherURL];
    // Let WebKit negotiate HTML/PDF exactly as the visible Browser does.
    NSString *referer = [context[@"publisher_download_referer"] isKindOfClass:[NSString class]]
        ? context[@"publisher_download_referer"]
        : @"";
    NSURL *refererURL = [NSURL URLWithString:referer];
    if (referer.length == 0 && [publisher isEqualToString:@"aaas"]) {
        NSString *refererPath = [publisherURL.path stringByReplacingOccurrencesOfString:@"/doi/pdf/" withString:@"/doi/"];
        refererPath = [refererPath stringByReplacingOccurrencesOfString:@"/doi/epdf/" withString:@"/doi/"];
        if ([publisherURL.path hasPrefix:@"/doi/suppl/"]) {
            NSString *supplementPath = [publisherURL.path substringFromIndex:@"/doi/suppl/".length];
            NSRange fileRange = [supplementPath rangeOfString:@"/suppl_file/"];
            if (fileRange.location != NSNotFound) {
                supplementPath = [supplementPath substringToIndex:fileRange.location];
            }
            refererPath = [@"/doi/" stringByAppendingString:supplementPath];
        }
        referer = [NSString stringWithFormat:@"https://www.science.org%@", refererPath ?: @""];
        refererURL = [NSURL URLWithString:referer];
    }
    if (refererURL && [self isAllowedPublisherURL:refererURL publisher:publisher]) {
        [request setValue:referer forHTTPHeaderField:@"Referer"];
    }

    self.hiddenPublisherTimeout = [NSTimer scheduledTimerWithTimeInterval:80.0
                                                                   target:self
                                                                 selector:@selector(hiddenPublisherDownloadTimedOut:)
                                                                 userInfo:nil
                                                                  repeats:NO];
    [self.hiddenPublisherWebView loadRequest:request];
}

- (BOOL)isAllowedScienceSupplementURL:(NSURL *)url {
    NSString *host = url.host.lowercaseString ?: @"";
    NSString *path = url.path.lowercaseString ?: @"";
    BOOL allowedHost = [host isEqualToString:@"science.org"]
        || [host hasSuffix:@".science.org"]
        || [host isEqualToString:@"sciencemag.org"]
        || [host hasSuffix:@".sciencemag.org"];
    BOOL allowedPath = [path hasPrefix:@"/doi/"]
        || [path hasPrefix:@"/content/suppl/"]
        || [path hasPrefix:@"/cgi/content/full/"]
        || [path hasSuffix:@".pdf"]
        || [path hasSuffix:@".doc"]
        || [path hasSuffix:@".docx"];
    return [url.scheme.lowercaseString isEqualToString:@"https"] && allowedHost && allowedPath;
}

- (BOOL)isHiddenPublisherSupplementDiscovery {
    NSString *kind = [self.hiddenPublisherContext[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? self.hiddenPublisherContext[@"publisher_download_kind"]
        : @"";
    return [kind isEqualToString:@"aaas-supplement-discovery"];
}

- (BOOL)isHiddenGenericSupplementDiscovery {
    NSString *kind = [self.hiddenPublisherContext[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? self.hiddenPublisherContext[@"publisher_download_kind"]
        : @"";
    return [kind isEqualToString:@"publisher-supplement-discovery"];
}

- (BOOL)isHiddenPublisherMainDownload {
    NSString *kind = [self.hiddenPublisherContext[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? self.hiddenPublisherContext[@"publisher_download_kind"]
        : @"";
    return [kind isEqualToString:@"publisher-main-pdf"]
        || [kind isEqualToString:@"aaas-published-pdf"];
}

- (BOOL)isScienceSupplementReference:(NSString *)value {
    NSString *decoded = value.stringByRemovingPercentEncoding ?: value ?: @"";
    return [decoded rangeOfString:@"/suppl(?:/|_)|/supplement|[_\\-.]sm\\.(?:pdf|docx?)(?:$|[?#\\s])|supplementary|supporting[ _-]+(?:information|materials)|mdar|reproducibility[ _-]+checklist|reporting[ _-]+(?:summary|checklist)"
                         options:NSRegularExpressionSearch | NSCaseInsensitiveSearch].location != NSNotFound;
}

- (BOOL)isNatureSecondaryReference:(NSString *)value {
    NSString *decoded = value.stringByRemovingPercentEncoding ?: value ?: @"";
    return [decoded rangeOfString:@"/esm/|moesm[0-9]+|_esm\\.|supplement|supporting[ _-]+information|peer[ _-]*review|reporting[ _-]+summary|source[ _-]+data|appendix"
                         options:NSRegularExpressionSearch | NSCaseInsensitiveSearch].location != NSNotFound;
}

- (BOOL)isNatureMainURL:(NSURL *)url {
    NSString *host = url.host.lowercaseString ?: @"";
    if (!([host isEqualToString:@"nature.com"] || [host hasSuffix:@".nature.com"])) return NO;
    if ([self isNatureSecondaryReference:url.absoluteString]) return NO;
    NSURL *target = [NSURL URLWithString:self.hiddenPublisherContext[@"publisher_download_target_url"] ?: @""];
    NSString *path = url.path.lowercaseString ?: @"";
    NSString *wanted = target.path.lowercaseString ?: @"";
    return wanted.length > 0 && ([path isEqualToString:wanted]
        || [path isEqualToString:[[wanted stringByDeletingPathExtension] stringByAppendingString:@"_reference.pdf"]]);
}

- (void)completeHiddenPublisherSupplementDiscoveryWithURLs:(NSArray<NSString *> *)urls {
    NSString *token = self.hiddenPublisherToken ?: @"";
    [self notifyHiddenPublisherDownloadToken:token
                                     success:YES
                                        data:@{@"supplement_urls": urls ?: @[]}
                                       error:nil];
    [self clearHiddenPublisherDownload];
}

- (void)inspectHiddenPublisherSupplementPage {
    if (![self isHiddenPublisherSupplementDiscovery] || !self.hiddenPublisherWebView) return;
    NSString *script =
        @"(() => {"
         "const acceptedHost = h => h === 'science.org' || h.endsWith('.science.org') || h === 'sciencemag.org' || h.endsWith('.sciencemag.org');"
         "const pagePath = location.pathname.toLowerCase();"
         "const pageIsSupplement = pagePath.includes('/doi/suppl/') || pagePath.includes('/content/suppl/') || /\\/dc\\d+(?:$|[/?#])/.test(pagePath);"
         "const pdfs = [], landings = [];"
         "for (const a of document.querySelectorAll('a[href], iframe[src], embed[src]')) {"
           "const raw = a.getAttribute('href') || a.getAttribute('src') || '';"
           "let u; try { u = new URL(raw, location.href); } catch (_) { continue; }"
           "if (u.origin === location.origin && u.pathname === location.pathname && u.search === location.search) continue;"
           "if (u.protocol === 'http:') u.protocol = 'https:';"
           "if (!acceptedHost(u.hostname.toLowerCase())) continue;"
           "const path = u.pathname.toLowerCase();"
           "const label = `${a.textContent || ''} ${a.getAttribute('title') || ''} ${a.getAttribute('type') || ''}`.toLowerCase();"
           "const supplementMarker = pageIsSupplement || path.includes('/suppl') || path.includes('/supplement') || /(?:^|[/.])dc\\d+(?:$|[/?#])/.test(path) || label.includes('supplement') || label.includes('supporting information');"
           "const extension = path.match(/\\.([a-z0-9]{2,5})$/)?.[1] || '';"
           "if ((extension && !['pdf', 'html', 'htm'].includes(extension)) || /^(video|audio)\\//.test(a.getAttribute('type') || '')) continue;"
           "const explicitPdf = /\\.pdf$/i.test(path) || /pdf/.test(String(a.getAttribute('type') || '').toLowerCase()) || /\\bpdf\\b/.test(label);"
           "const likelyMainPdf = path.includes('/doi/pdf/') || label.includes('full text pdf') || label.includes('article pdf');"
           "if (supplementMarker && explicitPdf && !likelyMainPdf) pdfs.push(u.href);"
           "else if (path.includes('/doi/suppl/') || path.includes('/content/suppl/') || path.includes('/cgi/content/full/') && /\\/dc\\d+/.test(path)) landings.push(u.href);"
         "}"
         "return {pdfs: [...new Set(pdfs)], landings: [...new Set(landings)], page: location.href};"
        "})()";
    __weak PaperMonitorDelegate *weakSelf = self;
    WKWebView *inspectedView = self.hiddenPublisherWebView;
    [inspectedView evaluateJavaScript:script completionHandler:^(id result, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            PaperMonitorDelegate *strongSelf = weakSelf;
            if (!strongSelf || strongSelf.hiddenPublisherWebView != inspectedView || ![strongSelf isHiddenPublisherSupplementDiscovery]) return;
            NSDictionary *payload = [result isKindOfClass:[NSDictionary class]] ? result : @{};
            NSArray *rawPDFs = [payload[@"pdfs"] isKindOfClass:[NSArray class]] ? payload[@"pdfs"] : @[];
            NSMutableArray<NSString *> *pdfs = [NSMutableArray array];
            for (id value in rawPDFs) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                if ([strongSelf isAllowedScienceSupplementURL:url]) [pdfs addObject:url.absoluteString];
            }
            if (pdfs.count > 0) {
                [strongSelf completeHiddenPublisherSupplementDiscoveryWithURLs:pdfs];
                return;
            }
            NSArray *landings = [payload[@"landings"] isKindOfClass:[NSArray class]] ? payload[@"landings"] : @[];
            for (id value in landings) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                NSString *absolute = url.absoluteString ?: @"";
                if (![strongSelf isAllowedScienceSupplementURL:url] || [strongSelf.hiddenPublisherDiscoveryVisitedURLs containsObject:absolute]) continue;
                if (strongSelf.hiddenPublisherDiscoveryDepth >= 4) break;
                [strongSelf.hiddenPublisherDiscoveryVisitedURLs addObject:absolute];
                strongSelf.hiddenPublisherDiscoveryDepth += 1;
                strongSelf.hiddenPublisherDiscoveryPageRetryCount = 0;
                [strongSelf.hiddenPublisherWebView loadRequest:[NSURLRequest requestWithURL:url]];
                return;
            }
            if (!error && strongSelf.hiddenPublisherDiscoveryPageRetryCount < 2) {
                strongSelf.hiddenPublisherDiscoveryPageRetryCount += 1;
                dispatch_after(
                    dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.0 * NSEC_PER_SEC)),
                    dispatch_get_main_queue(),
                    ^{
                        if (strongSelf.hiddenPublisherWebView == inspectedView) [strongSelf inspectHiddenPublisherSupplementPage];
                    }
                );
                return;
            }
            if (error) [strongSelf failHiddenPublisherDownload:error.localizedDescription];
            else [strongSelf completeHiddenPublisherSupplementDiscoveryWithURLs:@[]];
        });
    }];
}

- (void)inspectHiddenGenericSupplementPage {
    if (![self isHiddenGenericSupplementDiscovery] || !self.hiddenPublisherWebView) return;
    NSString *script =
        @"(() => {"
         "const files = [], landings = [];"
         "const nature = /(?:^|\\.)nature\\.com$/.test(location.hostname);"
         "const blocked = /just a moment|access denied|attention required|robot check/i.test(document.title) || !!document.querySelector('#challenge-running, #challenge-stage, form[action*=\"__cf_chl\"]');"
         "if (blocked) return {files: [], landings: [], blocked: true};"
         "for (const el of document.querySelectorAll('a[href], iframe[src], embed[src]')) {"
           "const raw = el.getAttribute('href') || el.getAttribute('src') || '';"
           "let u; try { u = new URL(raw, location.href); } catch (_) { continue; }"
           "if (u.origin === location.origin && u.pathname === location.pathname && u.search === location.search) continue;"
           "if (u.protocol === 'http:') u.protocol = 'https:';"
           "const path = u.pathname.toLowerCase();"
           "const label = `${el.textContent || ''} ${el.getAttribute('title') || ''} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('type') || ''}`.toLowerCase();"
           "const marker = `${path} ${u.search.toLowerCase()} ${label}`;"
           "if (nature && /peer[ _-]*review|reporting[ _-]+summary|source[ _-]+data/.test(marker)) continue;"
           "const supplementary = /supplement|supporting information|suppl_file|supinfo|suppinfo|suppdata|additional file|appendix|attachment|mmc\\d|figshare/.test(marker) || (nature && /\\/esm\\/|moesm\\d|_esm\\./.test(path));"
           "const extension = path.match(/\\.([a-z0-9]{2,5})$/)?.[1] || '';"
           "if ((extension && !['pdf', 'html', 'htm'].includes(extension)) || /^(video|audio)\\//.test(el.getAttribute('type') || '')) continue;"
           "const supported = /\\.pdf(?:$|[?#])/.test(`${path}${u.search}`) || /\\bpdf\\b/.test(label);"
           "const mainPdf = /article-pdf|\\/doi\\/(pdf|epdf)\\//.test(path) && !supplementary;"
           "if (supplementary && supported && !mainPdf) files.push(u.href);"
           "else if (supplementary && !supported) landings.push(u.href);"
         "}"
         "return {files: [...new Set(files)], landings: [...new Set(landings)], page: location.href};"
        "})()";
    __weak PaperMonitorDelegate *weakSelf = self;
    WKWebView *inspectedView = self.hiddenPublisherWebView;
    [inspectedView evaluateJavaScript:script completionHandler:^(id result, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            PaperMonitorDelegate *strongSelf = weakSelf;
            if (!strongSelf || strongSelf.hiddenPublisherWebView != inspectedView || ![strongSelf isHiddenGenericSupplementDiscovery]) return;
            NSDictionary *payload = [result isKindOfClass:[NSDictionary class]] ? result : @{};
            NSString *publisher = [strongSelf publisherNameForContext:strongSelf.hiddenPublisherContext ?: @{}];
            if ([payload[@"blocked"] boolValue]
                && strongSelf.hiddenPublisherDiscoveryPageRetryCount >= 3) {
                [strongSelf failHiddenPublisherDownload:@"Supplementary files require browser verification or article access. Open Website in Gewu Browser, complete verification or sign in, then retry Download."];
                return;
            }
            NSArray *rawFiles = [payload[@"files"] isKindOfClass:[NSArray class]] ? payload[@"files"] : @[];
            NSMutableArray<NSString *> *files = [NSMutableArray array];
            for (id value in rawFiles) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                if ([strongSelf isAllowedPublisherURL:url publisher:publisher]) {
                    [files addObject:url.absoluteString];
                }
            }
            if (files.count > 0) {
                [strongSelf completeHiddenPublisherSupplementDiscoveryWithURLs:files];
                return;
            }
            NSArray *landings = [payload[@"landings"] isKindOfClass:[NSArray class]] ? payload[@"landings"] : @[];
            for (id value in landings) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                NSString *absolute = url.absoluteString ?: @"";
                if (![strongSelf isAllowedPublisherURL:url publisher:publisher]
                    || [strongSelf.hiddenPublisherDiscoveryVisitedURLs containsObject:absolute]) {
                    continue;
                }
                if (strongSelf.hiddenPublisherDiscoveryDepth >= 5) break;
                [strongSelf.hiddenPublisherDiscoveryVisitedURLs addObject:absolute];
                strongSelf.hiddenPublisherDiscoveryDepth += 1;
                strongSelf.hiddenPublisherDiscoveryPageRetryCount = 0;
                [strongSelf.hiddenPublisherWebView loadRequest:[NSURLRequest requestWithURL:url]];
                return;
            }
            if (!error && strongSelf.hiddenPublisherDiscoveryPageRetryCount < 5) {
                strongSelf.hiddenPublisherDiscoveryPageRetryCount += 1;
                dispatch_after(
                    dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.0 * NSEC_PER_SEC)),
                    dispatch_get_main_queue(),
                    ^{
                        if (strongSelf.hiddenPublisherWebView == inspectedView) [strongSelf inspectHiddenGenericSupplementPage];
                    }
                );
                return;
            }
            if (error) {
                [strongSelf failHiddenPublisherDownload:error.localizedDescription ?: @"Supplement discovery failed."];
            } else {
                [strongSelf completeHiddenPublisherSupplementDiscoveryWithURLs:@[]];
            }
        });
    }];
}

- (void)inspectHiddenPublisherMainPage {
    if (![self isHiddenPublisherMainDownload] || !self.hiddenPublisherWebView) return;
    NSString *publisher = [self publisherNameForContext:self.hiddenPublisherContext ?: @{}];
    NSString *script =
        @"(() => {"
         "const urls = [];"
         "const science = /(?:^|\\.)(?:science|sciencemag)\\.org$/.test(location.hostname);"
         "const nature = /(?:^|\\.)nature\\.com$/.test(location.hostname);"
         "const decode = value => { try { return decodeURIComponent(value); } catch (_) { return value; } };"
         "const aps = /(?:^|\\.)aps\\.org$/.test(location.hostname);"
         "const accessRequired = aps && [...document.querySelectorAll('h1')].some(el => /^authorization required$/i.test((el.textContent || '').trim()));"
         "if (accessRequired) return {urls: [], clicked: false, accessRequired: true};"
         "const secondary = value => /supplement|supporting information|appendix/.test(value) || (nature && /\\/esm\\/|moesm\\d|_esm\\.|peer[ _-]*review|reporting[ _-]+summary|source[ _-]+data/.test(value)) || (science && /\\/suppl(?:\\/|_)|[_\\-.]sm\\.(?:pdf|docx?)(?:$|[?#\\s])|mdar|reproducibility[ _-]+checklist|reporting[ _-]+(?:summary|checklist)/.test(value));"
         "const blocked = (/just a moment|access denied|attention required|robot check/i.test(document.title) || !!document.querySelector('#challenge-running, #challenge-stage, form[action*=\"__cf_chl\"]'));"
         "if (blocked) return {urls: [], clicked: false, blocked: true};"
         "for (const meta of document.querySelectorAll('meta[name=\"citation_pdf_url\"], meta[property=\"citation_pdf_url\"]')) {"
           "const raw = meta.getAttribute('content') || '';"
           "try { if (raw && (!(science || nature) || !secondary(decode(raw).toLowerCase()))) urls.push(new URL(raw, location.href).href); } catch (_) {}"
         "}"
         "for (const el of document.querySelectorAll('a[href], iframe[src], embed[src]')) {"
           "const raw = el.getAttribute('href') || el.getAttribute('src') || '';"
           "let u; try { u = new URL(raw, location.href); } catch (_) { continue; }"
           "const path = u.pathname.toLowerCase();"
           "const label = `${el.textContent || ''} ${el.getAttribute('title') || ''} ${el.getAttribute('aria-label') || ''}`.toLowerCase();"
           "const supplementary = secondary(`${decode(path)} ${label}`);"
           "const pdfRoute = /\\.pdf$/i.test(path) || path.includes('/doi/pdf') || path.includes('/doi/epdf') || path.includes('/article-pdf/') || path.includes('/pdfft') || path.includes('downloadarticlefile.do');"
           "const pdfLabel = /(^|\\s)(download\\s+|view\\s+|open\\s+)?pdf(\\s|$)/.test(label);"
           "if (!supplementary && (pdfRoute || pdfLabel)) urls.push(u.href);"
         "}"
         "let clicked = false;"
         "if (!urls.length && !nature) {"
           "for (const el of document.querySelectorAll('button, [role=\"button\"], a')) {"
             "const label = `${el.textContent || ''} ${el.getAttribute('title') || ''} ${el.getAttribute('aria-label') || ''}`.trim().toLowerCase();"
             "const marker = science ? `${label} ${el.getAttribute('href') || ''}`.toLowerCase() : label;"
             "if (!(science ? secondary(marker) : /supplement|supporting information/.test(label)) && /(^|\\s)(download\\s+|view\\s+|open\\s+)?pdf(\\s|$)/.test(label)) {"
               "try { el.click(); clicked = true; } catch (_) {}"
               "break;"
             "}"
           "}"
         "}"
         "return {urls: [...new Set(urls)], clicked, page: location.href};"
        "})()";
    __weak PaperMonitorDelegate *weakSelf = self;
    WKWebView *inspectedView = self.hiddenPublisherWebView;
    [inspectedView evaluateJavaScript:script completionHandler:^(id result, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            PaperMonitorDelegate *strongSelf = weakSelf;
            if (!strongSelf || strongSelf.hiddenPublisherWebView != inspectedView || ![strongSelf isHiddenPublisherMainDownload]) return;
            NSDictionary *payload = [result isKindOfClass:[NSDictionary class]] ? result : @{};
            NSMutableArray *rawURLs = [([payload[@"urls"] isKindOfClass:[NSArray class]] ? payload[@"urls"] : @[]) mutableCopy];
            NSString *publisher = [strongSelf publisherNameForContext:strongSelf.hiddenPublisherContext ?: @{}];
            NSString *current = strongSelf.hiddenPublisherWebView.URL.absoluteString ?: @"";
            if ([payload[@"accessRequired"] boolValue]) {
                [strongSelf failHiddenPublisherDownload:@"APS requires institutional or personal subscription access for this PDF. Open Website in Gewu Browser, sign in with an authorized account or use your institution's network, then retry Download."];
                return;
            }
            if ([payload[@"blocked"] boolValue]
                && strongSelf.hiddenPublisherDiscoveryPageRetryCount >= 3) {
                NSString *detail = strongSelf.hiddenPublisherContext[@"publisher_download_response_detail"] ?: @"";
                [strongSelf failHiddenPublisherDownload:[NSString stringWithFormat:@"%@ requires browser verification or article access. Open Website in Gewu Browser, complete verification or sign in, then retry Download. %@", [publisher isEqualToString:@"aaas"] ? @"Science" : ([publisher isEqualToString:@"nature"] ? @"Nature" : publisher.uppercaseString), detail]];
                return;
            }
            // Establish the normal article session first. Never leave a browser
            // verification page to chase public supplements as a substitute.
            if (![payload[@"blocked"] boolValue] && !error) {
                NSString *target = strongSelf.hiddenPublisherContext[@"publisher_download_target_url"];
                if ([target isKindOfClass:[NSString class]] && target.length) {
                    [rawURLs insertObject:target atIndex:0];
                    if ([publisher isEqualToString:@"aaas"]) {
                        NSURLComponents *alternate = [NSURLComponents componentsWithString:target];
                        alternate.path = [alternate.path stringByReplacingOccurrencesOfString:@"/doi/pdf/" withString:@"/doi/epdf/"];
                        alternate.query = nil;
                        if (alternate.URL) [rawURLs addObject:alternate.URL.absoluteString];
                    }
                }
            }
            for (id value in rawURLs) {
                if (![value isKindOfClass:[NSString class]]) continue;
                NSURL *url = [NSURL URLWithString:(NSString *)value];
                NSString *absolute = url.absoluteString ?: @"";
                if (![strongSelf isAllowedPublisherURL:url publisher:publisher]
                    || ([publisher isEqualToString:@"aaas"] && [strongSelf isScienceSupplementReference:absolute])
                    || ([publisher isEqualToString:@"nature"] && ![strongSelf isNatureMainURL:url])
                    || [absolute isEqualToString:current]
                    || [strongSelf.hiddenPublisherDiscoveryVisitedURLs containsObject:absolute]) {
                    continue;
                }
                if (strongSelf.hiddenPublisherDiscoveryDepth >= 6) break;
                [strongSelf.hiddenPublisherDiscoveryVisitedURLs addObject:absolute];
                strongSelf.hiddenPublisherDiscoveryDepth += 1;
                strongSelf.hiddenPublisherDiscoveryPageRetryCount = 0;
                NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
                if (current.length > 0) [request setValue:current forHTTPHeaderField:@"Referer"];
                [strongSelf.hiddenPublisherWebView loadRequest:request];
                return;
            }
            BOOL clicked = [payload[@"clicked"] respondsToSelector:@selector(boolValue)]
                && [payload[@"clicked"] boolValue];
            if (!error && strongSelf.hiddenPublisherDiscoveryPageRetryCount < 160) {
                strongSelf.hiddenPublisherDiscoveryPageRetryCount += 1;
                NSTimeInterval delay = clicked ? 1.5 : 1.0;
                dispatch_after(
                    dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)),
                    dispatch_get_main_queue(),
                    ^{
                        if (strongSelf.hiddenPublisherWebView == inspectedView) [strongSelf inspectHiddenPublisherMainPage];
                    }
                );
                return;
            }
            NSString *message = error.localizedDescription
                ?: @"The publisher page did not expose a downloadable PDF.";
            [strongSelf failHiddenPublisherDownload:message];
        });
    }];
}

- (void)hiddenPublisherDownloadTimedOut:(NSTimer *)timer {
    if ([self isHiddenPublisherSupplementDiscovery] || [self isHiddenGenericSupplementDiscovery]) {
        [self failHiddenPublisherDownload:@"Supplementary PDF discovery timed out; the main PDF remains saved."];
        return;
    }
    if ([[self publisherNameForContext:self.hiddenPublisherContext ?: @{}] isEqualToString:@"nature"]) {
        NSString *detail = self.hiddenPublisherContext[@"publisher_download_response_detail"] ?: @"";
        [self failHiddenPublisherDownload:[NSString stringWithFormat:@"Nature did not provide the requested PDF. Open Website in Gewu Browser to check article access or complete verification, then retry Download. %@", detail]];
        return;
    }
    if ([self isHiddenPublisherMainDownload] && [[self publisherNameForContext:self.hiddenPublisherContext ?: @{}] isEqualToString:@"aaas"]) {
        NSString *detail = self.hiddenPublisherContext[@"publisher_download_response_detail"] ?: @"";
        [self failHiddenPublisherDownload:[NSString stringWithFormat:@"Science main PDF was not obtained. Open Website in Gewu Browser to check article access or complete verification, then retry Download. %@", detail]];
        return;
    }
    NSString *detail = self.hiddenPublisherContext[@"publisher_download_response_detail"] ?: @"";
    [self failHiddenPublisherDownload:[NSString stringWithFormat:@"The publisher did not provide a PDF before the background download timed out. Open Website in Gewu Browser to check article access or complete verification, then retry Download. %@", detail]];
}

- (void)webView:(WKWebView *)webView
decidePolicyForNavigationResponse:(WKNavigationResponse *)navigationResponse
decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler {
    if (webView != self.hiddenPublisherWebView) {
        decisionHandler(WKNavigationResponsePolicyAllow);
        return;
    }
    NSString *mimeType = navigationResponse.response.MIMEType.lowercaseString ?: @"";
    if (navigationResponse.forMainFrame && [self isHiddenPublisherMainDownload]
        && [navigationResponse.response isKindOfClass:[NSHTTPURLResponse class]]) {
        NSHTTPURLResponse *response = (NSHTTPURLResponse *)navigationResponse.response;
        NSMutableDictionary *context = [self.hiddenPublisherContext mutableCopy];
        context[@"publisher_download_response_detail"] = [NSString stringWithFormat:@"HTTP %ld at %@%@.",
            (long)response.statusCode, response.URL.host ?: @"", response.URL.path ?: @""];
        self.hiddenPublisherContext = context;
    }
    NSString *disposition = @"";
    if ([navigationResponse.response isKindOfClass:[NSHTTPURLResponse class]]) {
        id value = ((NSHTTPURLResponse *)navigationResponse.response).allHeaderFields[@"Content-Disposition"];
        if ([value isKindOfClass:[NSString class]]) disposition = [value lowercaseString];
    }
    BOOL isPDF = [mimeType containsString:@"pdf"] || [disposition containsString:@".pdf"];
    if (isPDF || !navigationResponse.canShowMIMEType) {
        self.hiddenPublisherDownloadTransitionPending = YES;
        decisionHandler(WKNavigationResponsePolicyDownload);
    } else {
        decisionHandler(WKNavigationResponsePolicyAllow);
    }
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    if (webView != self.hiddenPublisherWebView) return;
    NSString *absolute = webView.URL.absoluteString ?: @"";
    if (absolute.length > 0) [self.hiddenPublisherDiscoveryVisitedURLs addObject:absolute];
    self.hiddenPublisherDiscoveryPageRetryCount = 0;
    if ([self isHiddenPublisherSupplementDiscovery]) {
        [self inspectHiddenPublisherSupplementPage];
    } else if ([self isHiddenGenericSupplementDiscovery]) {
        [self inspectHiddenGenericSupplementPage];
    } else if ([self isHiddenPublisherMainDownload]) {
        [self inspectHiddenPublisherMainPage];
    }
}

- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    if (webView != self.webView || self.applicationIsTerminating) return;
    [self appendLauncherLogMessage:@"Workspace web process terminated; recovering the authenticated UI. The server and refresh jobs remain running."];
    if (!self.workspaceRecoveryWindow || -self.workspaceRecoveryWindow.timeIntervalSinceNow > 60) {
        self.workspaceRecoveryWindow = [NSDate date];
        self.workspaceRecoveryAttempts = 0;
    }
    if (++self.workspaceRecoveryAttempts > 3) {
        [self presentStartupFailure:@"The workspace preview repeatedly stopped. Please reopen Gewu Insight. Your refresh progress remains saved."];
        return;
    }
    [self closeNativeQuickLookNotifyingWeb:NO];
    [self showLoadingPage];
    // Do not restart the server or replay any in-flight user/data operations.
    [self loadApp];
}

- (void)webView:(WKWebView *)webView
navigationAction:(WKNavigationAction *)navigationAction
didBecomeDownload:(WKDownload *)download {
    if (webView != self.hiddenPublisherWebView) return;
    self.hiddenPublisherDownloadTransitionPending = NO;
    self.hiddenPublisherDownload = download;
    download.delegate = self;
}

- (void)webView:(WKWebView *)webView
navigationResponse:(WKNavigationResponse *)navigationResponse
didBecomeDownload:(WKDownload *)download {
    if (webView != self.hiddenPublisherWebView) return;
    self.hiddenPublisherDownloadTransitionPending = NO;
    self.hiddenPublisherDownload = download;
    download.delegate = self;
}

- (void)download:(WKDownload *)download
decideDestinationUsingResponse:(NSURLResponse *)response
suggestedFilename:(NSString *)suggestedFilename
completionHandler:(void (^)(NSURL * _Nullable destination))completionHandler {
    if (download != self.hiddenPublisherDownload) {
        completionHandler(nil);
        return;
    }
    if ([self isHiddenPublisherMainDownload]
        && [[self publisherNameForContext:self.hiddenPublisherContext ?: @{}] isEqualToString:@"nature"]
        && (![self isNatureMainURL:response.URL] || [self isNatureSecondaryReference:suggestedFilename])) {
        completionHandler(nil);
        [self failHiddenPublisherDownload:@"Nature returned an attachment or a different article instead of the main article PDF. Open Website to check article access, then retry Download."];
        return;
    }
    if ([self isHiddenPublisherMainDownload]
        && [[self publisherNameForContext:self.hiddenPublisherContext ?: @{}] isEqualToString:@"aaas"]
        && ([self isScienceSupplementReference:response.URL.absoluteString]
            || [self isScienceSupplementReference:suggestedFilename])) {
        completionHandler(nil);
        [self failHiddenPublisherDownload:@"Science returned supplementary material instead of the main article PDF. Open Website to check article access, then retry Download."];
        return;
    }
    NSMutableDictionary *context = [self.hiddenPublisherContext mutableCopy];
    context[@"publisher_download_final_url"] = response.URL.absoluteString ?: @"";
    context[@"publisher_download_filename"] = suggestedFilename.lastPathComponent ?: @"";
    self.hiddenPublisherContext = context;
    NSString *extension = suggestedFilename.pathExtension.lowercaseString ?: @"";
    NSString *mimeType = response.MIMEType.lowercaseString ?: @"";
    if (![extension isEqualToString:@"pdf"] && ![extension isEqualToString:@"doc"] && ![extension isEqualToString:@"docx"]) {
        if ([mimeType containsString:@"wordprocessingml"]) extension = @"docx";
        else if ([mimeType containsString:@"msword"]) extension = @"doc";
        else extension = @"pdf";
    }
    NSString *temporaryName = [NSString stringWithFormat:@"gewu-publisher-%@.%@", NSUUID.UUID.UUIDString, extension];
    NSString *temporaryPath = [NSTemporaryDirectory() stringByAppendingPathComponent:temporaryName];
    self.hiddenPublisherTemporaryPath = temporaryPath;
    completionHandler([NSURL fileURLWithPath:temporaryPath]);
}

- (void)downloadDidFinish:(WKDownload *)download {
    if (download != self.hiddenPublisherDownload) return;
    [self.hiddenPublisherTimeout invalidate];
    self.hiddenPublisherTimeout = nil;
    [self acceptHiddenPublisherFileAtPath:self.hiddenPublisherTemporaryPath ?: @""];
}

- (void)acceptHiddenPublisherFileAtPath:(NSString *)path {
    NSDictionary *attributes = path.length > 0
        ? [[NSFileManager defaultManager] attributesOfItemAtPath:path error:nil]
        : nil;
    unsigned long long fileSize = [attributes fileSize];
    NSFileHandle *handle = path.length > 0 ? [NSFileHandle fileHandleForReadingAtPath:path] : nil;
    NSData *prefix = [handle readDataOfLength:1024];
    [handle closeFile];
    NSString *prefixText = prefix ? [[NSString alloc] initWithData:prefix encoding:NSISOLatin1StringEncoding] : @"";
    NSString *extension = path.pathExtension.lowercaseString ?: @"";
    BOOL isPDF = [prefixText rangeOfString:@"%PDF-"].location != NSNotFound;
    const unsigned char *bytes = prefix.bytes;
    BOOL isDOCX = prefix.length >= 4 && bytes[0] == 'P' && bytes[1] == 'K' && bytes[2] == 3 && bytes[3] == 4;
    const unsigned char oleHeader[] = {0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1};
    BOOL isDOC = prefix.length >= sizeof(oleHeader)
        && memcmp(bytes, oleHeader, sizeof(oleHeader)) == 0;
    NSString *kind = [self.hiddenPublisherContext[@"publisher_download_kind"] isKindOfClass:[NSString class]]
        ? self.hiddenPublisherContext[@"publisher_download_kind"]
        : @"";
    BOOL supplementFile = [kind isEqualToString:@"publisher-supplement-file"]
        || [kind isEqualToString:@"aaas-supplement-pdf"];
    BOOL validSupplementDocument = supplementFile && (isDOCX || isDOC);
    if (path.length == 0 || fileSize < 1024 || (!isPDF && !validSupplementDocument)) {
        [self failHiddenPublisherDownload:@"The publisher returned a page instead of a supported PDF, DOC, or DOCX file."];
        return;
    }
    NSString *acceptedPath = path;
    if (!isPDF && validSupplementDocument) {
        NSString *wantedExtension = isDOCX ? @"docx" : @"doc";
        if (![extension isEqualToString:wantedExtension]) {
            acceptedPath = [[path stringByDeletingPathExtension] stringByAppendingPathExtension:wantedExtension];
            [[NSFileManager defaultManager] removeItemAtPath:acceptedPath error:nil];
            NSError *moveError = nil;
            if (![[NSFileManager defaultManager] moveItemAtPath:path toPath:acceptedPath error:&moveError]) {
                [self failHiddenPublisherDownload:moveError.localizedDescription ?: @"Could not prepare the Word supplement."];
                return;
            }
            self.hiddenPublisherTemporaryPath = acceptedPath;
        }
    }
    [self attachHiddenPublisherPDFAtPath:acceptedPath];
}

- (void)download:(WKDownload *)download didFailWithError:(NSError *)error resumeData:(NSData *)resumeData {
    if (download != self.hiddenPublisherDownload) return;
    NSString *message = error.localizedDescription.length > 0 ? error.localizedDescription : @"Published PDF download failed.";
    [self failHiddenPublisherDownload:message];
}

- (BOOL)isExpectedHiddenPublisherDownloadTransitionError:(NSError *)error {
    if (!self.hiddenPublisherDownloadTransitionPending || !error) return NO;
    NSString *domain = error.domain ?: @"";
    // WebKit still reports legacy policy-change code 102 when a navigation is
    // deliberately converted into a WKDownload, although the named constant
    // itself has been deprecated since macOS 10.14.
    const NSInteger frameLoadInterruptedByPolicyChange = 102;
    return error.code == frameLoadInterruptedByPolicyChange
        && ([domain isEqualToString:@"WebKitErrorDomain"] || [domain isEqualToString:WKErrorDomain]);
}

- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    if (webView != self.hiddenPublisherWebView || self.hiddenPublisherDownload) return;
    if ([self isExpectedHiddenPublisherDownloadTransitionError:error]) return;
    [self failHiddenPublisherDownload:error.localizedDescription ?: @"The publisher page could not be loaded."];
}

- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    if (webView != self.hiddenPublisherWebView || self.hiddenPublisherDownload) return;
    if ([self isExpectedHiddenPublisherDownloadTransitionError:error]) return;
    [self failHiddenPublisherDownload:error.localizedDescription ?: @"The publisher page could not be loaded."];
}

- (void)attachHiddenPublisherPDFAtPath:(NSString *)path {
    NSMutableDictionary *payload = [NSMutableDictionary dictionaryWithDictionary:self.hiddenPublisherContext ?: @{}];
    BOOL wasScienceSupplementDiscovery = [self isHiddenPublisherSupplementDiscovery];
    BOOL wasGenericSupplementDiscovery = [self isHiddenGenericSupplementDiscovery];
    BOOL wasSupplementDiscovery = wasScienceSupplementDiscovery || wasGenericSupplementDiscovery;
    if (wasScienceSupplementDiscovery) {
        payload[@"publisher_download_kind"] = @"aaas-supplement-pdf";
    } else if (wasGenericSupplementDiscovery) {
        payload[@"publisher_download_kind"] = @"publisher-supplement-file";
    }
    payload[@"source_path"] = path;
    payload[@"preserve_filename"] = @NO;
    NSError *jsonError = nil;
    NSData *body = [NSJSONSerialization dataWithJSONObject:payload options:0 error:&jsonError];
    if (!body || jsonError) {
        [self failHiddenPublisherDownload:@"Could not prepare the downloaded PDF for the Library."];
        return;
    }
    NSURL *endpoint = [self.url URLByAppendingPathComponent:@"api/manual-pdf-path"];
    NSMutableURLRequest *request = [self workspaceRequestForURL:endpoint];
    request.HTTPMethod = @"POST";
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    request.HTTPBody = body;
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSDictionary *responsePayload = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        NSInteger statusCode = [response isKindOfClass:[NSHTTPURLResponse class]]
            ? ((NSHTTPURLResponse *)response).statusCode
            : 0;
        dispatch_async(dispatch_get_main_queue(), ^{
            if (error || statusCode < 200 || statusCode >= 300 || ![responsePayload isKindOfClass:[NSDictionary class]]) {
                NSString *serverError = [responsePayload[@"error"] isKindOfClass:[NSString class]] ? responsePayload[@"error"] : nil;
                [self failHiddenPublisherDownload:serverError ?: error.localizedDescription ?: @"Could not add the published PDF to Gewu Insight."];
                return;
            }
            NSString *token = self.hiddenPublisherToken ?: @"";
            NSMutableDictionary *resultPayload = [NSMutableDictionary dictionaryWithDictionary:responsePayload];
            if (wasSupplementDiscovery) resultPayload[@"supplement_attached"] = @YES;
            [self notifyHiddenPublisherDownloadToken:token success:YES data:resultPayload error:nil];
            [self clearHiddenPublisherDownload];
        });
    }] resume];
}

- (void)failHiddenPublisherDownload:(NSString *)message {
    if ([[self publisherNameForContext:self.hiddenPublisherContext ?: @{}] isEqualToString:@"aaas"]) {
        [self appendLauncherLogMessage:[NSString stringWithFormat:@"Science download %@ (%@): %@ %@",
            self.hiddenPublisherContext[@"paper_id"] ?: @"",
            self.hiddenPublisherContext[@"publisher_download_kind"] ?: @"",
            message ?: @"Download failed", self.hiddenPublisherContext[@"publisher_download_response_detail"] ?: @""]];
    }
    NSString *token = self.hiddenPublisherToken ?: @"";
    [self notifyHiddenPublisherDownloadToken:token success:NO data:nil error:message ?: @"Published PDF download failed."];
    [self clearHiddenPublisherDownload];
}

- (void)notifyHiddenPublisherDownloadToken:(NSString *)token
                                   success:(BOOL)success
                                      data:(NSDictionary *)data
                                     error:(NSString *)error {
    NSMutableDictionary *payload = [NSMutableDictionary dictionary];
    payload[@"token"] = token ?: @"";
    payload[@"success"] = @(success);
    if (data) payload[@"data"] = data;
    if (error.length > 0) payload[@"error"] = error;
    NSData *jsonData = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
    NSString *json = jsonData ? [[NSString alloc] initWithData:jsonData encoding:NSUTF8StringEncoding] : @"{}";
    NSString *script = [NSString stringWithFormat:@"window.handleNativePublisherDownloadResult && window.handleNativePublisherDownloadResult(%@)", json];
    [self.webView evaluateJavaScript:script completionHandler:nil];
}

- (void)clearHiddenPublisherDownload {
    [self.hiddenPublisherTimeout invalidate];
    self.hiddenPublisherTimeout = nil;
    [self.hiddenPublisherWebView stopLoading];
    self.hiddenPublisherWebView.navigationDelegate = nil;
    self.hiddenPublisherWebView = nil;
    self.hiddenPublisherDownload.delegate = nil;
    self.hiddenPublisherDownload = nil;
    if (self.hiddenPublisherTemporaryPath.length > 0) {
        [[NSFileManager defaultManager] removeItemAtPath:self.hiddenPublisherTemporaryPath error:nil];
    }
    self.hiddenPublisherTemporaryPath = nil;
    self.hiddenPublisherContext = nil;
    self.hiddenPublisherToken = nil;
    self.hiddenPublisherDownloadTransitionPending = NO;
    self.hiddenPublisherDiscoveryVisitedURLs = nil;
    self.hiddenPublisherDiscoveryDepth = 0;
    self.hiddenPublisherDiscoveryPageRetryCount = 0;
}

- (NSRect)defaultRestoreFrameForScreen:(NSScreen *)screen {
    NSRect visibleFrame = screen.visibleFrame;
    CGFloat width = MIN(NSWidth(visibleFrame) - 40.0, MAX(980.0, floor(NSWidth(visibleFrame) * 0.82)));
    CGFloat height = MIN(NSHeight(visibleFrame) - 40.0, MAX(680.0, floor(NSHeight(visibleFrame) * 0.84)));
    width = MAX(640.0, width);
    height = MAX(480.0, height);
    return NSMakeRect(
        round(NSMidX(visibleFrame) - width / 2.0),
        round(NSMidY(visibleFrame) - height / 2.0),
        width,
        height
    );
}

- (void)toggleMainWindowFill {
    NSScreen *screen = self.window.screen ?: [NSScreen mainScreen];
    if (!screen) return;
    NSRect visibleFrame = screen.visibleFrame;
    NSRect currentFrame = self.window.frame;
    BOOL fillsVisibleFrame = fabs(NSMinX(currentFrame) - NSMinX(visibleFrame)) <= 2.0
        && fabs(NSMinY(currentFrame) - NSMinY(visibleFrame)) <= 2.0
        && fabs(NSWidth(currentFrame) - NSWidth(visibleFrame)) <= 2.0
        && fabs(NSHeight(currentFrame) - NSHeight(visibleFrame)) <= 2.0;
    NSRect targetFrame;
    if (fillsVisibleFrame) {
        targetFrame = self.windowRestoreFrame;
        NSRect intersection = NSIntersectionRect(targetFrame, visibleFrame);
        BOOL restoreIsUsable = !NSIsEmptyRect(targetFrame)
            && NSWidth(intersection) >= MIN(240.0, NSWidth(targetFrame))
            && NSHeight(intersection) >= MIN(160.0, NSHeight(targetFrame));
        BOOL restoreIsAlsoFilled = fabs(NSMinX(targetFrame) - NSMinX(visibleFrame)) <= 2.0
            && fabs(NSMinY(targetFrame) - NSMinY(visibleFrame)) <= 2.0
            && fabs(NSWidth(targetFrame) - NSWidth(visibleFrame)) <= 2.0
            && fabs(NSHeight(targetFrame) - NSHeight(visibleFrame)) <= 2.0;
        if (!restoreIsUsable || restoreIsAlsoFilled) {
            targetFrame = [self defaultRestoreFrameForScreen:screen];
        }
        targetFrame.size.width = MIN(NSWidth(targetFrame), NSWidth(visibleFrame));
        targetFrame.size.height = MIN(NSHeight(targetFrame), NSHeight(visibleFrame));
        targetFrame.origin.x = MIN(MAX(NSMinX(targetFrame), NSMinX(visibleFrame)), NSMaxX(visibleFrame) - NSWidth(targetFrame));
        targetFrame.origin.y = MIN(MAX(NSMinY(targetFrame), NSMinY(visibleFrame)), NSMaxY(visibleFrame) - NSHeight(targetFrame));
    } else {
        self.windowRestoreFrame = currentFrame;
        targetFrame = visibleFrame;
    }
    [self.window setFrame:targetFrame display:YES animate:YES];
}

- (void)positionTrafficLightButtons {
    if (!self.webView.superview || self.trafficLightFullScreenTransition
        || (self.window.styleMask & NSWindowStyleMaskFullScreen)) return;
    // Match .view-switcher / .view-switch in ui_server.py: top 6, height 32,
    // a 2-point top border and no bottom border put the label center at 23.
    const CGFloat tabBarHeight = 38.0;
    const CGFloat labelCenterFromTop = 23.0;
    NSButton *closeButton = [self.window standardWindowButton:NSWindowCloseButton];
    NSView *titlebarContainer = closeButton.superview.superview;
    if (!titlebarContainer.superview) return;
    // Extend the native container as well, keeping the entire button hittable.
    // Full-size content stays in place underneath the transparent title bar.
    NSRect topBar = self.webView.bounds;
    if (!self.webView.isFlipped) topBar.origin.y = NSMaxY(topBar) - tabBarHeight;
    topBar.size.height = tabBarHeight;
    NSRect containerFrame = titlebarContainer.frame;
    NSRect convertedBar = [self.webView convertRect:topBar toView:titlebarContainer.superview];
    containerFrame.origin.y = convertedBar.origin.y;
    containerFrame.size.height = convertedBar.size.height;
    if (!NSEqualRects(containerFrame, titlebarContainer.frame)) titlebarContainer.frame = containerFrame;

    NSPoint labelCenter = NSMakePoint(0, self.webView.isFlipped
        ? NSMinY(self.webView.bounds) + labelCenterFromTop
        : NSMaxY(self.webView.bounds) - labelCenterFromTop);
    CGFloat scale = self.window.backingScaleFactor ?: 1.0;
    for (NSNumber *kind in @[@(NSWindowCloseButton), @(NSWindowMiniaturizeButton), @(NSWindowZoomButton)]) {
        NSButton *button = [self.window standardWindowButton:kind.unsignedIntegerValue];
        if (!button.superview) continue;
        NSView *container = button.superview;
        NSRect frame = button.frame;
        NSPoint center = [self.webView convertPoint:labelCenter toView:container];
        frame.origin.y = round((center.y - NSHeight(frame) / 2.0) * scale) / scale;
        if (!NSEqualRects(frame, button.frame)) button.frame = frame;
    }
}

- (void)windowDidUpdate:(NSNotification *)notification {
    if (notification.object != self.window || self.trafficLightLayoutInProgress
        || self.trafficLightFullScreenTransition
        || (self.window.styleMask & NSWindowStyleMaskFullScreen)) return;
    // AppKit can reset the native titlebar after the resize/startup callbacks.
    // Finish its pending layout, then align before this update is displayed.
    // Do not queue another update: unchanged frames need no work or timer.
    self.trafficLightLayoutInProgress = YES;
    [self.window layoutIfNeeded];
    [self positionTrafficLightButtons];
    self.trafficLightLayoutInProgress = NO;
}

- (void)scheduleTrafficLightLayout:(NSNotification *)notification {
    if (notification.object != self.window || self.trafficLightLayoutScheduled) return;
    self.trafficLightLayoutScheduled = YES;
    dispatch_async(dispatch_get_main_queue(), ^{
        self.trafficLightLayoutScheduled = NO;
        [self positionTrafficLightButtons];
    });
}

- (void)windowDidResize:(NSNotification *)notification {
    [self scheduleTrafficLightLayout:notification];
}

- (void)windowDidEndLiveResize:(NSNotification *)notification {
    [self scheduleTrafficLightLayout:notification];
}

- (void)windowDidDeminiaturize:(NSNotification *)notification {
    [self scheduleTrafficLightLayout:notification];
}

- (void)windowWillEnterFullScreen:(NSNotification *)notification {
    if (notification.object == self.window) self.trafficLightFullScreenTransition = YES;
}

- (void)windowWillExitFullScreen:(NSNotification *)notification {
    if (notification.object == self.window) self.trafficLightFullScreenTransition = YES;
}

- (void)windowDidEnterFullScreen:(NSNotification *)notification {
    if (notification.object == self.window) self.trafficLightFullScreenTransition = NO;
}

- (void)windowDidExitFullScreen:(NSNotification *)notification {
    if (notification.object == self.window) self.trafficLightFullScreenTransition = NO;
    [self scheduleTrafficLightLayout:notification];
}

- (void)windowDidFailToEnterFullScreen:(NSWindow *)window {
    if (window != self.window) return;
    self.trafficLightFullScreenTransition = NO;
    [self positionTrafficLightButtons];
}

- (void)windowDidFailToExitFullScreen:(NSWindow *)window {
    if (window != self.window) return;
    self.trafficLightFullScreenTransition = NO;
    [self positionTrafficLightButtons];
}

- (void)windowDidChangeBackingProperties:(NSNotification *)notification {
    [self scheduleTrafficLightLayout:notification];
}

- (void)installMainMenu {
    NSMenu *mainMenu = [[NSMenu alloc] initWithTitle:@""];

    NSMenuItem *appMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:appMenuItem];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"Gewu Insight"];
    NSMenuItem *aboutItem = [appMenu addItemWithTitle:@"About Gewu Insight" action:@selector(openAbout:) keyEquivalent:@""];
    aboutItem.target = self;
    [appMenu addItem:[NSMenuItem separatorItem]];
    NSString *quitTitle = [NSString stringWithFormat:@"Quit %@", @"Gewu Insight"];
    [appMenu addItemWithTitle:quitTitle action:@selector(terminate:) keyEquivalent:@"q"];
    appMenuItem.submenu = appMenu;

    NSMenuItem *fileMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:fileMenuItem];
    NSMenu *fileMenu = [[NSMenu alloc] initWithTitle:@"File"];
    NSMenuItem *closeWindowItem = [fileMenu addItemWithTitle:@"Close Window" action:@selector(closeActiveWindow:) keyEquivalent:@"w"];
    closeWindowItem.target = self;
    closeWindowItem.keyEquivalentModifierMask = NSEventModifierFlagCommand;
    fileMenuItem.submenu = fileMenu;

    NSMenuItem *editMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:editMenuItem];
    NSMenu *editMenu = [[NSMenu alloc] initWithTitle:@"Edit"];
    [editMenu addItemWithTitle:@"Undo" action:@selector(undo:) keyEquivalent:@"z"];
    [editMenu addItemWithTitle:@"Redo" action:@selector(redo:) keyEquivalent:@"Z"];
    [editMenu addItem:[NSMenuItem separatorItem]];
    [editMenu addItemWithTitle:@"Cut" action:@selector(cut:) keyEquivalent:@"x"];
    [editMenu addItemWithTitle:@"Copy" action:@selector(copy:) keyEquivalent:@"c"];
    [editMenu addItemWithTitle:@"Paste" action:@selector(paste:) keyEquivalent:@"v"];
    [editMenu addItemWithTitle:@"Select All" action:@selector(selectAll:) keyEquivalent:@"a"];
    editMenuItem.submenu = editMenu;

    NSMenuItem *viewMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:viewMenuItem];
    NSMenu *viewMenu = [[NSMenu alloc] initWithTitle:@"View"];
    self.listViewItem = [viewMenu addItemWithTitle:@"List View" action:@selector(useListLibraryView:) keyEquivalent:@""];
    self.listViewItem.target = self;
    self.listViewItem.state = NSControlStateValueOn;
    self.tableViewItem = [viewMenu addItemWithTitle:@"Table View" action:@selector(useTableLibraryView:) keyEquivalent:@""];
    self.tableViewItem.target = self;
    [viewMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *toggleViewItem = [viewMenu addItemWithTitle:@"Toggle List/Table" action:@selector(toggleLibraryContentView:) keyEquivalent:@"v"];
    toggleViewItem.target = self;
    toggleViewItem.keyEquivalentModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagShift;
    viewMenuItem.submenu = viewMenu;

    NSMenuItem *loaderMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:loaderMenuItem];
    NSMenu *loaderMenu = [[NSMenu alloc] initWithTitle:@"Loader"];
    NSMenuItem *openLoaderItem = [loaderMenu addItemWithTitle:@"Open Loader" action:@selector(openLibraryLoader:) keyEquivalent:@"l"];
    openLoaderItem.target = self;
    NSMenuItem *refreshMetadataItem = [loaderMenu addItemWithTitle:@"Refresh All Metadata" action:@selector(openMetadataRefresh:) keyEquivalent:@""];
    refreshMetadataItem.target = self;
    NSMenuItem *findMissingIdentifiersItem = [loaderMenu addItemWithTitle:@"Find All Missing Identifiers" action:@selector(openIdentifierRecovery:) keyEquivalent:@""];
    findMissingIdentifiersItem.target = self;
    loaderMenuItem.submenu = loaderMenu;

    NSMenuItem *settingMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:settingMenuItem];
    NSMenu *settingMenu = [[NSMenu alloc] initWithTitle:@"Setting"];
    NSMenuItem *namingRuleMenuItem = [[NSMenuItem alloc] initWithTitle:@"Naming Rule" action:nil keyEquivalent:@""];
    NSMenu *namingRuleMenu = [[NSMenu alloc] initWithTitle:@"Naming Rule"];
    self.titleNamingItem = [namingRuleMenu addItemWithTitle:@"Use Title" action:@selector(useTitleNamingRule:) keyEquivalent:@""];
    self.titleNamingItem.target = self;
    self.citationNamingItem = [namingRuleMenu addItemWithTitle:@"Use Citation" action:@selector(useCitationNamingRule:) keyEquivalent:@""];
    self.citationNamingItem.target = self;
    self.citationNamingItem.state = NSControlStateValueOn;
    namingRuleMenuItem.submenu = namingRuleMenu;
    [settingMenu addItem:namingRuleMenuItem];
    NSMenuItem *pdfRenameSettingsItem = [settingMenu addItemWithTitle:@"PDF Rename Settings" action:@selector(openPdfRenameSettings:) keyEquivalent:@""];
    pdfRenameSettingsItem.target = self;
    NSMenuItem *quickLookSettingsItem = [settingMenu addItemWithTitle:@"Quick Look Settings" action:@selector(openQuickLookSettings:) keyEquivalent:@""];
    quickLookSettingsItem.target = self;
    NSMenuItem *libraryDestinationSettingsItem = [settingMenu addItemWithTitle:@"Add to Library" action:@selector(openLibraryDestinationSettings:) keyEquivalent:@""];
    libraryDestinationSettingsItem.target = self;
    NSMenuItem *websiteLinkSettingsItem = [settingMenu addItemWithTitle:@"Website Links" action:@selector(openWebsiteLinkSettings:) keyEquivalent:@""];
    websiteLinkSettingsItem.target = self;
    NSMenuItem *aiAccessItem = [settingMenu addItemWithTitle:@"AI Access" action:@selector(openAIAccessSettings:) keyEquivalent:@""];
    aiAccessItem.target = self;
    NSMenuItem *arxivSettingsItem = [settingMenu addItemWithTitle:@"arXiv Scope Settings" action:@selector(openArxivSettings:) keyEquivalent:@""];
    arxivSettingsItem.target = self;
    NSMenuItem *citationSettingsItem = [settingMenu addItemWithTitle:@"Literature Data Source" action:@selector(openCitationSettings:) keyEquivalent:@","];
    citationSettingsItem.target = self;
    NSMenuItem *fieldSettingsItem = [settingMenu addItemWithTitle:@"Field Settings" action:@selector(openFieldSettings:) keyEquivalent:@""];
    fieldSettingsItem.target = self;
    [settingMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *clearCacheItem = [settingMenu addItemWithTitle:@"Clear Monitor Cache" action:@selector(clearWebCache:) keyEquivalent:@""];
    clearCacheItem.target = self;
    NSMenuItem *fontSizeSettingsItem = [settingMenu addItemWithTitle:@"Font Size" action:@selector(openFontSizeSettings:) keyEquivalent:@""];
    fontSizeSettingsItem.target = self;
    settingMenuItem.submenu = settingMenu;

    NSMenuItem *helpMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:helpMenuItem];
    NSMenu *helpMenu = [[NSMenu alloc] initWithTitle:@"Help"];
    NSMenuItem *userGuideItem = [helpMenu addItemWithTitle:@"User Guide" action:@selector(openUserGuide:) keyEquivalent:@"?"];
    userGuideItem.target = self;
    NSMenuItem *contactItem = [helpMenu addItemWithTitle:@"Contact Us" action:@selector(contactUs:) keyEquivalent:@""];
    contactItem.target = self;
    helpMenuItem.submenu = helpMenu;

    NSApp.mainMenu = mainMenu;
}

- (void)showLoadingPage {
    [self.startupView removeFromSuperview];
    self.startupView = [[GewuStartupView alloc] initWithFrame:self.window.contentView.bounds];
    [self.window.contentView addSubview:self.startupView
                              positioned:NSWindowAbove
                              relativeTo:self.webView];
}

- (void)dismissStartupOverlay {
    GewuStartupView *overlay = self.startupView;
    if (!overlay) return;
    self.startupView = nil;
    __weak typeof(self) weakSelf = self;
    [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
        context.duration = 0.18;
        overlay.animator.alphaValue = 0.0;
    } completionHandler:^{
        [overlay removeFromSuperview];
        PaperMonitorDelegate *strongSelf = weakSelf;
        if (strongSelf) [strongSelf.window makeFirstResponder:strongSelf.webView];
    }];
}

- (void)ensureServerThenLoad {
    [self checkServerWithCompletion:^(BOOL available) {
        if (available) {
            self.serverRestartAttempts = 0;
            [self loadApp];
        } else {
            [self startServerIfNeeded];
            [self beginServerReadinessPolling];
        }
    }];
}

- (void)startServerIfNeeded {
    if (self.ownedServerTask.isRunning) {
        return;
    }
    self.ownedServerTask = nil;

    NSURL *helperURL = [[[[[NSBundle mainBundle] bundleURL]
        URLByAppendingPathComponent:@"Contents"]
        URLByAppendingPathComponent:@"MacOS"]
        URLByAppendingPathComponent:@"Gewu Insight Server"];

    NSTask *task = [[NSTask alloc] init];
    task.executableURL = helperURL;
    __weak typeof(self) weakSelf = self;
    task.terminationHandler = ^(NSTask *terminatedTask) {
        dispatch_async(dispatch_get_main_queue(), ^{
            PaperMonitorDelegate *strongSelf = weakSelf;
            if (!strongSelf) {
                return;
            }
            if (strongSelf.ownedServerTask == terminatedTask) strongSelf.ownedServerTask = nil;
            NSString *reason = terminatedTask.terminationReason == NSTaskTerminationReasonUncaughtSignal
                ? @"signal"
                : @"exit";
            [strongSelf appendLauncherLogMessage:[NSString stringWithFormat:
                @"Native launcher observed server %@ status %ld.",
                reason,
                (long)terminatedTask.terminationStatus
            ]];
            if (strongSelf.applicationIsTerminating) return;
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(GewuInsightServerRecoveryDelay * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
                [strongSelf recoverServerAfterUnexpectedExit];
            });
        });
    };

    NSError *error = nil;
    if (![task launchAndReturnError:&error]) {
        [self presentStartupFailure:[NSString stringWithFormat:@"Could not launch the local server helper: %@", error.localizedDescription]];
        return;
    }
    self.ownedServerTask = task;
}

- (void)beginServerReadinessPolling {
    if (self.serverReadinessPollActive) return;
    self.serverReadinessPollActive = YES;
    self.serverStartupDeadline = [NSDate dateWithTimeIntervalSinceNow:GewuInsightServerStartupTimeout];
    [self pollUntilReady];
}

- (void)pollUntilReady {
    if (!self.serverReadinessPollActive) return;
    [self checkServerWithCompletion:^(BOOL available) {
        if (!self.serverReadinessPollActive) return;
        if (available) {
            self.serverReadinessPollActive = NO;
            self.serverStartupDeadline = nil;
            self.serverRestartAttempts = 0;
            [self loadApp];
            return;
        }
        if (self.serverStartupDeadline &&
            [[NSDate date] compare:self.serverStartupDeadline] != NSOrderedAscending) {
            self.serverReadinessPollActive = NO;
            self.serverStartupDeadline = nil;
            [self presentStartupFailure:nil];
            return;
        }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(GewuInsightServerPollInterval * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            [self pollUntilReady];
        });
    }];
}

- (void)recoverServerAfterUnexpectedExit {
    if (self.applicationIsTerminating) return;
    [self checkServerWithCompletion:^(BOOL available) {
        if (self.applicationIsTerminating) return;
        if (available) {
            self.serverRestartAttempts = 0;
            return;
        }
        if (self.mainAppHasLoaded && !self.startupView) [self showLoadingPage];
        if ([self restartServerForCurrentOutageIfPossible]) {
            [self beginServerReadinessPolling];
        }
    }];
}

- (BOOL)restartServerForCurrentOutageIfPossible {
    if (self.applicationIsTerminating) return NO;
    if (self.ownedServerTask.isRunning) return YES;
    if (self.serverRestartAttempts >= GewuInsightServerMaxRestartAttempts) {
        self.serverReadinessPollActive = NO;
        self.serverStartupDeadline = nil;
        [self presentStartupFailure:@"The local UI server stopped and could not be restarted automatically. Check the launcher log for details."];
        return NO;
    }
    self.serverRestartAttempts += 1;
    [self appendLauncherLogMessage:[NSString stringWithFormat:
        @"Native launcher is restarting the server (attempt %ld of %ld).",
        (long)self.serverRestartAttempts,
        (long)GewuInsightServerMaxRestartAttempts
    ]];
    [self startServerIfNeeded];
    return YES;
}

- (void)checkServerWithCompletion:(void (^)(BOOL available))completion {
    NSURL *healthURL = [self.url URLByAppendingPathComponent:@"api/health"];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:healthURL];
    request.timeoutInterval = 0.7;
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSHTTPURLResponse *httpResponse = [response isKindOfClass:[NSHTTPURLResponse class]] ? (NSHTTPURLResponse *)response : nil;
        BOOL available = (error == nil && httpResponse.statusCode == 200 && data.length > 0);
        dispatch_async(dispatch_get_main_queue(), ^{
            completion(available);
        });
    }] resume];
}

- (NSMutableURLRequest *)workspaceRequestForURL:(NSURL *)url {
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    BOOL local = [url.scheme isEqualToString:self.url.scheme] &&
        [url.host isEqualToString:self.url.host] && [url.port isEqual:self.url.port];
    if (local) {
        NSString *dataRoot = NSProcessInfo.processInfo.environment[@"GEWU_DATA_ROOT"];
        NSURL *folder = dataRoot.length ? [NSURL fileURLWithPath:dataRoot isDirectory:YES] :
            [[[NSBundle mainBundle].bundleURL URLByDeletingLastPathComponent] URLByAppendingPathComponent:@"data" isDirectory:YES];
        NSString *token = [NSString stringWithContentsOfURL:[folder URLByAppendingPathComponent:@".gewu-workspace-token"]
                                                   encoding:NSUTF8StringEncoding error:nil];
        token = [token stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        if (token.length == 64) [request setValue:token forHTTPHeaderField:@"X-Gewu-Workspace"];
    }
    return request;
}

- (void)loadApp {
    [self.browserController invalidate];
    self.browserController = nil;
    self.mainAppHasLoaded = YES;
    [self dismissStartupFailureAlert];
    [self.webView loadRequest:[self workspaceRequestForURL:self.url]];
    [self refreshLibraryNamingRuleMenu];
}

- (void)useTitleNamingRule:(id)sender {
    [self setLibraryNamingRule:@"title"];
}

- (void)useCitationNamingRule:(id)sender {
    [self setLibraryNamingRule:@"citation"];
}

- (void)openCitationSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openCitationSettings && window.openCitationSettings()" completionHandler:nil];
}

- (void)openArxivSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openArxivSettings && window.openArxivSettings()" completionHandler:nil];
}

- (void)openFieldSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openFieldSettings && window.openFieldSettings()" completionHandler:nil];
}

- (void)openPdfRenameSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openPdfRenameSettings && window.openPdfRenameSettings()" completionHandler:nil];
}

- (void)openQuickLookSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openQuickLookSettings && window.openQuickLookSettings()" completionHandler:nil];
}

- (void)openFontSizeSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openFontSizeSettings && window.openFontSizeSettings()" completionHandler:nil];
}

- (void)openAIAccessSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openAIAccessSettings && window.openAIAccessSettings()" completionHandler:nil];
}

- (void)openLibraryDestinationSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openLibraryDestinationSettings && window.openLibraryDestinationSettings()" completionHandler:nil];
}

- (void)openWebsiteLinkSettings:(id)sender {
    [self.webView evaluateJavaScript:@"window.openWebsiteLinkSettings && window.openWebsiteLinkSettings()" completionHandler:nil];
}

- (void)openLibraryLoader:(id)sender {
    [self showLibraryLoaderWindow];
}

- (void)openMetadataRefresh:(id)sender {
    [self.webView evaluateJavaScript:@"window.openMetadataRefreshWindow && window.openMetadataRefreshWindow()" completionHandler:nil];
}

- (void)openIdentifierRecovery:(id)sender {
    [self.webView evaluateJavaScript:@"window.openIdentifierRecoveryWindow && window.openIdentifierRecoveryWindow()" completionHandler:nil];
}

- (void)setNativeLibraryViewMenuState:(NSString *)viewMode {
    BOOL table = [viewMode isEqualToString:@"table"];
    self.listViewItem.state = table ? NSControlStateValueOff : NSControlStateValueOn;
    self.tableViewItem.state = table ? NSControlStateValueOn : NSControlStateValueOff;
}

- (void)useListLibraryView:(id)sender {
    [self setNativeLibraryViewMenuState:@"list"];
    [self.webView evaluateJavaScript:@"window.setLibraryContentView && window.setLibraryContentView('list')" completionHandler:nil];
}

- (void)useTableLibraryView:(id)sender {
    [self setNativeLibraryViewMenuState:@"table"];
    [self.webView evaluateJavaScript:@"window.setLibraryContentView && window.setLibraryContentView('table')" completionHandler:nil];
}

- (void)toggleLibraryContentView:(id)sender {
    [self.webView evaluateJavaScript:@"window.toggleLibraryContentView && window.toggleLibraryContentView()" completionHandler:^(id result, NSError *error) {
        if ([result isKindOfClass:[NSString class]]) {
            [self setNativeLibraryViewMenuState:(NSString *)result];
        }
    }];
}

- (NSURL *)userGuideURL {
    return [self.url URLByAppendingPathComponent:@"user-guide"];
}

- (void)openUserGuide:(id)sender {
    [self showUserGuideWindow];
}

- (void)openAbout:(id)sender {
    [self showAboutWindow];
}

- (NSTextField *)aboutLabelWithString:(NSString *)value
                                 font:(NSFont *)font
                                frame:(NSRect)frame
                                color:(NSColor *)color {
    NSTextField *label = [NSTextField labelWithString:value ?: @""];
    label.frame = frame;
    label.font = font;
    label.textColor = color ?: NSColor.labelColor;
    label.alignment = NSTextAlignmentCenter;
    label.lineBreakMode = NSLineBreakByWordWrapping;
    label.maximumNumberOfLines = 0;
    label.selectable = YES;
    return label;
}

- (NSButton *)aboutLinkButtonWithTitle:(NSString *)title
                                 frame:(NSRect)frame
                                action:(SEL)action {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:action];
    button.frame = frame;
    button.bordered = NO;
    button.font = [NSFont systemFontOfSize:12.5 weight:NSFontWeightMedium];
    button.contentTintColor = NSColor.linkColor;
    button.focusRingType = NSFocusRingTypeNone;
    return button;
}

- (void)openAboutProjectWebsite:(id)sender {
    NSURL *url = [NSURL URLWithString:@"https://github.com/LKong92/Gewu-Insight"];
    if (url) [[NSWorkspace sharedWorkspace] openURL:url];
}

- (void)contactUs:(id)sender {
    NSURLComponents *components = [NSURLComponents componentsWithString:@"mailto:info@gewu-insight.com"];
    components.queryItems = @[
        [NSURLQueryItem queryItemWithName:@"subject" value:@"Gewu Insight — Feedback and Support"]
    ];
    // Let Launch Services choose the user's default email application.
    if ([[NSWorkspace sharedWorkspace] openURL:components.URL]) return;
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Could not open your email app";
    alert.informativeText = @"Set a default email app on your Mac, or contact info@gewu-insight.com directly.";
    [alert addButtonWithTitle:@"OK"];
    [alert runModal];
}

- (void)showAboutWindow {
    if (!self.aboutWindow) {
        const CGFloat width = 336.0;
        const CGFloat height = 380.0;
        self.aboutWindow = [[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, width, height)
                      styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable)
                        backing:NSBackingStoreBuffered
                          defer:NO];
        self.aboutWindow.title = @"About Gewu Insight";
        self.aboutWindow.titleVisibility = NSWindowTitleVisible;
        self.aboutWindow.titlebarAppearsTransparent = NO;
        self.aboutWindow.releasedWhenClosed = NO;
        self.aboutWindow.movableByWindowBackground = YES;
        self.aboutWindow.backgroundColor = NSColor.windowBackgroundColor;

        NSView *content = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, width, height)];
        self.aboutWindow.contentView = content;

        NSImageView *iconView = [[NSImageView alloc] initWithFrame:NSMakeRect(132, 288, 72, 72)];
        iconView.image = NSApp.applicationIconImage;
        iconView.imageScaling = NSImageScaleProportionallyUpOrDown;
        [content addSubview:iconView];

        [content addSubview:[self aboutLabelWithString:@"Gewu Insight"
                                                   font:[NSFont systemFontOfSize:23.5 weight:NSFontWeightSemibold]
                                                  frame:NSMakeRect(20, 251, 296, 30)
                                                  color:NSColor.labelColor]];
        NSURL *calligraphyURL = [[NSBundle mainBundle] URLForResource:@"GewuAboutCalligraphy" withExtension:@"png"];
        NSImage *calligraphyImage = calligraphyURL ? [[NSImage alloc] initWithContentsOfURL:calligraphyURL] : nil;
        if (calligraphyImage) {
            calligraphyImage.template = YES;
            NSImageView *calligraphyView = [[NSImageView alloc] initWithFrame:NSMakeRect(116, 222, 104, 22)];
            calligraphyView.image = calligraphyImage;
            calligraphyView.imageScaling = NSImageScaleProportionallyUpOrDown;
            calligraphyView.contentTintColor = NSColor.secondaryLabelColor;
            calligraphyView.accessibilityLabel = @"格物洞见";
            [content addSubview:calligraphyView];
        }

        NSBundle *bundle = NSBundle.mainBundle;
        NSString *version = [bundle objectForInfoDictionaryKey:@"CFBundleShortVersionString"] ?: @"";
        NSString *build = [bundle objectForInfoDictionaryKey:@"CFBundleVersion"] ?: @"";
        NSString *versionText = build.length
            ? [NSString stringWithFormat:@"Version %@ (Build %@)", version, build]
            : [NSString stringWithFormat:@"Version %@", version];
        [content addSubview:[self aboutLabelWithString:versionText
                                                   font:[NSFont systemFontOfSize:11.5]
                                                  frame:NSMakeRect(20, 200, 296, 16)
                                                  color:NSColor.tertiaryLabelColor]];

        NSTextField *taglineLabel = [self aboutLabelWithString:@"Your personal research workspace where papers,\nevidence, and files stay connected over time."
                                                           font:[NSFont systemFontOfSize:12.0]
                                                          frame:NSMakeRect(16, 152, 304, 36)
                                                          color:NSColor.labelColor];
        taglineLabel.maximumNumberOfLines = 2;
        taglineLabel.selectable = NO;
        [content addSubview:taglineLabel];

        NSButton *guideButton = [self aboutLinkButtonWithTitle:@"User Guide"
                                                        frame:NSMakeRect(83, 124, 82, 22)
                                                       action:@selector(openUserGuide:)];
        [content addSubview:guideButton];
        [content addSubview:[self aboutLabelWithString:@"·"
                                                   font:[NSFont systemFontOfSize:12]
                                                  frame:NSMakeRect(162, 125, 12, 20)
                                                  color:NSColor.tertiaryLabelColor]];
        NSButton *githubButton = [self aboutLinkButtonWithTitle:@"GitHub"
                                                         frame:NSMakeRect(171, 124, 82, 22)
                                                        action:@selector(openAboutProjectWebsite:)];
        [content addSubview:githubButton];

        [content addSubview:[self aboutLabelWithString:@"Designed and developed by Lingyuan Kong and Zhengran Wu,\nwith coding assistance from OpenAI Codex."
                                                   font:[NSFont systemFontOfSize:9.5]
                                                  frame:NSMakeRect(18, 88, 300, 25)
                                                  color:NSColor.secondaryLabelColor]];
        NSString *copyright = [bundle objectForInfoDictionaryKey:@"NSHumanReadableCopyright"]
            ?: @"Copyright © 2026 Lingyuan Kong and Zhengran Wu. All rights reserved.";
        NSString *copyrightDisplay = [copyright stringByReplacingOccurrencesOfString:@". All rights reserved."
                                                                          withString:@".\nAll Rights Reserved."];
        [content addSubview:[self aboutLabelWithString:copyrightDisplay
                                                   font:[NSFont systemFontOfSize:9]
                                                  frame:NSMakeRect(14, 52, 308, 25)
                                                  color:NSColor.tertiaryLabelColor]];
        NSTextField *licenseLabel = [self aboutLabelWithString:@"Source-available research software.\nAcademic/non-commercial research use permitted.\nCommercial use requires written authorization."
                                                         font:[NSFont systemFontOfSize:9]
                                                        frame:NSMakeRect(14, 9, 308, 35)
                                                        color:NSColor.secondaryLabelColor];
        licenseLabel.maximumNumberOfLines = 3;
        [content addSubview:licenseLabel];
        [self.aboutWindow center];
    }
    [self.aboutWindow makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (void)openUserGuidePDF {
    NSURL *pdfURL = [[NSBundle mainBundle] URLForResource:@"Gewu Insight User Guide" withExtension:@"pdf"];
    if (!pdfURL) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"User Guide PDF is unavailable";
        alert.informativeText = @"Rebuild or reinstall Gewu Insight with the complete application resources.";
        [alert addButtonWithTitle:@"OK"];
        [alert runModal];
        return;
    }
    NSURL *previewURL = [NSURL fileURLWithPath:@"/System/Applications/Preview.app"];
    NSWorkspaceOpenConfiguration *configuration = [NSWorkspaceOpenConfiguration configuration];
    [[NSWorkspace sharedWorkspace] openURLs:@[pdfURL]
                       withApplicationAtURL:previewURL
                              configuration:configuration
                          completionHandler:^(NSRunningApplication *application, NSError *error) {
        if (error) {
            [[NSWorkspace sharedWorkspace] openURL:pdfURL];
        }
    }];
}

- (void)showUserGuideWindow {
    if (!self.userGuideWindow) {
        WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
        WKUserContentController *userContentController = [[WKUserContentController alloc] init];
        [userContentController addScriptMessageHandler:self name:@"openUserGuidePDF"];
        configuration.userContentController = userContentController;
        self.userGuideWebView = [[WKWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
        self.userGuideWebView.UIDelegate = self;

        self.userGuideWindow = [[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, 980, 760)
                      styleMask:(NSWindowStyleMaskTitled |
                                 NSWindowStyleMaskClosable |
                                 NSWindowStyleMaskMiniaturizable |
                                 NSWindowStyleMaskResizable)
                        backing:NSBackingStoreBuffered
                          defer:NO];
        self.userGuideWindow.title = @"Gewu Insight User Guide";
        self.userGuideWindow.delegate = self;
        self.userGuideWindow.minSize = NSMakeSize(760, 560);
        self.userGuideWindow.contentView = self.userGuideWebView;
        [self.userGuideWindow center];
    }
    [self.userGuideWebView loadRequest:[self workspaceRequestForURL:[self userGuideURL]]];
    [self.userGuideWindow makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (NSURL *)loaderURL {
    NSURLComponents *components = [NSURLComponents componentsWithURL:self.url resolvingAgainstBaseURL:NO];
    components.queryItems = @[[[NSURLQueryItem alloc] initWithName:@"standalone" value:@"loader"]];
    return components.URL ?: self.url;
}

- (void)showLoaderPaperInLibrary:(NSDictionary *)payload {
    NSString *paperId = [payload[@"paper_id"] isKindOfClass:NSString.class] ? payload[@"paper_id"] : @"";
    NSNumber *itemId = [payload[@"library_item_id"] isKindOfClass:NSNumber.class] ? payload[@"library_item_id"] : @0;
    if (!paperId.length) return;
    // Arguments are passed as values, never interpolated into JavaScript.
    [self.webView callAsyncJavaScript:
        @"try { await window.revealLoaderPaper(paperId, itemId); return ''; } catch (error) { return error.message || 'Could not show paper in Library.'; }"
        arguments:@{@"paperId": paperId, @"itemId": itemId}
        inFrame:nil inContentWorld:WKContentWorld.pageWorld
        completionHandler:^(id result, NSError *error) {
            NSString *message = error ? @"Could not show paper in Library. Please try again."
                : ([result isKindOfClass:NSString.class] ? result : @"");
            if (!message.length) {
                [self.loaderWindow orderOut:nil];
                [self.window makeKeyAndOrderFront:nil];
                [NSApp activateIgnoringOtherApps:YES];
            }
            [self.loaderWebView callAsyncJavaScript:@"window.finishLoaderPaperReveal(errorMessage);"
                arguments:@{@"errorMessage": message} inFrame:nil inContentWorld:WKContentWorld.pageWorld completionHandler:nil];
        }];
}

- (void)showLibraryLoaderWindow {
    if (!self.loaderWindow) {
        WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
        WKUserContentController *userContentController = [[WKUserContentController alloc] init];
        [userContentController addScriptMessageHandler:self name:@"libraryLoaderWindow"];
        configuration.userContentController = userContentController;

        self.loaderWebView = [[WKWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
        self.loaderWebView.UIDelegate = self;

        self.loaderWindow = [[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, 1220, 780)
                      styleMask:(NSWindowStyleMaskTitled |
                                 NSWindowStyleMaskClosable |
                                 NSWindowStyleMaskMiniaturizable |
                                 NSWindowStyleMaskResizable)
                        backing:NSBackingStoreBuffered
                          defer:NO];
        self.loaderWindow.title = @"Folder Loader";
        self.loaderWindow.delegate = self;
        self.loaderWindow.minSize = NSMakeSize(940, 620);
        self.loaderWindow.contentView = self.loaderWebView;
        [self.loaderWindow center];
    }
    [self.loaderWebView loadRequest:[self workspaceRequestForURL:[self loaderURL]]];
    [self.loaderWindow makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (void)updateLibraryNamingRuleMenu:(NSString *)rule {
    BOOL useTitle = [rule isEqualToString:@"title"];
    self.titleNamingItem.state = useTitle ? NSControlStateValueOn : NSControlStateValueOff;
    self.citationNamingItem.state = useTitle ? NSControlStateValueOff : NSControlStateValueOn;
}

- (void)setLibraryNamingRule:(NSString *)rule {
    [self updateLibraryNamingRuleMenu:rule];
    NSURL *endpoint = [self.url URLByAppendingPathComponent:@"api/settings/library-naming"];
    NSMutableURLRequest *request = [self workspaceRequestForURL:endpoint];
    request.HTTPMethod = @"POST";
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    request.HTTPBody = [[NSString stringWithFormat:@"{\"rule\":\"%@\"}", rule] dataUsingEncoding:NSUTF8StringEncoding];
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        if (error) {
            return;
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            [self updateLibraryNamingRuleMenu:rule];
        });
    }] resume];
}

- (void)refreshLibraryNamingRuleMenu {
    NSURL *endpoint = [self.url URLByAppendingPathComponent:@"api/settings/library-naming"];
    NSURLRequest *request = [self workspaceRequestForURL:endpoint];
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        if (error || !data) {
            return;
        }
        NSDictionary *payload = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        NSString *rule = [payload isKindOfClass:[NSDictionary class]] ? payload[@"rule"] : nil;
        if (![rule isKindOfClass:[NSString class]]) {
            return;
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            [self updateLibraryNamingRuleMenu:rule];
        });
    }] resume];
}

- (void)clearWebCache:(id)sender {
    NSURL *endpoint = [self.url URLByAppendingPathComponent:@"api/cache/clear-web"];
    NSMutableURLRequest *request = [self workspaceRequestForURL:endpoint];
    request.HTTPMethod = @"POST";
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    request.HTTPBody = [@"{}" dataUsingEncoding:NSUTF8StringEncoding];
    [[[NSURLSession sharedSession] dataTaskWithRequest:request
                                    completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSString *message = @"Could not clear the monitor cache.";
        if (!error && data) {
            NSDictionary *payload = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
            if ([payload isKindOfClass:[NSDictionary class]]) {
                long long removed = [payload[@"removed_bytes"] longLongValue];
                NSInteger files = [payload[@"removed_files"] integerValue];
                message = [NSString stringWithFormat:@"Removed %@ from %ld cache files.", [self humanSize:removed], (long)files];
            }
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            NSAlert *alert = [[NSAlert alloc] init];
            alert.messageText = @"Monitor cache cleared";
            alert.informativeText = message;
            alert.alertStyle = error ? NSAlertStyleWarning : NSAlertStyleInformational;
            [alert addButtonWithTitle:@"OK"];
            [alert beginSheetModalForWindow:self.window completionHandler:nil];
        });
    }] resume];
}

- (NSString *)humanSize:(long long)bytes {
    double value = (double)bytes;
    NSArray<NSString *> *units = @[@"B", @"KB", @"MB", @"GB", @"TB"];
    NSInteger index = 0;
    while (value >= 1024.0 && index < (NSInteger)units.count - 1) {
        value /= 1024.0;
        index += 1;
    }
    if (index == 0) {
        return [NSString stringWithFormat:@"%lld %@", bytes, units[index]];
    }
    return [NSString stringWithFormat:@"%.1f %@", value, units[index]];
}

- (void)presentStartupFailure:(NSString *)message {
    if (self.applicationIsTerminating || self.startupFailurePresented) return;
    self.startupFailurePresented = YES;
    NSString *projectDir = [[[NSBundle mainBundle] bundleURL].URLByDeletingLastPathComponent path];
    NSString *logPath = [projectDir stringByAppendingPathComponent:@"logs/paper_monitor_launcher.log"];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Gewu Insight could not start";
    alert.informativeText = message ?: [NSString stringWithFormat:@"The local UI server did not become ready. Check the launcher log for details:\n\n%@", logPath];
    alert.alertStyle = NSAlertStyleWarning;
    [alert addButtonWithTitle:@"OK"];
    self.startupFailureAlert = alert;
    __weak typeof(self) weakSelf = self;
    [alert beginSheetModalForWindow:self.window completionHandler:^(__unused NSModalResponse response) {
        PaperMonitorDelegate *strongSelf = weakSelf;
        if (!strongSelf || strongSelf.startupFailureAlert != alert) return;
        strongSelf.startupFailureAlert = nil;
        strongSelf.startupFailurePresented = NO;
    }];
    [self recheckServerWhileStartupFailureIsVisible];
}

- (void)dismissStartupFailureAlert {
    NSAlert *alert = self.startupFailureAlert;
    self.startupFailureAlert = nil;
    self.startupFailurePresented = NO;
    if (!alert) return;
    if (alert.window.sheetParent) {
        [alert.window.sheetParent endSheet:alert.window];
    } else {
        [alert.window close];
    }
}

- (void)recheckServerWhileStartupFailureIsVisible {
    if (self.workspaceRecoveryAttempts > 3) return;
    if (!self.startupFailureAlert || self.applicationIsTerminating) return;
    [self checkServerWithCompletion:^(BOOL available) {
        if (!self.startupFailureAlert || self.applicationIsTerminating) return;
        if (available) {
            [self appendLauncherLogMessage:@"Native launcher dismissed a stale startup failure after server recovery."];
            self.serverRestartAttempts = 0;
            [self loadApp];
            return;
        }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.0 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            [self recheckServerWhileStartupFailureIsVisible];
        });
    }];
}

- (void)appendLauncherLogMessage:(NSString *)message {
    if (message.length == 0) return;
    NSString *projectDir = [[[NSBundle mainBundle] bundleURL].URLByDeletingLastPathComponent path];
    NSString *logPath = [projectDir stringByAppendingPathComponent:@"logs/paper_monitor_launcher.log"];
    NSFileHandle *handle = [NSFileHandle fileHandleForWritingAtPath:logPath];
    if (!handle) return;
    NSString *line = [NSString stringWithFormat:@"[%@] %@\n", [NSDate date], message];
    @try {
        [handle seekToEndOfFile];
        [handle writeData:[line dataUsingEncoding:NSUTF8StringEncoding]];
        [handle closeFile];
    } @catch (__unused NSException *exception) {
        @try { [handle closeFile]; } @catch (__unused NSException *closeException) {}
    }
}

- (void)openWorkspaceWebsiteRequest:(WKNavigationAction *)action {
    if (!GewuWorkspaceWebsiteRequest(action.request, action.sourceFrame.request.URL,
                                    action.sourceFrame.isMainFrame, self.url)) return;
    NSData *data = [NSJSONSerialization dataWithJSONObject:@[action.request.URL.absoluteString] options:0 error:nil];
    if (!data) return;
    NSString *argument = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    NSString *script = [NSString stringWithFormat:@"window.openWebsite && window.openWebsite((%@)[0])", argument];
    [self.webView evaluateJavaScript:script completionHandler:nil];
}

- (void)webView:(WKWebView *)webView
decidePolicyForNavigationAction:(WKNavigationAction *)action
decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    NSURL *url = action.request.URL;
    if (webView == self.webView && action.targetFrame.isMainFrame
        && GewuWorkspaceSameOrigin(url, self.url)
        && [@[@"", @"/", @"/user-guide"] containsObject:url.path ?: @""]
        && [(action.request.HTTPMethod ?: @"GET") isEqualToString:@"GET"]
        && !action.request.HTTPBody && !action.request.HTTPBodyStream
        && ![action.request valueForHTTPHeaderField:@"Authorization"].length) {
        NSMutableURLRequest *authenticated = [self workspaceRequestForURL:url];
        NSString *credential = [authenticated valueForHTTPHeaderField:@"X-Gewu-Workspace"];
        if (credential.length && ![[action.request valueForHTTPHeaderField:@"X-Gewu-Workspace"] isEqualToString:credential]) {
            // Cookies can disappear with a WebKit process. Reattach only to
            // the local top-level UI, never to frames, publishers or APIs.
            decisionHandler(WKNavigationActionPolicyCancel);
            [webView loadRequest:authenticated];
            return;
        }
    }
    BOOL webURL = [@[@"http", @"https"] containsObject:url.scheme.lowercaseString];
    if (webView == self.webView && webURL && !GewuWorkspaceSameOrigin(url, self.url)
        && (!action.targetFrame || action.targetFrame.isMainFrame)) {
        // Never navigate the privileged workspace into a remote document.
        // Only body-free GET destinations are forwarded; forms are not replayed.
        decisionHandler(WKNavigationActionPolicyCancel);
        [self openWorkspaceWebsiteRequest:action];
        return;
    }
    // Local downloads/Preview and the independent publisher download webview
    // retain their existing policies. This is not a subresource interceptor.
    decisionHandler(WKNavigationActionPolicyAllow);
}

- (WKWebView *)webView:(WKWebView *)webView
createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration
   forNavigationAction:(WKNavigationAction *)navigationAction
        windowFeatures:(WKWindowFeatures *)windowFeatures {
    if (webView == self.webView) {
        [self openWorkspaceWebsiteRequest:navigationAction];
        // Browser constructs an isolated configuration via its normal command
        // path, never the workspace configuration supplied to this delegate.
        return nil;
    }
    if (!navigationAction.targetFrame.isMainFrame && navigationAction.request.URL) {
        [[NSWorkspace sharedWorkspace] openURL:navigationAction.request.URL];
    }
    return nil;
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        // A short-lived native file operation; never create a window or server.
        // NSURL keeps the final symlink intact, including a dangling symlink.
        if (argc == 3 && strcmp(argv[1], "--trash-item") == 0) {
            NSURL *source = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[2]]];
            NSURL *destination = nil;
            NSError *error = nil;
            BOOL moved = [[NSFileManager defaultManager] trashItemAtURL:source
                resultingItemURL:&destination error:&error];
            if (!moved || !destination) {
                fprintf(stderr, "%s\n", error.localizedDescription.UTF8String ?: "macOS did not return the Trash location.");
                return 1;
            }
            printf("%s\n", destination.path.UTF8String);
            return 0;
        }
        NSApplication *application = [NSApplication sharedApplication];
        PaperMonitorDelegate *delegate = [[PaperMonitorDelegate alloc] init];
        application.delegate = delegate;
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        [application run];
    }
    return 0;
}
