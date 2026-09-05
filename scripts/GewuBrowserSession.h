#import <Foundation/Foundation.h>

// In-memory navigation only. Native history items retain WebKit's own request
// semantics; traversing history must never reconstruct a URL or replay a form.
@interface GewuBrowserSessionEntry : NSObject
@property(nonatomic, strong) id surface;
@property(nonatomic, strong) id item;
@property(nonatomic) BOOL home;
@end
@implementation GewuBrowserSessionEntry
@end

@interface GewuBrowserSession : NSObject
@property(nonatomic, strong) NSMutableArray<GewuBrowserSessionEntry *> *entries;
@property(nonatomic) NSInteger index;
- (GewuBrowserSessionEntry *)current;
- (void)recordSurface:(id)surface item:(id)item home:(BOOL)home traversal:(BOOL)traversal;
- (GewuBrowserSessionEntry *)move:(NSInteger)offset;
- (void)pruneSurface:(id)surface validItems:(NSArray *)items;
@end
@implementation GewuBrowserSession
- (instancetype)init {
    if ((self = [super init])) { _entries = [NSMutableArray array]; _index = -1; }
    return self;
}
- (GewuBrowserSessionEntry *)current {
    return self.index >= 0 && self.index < self.entries.count ? self.entries[self.index] : nil;
}
- (void)recordSurface:(id)surface item:(id)item home:(BOOL)home traversal:(BOOL)traversal {
    if (!surface || (!home && !item)) return;
    GewuBrowserSessionEntry *current = self.current;
    if (current.surface == surface && current.home == home && (home || current.item == item)) return;
    if (traversal) {
        NSInteger nearest = -1;
        for (NSInteger i = 0; i < self.entries.count; i++) {
            GewuBrowserSessionEntry *entry = self.entries[i];
            if (entry.surface == surface && entry.home == home && (home || entry.item == item)
                && (nearest < 0 || labs(i - self.index) < labs(nearest - self.index))) nearest = i;
        }
        if (nearest >= 0) { self.index = nearest; return; }
    }
    if (self.index + 1 < self.entries.count)
        [self.entries removeObjectsInRange:NSMakeRange(self.index + 1, self.entries.count - self.index - 1)];
    GewuBrowserSessionEntry *entry = [[GewuBrowserSessionEntry alloc] init];
    entry.surface = surface; entry.item = item; entry.home = home;
    [self.entries addObject:entry]; self.index = self.entries.count - 1;
    // Bound metadata even in a very long browsing session. Only two surfaces
    // exist; this list does not create or preload any webpages.
    if (self.entries.count > 256) { [self.entries removeObjectAtIndex:0]; self.index--; }
}
- (GewuBrowserSessionEntry *)move:(NSInteger)offset {
    NSInteger next = self.index + offset;
    if (next < 0 || next >= self.entries.count) return nil;
    self.index = next; return self.current;
}
- (void)pruneSurface:(id)surface validItems:(NSArray *)items {
    for (NSInteger i = self.entries.count - 1; i >= 0; i--) {
        GewuBrowserSessionEntry *entry = self.entries[i];
        if (entry.surface == surface && !entry.home && ![items containsObject:entry.item]) {
            [self.entries removeObjectAtIndex:i];
            if (i <= self.index) self.index--;
        }
    }
}
@end
