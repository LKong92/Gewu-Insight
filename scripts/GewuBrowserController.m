#import "GewuBrowserController.h"
#import "GewuBrowserNavigation.h"
#import "GewuBrowserFavicons.h"
#import "GewuBrowserSession.h"
#import "GewuBrowserAutoFill.h"
#import "GewuBrowserCapture.h"
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <CommonCrypto/CommonDigest.h>

// Right-clicking an editable document must keep AppKit's insertion target in
// this WebView, not the separate workspace/address-bar WebView. Leave all text
// handling to WebKit; never intercept credential values or the system picker.
@interface GewuBrowserWebView : WKWebView
@property(nonatomic, weak) GewuBrowserAutoFill *loginTrigger;
@end
@implementation GewuBrowserWebView
- (void)willOpenMenu:(NSMenu *)menu withEvent:(NSEvent *)event {
    if (self.window && !self.hidden) [self.window makeFirstResponder:self];
    [super willOpenMenu:menu withEvent:event];
    // Retain WebKit's own target/action and link request; only describe where
    // our UI delegate will place the new page. Never inspect editable fields.
    for (NSMenuItem *item in menu.itemArray) {
        if (item.tag == WebMenuItemTagOpenLinkInNewWindow && !item.hasSubmenu
            && [@[@"Open Link in New Window", @"在新窗口中打开链接", @"在新視窗中打開連結"] containsObject:item.title])
            item.title = @"Open Link in New Tab";
    }
    [self.loginTrigger nativeMenuWillOpen:menu inView:self event:event];
}
@end

@interface GewuAddressSuggestionButton : NSButton
@end
@implementation GewuAddressSuggestionButton
- (BOOL)acceptsFirstResponder { return NO; }
@end

@interface GewuBrowserPage : NSObject
@property(nonatomic, strong) WKWebView *view;
@property(nonatomic) BOOL reloadNavigation;
@property(nonatomic) BOOL navigationRequestedDownload;
@property(nonatomic) BOOL pendingRequestedDownload;
@property(nonatomic) BOOL attemptedHTTPSRecovery;
@property(nonatomic, copy) NSURLRequest *mainNavigationRequest;
@property(nonatomic, strong) NSURL *failedURL;
@property(nonatomic, copy) NSString *visitID;
@property(nonatomic, copy) NSString *captureDocumentID;
@property(nonatomic, copy) NSString *documentMIME;
@property(nonatomic) BOOL ready;
@property(nonatomic) BOOL terminated;
@property(nonatomic) BOOL historyTraversal;
@property(nonatomic) BOOL allowsInitialBlank;
@property(nonatomic, copy) NSString *errorMessage;
@property(nonatomic, strong) NSURL *blobRequestURL;
@property(nonatomic, strong) NSURL *blobSourceURL;
@property(nonatomic) BOOL downloadTransitionPending;
@property(nonatomic) BOOL openingPDF;
@property(nonatomic) double pdfProgress;
@property(nonatomic, strong) NSMutableDictionary *pendingPDFDocument;
@property(nonatomic, strong) WKNavigation *pdfNavigation;
@property(nonatomic, strong) NSMapTable<id, NSDictionary *> *pdfDocuments;
@property(nonatomic, strong) GewuBrowserPDFFile *capturedPDF;
@property(nonatomic, copy) NSString *capturedPDFURL;
@property(nonatomic, strong) NSDate *capturedPDFDate;
@property(nonatomic) BOOL exportingPDF;
@property(nonatomic, strong) NSDictionary *capturedPDFFrame;
@end
@implementation GewuBrowserPage
@end

@interface GewuBrowserTab : NSObject
@property(nonatomic, copy) NSString *identifier;
@property(nonatomic, copy) NSString *originPaperID;
@property(nonatomic, copy) NSString *originURL;
@property(nonatomic) NSInteger originLibraryItemID;
@property(nonatomic, copy) NSString *workspaceReturnID;
@property(nonatomic, strong) GewuBrowserPage *homePage;
@property(nonatomic, strong) GewuBrowserPage *contentPage;
@property(nonatomic, strong) GewuBrowserPage *currentPage;
@property(nonatomic, strong) GewuBrowserSession *session;
// Logical navigation may use the retained content view while Home is still
// presented. Never reveal that view's previous document during a new request.
@property(nonatomic) BOOL contentPendingFromHome;
@property(nonatomic, strong) WKNavigation *pendingHomeNavigation;
@end
@implementation GewuBrowserTab
- (instancetype)init {
    if ((self = [super init])) {
        _identifier = NSUUID.UUID.UUIDString;
        _session = [[GewuBrowserSession alloc] init];
    }
    return self;
}
@end

@interface GewuBrowserController ()
@property(nonatomic, strong, readwrite) WKWebView *webView;
@property(nonatomic, strong) GewuBrowserPage *currentPage;
@property(nonatomic, strong) GewuBrowserPage *homePage;
@property(nonatomic, strong) GewuBrowserPage *contentPage;
@property(nonatomic, strong) GewuBrowserSession *session;
@property(nonatomic, strong) NSMutableArray<GewuBrowserTab *> *tabs;
@property(nonatomic, strong) GewuBrowserTab *selectedTab;
@property(nonatomic) BOOL active;
@property(nonatomic) BOOL visible;
@property(nonatomic) BOOL canReturnToWorkspace;
@property(nonatomic) BOOL sidebarVisible;
@property(nonatomic) NSUInteger navigationInputGeneration;
@property(nonatomic) NSTimeInterval lastNavigationArrowTime;
@property(nonatomic) unsigned short lastNavigationArrowKey;
@property(nonatomic) BOOL navigationProbePending;
@property(nonatomic, copy) NSString *navigationProbe;
@property(nonatomic) BOOL initializing;
@property(nonatomic) BOOL invalidated;
@property(nonatomic, strong) id keyMonitor;
@property(nonatomic, strong) NSMapTable<WKDownload *, NSMutableDictionary *> *downloads;
@property(nonatomic, strong) GewuBrowserFavicons *favicons;
@property(nonatomic, strong) NSView *suggestionsView;
@property(nonatomic, copy) NSArray<NSDictionary *> *suggestionItems;
@property(nonatomic, strong) GewuBrowserAutoFill *loginTrigger;
@property(nonatomic, strong) NSMutableDictionary *captureSnapshots;
@property(nonatomic, strong) NSMutableDictionary<NSString *, GewuBrowserCapture *> *captures;
@property(nonatomic, copy) NSString *captureBackdropRequestID;
@end

@implementation GewuBrowserController

- (void)ensureTabModel {
    if (!self.tabs) self.tabs = [NSMutableArray array];
    if (!self.selectedTab) {
        self.selectedTab = [[GewuBrowserTab alloc] init];
        [self.tabs addObject:self.selectedTab];
    }
}
- (GewuBrowserPage *)currentPage { return self.selectedTab.currentPage; }
- (void)setCurrentPage:(GewuBrowserPage *)page { [self ensureTabModel]; self.selectedTab.currentPage = page; }
- (GewuBrowserPage *)homePage { return self.selectedTab.homePage; }
- (void)setHomePage:(GewuBrowserPage *)page { [self ensureTabModel]; self.selectedTab.homePage = page; }
- (GewuBrowserPage *)contentPage { return self.selectedTab.contentPage; }
- (void)setContentPage:(GewuBrowserPage *)page { [self ensureTabModel]; self.selectedTab.contentPage = page; }
- (GewuBrowserSession *)session { return self.selectedTab.session; }
- (void)setSession:(GewuBrowserSession *)session { [self ensureTabModel]; self.selectedTab.session = session; }

- (GewuBrowserTab *)tabForPage:(GewuBrowserPage *)page {
    if (!page) return nil;
    for (GewuBrowserTab *tab in self.tabs) if (tab.homePage == page || tab.contentPage == page) return tab;
    return nil;
}
- (GewuBrowserPage *)pageForView:(WKWebView *)view {
    if (!view) return nil;
    for (GewuBrowserTab *tab in self.tabs) {
        if (tab.homePage.view == view) return tab.homePage;
        if (tab.contentPage.view == view) return tab.contentPage;
    }
    return nil;
}
- (GewuBrowserPage *)presentedPageForTab:(GewuBrowserTab *)tab {
    return tab.contentPendingFromHome ? tab.homePage : tab.currentPage;
}
- (void)updatePageVisibility {
    GewuBrowserPage *presented = [self presentedPageForTab:self.selectedTab];
    // Favorites is drawn by the trusted workspace, never by a remote webpage.
    self.homePage.view.hidden = YES;
    self.contentPage.view.hidden = !self.visible || presented != self.contentPage;
}
- (void)returnToRetainedHomeInTab:(GewuBrowserTab *)tab {
    if (!tab.contentPendingFromHome) return;
    tab.contentPendingFromHome = NO; tab.pendingHomeNavigation = nil;
    tab.currentPage = tab.homePage;
    tab.contentPage.view.hidden = YES;
    if (tab == self.selectedTab) {
        self.webView = tab.homePage.view;
        [self updatePageVisibility]; [self emitState];
    } else [self emitTabs];
}
- (void)emitTabs {
    NSMutableArray *items = [NSMutableArray array];
    for (GewuBrowserTab *tab in self.tabs) {
        GewuBrowserPage *page = tab.currentPage;
        GewuBrowserPage *presented = [self presentedPageForTab:tab];
        BOOL home = presented == tab.homePage;
        NSString *url = home ? @"" : (page.failedURL ?: page.view.URL ?: page.mainNavigationRequest.URL).absoluteString ?: @"";
        NSString *title = home ? @"Favorites" : presented.view.title;
        if (!title.length) title = [NSURL URLWithString:url].host ?: @"New Tab";
        [items addObject:@{@"id":tab.identifier, @"title":title, @"url":url, @"home":@(home), @"loading":@(page.openingPDF || page.view.loading || (tab.contentPendingFromHome && !page.errorMessage.length))}];
    }
    [self emit:@{@"event":@"tabs", @"tabs":items, @"selected":self.selectedTab.identifier ?: @""}];
}
- (void)selectTab:(GewuBrowserTab *)tab {
    if (!tab || ![self.tabs containsObject:tab] || tab == self.selectedTab) return;
    self.navigationInputGeneration++;
    [self.loginTrigger cancelPending];
    NSRect previousFrame = [self presentedPageForTab:self.selectedTab].view.frame;
    // Tab switches do not stop loads, replay requests, or replace documents.
    self.homePage.view.hidden = YES; self.contentPage.view.hidden = YES;
    self.suggestionsView.hidden = YES;
    self.selectedTab = tab;
    self.webView = tab.currentPage.view;
    if (NSIsEmptyRect(self.webView.frame)) self.webView.frame = previousFrame;
    [self updatePageVisibility];
    [self.workspace.window makeFirstResponder:self.workspace];
    [self emitState];
}
- (GewuBrowserTab *)addTabWithRequest:(NSURLRequest *)request configuration:(WKWebViewConfiguration *)configuration {
    if (self.tabs.count >= 32) {
        [self emit:@{@"event":@"error", @"message":@"Close a tab before opening another (32 tabs maximum). Existing pages are kept."}];
        return nil;
    }
    GewuBrowserTab *tab = [[GewuBrowserTab alloc] init];
    GewuBrowserPage *page = configuration ? [self makePageWithConfiguration:configuration] : [self makePage];
    if (!request && !configuration) tab.homePage = page;
    else tab.contentPage = page;
    tab.currentPage = page;
    page.allowsInitialBlank = configuration != nil;
    page.mainNavigationRequest = request;
    [self.tabs addObject:tab];
    [self selectTab:tab];
    if (!configuration) {
        if (request) [page.view loadRequest:request];
        else [self showHomeRecordingVisit:YES];
    }
    [self emitState];
    return tab;
}
- (void)disposePage:(GewuBrowserPage *)page {
    if (!page) return;
    [self cancelPDFDownloadsForPage:page];
    [page.pdfDocuments removeAllObjects]; page.pendingPDFDocument = nil;
    page.capturedPDF = nil; page.capturedPDFURL = nil; page.capturedPDFFrame = nil;
    for (NSString *key in @[@"URL", @"title", @"loading", @"estimatedProgress", @"canGoBack", @"canGoForward"])
        [page.view removeObserver:self forKeyPath:key];
    page.view.navigationDelegate = nil; page.view.UIDelegate = nil;
    [page.view stopLoading]; [page.view removeFromSuperview];
}
- (void)closeTab:(GewuBrowserTab *)tab {
    if (!tab || ![self.tabs containsObject:tab]) return;
    [self.loginTrigger cancelPending];
    NSInteger index = [self.tabs indexOfObject:tab];
    if (self.tabs.count == 1) [self addTabWithRequest:nil configuration:nil];
    if (tab == self.selectedTab) [self selectTab:self.tabs[index > 0 ? index - 1 : 1]];
    [self.tabs removeObject:tab];
    [self disposePage:tab.homePage]; [self disposePage:tab.contentPage];
    [tab.session.entries removeAllObjects];
    [self emitState];
}

