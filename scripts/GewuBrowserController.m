#import "GewuBrowserController.h"
#import "GewuBrowserNavigation.h"
#import "GewuBrowserFavicons.h"
#import "GewuBrowserSession.h"
#import "GewuBrowserAutoFill.h"
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

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
@property(nonatomic) BOOL homeZoomApplied;
@property(nonatomic) double previousPageZoom;
@property(nonatomic) BOOL ready;
@property(nonatomic) BOOL terminated;
@property(nonatomic) BOOL historyTraversal;
@property(nonatomic) BOOL allowsInitialBlank;
@property(nonatomic, copy) NSString *errorMessage;
@end
@implementation GewuBrowserPage
@end

@interface GewuBrowserTab : NSObject
@property(nonatomic, copy) NSString *identifier;
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
@property(nonatomic, strong) WKWebsiteDataStore *browserDataStore;
@property(nonatomic) BOOL active;
@property(nonatomic) BOOL visible;
@property(nonatomic) BOOL canReturnToWorkspace;
@property(nonatomic) BOOL initializing;
@property(nonatomic) BOOL invalidated;
@property(nonatomic, strong) id keyMonitor;
@property(nonatomic, strong) NSMapTable<WKDownload *, NSMutableDictionary *> *downloads;
@property(nonatomic, strong) GewuBrowserFavicons *favicons;
@property(nonatomic, strong) NSView *suggestionsView;
@property(nonatomic, copy) NSArray<NSDictionary *> *suggestionItems;
@property(nonatomic) NSUInteger homeFitGeneration;
@property(nonatomic, strong) GewuBrowserAutoFill *loginTrigger;
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
    self.homePage.view.hidden = !self.visible || presented != self.homePage;
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
        NSString *url = (tab.contentPendingFromHome ? presented.view.URL : (page.failedURL ?: page.view.URL ?: page.mainNavigationRequest.URL)).absoluteString ?: @"";
        NSString *title = presented.view.title;
        if (!title.length) title = GewuBrowserGoogleHome([NSURL URLWithString:url]) || !url.length ? @"Home" : [NSURL URLWithString:url].host ?: @"New Tab";
        [items addObject:@{@"id":tab.identifier, @"title":title, @"url":url, @"loading":@(page.view.loading || (tab.contentPendingFromHome && !page.errorMessage.length))}];
    }
    [self emit:@{@"event":@"tabs", @"tabs":items, @"selected":self.selectedTab.identifier ?: @""}];
}
- (void)selectTab:(GewuBrowserTab *)tab {
    if (!tab || ![self.tabs containsObject:tab] || tab == self.selectedTab) return;
    [self.loginTrigger cancelPending];
    self.homeFitGeneration++;
    NSRect previousFrame = [self presentedPageForTab:self.selectedTab].view.frame;
    // Tab switches do not stop loads, replay requests, or replace documents.
    self.homePage.view.hidden = YES; self.contentPage.view.hidden = YES;
    self.suggestionsView.hidden = YES;
    self.selectedTab = tab;
    self.webView = tab.currentPage.view;
    if (!GewuBrowserGoogleHome(self.webView.URL)) [self restorePageZoom];
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
    if (!(flags & NSEventModifierFlagCommand)
        || (flags & (NSEventModifierFlagShift | NSEventModifierFlagOption | NSEventModifierFlagControl))
        || ![event.charactersIgnoringModifiers isEqualToString:@"["]) return NO;
    if (event.isARepeat) return YES;
    self.canReturnToWorkspace = NO;
    [self.workspace.window makeFirstResponder:self.workspace];
    [self emit:@{@"event":@"return-workspace"}];
    return YES;
}

- (void)emit:(NSDictionary *)event {
    if (self.onEvent && !self.invalidated) self.onEvent(event);
}

