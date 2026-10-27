#import <Cocoa/Cocoa.h>

// Install-only lifecycle hooks; the host keeps its existing normal quit behavior.
@interface GewuUpdateController : NSObject <NSMenuItemValidation>
@property(nonatomic, copy) NSMutableURLRequest *(^request)(NSString *action, NSString *token);
@property(nonatomic, copy) NSString *(^busyReason)(void);
@property(nonatomic, copy) void (^preparingChanged)(BOOL preparing);
@property(nonatomic, readonly) BOOL preparing;
- (void)start;
- (void)checkForUpdates:(id)sender;
- (void)toggleAutomaticChecks:(id)sender;
- (NSApplicationTerminateReply)applicationShouldTerminate;
+ (BOOL)allowStartup;
@end