- (instancetype)initWithWorkspace:(WKWebView *)workspace {
    self = [super init];
    if (self) {
        _workspace = workspace;
        NSString *navigationPath = [NSBundle.mainBundle pathForResource:@"GewuBrowserNavigationProbe" ofType:@"js"];
        _navigationProbe = navigationPath ? [NSString stringWithContentsOfFile:navigationPath encoding:NSUTF8StringEncoding error:nil] : @"";
        _downloads = [NSMapTable strongToStrongObjectsMapTable];
        [self ensureTabModel];
        __weak typeof(self) weakSelf = self;
        NSString *probePath = [NSBundle.mainBundle pathForResource:@"GewuBrowserLoginProbe" ofType:@"js"];
        NSString *probe = probePath ? [NSString stringWithContentsOfFile:probePath encoding:NSUTF8StringEncoding error:nil] : @"";
        _loginTrigger = [[GewuBrowserAutoFill alloc] initWithProbeScript:probe canUseView:^BOOL(WKWebView *view) {
            typeof(self) self = weakSelf;
            return self && !self.invalidated && self.active && self.visible && self.webView == view;
        }];
        _favicons = [[GewuBrowserFavicons alloc] init];
        _favicons.onIcon = ^(NSString *host, NSString *dataURL) {
            [weakSelf emit:@{@"event":@"favicon", @"host":host, @"data_url":dataURL}];
        };
        _keyMonitor = [NSEvent addLocalMonitorForEventsMatchingMask:(NSEventMaskKeyDown | NSEventMaskLeftMouseDown | NSEventMaskLeftMouseUp | NSEventMaskLeftMouseDragged | NSEventMaskRightMouseDown | NSEventMaskScrollWheel) handler:^NSEvent *(NSEvent *event) {
            GewuBrowserController *self = weakSelf;
            if (!self.active || event.window != self.workspace.window || self.workspace.window.attachedSheet) return event;
            // WebKit may redispatch the same unhandled arrow through AppKit.
            // That is one physical press, not intervening input. Remember only
            // its numeric identity, never event objects or typed characters.
            BOOL arrow = event.type == NSEventTypeKeyDown && (event.keyCode == 123 || event.keyCode == 126);
            BOOL redispatchedArrow = arrow && self.lastNavigationArrowTime == event.timestamp && self.lastNavigationArrowKey == event.keyCode;
            if (!redispatchedArrow) self.navigationInputGeneration++;
            if (arrow) { self.lastNavigationArrowTime = event.timestamp; self.lastNavigationArrowKey = event.keyCode; }
            if (event.type == NSEventTypeLeftMouseUp) { [self.loginTrigger considerMouseUp:event inView:self.webView]; return event; }
            [self.loginTrigger noteInputEvent:event];
            if (event.type == NSEventTypeScrollWheel || event.type == NSEventTypeLeftMouseDragged) return event;
            if (event.type != NSEventTypeKeyDown) {
                if (self.suggestionsView && !self.suggestionsView.hidden) {
                    NSPoint point = [self.suggestionsView convertPoint:event.locationInWindow fromView:nil];
                    if (!NSPointInRect(point, self.suggestionsView.bounds)) {
                        self.suggestionsView.hidden = YES;
                        [self emit:@{@"event":@"suggestions-dismissed"}];
                    }
                }
                return event;
            }
            if ([self handleWorkspaceReturnKeyEvent:event]) return nil;
            if (!redispatchedArrow) [self considerPageArrow:event];
            BOOL command = (event.modifierFlags & NSEventModifierFlagCommand) != 0;
            NSString *key = event.charactersIgnoringModifiers.lowercaseString;
            if (command && !(event.modifierFlags & (NSEventModifierFlagOption | NSEventModifierFlagControl))
                && [@[@"t", @"w"] containsObject:key]) {
                [self handleCommand:@{@"action":[key isEqualToString:@"t"] ? @"new-tab" : @"close-tab", @"tab_id":self.selectedTab.identifier}];
                return nil;
            }
            if (command && ([@[@"l", @"d"] containsObject:key])) {
                [self.workspace.window makeFirstResponder:self.workspace];
                [self emit:@{ @"event": [key isEqualToString:@"l"] ? @"focus-address" : @"bookmark" }];
                return nil;
            }
            if (command && [key isEqualToString:@"r"] && self.visible) { [self handleCommand:@{ @"action": @"reload" }]; return nil; }
            if (command && [key isEqualToString:@"f"] && self.visible) {
                [self.workspace.window makeFirstResponder:self.workspace];
                [self emit:@{ @"event": @"find" }]; return nil;
            }
            return event;
        }];
    }
    return self;
}

- (BOOL)handleWorkspaceReturnKeyEvent:(NSEvent *)event {
    // This shortcut belongs to the trusted workspace, even when the remote
    // WKWebView or the address field is first responder. Never traverse a web
    // page's history, replay its request, or let a sheet lose user input.
    if (event.type != NSEventTypeKeyDown || !self.active || !self.visible || !self.canReturnToWorkspace
        || !self.workspace.window || event.window != self.workspace.window || self.workspace.window.attachedSheet) return NO;
    NSEventModifierFlags flags = event.modifierFlags;
    // Input methods may expose a localized/full-width bracket instead of
    // ASCII. Keep the physical left-bracket key usable with Chinese input,
    // while also accepting '[' from layouts that put it on another key.
    BOOL leftBracket = [event.charactersIgnoringModifiers isEqualToString:@"["] || event.keyCode == 33;
    if (!(flags & NSEventModifierFlagCommand)
        || (flags & (NSEventModifierFlagShift | NSEventModifierFlagOption | NSEventModifierFlagControl))
        || !leftBracket) return NO;
    if (event.isARepeat) return YES;
    self.canReturnToWorkspace = NO;
    [self.workspace.window makeFirstResponder:self.workspace];
    [self emit:@{@"event":@"return-workspace"}];
    return YES;
}

- (void)considerPageArrow:(NSEvent *)event {
    // Let WebKit dispatch the original event. Only hand focus back after a
    // bounded, one-shot check; never consume/replay arrows or touch form values.
    BOOL up = event.keyCode == 126, left = event.keyCode == 123;
    WKWebView *view = [self presentedPageForTab:self.selectedTab].view;
    NSResponder *responder = self.workspace.window.firstResponder;
    if ((!up && !(left && self.sidebarVisible)) || !self.visible || self.navigationProbePending || !self.navigationProbe.length
        || event.modifierFlags & (NSEventModifierFlagCommand | NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagShift)
        || !view || view == self.homePage.view || ![responder isKindOfClass:NSView.class] || ![(NSView *)responder isDescendantOf:view]) return;
    self.navigationProbePending = YES;
    NSUInteger generation = self.navigationInputGeneration;
    NSString *tabID = self.selectedTab.identifier;
    NSURL *url = view.URL;
    __weak typeof(self) weakSelf = self;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 20 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
        typeof(self) self = weakSelf;
        if (!self) return;
        if (generation != self.navigationInputGeneration || self.invalidated) { self.navigationProbePending = NO; return; }
        NSString *script = [NSString stringWithFormat:@"(%@)(\"%@\")", self.navigationProbe, up ? @"up" : @"left"];
        [view evaluateJavaScript:script inFrame:nil inContentWorld:[WKContentWorld worldWithName:@"GewuBrowserNavigation"] completionHandler:^(id result, NSError *error) {
            typeof(self) self = weakSelf;
            self.navigationProbePending = NO;
            if (!self || error || ![result isKindOfClass:NSNumber.class] || ![result boolValue] || self.invalidated
                || generation != self.navigationInputGeneration || !self.active || !self.visible || self.workspace.window.attachedSheet
                || self.workspace.window.firstResponder != responder || ![self.selectedTab.identifier isEqualToString:tabID]
                || [self presentedPageForTab:self.selectedTab].view != view || ![view.URL isEqual:url] || (!up && !self.sidebarVisible)) return;
            [self.workspace.window makeFirstResponder:self.workspace];
            [self emit:@{@"event":@"focus-chrome", @"destination":up ? @"tabs" : @"sidebar"}];
        }];
    });
}

- (void)emit:(NSDictionary *)event {
    if (self.onEvent && !self.invalidated) self.onEvent(event);
}

- (void)emitState {
    if (!self.webView) return;
    BOOL pending = self.selectedTab.contentPendingFromHome;
    WKWebView *presented = [self presentedPageForTab:self.selectedTab].view;
    BOOL home = [self presentedPageForTab:self.selectedTab] == self.homePage;
    [self emit:@{ @"event": @"state", @"url": home ? @"" : (self.currentPage.failedURL ?: self.webView.URL).absoluteString ?: @"",
        @"home":@(home), @"title": home ? @"Favorites" : presented.title ?: @"", @"loading": @(self.currentPage.openingPDF || self.webView.loading || (pending && !self.currentPage.errorMessage.length)),
        @"progress": @(self.currentPage.openingPDF ? self.currentPage.pdfProgress : self.webView.estimatedProgress), @"canBack": @(self.session.index > 0),
        @"canForward": @(self.session.index + 1 < self.session.entries.count),
        @"tab_id":self.selectedTab.identifier ?: @"", @"workspace_return_id":self.selectedTab.workspaceReturnID ?: @"", @"openingPDF":@(self.currentPage.openingPDF), @"error":self.currentPage.errorMessage ?: @"" }];
    [self emitTabs];
}

+ (WKWebsiteDataStore *)externalWebsiteDataStore {
    // Keep the existing Browser profile, including before the first Browser tab.
    // Sharing stays inside WebKit; no cookies are exported to Python or Safari.
    static WKWebsiteDataStore *store;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        NSUUID *profile = [[NSUUID alloc] initWithUUIDString:@"19E88B78-44C0-4C42-B496-F2C7F625B507"];
        store = [WKWebsiteDataStore dataStoreForIdentifier:profile];
    });
    return store;
}

+ (WKWebViewConfiguration *)externalPageConfiguration {
    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    configuration.websiteDataStore = [self externalWebsiteDataStore];
    // Keep WebKit's system-generated OS/engine/version tokens. The compatibility
    // suffix prevents sites from mistaking desktop WKWebView for a text-only
    // client; retain our own product token rather than hiding the embedding app.
    configuration.applicationNameForUserAgent = @"Safari/605.1.15 GewuInsight/0.1";
    configuration.preferences.javaScriptCanOpenWindowsAutomatically = NO;
    configuration.userContentController = [[WKUserContentController alloc] init];
    return configuration;
}

- (GewuBrowserPage *)makePage {
    return [self makePageWithConfiguration:[GewuBrowserController externalPageConfiguration]];
}

