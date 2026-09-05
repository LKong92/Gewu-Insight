#import "GewuBrowserAutoFill.m"
@interface MenuNode : NSObject
@property(copy) NSString *role, *title;
@property(copy) NSArray *children;
@property BOOL enabled;
@end
@implementation MenuNode
- (NSString *)accessibilityRole { return self.role; }
- (NSString *)accessibilityTitle { return self.title; }
- (NSArray *)accessibilityChildren { return self.children ?: @[]; }
- (BOOL)isAccessibilityEnabled { return self.enabled; }
- (BOOL)accessibilityPerformPress { return YES; }
@end
@interface TestMenu : NSMenu
@property(copy) NSArray *nodes;
@end
@implementation TestMenu
- (NSArray *)accessibilityChildren { return self.nodes; }
@end
static MenuNode *node(NSString *role, NSString *title, NSArray *children) {
    MenuNode *n = [MenuNode new]; n.role=role; n.title=title; n.children=children; n.enabled=YES; return n;
}
static void check(BOOL pass) { if (!pass) { fputs("FAILED: system menu boundary\n",stderr); exit(1); } }
int main(void) {
    @autoreleasepool {
        TestMenu *menu = [TestMenu new];
        MenuNode *passwords = node(NSAccessibilityMenuItemRole,@"Passwords…",@[]);
        MenuNode *root = node(NSAccessibilityMenuItemRole,@"AutoFill",@[node(NSAccessibilityMenuRole,@"",@[passwords])]);
        menu.nodes = @[root]; check(GewuBrowserPasswordMenuItem(menu) == (id)passwords);
        passwords.enabled = NO; check(!GewuBrowserPasswordMenuItem(menu)); passwords.enabled = YES;
        menu.nodes = @[passwords]; check(!GewuBrowserPasswordMenuItem(menu));
        menu.nodes = @[node(NSAccessibilityWindowRole,@"AutoFill",@[passwords])]; check(!GewuBrowserPasswordMenuItem(menu));
        menu.nodes = @[node(NSAccessibilityTextFieldRole,@"AutoFill",@[passwords])]; check(!GewuBrowserPasswordMenuItem(menu));
        root.title=@"自动填充"; passwords.title=@"密码..."; menu.nodes=@[root]; check(GewuBrowserPasswordMenuItem(menu)==(id)passwords);
        root.title=@"Unknown menu"; check(!GewuBrowserPasswordMenuItem(menu));
        check(!GewuBrowserPasswordMenuItem(nil));
        puts("8 native menu-boundary checks passed");
    }
}