- (void)emitState {
    if (!self.webView) return;
    BOOL pending = self.selectedTab.contentPendingFromHome;
    WKWebView *presented = [self presentedPageForTab:self.selectedTab].view;
    [self emit:@{ @"event": @"state", @"url": (pending ? presented.URL : (self.currentPage.failedURL ?: self.webView.URL)).absoluteString ?: @"",
        @"title": presented.title ?: @"", @"loading": @(self.webView.loading || (pending && !self.currentPage.errorMessage.length)),
        @"progress": @(self.webView.estimatedProgress), @"canBack": @(self.session.index > 0),
        @"canForward": @(self.session.index + 1 < self.session.entries.count),
        @"tab_id":self.selectedTab.identifier ?: @"", @"error":self.currentPage.errorMessage ?: @"" }];
    [self emitTabs];
}

- (GewuBrowserPage *)makePage {
    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    // Dedicated persistent profile. No Safari cookie import, app script handlers,
    // process-wide proxy overrides, HTML rewriting, or background publisher driver.
    NSUUID *profile = [[NSUUID alloc] initWithUUIDString:@"19E88B78-44C0-4C42-B496-F2C7F625B507"];
    if (!self.browserDataStore) self.browserDataStore = [WKWebsiteDataStore dataStoreForIdentifier:profile];
    configuration.websiteDataStore = self.browserDataStore;
    // Keep WebKit's system-generated OS/engine/version tokens. The compatibility
    // suffix prevents sites from mistaking desktop WKWebView for a text-only
    // client; retain our own product token rather than hiding the embedding app.
    configuration.applicationNameForUserAgent = @"Safari/605.1.15 GewuInsight/0.1";
    configuration.preferences.javaScriptCanOpenWindowsAutomatically = NO;
    configuration.userContentController = [[WKUserContentController alloc] init];
    return [self makePageWithConfiguration:configuration];
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
    self.homeFitGeneration++;
    [self.webView stopLoading];
    self.homePage.view.hidden = YES; self.contentPage.view.hidden = YES;
    self.selectedTab.contentPendingFromHome = NO; self.selectedTab.pendingHomeNavigation = nil;
    self.suggestionsView.hidden = YES;
    NSRect previousFrame = self.webView.frame;
    self.currentPage = page;
    self.webView = page.view;
    // A cached Home keeps its fitted dimensions until local chrome sends the
    // next layout, avoiding an intermediate full-height Home and zoom flash.
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
    // No request, reload, reconstructed HTML, or credential copying on a warm
    // Home. Explicit Reload is separate. Cold/terminated pages load on demand.
    if (!self.homePage.ready || self.homePage.terminated || !GewuBrowserGoogleHome(self.webView.URL)) {
        if (!self.webView.loading) [self.webView loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://www.google.com/"]]];
    }
    [self emitState];
}

- (void)openContentRequest:(NSURLRequest *)request {
    if (!self.contentPage) self.contentPage = [self makePage];
    BOOL fromHome = self.selectedTab.contentPendingFromHome || (self.currentPage == self.homePage
        && self.homePage.ready && GewuBrowserGoogleHome(self.homePage.view.URL));
    if (fromHome) {
        [self.loginTrigger cancelPending]; self.homeFitGeneration++;
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
        if ([keyPath isEqualToString:@"URL"] && !GewuBrowserGoogleHome(self.webView.URL)) [self restorePageZoom];
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

- (void)restorePageZoom {
    self.homeFitGeneration++;
    if (self.currentPage.homeZoomApplied) {
        self.webView.pageZoom = self.currentPage.previousPageZoom;
        [self.webView evaluateJavaScript:@"document.getElementById('gewu-insight-home-surface')?.remove()" completionHandler:nil];
    }
    self.currentPage.homeZoomApplied = NO;
}

- (void)fitHomeGeneration:(NSUInteger)generation attempts:(NSUInteger)attempts {
    if (generation != self.homeFitGeneration || !self.visible || self.invalidated || self.webView.loading
        || !GewuBrowserGoogleHome(self.webView.URL)) return;
    // Hide only Home's secondary language/region/footer chrome. Return
    // dimensions only: no form reads, input/scroll handlers or focus changes.
    NSString *geometry = @"(() => { const u = new URL(location.href);"
        "if (u.protocol !== 'https:' || !['google.com','www.google.com'].includes(u.hostname) || u.port || !['/','/webhp'].includes(u.pathname) || u.searchParams.has('q')) return null;"
        "if (!document.getElementById('gewu-insight-home-surface')) {"
        "const s = document.createElement('style'); s.id = 'gewu-insight-home-surface';"
        "s.textContent = 'footer, #fbar, [role=contentinfo], #SIvCob, #gws-output-pages-elements-homepage_additional_languages__als { display: none !important; }';"
        "document.head.appendChild(s); }"
        "return {width:innerWidth,height:innerHeight,contentWidth:document.documentElement.scrollWidth,contentHeight:document.documentElement.scrollHeight}; })()";
    [self.webView evaluateJavaScript:geometry completionHandler:^(id value, NSError *error) {
        if (error || ![value isKindOfClass:NSDictionary.class] || generation != self.homeFitGeneration
            || !self.visible || self.invalidated || self.webView.loading || !GewuBrowserGoogleHome(self.webView.URL)) return;
        double zoom = GewuBrowserHomeFitZoom(self.webView.pageZoom, [value[@"width"] doubleValue], [value[@"height"] doubleValue],
            [value[@"contentWidth"] doubleValue], [value[@"contentHeight"] doubleValue]);
        if (fabs(zoom - self.webView.pageZoom) < .001) return;
        self.webView.pageZoom = zoom;
        if (attempts > 1) dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 60 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
            [self fitHomeGeneration:generation attempts:attempts - 1];
        });
    }];
}

- (void)scheduleHomeFit {
    if (!self.visible || self.webView.loading || !GewuBrowserGoogleHome(self.webView.URL)) return;
    if (!self.currentPage.homeZoomApplied) self.currentPage.previousPageZoom = self.webView.pageZoom;
    self.currentPage.homeZoomApplied = YES;
    NSUInteger generation = ++self.homeFitGeneration;
    // Coalesce live window/sidebar resizing, then fit at most three times.
    // Nothing polls in the background or runs on ordinary webpages.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 80 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
        if (generation != self.homeFitGeneration || self.invalidated || !self.visible || !GewuBrowserGoogleHome(self.webView.URL)) return;
        self.webView.pageZoom = self.currentPage.previousPageZoom;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 60 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
            [self fitHomeGeneration:generation attempts:3];
        });
    });
}