- (GewuBrowserPage *)makePageWithConfiguration:(WKWebViewConfiguration *)configuration {
    // Popup configurations MUST be the exact WebKit-supplied configuration.
    // All openers are our isolated external views, never the trusted workspace.
    GewuBrowserPage *page = [[GewuBrowserPage alloc] init];
    page.view = [[GewuBrowserWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
    ((GewuBrowserWebView *)page.view).loginTrigger = self.loginTrigger;
    page.view.navigationDelegate = self;
    page.view.UIDelegate = self;
    page.view.allowsBackForwardNavigationGestures = YES;
    page.view.hidden = YES;
    page.view.accessibilityLabel = @"Browser webpage";
    for (NSString *key in @[@"URL", @"title", @"loading", @"estimatedProgress", @"canGoBack", @"canGoForward"]) {
        [page.view addObserver:self forKeyPath:key options:NSKeyValueObservingOptionNew context:NULL];
    }
    [self.workspace.superview addSubview:page.view positioned:NSWindowAbove relativeTo:self.workspace];
    return page;
}

- (void)ensureWebView {
    if (self.webView || self.initializing || self.invalidated) return;
    self.initializing = YES;
    [self ensureTabModel];
    self.homePage = [self makePage];
    self.currentPage = self.homePage;
    self.webView = self.homePage.view;
    self.initializing = NO;
    [self emit:@{ @"event": @"ready" }];
}

- (void)activatePage:(GewuBrowserPage *)page {
    if (page == self.currentPage && !self.selectedTab.contentPendingFromHome) return;
    [self.loginTrigger cancelPending];
    [self.webView stopLoading];
    self.homePage.view.hidden = YES; self.contentPage.view.hidden = YES;
    self.selectedTab.contentPendingFromHome = NO; self.selectedTab.pendingHomeNavigation = nil;
    self.suggestionsView.hidden = YES;
    NSRect previousFrame = self.webView.frame;
    self.currentPage = page;
    self.webView = page.view;
    // Retain surface geometry until local chrome sends the next layout.
    if (NSIsEmptyRect(self.webView.frame)) self.webView.frame = previousFrame;
    [self updatePageVisibility];
    [self emit:@{@"event":@"navigation-start"}];
    [self emitState];
}

- (void)showHomeRecordingVisit:(BOOL)record {
    if (!self.homePage) self.homePage = [self makePage];
    [self activatePage:self.homePage];
    if (record) [self.session recordSurface:self.homePage item:nil home:YES traversal:NO];
    [self emit:@{@"event":@"navigation-start"}];
    // The unloaded Home surface is only an in-memory navigation anchor. Local
    // Favorites needs no Google document, network request or HTML snapshot.
    self.homePage.ready = YES; self.homePage.terminated = NO;
    self.homePage.failedURL = nil; self.homePage.errorMessage = nil;
    [self emitState];
}

- (void)openContentRequest:(NSURLRequest *)request {
    if (!self.contentPage) self.contentPage = [self makePage];
    BOOL fromHome = self.selectedTab.contentPendingFromHome || (self.currentPage == self.homePage && self.homePage.ready);
    if (fromHome) {
        [self.loginTrigger cancelPending];
        self.suggestionsView.hidden = YES;
        self.selectedTab.contentPendingFromHome = YES;
        self.currentPage = self.contentPage; self.webView = self.contentPage.view;
        if (NSIsEmptyRect(self.webView.frame)) self.webView.frame = self.homePage.view.frame;
        [self updatePageVisibility];
    } else [self activatePage:self.contentPage];
    self.currentPage.historyTraversal = NO;
    self.currentPage.attemptedHTTPSRecovery = NO;
    self.currentPage.failedURL = nil; self.currentPage.errorMessage = nil;
    self.currentPage.mainNavigationRequest = request;
    [self emit:@{@"event":@"navigation-start"}];
    WKNavigation *navigation = [self.webView loadRequest:request];
    if (fromHome) self.selectedTab.pendingHomeNavigation = navigation;
    [self emitState];
}

- (void)moveInSession:(NSInteger)offset {
    GewuBrowserSessionEntry *entry = [self.session move:offset];
    if (!entry) return;
    if (entry.home) [self showHomeRecordingVisit:NO];
    else {
        [self activatePage:entry.surface];
        if (self.webView.backForwardList.currentItem != entry.item) {
            self.currentPage.historyTraversal = YES;
            [self.webView goToBackForwardListItem:entry.item];
        }
        [self emitState];
    }
}

- (void)observeValueForKeyPath:(NSString *)keyPath ofObject:(id)object change:(NSDictionary *)change context:(void *)context {
    if (object == self.webView) {
        if ([keyPath isEqualToString:@"URL"]) [self.loginTrigger cancelPending];
        if ([keyPath isEqualToString:@"URL"]) {
            WKWebView *view = self.webView;
            // Same-document navigation (pushState/hash changes) has no commit
            // callback. Wait for WebKit's history item to catch up to its URL.
            dispatch_async(dispatch_get_main_queue(), ^{
                if (!self.invalidated && view == self.webView && !view.loading
                    && [view.URL isEqual:view.backForwardList.currentItem.URL]) [self recordCurrentHistory];
            });
        }
        [self emitState]; return;
    }
    // A retained Home may update its title or progress while hidden. Never let
    // it overwrite the visible page's address, controls or navigation state.
    GewuBrowserPage *page = [self pageForView:object];
    if (page) {
        if ([keyPath isEqualToString:@"URL"] && !page.view.loading
            && [page.view.URL isEqual:page.view.backForwardList.currentItem.URL]) [self recordHistoryForPage:page];
        [self emitTabs];
    } else
        [super observeValueForKeyPath:keyPath ofObject:object change:change context:context];
}


- (void)handleCommand:(NSDictionary *)command {
    NSString *action = [command[@"action"] isKindOfClass:NSString.class] ? command[@"action"] : @"";
    if ([action isEqualToString:@"layout"]) {
        self.active = [command[@"active"] boolValue];
        if (!self.active) self.captureBackdropRequestID = nil;
        self.sidebarVisible = [command[@"sidebarVisible"] boolValue];
        self.canReturnToWorkspace = self.active && [command[@"canReturnToWorkspace"] boolValue];
        self.favicons.active = self.active;
        BOOL shown = self.active && [command[@"visible"] boolValue];
        if (self.active) [self ensureWebView];
        if (!self.webView) return;
        double viewport = [command[@"viewportWidth"] doubleValue];
        double scale = viewport > 0 ? self.workspace.bounds.size.width / viewport : 1;
        double x = [command[@"x"] doubleValue] * scale;
        double top = [command[@"y"] doubleValue] * scale;
        double width = [command[@"width"] doubleValue] * scale;
        double height = [command[@"height"] doubleValue] * scale;
        if (!isfinite(x) || !isfinite(top) || !isfinite(width) || !isfinite(height)) shown = NO;
        NSRect rect = NSMakeRect(x, self.workspace.bounds.size.height - top - height, width, height);
        rect = NSIntersectionRect(rect, self.workspace.bounds);
        if (rect.size.width < 1 || rect.size.height < 1) shown = NO;
        WKWebView *presented = [self presentedPageForTab:self.selectedTab].view;
        BOOL resized = !NSEqualSizes(presented.frame.size, rect.size) || (shown && !self.visible);
        presented.frame = rect;
        self.visible = shown;
        [self updatePageVisibility];
        if (!shown || resized) [self.loginTrigger cancelPending];
        if (!shown) self.suggestionsView.hidden = YES;
        if (!shown && [self.workspace.window.firstResponder isKindOfClass:NSView.class]
            && [(NSView *)self.workspace.window.firstResponder isDescendantOf:self.webView]) {
            [self.workspace.window makeFirstResponder:self.workspace];
        }
        return;
    }
    if ([action isEqualToString:@"capture-cancel"]) {
        if ([command[@"request_id"] isEqual:self.captureBackdropRequestID]) self.captureBackdropRequestID = nil;
        [self.captures[command[@"token"] ?: @""] cancel];
        [self.captures removeObjectForKey:command[@"token"] ?: @""];
        [self.captureSnapshots removeObjectForKey:command[@"snapshot_id"] ?: @""]; return;
    }
    if (!self.active) return;
    [self ensureWebView];
    if ([action isEqualToString:@"capture"]) { [self capturePage:command]; return; }
    if ([action isEqualToString:@"capture-download"]) { [self captureDownload:command]; return; }
    if ([action isEqualToString:@"new-tab"]) {
        NSString *value = [command[@"url"] isKindOfClass:NSString.class] ? command[@"url"] : nil;
        NSURL *url = value.length ? [NSURL URLWithString:value] : nil;
        if (value.length && !GewuBrowserPublicURL(url)) {
            [self emit:@{@"event":@"error", @"message":@"Use a public HTTP or HTTPS website. Local app and file addresses are not available in Browser."}];
            return;
        }
        GewuBrowserTab *tab = [self addTabWithRequest:url ? [NSURLRequest requestWithURL:url] : nil configuration:nil];
        tab.originPaperID = [command[@"origin_paper_id"] isKindOfClass:NSString.class] ? command[@"origin_paper_id"] : nil;
        tab.originURL = url.absoluteString;
        tab.originLibraryItemID = [command[@"origin_library_item_id"] integerValue];
        tab.workspaceReturnID = [command[@"workspace_return_id"] isKindOfClass:NSString.class] ? command[@"workspace_return_id"] : nil;
        [self emitState];
        if (!url) [self emit:@{@"event":@"focus-address"}];
    } else if ([@[@"select-tab", @"close-tab"] containsObject:action]) {
        NSString *identifier = [command[@"tab_id"] isKindOfClass:NSString.class] ? command[@"tab_id"] : @"";
        for (GewuBrowserTab *tab in self.tabs.copy) if ([tab.identifier isEqualToString:identifier]) {
            if ([action isEqualToString:@"select-tab"]) [self selectTab:tab]; else [self closeTab:tab];
            break;
        }
    } else if ([action isEqualToString:@"home"]) { [self showHomeRecordingVisit:YES]; }
    else if ([action isEqualToString:@"navigate"]) {
        NSString *value = command[@"url"];
        NSURL *url = [value isKindOfClass:NSString.class] ? [NSURL URLWithString:value] : nil;
        if (!GewuBrowserPublicURL(url)) { [self emit:@{ @"event": @"error", @"message": @"Use a public HTTP or HTTPS website. Local app and file addresses are not available in Browser." }]; return; }
        self.selectedTab.originPaperID = [command[@"origin_paper_id"] isKindOfClass:NSString.class] ? command[@"origin_paper_id"] : nil;
        self.selectedTab.originURL = url.absoluteString;
        self.selectedTab.originLibraryItemID = [command[@"origin_library_item_id"] integerValue];
        self.selectedTab.workspaceReturnID = [command[@"workspace_return_id"] isKindOfClass:NSString.class] ? command[@"workspace_return_id"] : nil;
        [self openContentRequest:[NSURLRequest requestWithURL:url]];
    } else if ([action isEqualToString:@"back"]) { [self moveInSession:-1]; }
    else if ([action isEqualToString:@"forward"]) { [self moveInSession:1]; }
    else if ([action isEqualToString:@"reload"]) {
        NSDictionary *pdf = self.currentPage.failedURL ? nil : [self PDFDocumentForPage:self.currentPage];
        if (pdf) {
            self.currentPage.pendingPDFDocument = [pdf mutableCopy];
            self.currentPage.pdfNavigation = [self.webView loadData:pdf[@"data"] MIMEType:@"application/pdf" characterEncodingName:@"UTF-8" baseURL:self.webView.URL];
            return;
        }
        self.currentPage.attemptedHTTPSRecovery = NO;
        if (self.currentPage == self.homePage && !self.selectedTab.contentPendingFromHome) {
            [self showHomeRecordingVisit:NO];
        } else if (self.selectedTab.contentPendingFromHome) {
            // The reused view still owns the previous document before commit;
            // reload that pending request, not the old document's URL.
            self.selectedTab.pendingHomeNavigation = [self.webView loadRequest:self.currentPage.mainNavigationRequest];
        } else if (self.currentPage.failedURL && [self.currentPage.mainNavigationRequest.HTTPMethod isEqualToString:@"GET"]) [self.webView loadRequest:[NSURLRequest requestWithURL:self.currentPage.failedURL]];
        else [self.webView reload];
    }
    else if ([action isEqualToString:@"stop"]) { [self cancelPDFDownloadsForPage:self.currentPage]; [self.webView stopLoading]; [self returnToRetainedHomeInTab:self.selectedTab]; [self emitState]; }
    else if ([action isEqualToString:@"focus"]) { [self.workspace.window makeFirstResponder:[self presentedPageForTab:self.selectedTab] == self.homePage ? self.workspace : [self presentedPageForTab:self.selectedTab].view]; }
    else if ([action isEqualToString:@"suggestions"]) { [self showAddressSuggestions:command]; }
    else if ([action isEqualToString:@"editor"]) { [self presentEditor:command]; }
    else if ([action isEqualToString:@"confirm"]) { [self presentConfirmation:command]; }
    else if ([action isEqualToString:@"favicon"]) {
        NSString *url = [command[@"url"] isKindOfClass:NSString.class] ? command[@"url"] : @"";
        [self.favicons requestURL:[NSURL URLWithString:url]];
    }
    else if ([action isEqualToString:@"import-bookmarks"]) { [self importBookmarks]; }
    else if ([action isEqualToString:@"read-bookmark-source"]) { [self readBookmarkSource:command]; }
    else if ([action isEqualToString:@"choose-bookmark-source-folder"]) { [self chooseBookmarkSourceFolder:command]; }
    else if ([action isEqualToString:@"export-bookmarks"]) { [self exportBookmarks:command]; }
    else if ([action isEqualToString:@"passwords"]) {
        NSURL *passwords = [NSWorkspace.sharedWorkspace URLForApplicationWithBundleIdentifier:@"com.apple.Passwords"];
        if (passwords) [NSWorkspace.sharedWorkspace openApplicationAtURL:passwords configuration:NSWorkspaceOpenConfiguration.configuration completionHandler:nil];
        else [self emit:@{@"event":@"error", @"message":@"Use Passwords in macOS System Settings on this Mac. Gewu Insight does not read or store website passwords."}];
    }
    else if ([action isEqualToString:@"share"]) {
        if ([self presentedPageForTab:self.selectedTab] == self.homePage) return;
        NSMenu *menu = [[NSMenu alloc] initWithTitle:@"Page actions"];
        NSArray *titles = @[@"Add Bookmark", @"Copy Link", @"Save Download", @"Open in Safari"];
        for (NSInteger i = 0; i < titles.count; i++) {
            NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:titles[i] action:@selector(shareAction:) keyEquivalent:@""];
            item.target = self; item.tag = i; [menu addItem:item];
        }
        CGFloat scale = self.workspace.bounds.size.width / MAX(1, [command[@"viewportWidth"] doubleValue]);
        [menu popUpMenuPositioningItem:nil atLocation:NSMakePoint([command[@"x"] doubleValue] * scale, self.workspace.bounds.size.height - [command[@"y"] doubleValue] * scale) inView:self.workspace];
    }
    else if ([action isEqualToString:@"external"]) {
        NSURL *url = self.currentPage.failedURL ?: self.webView.URL;
        if (GewuBrowserPublicURL(url)) {
            NSURL *safari = [[NSWorkspace sharedWorkspace] URLForApplicationWithBundleIdentifier:@"com.apple.Safari"];
            if (safari) [[NSWorkspace sharedWorkspace] openURLs:@[url] withApplicationAtURL:safari configuration:[NSWorkspaceOpenConfiguration configuration] completionHandler:nil];
        }
    } else if ([action isEqualToString:@"download"]) {
        if (self.currentPage.openingPDF) { [self emit:@{@"event":@"download", @"message":@"Wait for the PDF to finish loading before saving it."}]; return; }
        GewuBrowserPage *page = self.currentPage;
        if (!page.failedURL && ([page.documentMIME.lowercaseString containsString:@"pdf"] || [self PDFDocumentForPage:page])) {
            if (page.exportingPDF) { [self emit:@{@"event":@"download", @"message":@"Preparing the loaded PDF…"}]; return; }
            page.exportingPDF = YES;
            [self emit:@{@"event":@"download", @"message":@"Preparing the loaded PDF…"}];
            [self loadedPDFForPage:page URL:page.view.URL.absoluteString completion:^(GewuBrowserPDFFile *file, NSString *error) {
                page.exportingPDF = NO;
                if (file) [self saveDisplayedPDF:@{@"file":file, @"filename":file.filename}];
                else [self emit:@{@"event":@"error", @"message":error ?: @"The loaded PDF is unavailable. Retry after it finishes loading."}];
            }];
            return;
        }
        if(page.exportingPDF) return;
        page.exportingPDF=YES;
        NSString *generation=page.captureDocumentID;
        GewuLoadedBrowserPDFFrames(page.view, ^(NSArray<NSDictionary *> *frames){
            page.exportingPDF=NO;
            if(self.invalidated || ![self tabForPage:page] || ![page.captureDocumentID isEqual:generation]) return;
            NSArray *valid=[frames filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(NSDictionary *frame,NSDictionary *bindings){return GewuBrowserPublicURL([NSURL URLWithString:frame[@"url"]]);}]];
            if(valid.count>1){[self emit:@{@"event":@"error",@"message":@"Multiple loaded PDFs found. Use Save to Gewu to choose a PDF."}];return;}
            if(valid.count==1){
                page.exportingPDF=YES;
                [self loadedPDFForPage:page frame:valid[0] completion:^(GewuBrowserPDFFile *file,NSString *error){
                    page.exportingPDF=NO;
                    if(file)[self saveDisplayedPDF:@{@"file":file,@"filename":file.filename}];
                    else [self emit:@{@"event":@"error",@"message":error?:@"The embedded PDF is unavailable."}];
                }]; return;
            }
            NSURL *downloadURL=page.failedURL?:page.view.URL;
            if(GewuBrowserPublicURL(downloadURL)) [page.view startDownloadUsingRequest:[NSURLRequest requestWithURL:downloadURL] completionHandler:^(WKDownload *download){[self registerDownload:download];}];
        });
    } else if ([action isEqualToString:@"find"]) {
        if ([self presentedPageForTab:self.selectedTab] == self.homePage) return;
        NSString *text = [command[@"text"] isKindOfClass:NSString.class] ? command[@"text"] : @"";
        if (text.length > 500) return;
        WKFindConfiguration *configuration = [[WKFindConfiguration alloc] init];
        configuration.backwards = [command[@"backwards"] boolValue];
        configuration.wraps = YES;
        [self.webView findString:text withConfiguration:configuration completionHandler:^(WKFindResult *result) {
            [self emit:@{ @"event": @"find-result", @"found": @(result.matchFound) }];
        }];
    }
}


