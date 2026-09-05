#import "GewuBrowserController.h"
#import "GewuBrowserNavigation.h"
#import "GewuBrowserFavicons.h"
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

// Right-clicking an editable document must keep AppKit's insertion target in
// this WebView, not the separate workspace/address-bar WebView. Leave all text
// handling to WebKit; never intercept credential values or the system picker.
@interface GewuBrowserWebView : WKWebView
@end
@implementation GewuBrowserWebView
- (void)willOpenMenu:(NSMenu *)menu withEvent:(NSEvent *)event {
    if (self.window && !self.hidden) [self.window makeFirstResponder:self];
    [super willOpenMenu:menu withEvent:event];
}
@end

@interface GewuAddressSuggestionButton : NSButton
@end
@implementation GewuAddressSuggestionButton
- (BOOL)acceptsFirstResponder { return NO; }
@end

@interface GewuBrowserController ()
@property(nonatomic, strong, readwrite) WKWebView *webView;
@property(nonatomic) BOOL active;
@property(nonatomic) BOOL visible;
@property(nonatomic) BOOL initializing;
@property(nonatomic) BOOL invalidated;
@property(nonatomic) BOOL reloadNavigation;
@property(nonatomic) BOOL navigationRequestedDownload;
@property(nonatomic) BOOL attemptedHTTPSRecovery;
@property(nonatomic, copy) NSURLRequest *mainNavigationRequest;
@property(nonatomic, strong) NSURL *failedURL;
@property(nonatomic, copy) NSString *visitID;
@property(nonatomic, strong) id keyMonitor;
@property(nonatomic, strong) NSMapTable<WKDownload *, NSMutableDictionary *> *downloads;
@property(nonatomic, strong) GewuBrowserFavicons *favicons;
@property(nonatomic, strong) NSView *suggestionsView;
@property(nonatomic, copy) NSArray<NSDictionary *> *suggestionItems;
@end

@implementation GewuBrowserController