- (void)handleCommand:(NSDictionary *)command {
    NSString *action = [command[@"action"] isKindOfClass:NSString.class] ? command[@"action"] : @"";
    if ([action isEqualToString:@"layout"]) {
        self.active = [command[@"active"] boolValue];
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
        if (resized) [self scheduleHomeFit];
        if (!shown) self.suggestionsView.hidden = YES;
        if (!shown && [self.workspace.window.firstResponder isKindOfClass:NSView.class]
            && [(NSView *)self.workspace.window.firstResponder isDescendantOf:self.webView]) {
            [self.workspace.window makeFirstResponder:self.workspace];
        }
        return;
    }
    if (!self.active) return;
    [self ensureWebView];
    if ([action isEqualToString:@"new-tab"]) {
        NSString *value = [command[@"url"] isKindOfClass:NSString.class] ? command[@"url"] : nil;
        NSURL *url = value.length ? [NSURL URLWithString:value] : nil;
        if (value.length && !GewuBrowserPublicURL(url)) {
            [self emit:@{@"event":@"error", @"message":@"Use a public HTTP or HTTPS website. Local app and file addresses are not available in Browser."}];
            return;
        }
        [self addTabWithRequest:url ? [NSURLRequest requestWithURL:url] : nil configuration:nil];
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
        if ([url.absoluteString isEqualToString:@"https://www.google.com/"]) [self showHomeRecordingVisit:YES];
        else [self openContentRequest:[NSURLRequest requestWithURL:url]];
    } else if ([action isEqualToString:@"back"]) { [self moveInSession:-1]; }
    else if ([action isEqualToString:@"forward"]) { [self moveInSession:1]; }
    else if ([action isEqualToString:@"reload"]) {
        self.currentPage.attemptedHTTPSRecovery = NO;
        if (self.selectedTab.contentPendingFromHome) {
            // The reused view still owns the previous document before commit;
            // reload that pending request, not the old document's URL.
            self.selectedTab.pendingHomeNavigation = [self.webView loadRequest:self.currentPage.mainNavigationRequest];
        } else if (self.currentPage.failedURL && [self.currentPage.mainNavigationRequest.HTTPMethod isEqualToString:@"GET"]) [self.webView loadRequest:[NSURLRequest requestWithURL:self.currentPage.failedURL]];
        else [self.webView reload];
    }
    else if ([action isEqualToString:@"stop"]) { [self.webView stopLoading]; [self returnToRetainedHomeInTab:self.selectedTab]; }
    else if ([action isEqualToString:@"focus"]) { [self.workspace.window makeFirstResponder:[self presentedPageForTab:self.selectedTab].view]; }
    else if ([action isEqualToString:@"suggestions"]) { [self showAddressSuggestions:command]; }
    else if ([action isEqualToString:@"editor"]) { [self presentEditor:command]; }
    else if ([action isEqualToString:@"confirm"]) { [self presentConfirmation:command]; }
    else if ([action isEqualToString:@"favicon"]) {
        NSString *url = [command[@"url"] isKindOfClass:NSString.class] ? command[@"url"] : @"";
        [self.favicons requestURL:[NSURL URLWithString:url]];
    }
    else if ([action isEqualToString:@"import-bookmarks"]) { [self importBookmarks]; }
    else if ([action isEqualToString:@"export-bookmarks"]) { [self exportBookmarks:command]; }
    else if ([action isEqualToString:@"passwords"]) {
        NSURL *passwords = [NSWorkspace.sharedWorkspace URLForApplicationWithBundleIdentifier:@"com.apple.Passwords"];
        if (passwords) [NSWorkspace.sharedWorkspace openApplicationAtURL:passwords configuration:NSWorkspaceOpenConfiguration.configuration completionHandler:nil];
        else [self emit:@{@"event":@"error", @"message":@"Use Passwords in macOS System Settings on this Mac. Gewu Insight does not read or store website passwords."}];
    }
    else if ([action isEqualToString:@"share"]) {
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
        if (GewuBrowserPublicURL(self.webView.URL)) {
            __weak typeof(self) weakSelf = self;
            [self.webView startDownloadUsingRequest:[NSURLRequest requestWithURL:self.webView.URL] completionHandler:^(WKDownload *download) {
                [weakSelf registerDownload:download];
            }];
        }
    } else if ([action isEqualToString:@"find"]) {
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
    // Home stays on screen during a pending GET. A second explicit search or
    // link replaces that request, without exposing the old content document.
    if (tab == self.selectedTab && tab.contentPendingFromHome && page == tab.homePage
        && action.targetFrame.isMainFrame && GewuBrowserPublicURL(action.request.URL)
        && !GewuBrowserGoogleHome(action.request.URL) && GewuBrowserCanRetainHomeForRequest(action.request)
        && (action.navigationType == WKNavigationTypeFormSubmitted || action.navigationType == WKNavigationTypeLinkActivated)) {
        decisionHandler(WKNavigationActionPolicyCancel);
        if (action.navigationType == WKNavigationTypeLinkActivated
            && ((action.modifierFlags & NSEventModifierFlagCommand) || action.buttonNumber == 2)) {
            GewuBrowserTab *opened = [self addTabWithRequest:action.request configuration:nil];
            opened.currentPage.pendingRequestedDownload = action.shouldPerformDownload;
        } else {
            [self openContentRequest:action.request];
            self.currentPage.pendingRequestedDownload = action.shouldPerformDownload;
        }
        return;
    }
    if (!page || (page != tab.currentPage && (action.targetFrame.isMainFrame || !action.targetFrame))) {
        decisionHandler(WKNavigationActionPolicyCancel); return;
    }
    NSURL *url = action.request.URL;
    if ([url.absoluteString isEqualToString:@"about:blank"] && (!action.targetFrame.isMainFrame || page.allowsInitialBlank)) { decisionHandler(WKNavigationActionPolicyAllow); return; }
    if (!GewuBrowserPublicURL(url)) {
        BOOL wasActive = webView == self.webView;
        if (action.targetFrame.isMainFrame || !action.targetFrame) [self returnToRetainedHomeInTab:tab];
        if (wasActive && (action.targetFrame.isMainFrame || !action.targetFrame)) [self emit:@{ @"event": @"error", @"message": @"This address cannot be opened here. Use Open in Safari for application links or special sign-in flows." }];
        decisionHandler(WKNavigationActionPolicyCancel); return;
    }
    if (webView == self.webView && action.targetFrame && action.navigationType == WKNavigationTypeLinkActivated
        && ((action.modifierFlags & NSEventModifierFlagCommand) || action.buttonNumber == 2)
        && GewuBrowserCanRetainHomeForRequest(action.request)) {
        decisionHandler(WKNavigationActionPolicyCancel);
        GewuBrowserTab *opened = [self addTabWithRequest:action.request configuration:nil];
        opened.currentPage.pendingRequestedDownload = action.shouldPerformDownload;
        return;
    }
    // target=_blank is handled by createWebView using WebKit's configuration,
    // not replayed in the opener (including forms and window.opener flows).
    if (!action.targetFrame) { decisionHandler(WKNavigationActionPolicyAllow); return; }
    if (action.targetFrame.isMainFrame || !action.targetFrame) {
        // Preserve the live Home document when following an ordinary GET
        // search/link. Never intercept/reconstruct a POST or a streamed body.
        if (webView == self.webView && self.currentPage == self.homePage && self.homePage.ready
            && GewuBrowserGoogleHome(webView.URL) && !GewuBrowserGoogleHome(url)
            && GewuBrowserCanRetainHomeForRequest(action.request)) {
            decisionHandler(WKNavigationActionPolicyCancel);
            [self openContentRequest:action.request];
            self.currentPage.pendingRequestedDownload = action.shouldPerformDownload;
            return;
        }
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
    if (webView != self.webView || !self.active || !self.visible || action.targetFrame
        || !(GewuBrowserPublicURL(action.request.URL) || [action.request.URL.absoluteString isEqualToString:@"about:blank"])) return nil;
    GewuBrowserTab *tab = [self addTabWithRequest:action.request configuration:configuration];
    tab.currentPage.pendingRequestedDownload = action.shouldPerformDownload;
    return tab.currentPage.view;
}
- (void)webViewDidClose:(WKWebView *)webView {
    GewuBrowserPage *page = [self pageForView:webView];
    if (page.allowsInitialBlank) [self closeTab:[self tabForPage:page]];
}

- (void)webView:(WKWebView *)webView decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler {
    if (!GewuBrowserPublicURL(response.response.URL)) { decisionHandler(WKNavigationResponsePolicyCancel); return; }
    GewuBrowserPage *page = [self pageForView:webView];
    if (!page) { decisionHandler(WKNavigationResponsePolicyCancel); return; }
    decisionHandler(GewuBrowserResponsePolicy(response.response, response.canShowMIMEType,
        response.forMainFrame && page.navigationRequestedDownload));
}

- (void)webView:(WKWebView *)webView didStartProvisionalNavigation:(WKNavigation *)navigation {
    GewuBrowserPage *page = [self pageForView:webView];
    GewuBrowserTab *tab = [self tabForPage:page];
    if (!page || page != tab.currentPage) return;
    if (tab.contentPendingFromHome && tab.pendingHomeNavigation && tab.pendingHomeNavigation != navigation) return;
    page.failedURL = nil; page.errorMessage = nil;
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
    if (!tab || page != tab.currentPage || tab.contentPendingFromHome) return;
    WKBackForwardList *list = page.view.backForwardList;
    NSMutableArray *items = [list.backList mutableCopy];
    [items addObjectsFromArray:list.forwardList];
    if (list.currentItem) [items addObject:list.currentItem];
    [tab.session pruneSurface:page validItems:items];
    [tab.session recordSurface:page item:list.currentItem
        home:page == tab.homePage && GewuBrowserGoogleHome(page.view.URL)
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
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    GewuBrowserPage *page = [self pageForView:webView];
    GewuBrowserTab *tab = [self tabForPage:page];
    if (!page || page != tab.currentPage || tab.contentPendingFromHome) return;
    page.ready = YES; page.terminated = NO; page.attemptedHTTPSRecovery = NO;
    if (webView == self.webView) { [self emitState]; [self scheduleHomeFit]; } else [self emitTabs];
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
    if (!download || self.invalidated) return;
    download.delegate = self;
    [self.downloads setObject:[NSMutableDictionary dictionary] forKey:download];
}
- (void)webView:(WKWebView *)webView navigationAction:(WKNavigationAction *)navigationAction didBecomeDownload:(WKDownload *)download {
    [self registerDownload:download]; [self returnToRetainedHomeInTab:[self tabForPage:[self pageForView:webView]]];
}
- (void)webView:(WKWebView *)webView navigationResponse:(WKNavigationResponse *)navigationResponse didBecomeDownload:(WKDownload *)download {
    [self registerDownload:download]; [self returnToRetainedHomeInTab:[self tabForPage:[self pageForView:webView]]];
}
- (void)download:(WKDownload *)download willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request decisionHandler:(void (^)(WKDownloadRedirectPolicy))decisionHandler {
    decisionHandler(GewuBrowserPublicURL(request.URL) ? WKDownloadRedirectPolicyAllow : WKDownloadRedirectPolicyCancel);
}
- (void)download:(WKDownload *)download decideDestinationUsingResponse:(NSURLResponse *)response suggestedFilename:(NSString *)suggestedFilename completionHandler:(void (^)(NSURL *))completionHandler {
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
    NSURL *directory = context[@"directory"];
    if (directory) [[NSFileManager defaultManager] removeItemAtURL:directory error:nil];
    [self.downloads removeObjectForKey:download];
    if (error.code != NSURLErrorCancelled) [self emit:@{ @"event": @"error", @"message": [NSString stringWithFormat:@"Download failed (%@ %ld). Check the website session and network, then try again. Existing files were not changed.", error.domain, (long)error.code] }];
}
- (void)invalidate {
    if (self.invalidated) return;
    self.invalidated = YES;
    [self.loginTrigger cancelPending];
    if (self.keyMonitor) [NSEvent removeMonitor:self.keyMonitor];
    self.keyMonitor = nil;
    [self.favicons invalidate];
    [self.suggestionsView removeFromSuperview]; self.suggestionsView = nil; self.suggestionItems = nil;
    for (WKDownload *download in self.downloads.keyEnumerator.allObjects) [download cancel:nil];
    for (GewuBrowserTab *tab in self.tabs) {
        [self disposePage:tab.homePage]; [self disposePage:tab.contentPage];
        [tab.session.entries removeAllObjects];
    }
    [self.tabs removeAllObjects]; self.selectedTab = nil; self.webView = nil; self.browserDataStore = nil;
}
@end