// Read only article metadata after the trusted toolbar command. Remote pages
// have no message handler, capture token, local path or workspace API access.
- (void)captureBackdropForPage:(GewuBrowserPage *)page requestID:(NSString *)requestID {
    self.captureBackdropRequestID = requestID;
    NSRect bounds = page.view.bounds;
    if (bounds.size.width < 1 || bounds.size.height < 1) return;
    GewuBrowserTab *tab = self.selectedTab;
    NSURL *url = page.view.URL;
    NSString *generation = page.captureDocumentID ?: @"";
    WKSnapshotConfiguration *configuration = [WKSnapshotConfiguration new];
    configuration.rect = bounds;
    configuration.snapshotWidth = @(MIN(1600, bounds.size.width));
    configuration.afterScreenUpdates = NO;
    __weak typeof(self) weakSelf = self;
    [page.view takeSnapshotWithConfiguration:configuration completionHandler:^(NSImage *image, NSError *error) {
        typeof(self) self = weakSelf;
        if (!self || self.invalidated || !self.active || error || !image
            || ![self.captureBackdropRequestID isEqual:requestID] || self.selectedTab != tab || self.currentPage != page
            || ![page.view.URL isEqual:url] || ![(page.captureDocumentID ?: @"") isEqual:generation]) return;
        // A one-shot visible-viewport image stays only in the trusted dialog's
        // memory. Never store it, send it to a server or include it in metadata.
        NSBitmapImageRep *bitmap = [NSBitmapImageRep imageRepWithData:image.TIFFRepresentation];
        NSData *jpeg = [bitmap representationUsingType:NSBitmapImageFileTypeJPEG properties:@{NSImageCompressionFactor:@0.55}];
        if (!jpeg.length || jpeg.length > 4 * 1024 * 1024) return;
        [self emit:@{@"event":@"capture-backdrop", @"request_id":requestID,
                     @"image":[@"data:image/jpeg;base64," stringByAppendingString:[jpeg base64EncodedStringWithOptions:0]]}];
    }];
}
- (void)capturePage:(NSDictionary *)command {
    NSString *requestID = [command[@"request_id"] isKindOfClass:NSString.class] ? command[@"request_id"] : @"";
    GewuBrowserPage *page = self.currentPage;
    GewuBrowserTab *tab = self.selectedTab;
    NSURL *url = page.view.URL;
    if (page == tab.homePage || page.view.loading || page.openingPDF || page.errorMessage.length || !GewuBrowserPublicURL(url)) {
        [self emit:@{@"event":@"capture-metadata", @"request_id":requestID, @"error":@"Wait for an article or PDF to finish loading, then try Save to Gewu again."}]; return;
    }
    [self captureBackdropForPage:page requestID:requestID];
    NSString *generation = page.captureDocumentID ?: @"";
    NSString *script = [NSString stringWithContentsOfURL:[NSBundle.mainBundle URLForResource:@"GewuBrowserCaptureProbe" withExtension:@"js"] encoding:NSUTF8StringEncoding error:nil];
    if (!script.length) { [self emit:@{@"event":@"capture-metadata", @"request_id":requestID, @"error":@"The article collector is missing. Rebuild Gewu Insight.app."}]; return; }
    [page.view evaluateJavaScript:script inFrame:nil inContentWorld:[WKContentWorld worldWithName:@"GewuBrowserCapture"] completionHandler:^(id value, NSError *error) {
        if (![self.tabs containsObject:tab] || ![page.view.URL isEqual:url] || ![(page.captureDocumentID ?: @"") isEqual:generation]) {
            [self emit:@{@"event":@"capture-metadata", @"request_id":requestID, @"error":@"The page changed during identification. Try Save to Gewu on the current article."}]; return;
        }
        NSMutableDictionary *snapshot = [value isKindOfClass:NSDictionary.class] ? [value mutableCopy] : [NSMutableDictionary dictionary];
        BOOL pdf = [page.documentMIME.lowercaseString isEqual:@"application/pdf"] || [snapshot[@"is_pdf"] boolValue];
        NSMutableArray *urls = [NSMutableArray array];
        if (pdf) [urls addObject:url.absoluteString];
        NSArray *candidates = [snapshot[@"pdf_urls"] isKindOfClass:NSArray.class] ? snapshot[@"pdf_urls"] : @[];
        for (id candidate in candidates) {
            if ([candidate isKindOfClass:NSString.class] && GewuBrowserPublicURL([NSURL URLWithString:candidate]) && ![urls containsObject:candidate]) [urls addObject:candidate];
            if (urls.count >= 8) break;
        }
        GewuLoadedBrowserPDFFrames(page.view, ^(NSArray<NSDictionary *> *frames) {
            if (![self.tabs containsObject:tab] || ![page.view.URL isEqual:url] || ![(page.captureDocumentID ?: @"") isEqual:generation]) {
                [self emit:@{@"event":@"capture-metadata", @"request_id":requestID, @"error":@"The page changed. Reopen Save to Gewu."}]; return;
            }
            NSMutableDictionary *embedded = [NSMutableDictionary dictionary];
            NSMutableArray *loaded = [NSMutableArray array];
            if (pdf) [loaded addObject:url.absoluteString];
            for (NSDictionary *frame in frames) {
                NSString *source=frame[@"url"];
                if (!GewuBrowserPublicURL([NSURL URLWithString:source]) || embedded.count>=8) continue;
                // Ambiguous identical URLs are not silently bound to an arbitrary frame.
                if (embedded[source]) { embedded[source]=NSNull.null; continue; }
                embedded[source]=frame;
                if (![urls containsObject:source]) [urls insertObject:source atIndex:0];
                [loaded addObject:source];
            }
            for (NSString *source in embedded.allKeys) if (embedded[source]==NSNull.null) { [embedded removeObjectForKey:source]; [loaded removeObject:source]; }
            while (urls.count>8) [urls removeLastObject];
            [loaded filterUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(NSString *source,NSDictionary *bindings){return [urls containsObject:source];}]];
            NSString *key = NSUUID.UUID.UUIDString;
            if (!self.captureSnapshots) self.captureSnapshots = [NSMutableDictionary dictionary];
            [self.captureSnapshots removeAllObjects];
            self.captureSnapshots[key] = @{@"page":page, @"url":url, @"generation":generation, @"urls":urls, @"frames":embedded};
            snapshot[@"url"] = url.absoluteString; snapshot[@"is_pdf"] = @(pdf); snapshot[@"pdf_urls"] = urls;
            snapshot[@"loaded_pdf_urls"]=loaded;
            snapshot[@"snapshot_id"] = key; snapshot[@"tab_id"] = tab.identifier;
            snapshot[@"origin_paper_id"] = tab.originPaperID ?: @""; snapshot[@"origin_url"] = tab.originURL ?: @"";
            snapshot[@"origin_library_item_id"]=@(tab.originLibraryItemID);
            [self emit:@{@"event":@"capture-metadata", @"request_id":requestID, @"snapshot":snapshot}];
        });
    }];
}
// Cache only bytes belonging to this exact document generation/candidate.
// A navigation clears this cache even when a URL is reused for a different PDF.
- (void)retainCapturedPDF:(GewuBrowserPDFFile *)file page:(GewuBrowserPage *)page URL:(NSString *)url {
    page.capturedPDF = file; page.capturedPDFURL = url; page.capturedPDFFrame = nil; page.capturedPDFDate = NSDate.date;
    NSMutableArray *pages = [NSMutableArray array]; NSUInteger bytes = 0;
    for (GewuBrowserTab *tab in self.tabs) if (tab.contentPage.capturedPDF) {
        [pages addObject:tab.contentPage]; bytes += tab.contentPage.capturedPDF.size;
    }
    [pages sortUsingComparator:^NSComparisonResult(GewuBrowserPage *a, GewuBrowserPage *b) { return [a.capturedPDFDate compare:b.capturedPDFDate]; }];
    NSUInteger count = pages.count;
    for (GewuBrowserPage *old in pages) {
        if (bytes <= 256 * 1024 * 1024 && count <= 8) break;
        if (old == page) continue;
        bytes -= old.capturedPDF.size; count--; old.capturedPDF = nil; old.capturedPDFURL = nil;
    }
}
- (void)loadedPDFForPage:(GewuBrowserPage *)page frame:(NSDictionary *)frame completion:(void (^)(GewuBrowserPDFFile *, NSString *))completion {
    NSString *generation=page.captureDocumentID, *url=frame[@"url"];
    void (^received)(GewuBrowserPDFFile *,NSString *)=^(GewuBrowserPDFFile *file,NSString *error){
        if(self.invalidated || ![self tabForPage:page] || ![page.captureDocumentID isEqual:generation]) { completion(nil,@"The page changed. Reopen Save to Gewu."); return; }
        if(file){[self retainCapturedPDF:file page:page URL:url];page.capturedPDFFrame=frame;}
        completion(file,error);
    };
    if(page.capturedPDF && [page.capturedPDFURL isEqual:url] && [page.capturedPDFFrame[@"token"] isEqual:frame[@"token"]]) {
        GewuBrowserPDFFrameIsCurrent(page.view,frame,^(BOOL current){received(current?page.capturedPDF:nil,current?nil:@"The embedded PDF changed. Reopen Save to Gewu.");});
    } else GewuReadLoadedBrowserPDFFrame(page.view,frame,received);
}
- (void)loadedPDFForPage:(GewuBrowserPage *)page URL:(NSString *)url completion:(void (^)(GewuBrowserPDFFile *, NSString *))completion {
    if (page.capturedPDF && [page.capturedPDFURL isEqual:url]) { completion(page.capturedPDF, nil); return; }
    NSURL *pageURL = page.view.URL; NSString *generation = page.captureDocumentID;
    if (![url isEqual:pageURL.absoluteString] || page.view.loading || page.openingPDF) {
        completion(nil, @"The complete PDF is not loaded in this tab. Open it first, or explicitly download it in Details."); return;
    }
    void (^received)(GewuBrowserPDFFile *, NSString *) = ^(GewuBrowserPDFFile *file, NSString *error) {
        if (self.invalidated || ![self tabForPage:page] || ![page.view.URL isEqual:pageURL] || ![page.captureDocumentID isEqual:generation]) {
            completion(nil, @"The source page changed. Reopen Save to Gewu on the current PDF."); return;
        }
        if (file) [self retainCapturedPDF:file page:page URL:url];
        completion(file, error);
    };
    NSDictionary *pdf = [self PDFDocumentForPage:page];
    if (pdf) {
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            GewuBrowserPDFFile *file = [GewuBrowserPDFFile fileWithData:pdf[@"data"] filename:pdf[@"filename"]];
            dispatch_async(dispatch_get_main_queue(), ^{ received(file, file ? nil : @"Choose a complete PDF up to 128 MB."); });
        });
    } else if ([page.documentMIME.lowercaseString containsString:@"pdf"]) {
        GewuReadLoadedBrowserPDF(page.view, pageURL.lastPathComponent, received);
    } else received(nil, @"Open the PDF itself before saving its loaded file, or explicitly download it in Details.");
}
- (void)captureDownload:(NSDictionary *)command {
    NSString *token = [command[@"token"] isKindOfClass:NSString.class] ? command[@"token"] : @"";
    NSDictionary *snapshot = self.captureSnapshots[command[@"snapshot_id"] ?: @""];
    GewuBrowserPage *page = snapshot[@"page"];
    NSString *url = [command[@"url"] isKindOfClass:NSString.class] ? command[@"url"] : @"";
    BOOL (^valid)(void) = ^BOOL{ return !self.invalidated && page && [self tabForPage:page] && [page.view.URL isEqual:snapshot[@"url"]]
        && [(page.captureDocumentID ?: @"") isEqual:snapshot[@"generation"]] && [snapshot[@"urls"] containsObject:url] && token.length; };
    if (!valid()) {
        [self emit:@{@"event":@"capture-pdf", @"token":token, @"error":@"The source page changed. Reopen Save to Gewu or choose a local PDF."}]; return;
    }
    if (!self.captures) self.captures = [NSMutableDictionary dictionary];
    [self.captures[token] cancel];
    GewuBrowserCapture *capture = [GewuBrowserCapture new]; self.captures[token] = capture;
    __weak typeof(self) weakSelf = self;
    __weak GewuBrowserCapture *weakCapture = capture;
    void (^completion)(NSString *) = ^(NSString *error) {
        if (!weakCapture || weakSelf.captures[token] != weakCapture) return;
        [weakSelf.captures removeObjectForKey:token];
        [weakSelf emit:@{@"event":@"capture-pdf", @"token":token, @"error":error ?: @""}];
    };
    capture.progress = ^(NSString *message) {
        if (weakCapture && weakSelf.captures[token] == weakCapture)
            [weakSelf emit:@{@"event":@"capture-progress", @"token":token, @"message":message}];
    };
    capture.receivedPDF = ^(GewuBrowserPDFFile *file) { if (valid()) [weakSelf retainCapturedPDF:file page:page URL:url]; };
    if ([command[@"allow_download"] boolValue]) {
        // This path is reachable only through the explicit Details download action.
        [capture downloadURL:[NSURL URLWithString:url] fromView:page.view workspaceURL:self.workspace.URL uploadToken:command[@"upload_token"] completion:completion];
        return;
    }
    void (^readComplete)(GewuBrowserPDFFile *,NSString *) = ^(GewuBrowserPDFFile *file, NSString *error) {
        if (weakSelf.captures[token] != capture) return; // cancelled/superseded panel
        if (!file || !valid()) { completion(error ?: @"The source page changed. Reopen Save to Gewu."); return; }
        [capture uploadPDFFile:file sourceURL:[NSURL URLWithString:url] workspaceURL:self.workspace.URL uploadToken:command[@"upload_token"] completion:completion];
    };
    NSDictionary *frame = snapshot[@"frames"][url];
    if (frame) [self loadedPDFForPage:page frame:frame completion:readComplete];
    else [self loadedPDFForPage:page URL:url completion:readComplete];
}