- (instancetype)initWithWorkspace:(WKWebView *)workspace {
    self = [super init];
    if (self) {
        _workspace = workspace;
        _downloads = [NSMapTable strongToStrongObjectsMapTable];
        __weak typeof(self) weakSelf = self;
        _favicons = [[GewuBrowserFavicons alloc] init];
        _favicons.onIcon = ^(NSString *host, NSString *dataURL) {
            [weakSelf emit:@{@"event":@"favicon", @"host":host, @"data_url":dataURL}];
        };
        _keyMonitor = [NSEvent addLocalMonitorForEventsMatchingMask:(NSEventMaskKeyDown | NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown) handler:^NSEvent *(NSEvent *event) {
            GewuBrowserController *self = weakSelf;
            if (!self.active || event.window != self.workspace.window || self.workspace.window.attachedSheet) return event;
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
            BOOL command = (event.modifierFlags & NSEventModifierFlagCommand) != 0;
            NSString *key = event.charactersIgnoringModifiers.lowercaseString;
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

- (void)emit:(NSDictionary *)event {
    if (self.onEvent && !self.invalidated) self.onEvent(event);
}

- (void)emitState {
    if (!self.webView) return;
    [self emit:@{ @"event": @"state", @"url": (self.failedURL ?: self.webView.URL).absoluteString ?: @"",
        @"title": self.webView.title ?: @"", @"loading": @(self.webView.loading),
        @"progress": @(self.webView.estimatedProgress), @"canBack": @(self.webView.canGoBack),
        @"canForward": @(self.webView.canGoForward) }];
}

- (void)ensureWebView {
    if (self.webView || self.initializing || self.invalidated) return;
    self.initializing = YES;
    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    // Dedicated persistent profile. No Safari cookie import, app script handlers,
    // process-wide proxy overrides, HTML rewriting, or background publisher driver.
    NSUUID *profile = [[NSUUID alloc] initWithUUIDString:@"19E88B78-44C0-4C42-B496-F2C7F625B507"];
    configuration.websiteDataStore = [WKWebsiteDataStore dataStoreForIdentifier:profile];
    // Keep WebKit's system-generated OS/engine/version tokens. The compatibility
    // suffix prevents sites from mistaking desktop WKWebView for a text-only
    // client; retain our own product token rather than hiding the embedding app.
    configuration.applicationNameForUserAgent = @"Safari/605.1.15 GewuInsight/0.1";
    configuration.preferences.javaScriptCanOpenWindowsAutomatically = NO;
    configuration.userContentController = [[WKUserContentController alloc] init];
    self.webView = [[GewuBrowserWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
    self.webView.navigationDelegate = self;
    self.webView.UIDelegate = self;
    self.webView.allowsBackForwardNavigationGestures = YES;
    self.webView.hidden = YES;
    self.webView.accessibilityLabel = @"Browser webpage";
    for (NSString *key in @[@"URL", @"title", @"loading", @"estimatedProgress", @"canGoBack", @"canGoForward"]) {
        [self.webView addObserver:self forKeyPath:key options:NSKeyValueObservingOptionNew context:NULL];
    }
    [self.workspace.superview addSubview:self.webView positioned:NSWindowAbove relativeTo:self.workspace];
    self.initializing = NO;
    [self emit:@{ @"event": @"ready" }];
}

- (void)observeValueForKeyPath:(NSString *)keyPath ofObject:(id)object change:(NSDictionary *)change context:(void *)context {
    if (object == self.webView) { [self emitState]; return; }
    [super observeValueForKeyPath:keyPath ofObject:object change:change context:context];
}

- (void)handleCommand:(NSDictionary *)command {
    NSString *action = [command[@"action"] isKindOfClass:NSString.class] ? command[@"action"] : @"";
    if ([action isEqualToString:@"layout"]) {
        self.active = [command[@"active"] boolValue];
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
        self.webView.frame = rect;
        self.webView.hidden = !shown;
        self.visible = shown;
        if (!shown) self.suggestionsView.hidden = YES;
        if (!shown && [self.workspace.window.firstResponder isKindOfClass:NSView.class]
            && [(NSView *)self.workspace.window.firstResponder isDescendantOf:self.webView]) {
            [self.workspace.window makeFirstResponder:self.workspace];
        }
        return;
    }
    if (!self.active) return;
    [self ensureWebView];
    if ([action isEqualToString:@"navigate"] || [action isEqualToString:@"home"]) {
        NSString *value = [action isEqualToString:@"home"] ? @"https://www.google.com/" : command[@"url"];
        NSURL *url = [value isKindOfClass:NSString.class] ? [NSURL URLWithString:value] : nil;
        if (!GewuBrowserPublicURL(url)) { [self emit:@{ @"event": @"error", @"message": @"Use a public HTTP or HTTPS website. Local app and file addresses are not available in Browser." }]; return; }
        self.attemptedHTTPSRecovery = NO;
        [self.webView loadRequest:[NSURLRequest requestWithURL:url]];
    } else if ([action isEqualToString:@"back"]) { [self.webView goBack]; }
    else if ([action isEqualToString:@"forward"]) { [self.webView goForward]; }
    else if ([action isEqualToString:@"reload"]) {
        self.attemptedHTTPSRecovery = NO;
        if (self.failedURL && [self.mainNavigationRequest.HTTPMethod isEqualToString:@"GET"]) [self.webView loadRequest:[NSURLRequest requestWithURL:self.failedURL]];
        else [self.webView reload];
    }
    else if ([action isEqualToString:@"stop"]) { [self.webView stopLoading]; }
    else if ([action isEqualToString:@"focus"]) { [self.workspace.window makeFirstResponder:self.webView]; }
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
        NSURL *url = self.failedURL ?: self.webView.URL;
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
    NSURL *url = action.request.URL;
    if ([url.absoluteString isEqualToString:@"about:blank"] && !action.targetFrame.isMainFrame) { decisionHandler(WKNavigationActionPolicyAllow); return; }
    if (!GewuBrowserPublicURL(url)) {
        if (action.targetFrame.isMainFrame || !action.targetFrame) [self emit:@{ @"event": @"error", @"message": @"This address cannot be opened here. Use Open in Safari for application links or special sign-in flows." }];
        decisionHandler(WKNavigationActionPolicyCancel); return;
    }
    if (action.targetFrame.isMainFrame || !action.targetFrame) {
        self.mainNavigationRequest = action.request;
        self.navigationRequestedDownload = action.shouldPerformDownload;
        self.reloadNavigation = action.navigationType == WKNavigationTypeReload;
        if (action.navigationType != WKNavigationTypeOther) self.attemptedHTTPSRecovery = NO;
    }
    // Defer HTML download attributes until MIME is known, including URLs without
    // a .pdf suffix. Explicit Save Download still uses WKDownload directly.
    decisionHandler(WKNavigationActionPolicyAllow);
}

- (WKWebView *)webView:(WKWebView *)webView createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration forNavigationAction:(WKNavigationAction *)action windowFeatures:(WKWindowFeatures *)windowFeatures {
    // Normal target=_blank links stay in this Browser surface and its back stack.
    // Do not create an untracked window or expose workspace bridges to a popup.
    if (GewuBrowserPublicURL(action.request.URL)) [self.webView loadRequest:action.request];
    return nil;
}

- (void)webView:(WKWebView *)webView decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler {
    if (!GewuBrowserPublicURL(response.response.URL)) { decisionHandler(WKNavigationResponsePolicyCancel); return; }
    decisionHandler(GewuBrowserResponsePolicy(response.response, response.canShowMIMEType,
        response.forMainFrame && self.navigationRequestedDownload));
}

- (void)webView:(WKWebView *)webView didStartProvisionalNavigation:(WKNavigation *)navigation {
    self.failedURL = nil;
    if (!self.reloadNavigation || !self.visitID) self.visitID = NSUUID.UUID.UUIDString;
    self.reloadNavigation = NO;
    [self emit:@{ @"event": @"navigation-start" }];
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    self.attemptedHTTPSRecovery = NO;
    [self emitState];
    NSURL *pageURL = webView.URL;
    if (GewuBrowserPublicURL(pageURL)) {
        [webView evaluateJavaScript:@"Array.from(document.querySelectorAll('link[rel]')).find(x => x.rel.toLowerCase().split(/\\s+/).includes('icon'))?.href || ''" completionHandler:^(id value, NSError *error) {
            if (!error && [value isKindOfClass:NSString.class]) [self.favicons preferIcon:[NSURL URLWithString:value] forPage:pageURL];
        }];
    }
    if (GewuBrowserPublicURL(webView.URL)) [self emit:@{ @"event": @"visit", @"event_id": self.visitID ?: NSUUID.UUID.UUIDString,
        @"url": webView.URL.absoluteString, @"title": webView.title ?: webView.URL.host ?: @"Webpage" }];
}

- (void)navigationFailed:(NSError *)error {
    if (error.code == NSURLErrorCancelled || (error.code == 102 && [error.domain isEqualToString:WKErrorDomain])) return;
    NSURL *secureURL = GewuBrowserHTTPSRecoveryURL(error, self.mainNavigationRequest, self.attemptedHTTPSRecovery);
    if (GewuBrowserPublicURL(secureURL)) {
        self.attemptedHTTPSRecovery = YES;
        [self.webView loadRequest:[NSURLRequest requestWithURL:secureURL]];
        return;
    }
    id failed = error.userInfo[NSURLErrorFailingURLErrorKey];
    self.failedURL = [failed isKindOfClass:NSURL.class] && GewuBrowserPublicURL(failed) ? failed : self.mainNavigationRequest.URL;
    [self emit:@{ @"event": @"error", @"message": GewuBrowserNavigationErrorMessage(error) }];
    [self emitState];
}
- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error { [self navigationFailed:error]; }
- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error { [self navigationFailed:error]; }
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    [self emit:@{ @"event": @"error", @"message": @"The webpage process stopped. Reload to continue; your bookmarks and history are safe." }];
}

- (void)webView:(WKWebView *)webView runJavaScriptAlertPanelWithMessage:(NSString *)message initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(void))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = frame.request.URL.host ?: @"Website message";
    alert.informativeText = [message substringToIndex:MIN(message.length, 2000)];
    [alert addButtonWithTitle:@"OK"];
    [alert beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) { completionHandler(); }];
}
- (void)webView:(WKWebView *)webView runJavaScriptConfirmPanelWithMessage:(NSString *)message initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(BOOL))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = frame.request.URL.host ?: @"Website confirmation";
    alert.informativeText = [message substringToIndex:MIN(message.length, 2000)];
    [alert addButtonWithTitle:@"OK"]; [alert addButtonWithTitle:@"Cancel"];
    [alert beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) { completionHandler(response == NSAlertFirstButtonReturn); }];
}
- (void)webView:(WKWebView *)webView runJavaScriptTextInputPanelWithPrompt:(NSString *)prompt defaultText:(NSString *)defaultText initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSString *))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = frame.request.URL.host ?: @"Website input";
    alert.informativeText = [prompt substringToIndex:MIN(prompt.length, 2000)];
    NSTextField *input = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 320, 24)]; input.stringValue = defaultText ?: @"";
    alert.accessoryView = input;
    [alert addButtonWithTitle:@"OK"]; [alert addButtonWithTitle:@"Cancel"];
    [alert beginSheetModalForWindow:self.workspace.window completionHandler:^(NSModalResponse response) { completionHandler(response == NSAlertFirstButtonReturn ? input.stringValue : nil); }];
}
- (void)webView:(WKWebView *)webView runOpenPanelWithParameters:(WKOpenPanelParameters *)parameters initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSArray<NSURL *> *))completionHandler {
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
- (void)webView:(WKWebView *)webView navigationAction:(WKNavigationAction *)navigationAction didBecomeDownload:(WKDownload *)download { [self registerDownload:download]; }
- (void)webView:(WKWebView *)webView navigationResponse:(WKNavigationResponse *)navigationResponse didBecomeDownload:(WKDownload *)download { [self registerDownload:download]; }
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
    if (self.keyMonitor) [NSEvent removeMonitor:self.keyMonitor];
    self.keyMonitor = nil;
    [self.favicons invalidate];
    [self.suggestionsView removeFromSuperview]; self.suggestionsView = nil; self.suggestionItems = nil;
    for (NSString *key in @[@"URL", @"title", @"loading", @"estimatedProgress", @"canGoBack", @"canGoForward"]) [self.webView removeObserver:self forKeyPath:key];
    for (WKDownload *download in self.downloads.keyEnumerator.allObjects) [download cancel:nil];
    [self.webView stopLoading]; [self.webView removeFromSuperview];
    self.webView.navigationDelegate = nil; self.webView.UIDelegate = nil;
}
@end