- (void)showAddressSuggestions:(NSDictionary *)command {
    NSArray *items = [command[@"items"] isKindOfClass:NSArray.class] ? command[@"items"] : @[];
    self.suggestionsView.hidden = YES;
    self.suggestionItems = @[];
    if (!self.visible || !items.count) return;
    NSMutableArray *valid = [NSMutableArray array];
    for (id item in items) {
        if (![item isKindOfClass:NSDictionary.class]) continue;
        NSString *url = [item[@"url"] isKindOfClass:NSString.class] ? item[@"url"] : nil;
        if (!GewuBrowserPublicURL([NSURL URLWithString:url ?: @""])) continue;
        NSString *title = [item[@"title"] isKindOfClass:NSString.class] ? item[@"title"] : url;
        [valid addObject:@{@"url":url, @"title":[title substringToIndex:MIN(title.length, 1000)]}];
        if (valid.count == 8) break;
    }
    if (!valid.count) return;
    double viewport = [command[@"viewportWidth"] doubleValue];
    double scale = viewport > 0 ? self.workspace.bounds.size.width / viewport : 1;
    double x = [command[@"x"] doubleValue] * scale, top = [command[@"y"] doubleValue] * scale;
    double width = [command[@"width"] doubleValue] * scale;
    if (!isfinite(x) || !isfinite(top) || !isfinite(width) || width < 100) return;
    CGFloat rowHeight = 45;
    CGFloat height = MIN(valid.count * rowHeight + 8, self.workspace.bounds.size.height - top - 6);
    if (height < rowHeight + 8) return;
    NSUInteger count = MIN(valid.count, (NSUInteger)((height - 8) / rowHeight));
    height = count * rowHeight + 8;
    self.suggestionItems = [valid subarrayWithRange:NSMakeRange(0, count)];
    if (!self.suggestionsView) {
        self.suggestionsView = [[NSView alloc] init];
        self.suggestionsView.wantsLayer = YES;
        self.suggestionsView.layer.cornerRadius = 8;
        self.suggestionsView.layer.borderWidth = 1;
        self.suggestionsView.layer.borderColor = NSColor.separatorColor.CGColor;
        self.suggestionsView.layer.backgroundColor = NSColor.controlBackgroundColor.CGColor;
        [self.workspace.superview addSubview:self.suggestionsView positioned:NSWindowAbove relativeTo:self.webView];
        self.suggestionsView.accessibilityLabel = @"History suggestions";
    }
    self.suggestionsView.frame = NSIntersectionRect(NSMakeRect(x, self.workspace.bounds.size.height - top - height, width, height), self.workspace.bounds);
    for (NSView *view in self.suggestionsView.subviews.copy) [view removeFromSuperview];
    NSInteger selected = [command[@"selected"] integerValue];
    [self.suggestionItems enumerateObjectsUsingBlock:^(NSDictionary *item, NSUInteger index, BOOL *stop) {
        GewuAddressSuggestionButton *button = [[GewuAddressSuggestionButton alloc] initWithFrame:NSMakeRect(5, height - 4 - (index + 1) * rowHeight, self.suggestionsView.bounds.size.width - 10, rowHeight)];
        button.bordered = NO; button.alignment = NSTextAlignmentLeft;
        button.wantsLayer = YES; button.layer.cornerRadius = 5;
        button.layer.backgroundColor = (selected == (NSInteger)index ? [NSColor.selectedContentBackgroundColor colorWithAlphaComponent:.14] : NSColor.clearColor).CGColor;
        NSMutableParagraphStyle *style = [[NSMutableParagraphStyle alloc] init];
        style.lineBreakMode = NSLineBreakByTruncatingTail;
        NSMutableAttributedString *title = [[NSMutableAttributedString alloc] initWithString:[NSString stringWithFormat:@"%@\n", item[@"title"]] attributes:@{NSFontAttributeName:[NSFont systemFontOfSize:12 weight:NSFontWeightMedium], NSForegroundColorAttributeName:NSColor.labelColor, NSParagraphStyleAttributeName:style}];
        [title appendAttributedString:[[NSAttributedString alloc] initWithString:item[@"url"] attributes:@{NSFontAttributeName:[NSFont systemFontOfSize:11], NSForegroundColorAttributeName:NSColor.secondaryLabelColor, NSParagraphStyleAttributeName:style}]];
        button.attributedTitle = title; button.cell.wraps = YES;
        button.toolTip = item[@"url"]; button.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", item[@"title"], item[@"url"]];
        button.target = self; button.action = @selector(chooseAddressSuggestion:); button.tag = index;
        [self.suggestionsView addSubview:button];
    }];
    self.suggestionsView.hidden = NO;
}

- (void)chooseAddressSuggestion:(NSButton *)sender {
    if (sender.tag < 0 || sender.tag >= self.suggestionItems.count) return;
    NSString *url = self.suggestionItems[sender.tag][@"url"];
    self.suggestionsView.hidden = YES;
    [self emit:@{@"event":@"address-suggestion", @"url":url}];
}

- (void)presentEditor:(NSDictionary *)command {
    if (self.workspace.window.attachedSheet) {
        [self emit:@{ @"event": @"editor-result", @"cancelled": @YES }];
        return;
    }
    // JSON null is NSNull, not nil. A new bookmark has no database ID yet.
    NSInteger bookmarkID = [command[@"id"] isKindOfClass:NSNumber.class] ? [command[@"id"] integerValue] : 0;
    NSInteger parentID = [command[@"parent_id"] isKindOfClass:NSNumber.class] ? [command[@"parent_id"] integerValue] : 0;
    BOOL folder = [command[@"kind"] isEqualToString:@"folder"];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = bookmarkID > 0 ? (folder ? @"Edit Folder" : @"Edit Bookmark") : (folder ? @"New Folder" : @"Add Bookmark");
    alert.informativeText = folder ? @"Organize your saved websites." : @"Save this page in your browser bookmarks.";
    NSTextField *name = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 340, 26)];
    name.stringValue = [command[@"title"] isKindOfClass:NSString.class] ? command[@"title"] : @"";
    name.placeholderString = @"Name";
    NSTextField *url = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 340, 26)];
    url.stringValue = [command[@"url"] isKindOfClass:NSString.class] ? command[@"url"] : @"";
    url.placeholderString = @"Website address";
    NSPopUpButton *location = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(0, 0, 340, 28) pullsDown:NO];
    [location addItemWithTitle:@"Bookmarks"]; location.lastItem.representedObject = @0;
    NSArray *folders = [command[@"folders"] isKindOfClass:NSArray.class] ? command[@"folders"] : @[];
    for (NSDictionary *item in folders) {
        if (![item isKindOfClass:NSDictionary.class] || ![item[@"title"] isKindOfClass:NSString.class] || ![item[@"id"] isKindOfClass:NSNumber.class]) continue;
        [location addItemWithTitle:item[@"title"]]; location.lastItem.representedObject = item[@"id"];
        if ([item[@"id"] integerValue] == parentID) [location selectItem:location.lastItem];
    }
    NSMutableArray<NSView *> *views = [NSMutableArray arrayWithArray:@[[NSTextField labelWithString:@"Name"], name]];
    if (!folder) [views addObjectsFromArray:@[[NSTextField labelWithString:@"Address"], url]];
    [views addObjectsFromArray:@[[NSTextField labelWithString:@"Add to"], location]];
    NSStackView *stack = [NSStackView stackViewWithViews:views];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeLeading; stack.spacing = 5;
    stack.frame = NSMakeRect(0, 0, 340, folder ? 106 : 158);
    for (NSView *view in views) [view.widthAnchor constraintEqualToConstant:340].active = YES;
    alert.accessoryView = stack;
    [alert addButtonWithTitle:bookmarkID ? @"Save" : @"Add"];
    [alert addButtonWithTitle:@"Cancel"];
    alert.window.initialFirstResponder = name;
    [alert beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) {
        [self emit:@{ @"event": @"editor-result", @"cancelled": @(response != NSAlertFirstButtonReturn),
            @"title": name.stringValue, @"url": url.stringValue, @"parent_id": location.selectedItem.representedObject ?: @0 }];
    }];
}

- (void)importBookmarks {
    if (self.workspace.window.attachedSheet) return;
    NSOpenPanel *panel = NSOpenPanel.openPanel;
    panel.title = @"Import Bookmarks"; panel.prompt = @"Import";
    panel.message = @"Choose Safari or Chrome bookmark HTML, or a Safari ZIP containing Bookmarks HTML. Passwords and history are not imported.";
    panel.allowedContentTypes = @[UTTypeHTML, UTTypeZIP]; panel.allowsMultipleSelection = NO;
    [panel beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) {
        if (response != NSModalResponseOK) return;
        NSNumber *size = nil; [panel.URL getResourceValue:&size forKey:NSURLFileSizeKey error:nil];
        if (!size || size.unsignedLongLongValue > 10 * 1024 * 1024) { [self emit:@{@"event":@"error", @"message":@"Choose a bookmark export no larger than 10 MB."}]; return; }
        NSData *content = [NSData dataWithContentsOfURL:panel.URL options:NSDataReadingMappedIfSafe error:nil];
        if (!content || content.length > 10 * 1024 * 1024) { [self emit:@{@"event":@"error", @"message":@"The selected bookmark file could not be read."}]; return; }
        [self emit:@{@"event":@"bookmark-import", @"content_base64":[content base64EncodedStringWithOptions:0]}];
    }];
}

- (void)exportBookmarks:(NSDictionary *)command {
    if (self.workspace.window.attachedSheet) return;
    NSString *html = [command[@"html"] isKindOfClass:NSString.class] ? command[@"html"] : nil;
    NSData *content = [html dataUsingEncoding:NSUTF8StringEncoding];
    if (!content.length || content.length > 10 * 1024 * 1024) return;
    NSSavePanel *panel = NSSavePanel.savePanel;
    panel.title = @"Export Bookmarks"; panel.allowedContentTypes = @[UTTypeHTML];
    panel.nameFieldStringValue = @"Gewu Insight Bookmarks.html";
    panel.message = @"Exports bookmark names, links, and folders only. Keep this file private if your bookmarks contain private links.";
    [panel beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) {
        if (response != NSModalResponseOK) return;
        BOOL saved = [content writeToURL:panel.URL options:NSDataWritingAtomic error:nil];
        [self emit:@{@"event":saved ? @"download" : @"error", @"message":saved ? @"Bookmarks exported as HTML. Website passwords and history were not exported." : @"The bookmark export could not be saved."}];
    }];
}

- (void)readBookmarkSource:(NSDictionary *)command {
    NSString *source = command[@"source"];
    if (![@[@"safari", @"chrome"] containsObject:source] || self.workspace.window.attachedSheet) return;
    BOOL safari = [source isEqualToString:@"safari"];
    NSString *expected = safari ? @"Bookmarks.plist" : @"Bookmarks";
    NSString *preference = [@"GewuBookmarkSource-" stringByAppendingString:source];
    NSString *saved = [NSUserDefaults.standardUserDefaults stringForKey:preference];
    NSString *path = saved.length ? saved : [NSHomeDirectory() stringByAppendingPathComponent:safari ? @"Library/Safari/Bookmarks.plist" : @"Library/Application Support/Google/Chrome/Default/Bookmarks"];
    NSOpenPanel *panel = NSOpenPanel.openPanel;
    panel.title = safari ? @"Sync from Safari" : @"Sync from Chrome";
    panel.prompt = @"Choose Bookmark File";
    panel.directoryURL = [NSURL fileURLWithPath:path.stringByDeletingLastPathComponent isDirectory:YES];
    panel.nameFieldStringValue = expected; panel.showsHiddenFiles = YES;
    panel.canChooseDirectories = NO; panel.allowsMultipleSelection = NO;
    panel.message = safari ? @"Choose Safari's Bookmarks.plist. Next, choose one folder to sync into Gewu. This never writes to Safari. If macOS denies access, use Bookmarks menu > Import with a Safari HTML export instead."
        : @"Choose the Bookmarks file inside the desired Chrome profile (Default or Profile 1, etc.). Next, choose one folder. Only bookmarks are read; Chrome is never modified.";
    [panel beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) {
        if (response != NSModalResponseOK) { [self emit:@{@"event":@"bookmark-source-cancel"}]; return; }
        NSURL *url = panel.URL;
        NSNumber *size = nil, *regular = nil;
        [url getResourceValue:&size forKey:NSURLFileSizeKey error:nil];
        [url getResourceValue:&regular forKey:NSURLIsRegularFileKey error:nil];
        if (![url.lastPathComponent isEqualToString:expected] || !regular.boolValue || !size || size.unsignedLongLongValue > 10 * 1024 * 1024) {
            [self emit:@{@"event":@"bookmark-source-cancel", @"message":[NSString stringWithFormat:@"Choose %@, no larger than 10 MB. No other profile files are read.", expected]}]; return;
        }
        // Explicit user-selected file only. No profile enumeration, passwords,
        // history, cookies, background watcher, or source write permissions.
        NSData *content = [NSData dataWithContentsOfURL:url options:NSDataReadingMappedIfSafe error:nil];
        if (!content.length || content.length > 10 * 1024 * 1024) {
            [self emit:@{@"event":@"bookmark-source-cancel", @"message":@"macOS could not read this bookmark file. Use an HTML bookmark export with Import instead; no privacy settings were changed."}]; return;
        }
        [NSUserDefaults.standardUserDefaults setObject:url.path forKey:preference];
        NSData *identity = [url.URLByStandardizingPath.path dataUsingEncoding:NSUTF8StringEncoding];
        unsigned char digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(identity.bytes, (CC_LONG)identity.length, digest);
        NSMutableString *sourceID = [NSMutableString string];
        for (NSUInteger i = 0; i < sizeof(digest); i++) [sourceID appendFormat:@"%02x", digest[i]];
        [self emit:@{@"event":@"bookmark-source", @"source":source, @"source_id":sourceID, @"content_base64":[content base64EncodedStringWithOptions:0]}];
    }];
}

- (void)chooseBookmarkSourceFolder:(NSDictionary *)command {
    NSArray *folders = [command[@"folders"] isKindOfClass:NSArray.class] ? command[@"folders"] : nil;
    if (!folders.count || folders.count > 2000 || self.workspace.window.attachedSheet) {
        [self emit:@{@"event":@"bookmark-source-cancel", @"message":@"No selectable source folder was found."}]; return;
    }
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Choose a folder to sync into Gewu";
    alert.informativeText = @"Only the selected folder and its subfolders are included. Repeat this action to refresh from the same source. Local edits and source deletions are kept; nothing is written back to Safari or Chrome.";
    [alert addButtonWithTitle:@"Sync Selected Folder"]; [alert addButtonWithTitle:@"Cancel"];
    NSPopUpButton *choice = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(0, 0, 440, 28) pullsDown:NO];
    for (NSDictionary *folder in folders) {
        if (![folder isKindOfClass:NSDictionary.class] || ![folder[@"id"] isKindOfClass:NSString.class] || ![folder[@"title"] isKindOfClass:NSString.class]) continue;
        NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:[NSString stringWithFormat:@"%@ (%ld bookmarks)", folder[@"title"], (long)[folder[@"count"] integerValue]] action:nil keyEquivalent:@""];
        item.representedObject = folder[@"id"]; [choice.menu addItem:item];
    }
    if (!choice.numberOfItems) { [self emit:@{@"event":@"bookmark-source-cancel"}]; return; }
    alert.accessoryView = choice;
    [alert beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) {
        [self emit:response == NSAlertFirstButtonReturn ? @{@"event":@"bookmark-source-folder", @"folder_id":choice.selectedItem.representedObject} : @{@"event":@"bookmark-source-cancel"}];
    }];
}

- (void)shareAction:(NSMenuItem *)sender {
    if (sender.tag == 0) [self emit:@{ @"event": @"bookmark" }];
    else if (sender.tag == 1 && self.webView.URL) {
        [NSPasteboard.generalPasteboard clearContents];
        [NSPasteboard.generalPasteboard setString:self.webView.URL.absoluteString forType:NSPasteboardTypeString];
    } else if (sender.tag == 2) [self handleCommand:@{ @"action": @"download" }];
    else if (sender.tag == 3) [self handleCommand:@{ @"action": @"external" }];
}

- (void)presentConfirmation:(NSDictionary *)command {
    if (self.workspace.window.attachedSheet) {
        [self emit:@{ @"event": @"confirm-result", @"confirmed": @NO }];
        return;
    }
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = [command[@"title"] isKindOfClass:NSString.class] ? command[@"title"] : @"Confirm";
    alert.informativeText = [command[@"message"] isKindOfClass:NSString.class] ? command[@"message"] : @"";
    [alert addButtonWithTitle:[command[@"button"] isKindOfClass:NSString.class] ? command[@"button"] : @"Delete"];
    [alert addButtonWithTitle:@"Cancel"];
    NSPopUpButton *range = nil;
    if ([command[@"history"] boolValue]) {
        range = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(0, 0, 300, 28) pullsDown:NO];
        [range addItemsWithTitles:@[@"Last hour", @"Last 24 hours", @"Last 7 days", @"All history"]];
        alert.accessoryView = range;
    }
    [alert beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) {
        [self emit:@{ @"event": @"confirm-result", @"confirmed": @(response == NSAlertFirstButtonReturn),
            @"range": range ? @[@"hour", @"day", @"week", @"all"][range.indexOfSelectedItem] : @"" }];
    }];
}

- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    GewuBrowserPage *page = [self pageForView:webView];
    GewuBrowserTab *tab = [self tabForPage:page];
    // The unloaded Home view is a navigation anchor only. All Favorites and
    // address actions use the trusted workspace and a separate content view.
    if (page && page == tab.homePage) { decisionHandler(WKNavigationActionPolicyCancel); return; }
    if (!page || (page != tab.currentPage && (action.targetFrame.isMainFrame || !action.targetFrame))) {
        decisionHandler(WKNavigationActionPolicyCancel); return;
    }
    NSURL *url = action.request.URL;
    BOOL blob = [url.scheme.lowercaseString isEqual:@"blob"];
    if (blob) {
        NSURL *source = action.sourceFrame.request.URL;
        if (GewuBrowserBlobURL(url, source)) {
            page.blobRequestURL = url; page.blobSourceURL = source;
        } else if (![url isEqual:page.blobRequestURL] || !GewuBrowserBlobURL(url, page.blobSourceURL)) {
            decisionHandler(WKNavigationActionPolicyCancel); return;
        }
    }
    // Challenge widgets and ordinary embeds use local child documents. Leave
    // their origin/sandbox rules to WebKit; never expose the trusted workspace.
    if (action.targetFrame && !action.targetFrame.isMainFrame && GewuBrowserInternalFrameURL(url)) {
        decisionHandler(WKNavigationActionPolicyAllow); return;
    }
    if ([url.absoluteString isEqualToString:@"about:blank"] && (!action.targetFrame.isMainFrame || page.allowsInitialBlank)) { decisionHandler(WKNavigationActionPolicyAllow); return; }
    if (!GewuBrowserPublicURL(url) && !blob) {
        BOOL wasActive = webView == self.webView;
        if (action.targetFrame.isMainFrame || !action.targetFrame) [self returnToRetainedHomeInTab:tab];
        if (wasActive && (action.targetFrame.isMainFrame || !action.targetFrame)) [self emit:@{ @"event": @"error", @"message": @"This address cannot be opened here. Use Open in Safari for application links or special sign-in flows." }];
        decisionHandler(WKNavigationActionPolicyCancel); return;
    }
    if (webView == self.webView && action.targetFrame && action.navigationType == WKNavigationTypeLinkActivated
        && ((action.modifierFlags & NSEventModifierFlagCommand) || action.buttonNumber == 2)
        && GewuBrowserCanRetainHomeForRequest(action.request)) {
        decisionHandler(WKNavigationActionPolicyCancel);
        GewuBrowserTab *origin = [self tabForPage:page];
        GewuBrowserTab *opened = [self addTabWithRequest:action.request configuration:nil];
        opened.originPaperID = origin.originPaperID; opened.originURL = origin.originURL; opened.originLibraryItemID = origin.originLibraryItemID; opened.workspaceReturnID = origin.workspaceReturnID; [self emitState];
        opened.currentPage.pendingRequestedDownload = action.shouldPerformDownload;
        if (blob) { opened.currentPage.blobRequestURL = page.blobRequestURL; opened.currentPage.blobSourceURL = page.blobSourceURL; }
        return;
    }
    // target=_blank is handled by createWebView using WebKit's configuration,
    // not replayed in the opener (including forms and window.opener flows).
    if (!action.targetFrame) { decisionHandler(WKNavigationActionPolicyAllow); return; }
    if (action.targetFrame.isMainFrame || !action.targetFrame) {
        page.mainNavigationRequest = action.request;
        page.navigationRequestedDownload = action.shouldPerformDownload || page.pendingRequestedDownload;
        page.pendingRequestedDownload = NO;
        page.reloadNavigation = action.navigationType == WKNavigationTypeReload;
        page.historyTraversal = action.navigationType == WKNavigationTypeBackForward;
        if (action.navigationType != WKNavigationTypeOther) page.attemptedHTTPSRecovery = NO;
    }
    // Defer HTML download attributes until MIME is known, including URLs without
    // a .pdf suffix. Explicit Save Download still uses WKDownload directly.
    decisionHandler(WKNavigationActionPolicyAllow);
}

- (WKWebView *)webView:(WKWebView *)webView createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration forNavigationAction:(WKNavigationAction *)action windowFeatures:(WKWindowFeatures *)windowFeatures {
    GewuBrowserPage *opener = [self pageForView:webView];
    BOOL blob = [action.request.URL isEqual:opener.blobRequestURL] && GewuBrowserBlobURL(action.request.URL, opener.blobSourceURL);
    if (webView != self.webView || !self.active || !self.visible || action.targetFrame
        || !(GewuBrowserPublicURL(action.request.URL) || blob || [action.request.URL.absoluteString isEqualToString:@"about:blank"])) return nil;
    GewuBrowserTab *origin = [self tabForPage:[self pageForView:webView]];
    GewuBrowserTab *tab = [self addTabWithRequest:action.request configuration:configuration];
    tab.originPaperID = origin.originPaperID; tab.originURL = origin.originURL; tab.originLibraryItemID = origin.originLibraryItemID; tab.workspaceReturnID = origin.workspaceReturnID; [self emitState];
    tab.currentPage.pendingRequestedDownload = action.shouldPerformDownload;
    if (blob) { tab.currentPage.blobRequestURL = opener.blobRequestURL; tab.currentPage.blobSourceURL = opener.blobSourceURL; }
    return tab.currentPage.view;
}
- (void)webViewDidClose:(WKWebView *)webView {
    GewuBrowserPage *page = [self pageForView:webView];
    if (page.allowsInitialBlank) [self closeTab:[self tabForPage:page]];
}

- (void)webView:(WKWebView *)webView decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler {
    GewuBrowserPage *page = [self pageForView:webView];
    if (!page || page == [self tabForPage:page].homePage) { decisionHandler(WKNavigationResponsePolicyCancel); return; }
    if (!response.forMainFrame && response.canShowMIMEType && GewuBrowserInternalFrameURL(response.response.URL)) {
        decisionHandler(WKNavigationResponsePolicyAllow); return;
    }
    BOOL blob = [response.response.URL isEqual:page.blobRequestURL] && GewuBrowserBlobURL(response.response.URL, page.blobSourceURL);
    if (!GewuBrowserPublicURL(response.response.URL) && !blob) { decisionHandler(WKNavigationResponsePolicyCancel); return; }
    if (response.forMainFrame) page.documentMIME = response.response.MIMEType;
    WKNavigationResponsePolicy policy = GewuBrowserResponsePolicy(response.response, response.canShowMIMEType,
        response.forMainFrame && page.navigationRequestedDownload);
    if (blob && response.forMainFrame) {
        // A page-generated file gets a public source address after displaying its
        // bytes; do not turn blob HTML into a privileged or persistent document.
        NSString *mime = response.response.MIMEType.lowercaseString ?: @"";
        policy = (GewuBrowserPDFResponse(response.response) || [mime containsString:@"octet-stream"])
            ? WKNavigationResponsePolicyDownload : WKNavigationResponsePolicyCancel;
    }
    // loadData already holds the received bytes, never start a second transfer.
    if (page.pendingPDFDocument && GewuBrowserPDFResponse(response.response)
        && ![response.response isKindOfClass:NSHTTPURLResponse.class]) policy = WKNavigationResponsePolicyAllow;
    page.downloadTransitionPending = policy == WKNavigationResponsePolicyDownload;
    decisionHandler(policy);
}

- (void)webView:(WKWebView *)webView didStartProvisionalNavigation:(WKNavigation *)navigation {
    if (webView == self.webView) self.navigationInputGeneration++;
    GewuBrowserPage *page = [self pageForView:webView];
    GewuBrowserTab *tab = [self tabForPage:page];
    if (!page || page != tab.currentPage) return;
    if (tab.contentPendingFromHome && tab.pendingHomeNavigation && tab.pendingHomeNavigation != navigation) return;
    if (navigation != page.pdfNavigation) {
        [self cancelPDFDownloadsForPage:page];
        page.pendingPDFDocument = nil;
    }
    page.failedURL = nil; page.errorMessage = nil;
    page.ready = NO;
    page.captureDocumentID = NSUUID.UUID.UUIDString; page.documentMIME = nil;
    page.capturedPDF = nil; page.capturedPDFURL = nil; page.capturedPDFFrame = nil;
    if (!page.reloadNavigation || !page.visitID) page.visitID = NSUUID.UUID.UUIDString;
    page.reloadNavigation = NO;
    if (webView == self.webView) {
        [self.loginTrigger cancelPending];
        [self emit:@{ @"event": @"navigation-start" }];
    }
    [self emitTabs];
}

- (void)recordCurrentHistory {
    [self recordHistoryForPage:self.currentPage];
}
- (void)recordHistoryForPage:(GewuBrowserPage *)page {
    GewuBrowserTab *tab = [self tabForPage:page];
    if (!tab || page != tab.currentPage || tab.contentPendingFromHome || page == tab.homePage) return;
    WKBackForwardList *list = page.view.backForwardList;
    NSMutableArray *items = [list.backList mutableCopy];
    [items addObjectsFromArray:list.forwardList];
    if (list.currentItem) [items addObject:list.currentItem];
    NSDictionary *generated = page.captureDocumentID ? [page.pdfDocuments objectForKey:page.captureDocumentID] : nil;
    if (generated && page.ready && list.currentItem) {
        [page.pdfDocuments setObject:generated forKey:list.currentItem];
        [page.pdfDocuments removeObjectForKey:page.captureDocumentID];
    }
    [tab.session pruneSurface:page validItems:items];
    [tab.session recordSurface:page item:list.currentItem
        home:NO
        traversal:page.historyTraversal];
    page.historyTraversal = NO;
    if (tab == self.selectedTab) [self emitState]; else [self emitTabs];
}

- (void)webView:(WKWebView *)webView didCommitNavigation:(WKNavigation *)navigation {
    GewuBrowserPage *page = [self pageForView:webView];
    GewuBrowserTab *tab = [self tabForPage:page];
    if (!page || page != tab.currentPage) return;
    if (tab.contentPendingFromHome) {
        if (tab.pendingHomeNavigation && navigation != tab.pendingHomeNavigation) return;
        // Commit replaces the old document. Provisional starts, redirects and
        // URL/progress notifications must never reveal the reused view early.
        tab.contentPendingFromHome = NO; tab.pendingHomeNavigation = nil;
        tab.homePage.view.hidden = YES;
        if (tab == self.selectedTab) [self updatePageVisibility];
    }
    page.ready = NO; page.terminated = NO;
    [self recordHistoryForPage:page];
    if (page.pendingPDFDocument && page.pdfNavigation == navigation
        && [page.view.backForwardList.currentItem.URL isEqual:page.view.URL]) {
        if (!page.pdfDocuments) page.pdfDocuments = [NSMapTable strongToStrongObjectsMapTable];
        [page.pdfDocuments setObject:page.pendingPDFDocument forKey:page.view.backForwardList.currentItem];
        page.pendingPDFDocument = nil; page.pdfNavigation = nil;
        [self trimPDFCache];
    }
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    GewuBrowserPage *page = [self pageForView:webView];
    GewuBrowserTab *tab = [self tabForPage:page];
    if (!page || page != tab.currentPage || tab.contentPendingFromHome) return;
    page.ready = YES; page.terminated = NO; page.attemptedHTTPSRecovery = NO;
    if (page.pendingPDFDocument && page.pdfNavigation == navigation) {
        // A new popup's first loadData may finish before WebKit creates a history
        // item. Bind it to this document generation until an item is available.
        if (!page.pdfDocuments) page.pdfDocuments = [NSMapTable strongToStrongObjectsMapTable];
        id key = page.view.backForwardList.currentItem ?: (id)page.captureDocumentID;
        if (key) [page.pdfDocuments setObject:page.pendingPDFDocument forKey:key];
        page.pendingPDFDocument = nil; page.pdfNavigation = nil;
        [self recordHistoryForPage:page]; [self trimPDFCache];
    }
    if ([self PDFDocumentForPage:page]) page.documentMIME = @"application/pdf";
    if (webView == self.webView) { [self emitState]; } else [self emitTabs];
    NSURL *pageURL = webView.URL;
    if (GewuBrowserPublicURL(pageURL)) {
        [webView evaluateJavaScript:@"Array.from(document.querySelectorAll('link[rel]')).find(x => x.rel.toLowerCase().split(/\\s+/).includes('icon'))?.href || ''" completionHandler:^(id value, NSError *error) {
            if (!error && [value isKindOfClass:NSString.class]) [self.favicons preferIcon:[NSURL URLWithString:value] forPage:pageURL];
            // The tab strip also needs an icon when this site is not bookmarked.
            if ([self pageForView:webView]) [self.favicons requestURL:pageURL];
        }];
    }
    if (GewuBrowserPublicURL(webView.URL)) [self emit:@{ @"event": @"visit", @"event_id": page.visitID ?: NSUUID.UUID.UUIDString,
        @"url": webView.URL.absoluteString, @"title": webView.title ?: webView.URL.host ?: @"Webpage" }];
}

- (void)navigationFailed:(NSError *)error {
    [self navigationFailed:error inPage:self.currentPage];
}
- (void)navigationFailed:(NSError *)error inPage:(GewuBrowserPage *)page {
    if (![self tabForPage:page]) return;
    if (page.downloadTransitionPending && error.code == 102
        && ([error.domain isEqual:@"WebKitErrorDomain"] || [error.domain isEqual:WKErrorDomain])) return;
    if (error.code == NSURLErrorCancelled || (error.code == 102 && [error.domain isEqualToString:WKErrorDomain])) return;
    NSURL *secureURL = GewuBrowserHTTPSRecoveryURL(error, page.mainNavigationRequest, page.attemptedHTTPSRecovery);
    if (GewuBrowserPublicURL(secureURL)) {
        page.attemptedHTTPSRecovery = YES;
        WKNavigation *navigation = [page.view loadRequest:[NSURLRequest requestWithURL:secureURL]];
        GewuBrowserTab *tab = [self tabForPage:page];
        if (tab.contentPendingFromHome) tab.pendingHomeNavigation = navigation;
        return;
    }
    id failed = error.userInfo[NSURLErrorFailingURLErrorKey];
    page.failedURL = [failed isKindOfClass:NSURL.class] && GewuBrowserPublicURL(failed) ? failed : page.mainNavigationRequest.URL;
    page.errorMessage = GewuBrowserNavigationErrorMessage(error);
    if (page == self.currentPage) [self emitState]; else [self emitTabs];
}
- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    GewuBrowserPage *page = [self pageForView:webView];
    if ((page.downloadTransitionPending || page.openingPDF) && error.code == 102
        && ([error.domain isEqual:@"WebKitErrorDomain"] || [error.domain isEqual:WKErrorDomain])) return;
    GewuBrowserTab *tab = [self tabForPage:page];
    if (tab.contentPendingFromHome) {
        if (page != tab.currentPage || (tab.pendingHomeNavigation && navigation != tab.pendingHomeNavigation)) return;
        if (error.code == NSURLErrorCancelled || (error.code == 102 && [error.domain isEqualToString:WKErrorDomain])) {
            [self returnToRetainedHomeInTab:tab]; return;
        }
    }
    [self navigationFailed:error inPage:page];
}
- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    GewuBrowserPage *page = [self pageForView:webView];
    if ([self tabForPage:page].contentPendingFromHome) return;
    [self navigationFailed:error inPage:page];
}
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    GewuBrowserPage *page = [self pageForView:webView];
    if (page == [self tabForPage:page].homePage) return;
    page.terminated = YES; page.ready = NO;
    page.errorMessage = @"The webpage process stopped. Reload to continue; your bookmarks and history are safe.";
    if (webView != self.webView) { [self emitTabs]; return; }
    [self emitState];
    [self emit:@{ @"event": @"error", @"message": @"The webpage process stopped. Reload to continue; your bookmarks and history are safe." }];
}

- (void)webView:(WKWebView *)webView runJavaScriptAlertPanelWithMessage:(NSString *)message initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(void))completionHandler {
    if (webView != self.webView || !self.active || self.workspace.window.attachedSheet) { completionHandler(); return; }
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = frame.request.URL.host ?: @"Website message";
    alert.informativeText = [message substringToIndex:MIN(message.length, 2000)];
    [alert addButtonWithTitle:@"OK"];
    [alert beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) { completionHandler(); }];
}
- (void)webView:(WKWebView *)webView runJavaScriptConfirmPanelWithMessage:(NSString *)message initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(BOOL))completionHandler {
    if (webView != self.webView || !self.active || self.workspace.window.attachedSheet) { completionHandler(NO); return; }
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = frame.request.URL.host ?: @"Website confirmation";
    alert.informativeText = [message substringToIndex:MIN(message.length, 2000)];
    [alert addButtonWithTitle:@"OK"]; [alert addButtonWithTitle:@"Cancel"];
    [alert beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) { completionHandler(response == NSAlertFirstButtonReturn); }];
}
- (void)webView:(WKWebView *)webView runJavaScriptTextInputPanelWithPrompt:(NSString *)prompt defaultText:(NSString *)defaultText initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSString *))completionHandler {
    if (webView != self.webView || !self.active || self.workspace.window.attachedSheet) { completionHandler(nil); return; }
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = frame.request.URL.host ?: @"Website input";
    alert.informativeText = [prompt substringToIndex:MIN(prompt.length, 2000)];
    NSTextField *input = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 320, 24)]; input.stringValue = defaultText ?: @"";
    alert.accessoryView = input;
    [alert addButtonWithTitle:@"OK"]; [alert addButtonWithTitle:@"Cancel"];
    [alert beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) { completionHandler(response == NSAlertFirstButtonReturn ? input.stringValue : nil); }];
}
- (void)webView:(WKWebView *)webView runOpenPanelWithParameters:(WKOpenPanelParameters *)parameters initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSArray<NSURL *> *))completionHandler {
    if (webView != self.webView || !self.active || self.workspace.window.attachedSheet) { completionHandler(nil); return; }
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.message = [NSString stringWithFormat:@"Choose files to upload to %@", frame.request.URL.host ?: @"this website"];
    panel.allowsMultipleSelection = parameters.allowsMultipleSelection;
    panel.canChooseDirectories = parameters.allowsDirectories;
    [panel beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) { completionHandler(response == NSModalResponseOK ? panel.URLs : nil); }];
}

- (void)registerDownload:(WKDownload *)download {
    if (!download) return;
    if (self.invalidated) { [download cancel:nil]; return; }
    download.delegate = self;
    [self.downloads setObject:[NSMutableDictionary dictionary] forKey:download];
}
- (NSDictionary *)PDFDocumentForPage:(GewuBrowserPage *)page {
    if (!page.pdfDocuments) return nil;
    return [page.pdfDocuments objectForKey:page.view.backForwardList.currentItem]
        ?: [page.pdfDocuments objectForKey:page.captureDocumentID];
}
- (void)trimPDFCache {
    NSMutableArray *cached = [NSMutableArray array];
    NSUInteger bytes = 0;
    for (GewuBrowserTab *tab in self.tabs) {
        GewuBrowserPage *page = tab.contentPage;
        WKBackForwardList *list = page.view.backForwardList;
        NSMutableArray *valid = [NSMutableArray arrayWithArray:list.backList ?: @[]];
        [valid addObjectsFromArray:list.forwardList ?: @[]];
        if (list.currentItem) [valid addObject:list.currentItem];
        if (page.captureDocumentID) [valid addObject:page.captureDocumentID];
        for (id item in page.pdfDocuments.keyEnumerator.allObjects) {
            NSDictionary *doc = [page.pdfDocuments objectForKey:item];
            if (![valid containsObject:item]) { [page.pdfDocuments removeObjectForKey:item]; continue; }
            bytes += [doc[@"data"] length];
            [cached addObject:@{@"page":page, @"item":item, @"doc":doc}];
        }
    }
    [cached sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) { return [a[@"doc"][@"date"] compare:b[@"doc"][@"date"]]; }];
    NSUInteger count = cached.count;
    for (NSDictionary *entry in cached) {
        if (bytes <= 256 * 1024 * 1024 && count <= 8) break;
        GewuBrowserPage *page = entry[@"page"];
        bytes -= [entry[@"doc"][@"data"] length]; count--;
        [page.pdfDocuments removeObjectForKey:entry[@"item"]];
    }
}
// WebKit's native PDF HUD hands its in-memory PDF to this optional delegate
// callback. Without it, its download button has no host save implementation.
- (void)_webView:(WKWebView *)webView saveDataToFile:(NSData *)data suggestedFilename:(NSString *)filename mimeType:(NSString *)mimeType originatingURL:(NSURL *)url {
    GewuBrowserPage *page = [self pageForView:webView];
    if (!page || self.invalidated || ![mimeType.lowercaseString containsString:@"pdf"] || !GewuBrowserPublicURL(url)) return;
    [self emit:@{@"event":@"download", @"message":@"Preparing the loaded PDF…"}];
    if (page.exportingPDF) return;
    page.exportingPDF = YES;
    NSString *generation = page.captureDocumentID;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        GewuBrowserPDFFile *file = [GewuBrowserPDFFile fileWithData:data filename:filename];
        dispatch_async(dispatch_get_main_queue(), ^{
            page.exportingPDF = NO;
            if (self.invalidated || ![self tabForPage:page] || ![page.captureDocumentID isEqual:generation]) return;
            if (!file) { [self emit:@{@"event":@"error", @"message":@"WebKit did not provide a complete PDF up to 128 MB."}]; return; }
            [self saveDisplayedPDF:@{@"file":file, @"filename":file.filename}];
        });
    });
}
- (void)saveDisplayedPDF:(NSDictionary *)pdf {
    if (!self.workspace.window || self.workspace.window.attachedSheet) {
        [self emit:@{@"event":@"error", @"message":@"Close the open dialog, then click Save Download again."}]; return;
    }
    NSSavePanel *panel = [NSSavePanel savePanel];
    panel.title = @"Save Download"; panel.nameFieldStringValue = pdf[@"filename"] ?: @"Article.pdf";
    panel.directoryURL = [NSFileManager.defaultManager URLsForDirectory:NSDownloadsDirectory inDomains:NSUserDomainMask].firstObject;
    [panel beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse result) {
        if (result != NSModalResponseOK || !panel.URL) { [self emit:@{@"event":@"download", @"message":@"Save cancelled."}]; return; }
        NSURL *destination = panel.URL;
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            GewuBrowserPDFFile *file = pdf[@"file"];
            NSData *data = file ? [NSData dataWithContentsOfURL:file.URL options:NSDataReadingMappedIfSafe error:nil] : pdf[@"data"];
            BOOL saved = [data writeToURL:destination options:NSDataWritingAtomic error:nil];
            dispatch_async(dispatch_get_main_queue(), ^{
                [self emit:@{@"event":saved ? @"download" : @"error", @"message":saved ? @"File saved to the selected location." : @"The file could not be saved to the selected location."}];
            });
        });
    }];
}
- (void)cancelPDFDownloadsForPage:(GewuBrowserPage *)page {
    for (WKDownload *download in self.downloads.keyEnumerator.allObjects) {
        NSDictionary *context = [self.downloads objectForKey:download];
        if (context[@"page"] != page) continue;
        [context[@"timer"] invalidate];
        NSURL *directory = context[@"directory"];
        download.delegate = nil;
        [download cancel:^(NSData *resume) { if (directory) [NSFileManager.defaultManager removeItemAtURL:directory error:nil]; }];
        [self.downloads removeObjectForKey:download];
    }
    page.openingPDF = NO; page.downloadTransitionPending = NO;
}
- (void)registerPageDownload:(WKDownload *)download view:(WKWebView *)view {
    GewuBrowserPage *page = [self pageForView:view];
    if (!page) { [download cancel:nil]; return; }
    [self cancelPDFDownloadsForPage:page];
    [self registerDownload:download];
    NSMutableDictionary *context = [self.downloads objectForKey:download];
    context[@"page"] = page; context[@"generation"] = page.captureDocumentID ?: @"";
    context[@"source"] = page.blobSourceURL ?: view.URL ?: page.mainNavigationRequest.URL;
    page.downloadTransitionPending = YES;
}
- (void)failPDFDownload:(WKDownload *)download message:(NSString *)message {
    NSDictionary *context = [self.downloads objectForKey:download];
    GewuBrowserPage *page = context[@"page"];
    if (!page) return;
    if (GewuBrowserPublicURL(context[@"source"])) page.failedURL = context[@"source"];
    [self cancelPDFDownloadsForPage:page];
    if (![self tabForPage:page]) return;
    page.errorMessage = message;
    if (page == self.currentPage) [self emitState]; else [self emitTabs];
}
- (void)webView:(WKWebView *)webView navigationAction:(WKNavigationAction *)navigationAction didBecomeDownload:(WKDownload *)download {
    [self registerPageDownload:download view:webView];
}
- (void)webView:(WKWebView *)webView navigationResponse:(WKNavigationResponse *)navigationResponse didBecomeDownload:(WKDownload *)download {
    [self registerPageDownload:download view:webView];
}
- (void)download:(WKDownload *)download willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request decisionHandler:(void (^)(WKDownloadRedirectPolicy))decisionHandler {
    decisionHandler(GewuBrowserPublicURL(request.URL) ? WKDownloadRedirectPolicyAllow : WKDownloadRedirectPolicyCancel);
}
- (void)download:(WKDownload *)download decideDestinationUsingResponse:(NSURLResponse *)response suggestedFilename:(NSString *)suggestedFilename completionHandler:(void (^)(NSURL *))completionHandler {
    NSMutableDictionary *context = [self.downloads objectForKey:download];
    if (!context || self.invalidated) { completionHandler(nil); return; }
    GewuBrowserPage *page = context[@"page"];
    NSString *mime = response.MIMEType.lowercaseString ?: @"";
    BOOL binary = [@[@"application/octet-stream", @"binary/octet-stream"] containsObject:mime];
    BOOL pdf = GewuBrowserPDFResponse(response) || binary
        || ([suggestedFilename.pathExtension.lowercaseString isEqual:@"pdf"] && ![mime isEqual:@"text/html"]);
    if (page && pdf) {
        if (!GewuBrowserPublicURL(response.URL) && !([response.URL isEqual:page.blobRequestURL] && GewuBrowserBlobURL(response.URL, page.blobSourceURL))) {
            completionHandler(nil); [self failPDFDownload:download message:@"The PDF returned an unsupported address."]; return;
        }
        if (response.expectedContentLength > 128 * 1024 * 1024) {
            completionHandler(nil); [self failPDFDownload:download message:@"This PDF exceeds the 128 MB preview limit. Use Save Download to choose a file location."]; return;
        }
        NSURL *directory = [NSURL fileURLWithPath:[NSTemporaryDirectory() stringByAppendingPathComponent:[@"gewu-browser-pdf-" stringByAppendingString:NSUUID.UUID.UUIDString]] isDirectory:YES];
        if (![NSFileManager.defaultManager createDirectoryAtURL:directory withIntermediateDirectories:NO attributes:@{NSFilePosixPermissions:@0700} error:nil]) {
            completionHandler(nil); [self failPDFDownload:download message:@"Could not prepare the PDF preview."]; return;
        }
        context[@"directory"] = directory; context[@"staging"] = [directory URLByAppendingPathComponent:@"preview.pdf"];
        context[@"preview"] = @YES; context[@"binary"] = @(binary);
        context[@"filename"] = suggestedFilename.lastPathComponent.length ? suggestedFilename.lastPathComponent : @"Article.pdf";
        context[@"source"] = GewuBrowserPublicURL(response.URL) ? response.URL : page.blobSourceURL;
        page.openingPDF = YES; page.pdfProgress = 0; page.errorMessage = nil;
        __weak typeof(self) weakSelf = self;
        __weak WKDownload *weakDownload = download;
        NSDate *started = NSDate.date;
        context[@"timer"] = [NSTimer scheduledTimerWithTimeInterval:0.5 repeats:YES block:^(NSTimer *timer) {
            typeof(self) self = weakSelf; WKDownload *download = weakDownload;
            NSDictionary *current = [self.downloads objectForKey:download];
            if (!current) { [timer invalidate]; return; }
            NSNumber *size = [NSFileManager.defaultManager attributesOfItemAtPath:[current[@"staging"] path] error:nil][NSFileSize];
            if (size.unsignedLongLongValue > 128 * 1024 * 1024 || -started.timeIntervalSinceNow > 120) {
                [self failPDFDownload:download message:@"The PDF preview exceeded its size or time limit. Retry or use Save Download."]; return;
            }
            page.pdfProgress = download.progress.fractionCompleted;
            if (page == self.currentPage) [self emitState]; else [self emitTabs];
        }];
        if (page == self.currentPage) [self emitState]; else [self emitTabs];
        completionHandler(context[@"staging"]); return;
    }
    // Other attachments and the explicit Save Download command still ask for a
    // destination. Never silently write them to Downloads.
    page.downloadTransitionPending = NO;
    if (page) { [context removeObjectForKey:@"page"]; [self returnToRetainedHomeInTab:[self tabForPage:page]]; }
    if (!self.workspace.window || self.workspace.window.attachedSheet) { completionHandler(nil); [self.downloads removeObjectForKey:download]; return; }
    NSSavePanel *panel = [NSSavePanel savePanel];
    panel.title = @"Save Download";
    panel.nameFieldStringValue = suggestedFilename.lastPathComponent.length ? suggestedFilename.lastPathComponent : @"Download";
    panel.directoryURL = [[NSFileManager defaultManager] URLsForDirectory:NSDownloadsDirectory inDomains:NSUserDomainMask].firstObject;
    panel.canCreateDirectories = YES;
    [panel beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse result) {
        if (result != NSModalResponseOK || !panel.URL) { completionHandler(nil); [self.downloads removeObjectForKey:download]; return; }
        NSURL *temporary = [NSURL fileURLWithPath:[NSTemporaryDirectory() stringByAppendingPathComponent:[@"gewu-browser-" stringByAppendingString:NSUUID.UUID.UUIDString]] isDirectory:YES];
        NSError *error = nil;
        if (![[NSFileManager defaultManager] createDirectoryAtURL:temporary withIntermediateDirectories:NO attributes:nil error:&error]) { completionHandler(nil); return; }
        NSURL *staging = [temporary URLByAppendingPathComponent:@"download"];
        NSMutableDictionary *context = [self.downloads objectForKey:download];
        context[@"directory"] = temporary; context[@"staging"] = staging; context[@"destination"] = panel.URL;
        context[@"replace"] = @([[NSFileManager defaultManager] fileExistsAtPath:panel.URL.path]);
        [self emit:@{ @"event": @"download", @"message": @"Downloading with the browser session. You can keep browsing." }];
        completionHandler(staging);
    }];
}
- (void)downloadDidFinish:(WKDownload *)download {
    NSDictionary *context = [self.downloads objectForKey:download];
    if (!context) return;
    if ([context[@"preview"] boolValue]) {
        [context[@"timer"] invalidate];
        GewuBrowserPage *page = context[@"page"];
        NSURL *file = context[@"staging"], *directory = context[@"directory"];
        __weak typeof(self) weakSelf = self;
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            NSData *data = [NSData dataWithContentsOfURL:file options:NSDataReadingMappedIfSafe error:nil];
            NSData *prefix = [data subdataWithRange:NSMakeRange(0, MIN(data.length, 1024))];
            BOOL valid = data.length > 0 && data.length <= 128 * 1024 * 1024
                && [prefix rangeOfData:[@"%PDF-" dataUsingEncoding:NSASCIIStringEncoding] options:0 range:NSMakeRange(0, prefix.length)].location != NSNotFound;
            [NSFileManager.defaultManager removeItemAtURL:directory error:nil];
            dispatch_async(dispatch_get_main_queue(), ^{
                typeof(self) self = weakSelf;
                if (!self || self.invalidated || [self.downloads objectForKey:download] != context) return;
                if (!valid && [context[@"binary"] boolValue] && data.length && data.length <= 128 * 1024 * 1024) {
                    [self.downloads removeObjectForKey:download];
                    page.openingPDF = NO; page.downloadTransitionPending = NO;
                    [self saveDisplayedPDF:@{@"data":data, @"filename":context[@"filename"]}];
                    [self emitState]; return;
                }
                if (!valid) { [self failPDFDownload:download message:@"The website returned a file that is not a readable PDF. Return to the website and check its download or sign-in page."]; return; }
                [self.downloads removeObjectForKey:download];
                page.openingPDF = NO; page.downloadTransitionPending = NO;
                GewuBrowserTab *tab = [self tabForPage:page];
                if (!tab || tab.currentPage != page || ![(page.captureDocumentID ?: @"") isEqual:context[@"generation"]]) return;
                page.pendingPDFDocument = [@{@"data":data, @"filename":context[@"filename"], @"date":NSDate.date} mutableCopy];
                page.navigationRequestedDownload = NO;
                page.pdfNavigation = [page.view loadData:data MIMEType:@"application/pdf" characterEncodingName:@"UTF-8" baseURL:context[@"source"]];
                if (tab.contentPendingFromHome) tab.pendingHomeNavigation = page.pdfNavigation;
                if (page == self.currentPage) [self emitState]; else [self emitTabs];
            });
        });
        return;
    }
    NSURL *target = context[@"destination"], *staging = context[@"staging"];
    NSFileManager *manager = [NSFileManager defaultManager];
    NSError *error = nil;
    BOOL saved = NO;
    if (target && staging) {
        if ([context[@"replace"] boolValue] && [manager fileExistsAtPath:target.path]) saved = [manager replaceItemAtURL:target withItemAtURL:staging backupItemName:nil options:0 resultingItemURL:nil error:&error];
        else saved = [manager moveItemAtURL:staging toURL:target error:&error];
    }
    if (saved) {
        // Browser downloads are not imported into the paper catalog.
        [self emit:@{ @"event": @"download", @"message": [NSString stringWithFormat:@"Saved %@", target.lastPathComponent] }];
        if (context[@"directory"]) [manager removeItemAtURL:context[@"directory"] error:nil];
    } else {
        // Keep the completed download recoverable if the destination changed.
        [self emit:@{ @"event": @"error", @"message": @"The download finished but could not be moved to the chosen location. Its temporary copy has been preserved." }];
        if (staging) [[NSWorkspace sharedWorkspace] activateFileViewerSelectingURLs:@[staging]];
    }
    [self.downloads removeObjectForKey:download];
}
- (void)download:(WKDownload *)download didFailWithError:(NSError *)error resumeData:(NSData *)resumeData {
    NSDictionary *context = [self.downloads objectForKey:download];
    if (!context) return;
    if ([context[@"preview"] boolValue]) {
        [self failPDFDownload:download message:@"The PDF download failed. Return to the website and retry after checking its session and network."]; return;
    }
    NSURL *directory = context[@"directory"];
    if (directory) [[NSFileManager defaultManager] removeItemAtURL:directory error:nil];
    [self.downloads removeObjectForKey:download];
    if (error.code != NSURLErrorCancelled) [self emit:@{ @"event": @"error", @"message": [NSString stringWithFormat:@"Download failed (%@ %ld). Check the website session and network, then try again. Existing files were not changed.", error.domain, (long)error.code] }];
}
- (void)invalidate {
    if (self.invalidated) return;
    self.invalidated = YES;
    self.captureBackdropRequestID = nil;
    [self.loginTrigger cancelPending];
    if (self.keyMonitor) [NSEvent removeMonitor:self.keyMonitor];
    self.keyMonitor = nil;
    [self.favicons invalidate];
    for (GewuBrowserCapture *capture in self.captures.allValues) [capture cancel];
    [self.captures removeAllObjects]; [self.captureSnapshots removeAllObjects];
    [self.suggestionsView removeFromSuperview]; self.suggestionsView = nil; self.suggestionItems = nil;
    for (WKDownload *download in self.downloads.keyEnumerator.allObjects) {
        NSDictionary *context = [self.downloads objectForKey:download];
        [context[@"timer"] invalidate]; download.delegate = nil;
        NSURL *directory = context[@"directory"];
        [download cancel:^(NSData *resume) { if (directory) [NSFileManager.defaultManager removeItemAtURL:directory error:nil]; }];
    }
    [self.downloads removeAllObjects];
    for (GewuBrowserTab *tab in self.tabs) {
        [self disposePage:tab.homePage]; [self disposePage:tab.contentPage];
        [tab.session.entries removeAllObjects];
    }
    [self.tabs removeAllObjects]; self.selectedTab = nil; self.webView = nil;
}
@end
