#import "GewuUpdateController.h"
#import <Sparkle/Sparkle.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>

static NSString *GewuUpdateStatePath(void) {
    NSString *root = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/Gewu Insight/Updates"];
    // Disposable native tests never share the installed App's update marker.
    if ([NSBundle.mainBundle.bundleIdentifier hasSuffix:@".updater-test"] && getenv("GEWU_UPDATE_STATE_DIR"))
        root = [NSString stringWithUTF8String:getenv("GEWU_UPDATE_STATE_DIR")];
    return [root stringByAppendingPathComponent:@"install.plist"];
}

@interface GewuUpdateController () <SPUUpdaterDelegate>
@property(nonatomic, strong) SPUStandardUpdaterController *controller;
@property(nonatomic) BOOL pendingInstallation;
@property(nonatomic) BOOL preparing;
@property(nonatomic) BOOL prepared;
@property(nonatomic, copy) NSString *targetBuild;
@property(nonatomic, copy) NSString *lease;
@end

@implementation GewuUpdateController
+ (BOOL)allowStartup {
    NSDictionary *state = [NSDictionary dictionaryWithContentsOfFile:GewuUpdateStatePath()];
    if (!state || ![state[@"app"] isEqualToString:NSBundle.mainBundle.bundlePath]) return YES;
    NSString *build = [NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleVersion"];
    if ([SUStandardVersionComparator.defaultComparator compareVersion:build toVersion:state[@"target"] ?: @""] != NSOrderedAscending) {
        [NSFileManager.defaultManager removeItemAtPath:GewuUpdateStatePath() error:nil];
        return YES;
    }
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"Gewu Insight is being updated";
    alert.informativeText = @"Wait for the installer to reopen Gewu. If installation was interrupted, download the latest Mac release and replace the App. Your existing Gewu Database stays in its original folder.";
    [alert addButtonWithTitle:@"Close"];
    [alert runModal];
    return NO;
}

- (void)start {
    self.controller = [[SPUStandardUpdaterController alloc] initWithStartingUpdater:YES updaterDelegate:self userDriverDelegate:nil];
}

- (void)checkForUpdates:(id)sender {
    [self.controller checkForUpdates:sender];
}

- (void)toggleAutomaticChecks:(id)sender {
    self.controller.updater.automaticallyChecksForUpdates = !self.controller.updater.automaticallyChecksForUpdates;
}

- (BOOL)validateMenuItem:(NSMenuItem *)item {
    if (item.action == @selector(toggleAutomaticChecks:)) {
        item.state = self.controller.updater.automaticallyChecksForUpdates ? NSControlStateValueOn : NSControlStateValueOff;
        return !self.preparing;
    }
    return self.controller.updater.canCheckForUpdates && !self.preparing;
}

- (BOOL)updater:(SPUUpdater *)updater shouldProceedWithUpdate:(SUAppcastItem *)item updateCheck:(SPUUpdateCheck)check error:(NSError **)error {
    NSURL *url = item.fileURL;
    BOOL approved = [url.scheme isEqualToString:@"https"] && [url.host isEqualToString:@"github.com"]
        && [url.path hasPrefix:@"/LKong92/Gewu-Insight/releases/download/macos-"]
        && [url.pathExtension isEqualToString:@"dmg"];
    // A signed, separately identified local fixture may exercise real Sparkle.
    if ([NSBundle.mainBundle.bundleIdentifier hasSuffix:@".updater-test"])
        approved = [url.host isEqualToString:@"127.0.0.1"] && [url.pathExtension isEqualToString:@"dmg"];
    if (!approved && error) *error = [NSError errorWithDomain:@"GewuUpdate" code:1 userInfo:@{NSLocalizedDescriptionKey:@"The update does not point to an official Mac installer."}];
    return approved;
}

- (void)updater:(SPUUpdater *)updater willInstallUpdate:(SUAppcastItem *)item {
    self.pendingInstallation = YES;
    self.targetBuild = item.versionString;
}

- (void)updater:(SPUUpdater *)updater didExtractUpdate:(SUAppcastItem *)item {
    // Also protect a later ordinary Quit after the user deferred relaunch.
    self.pendingInstallation = YES;
    self.targetBuild = item.versionString;
}

- (void)sendAction:(NSString *)action completion:(void (^)(NSDictionary *, NSError *))completion {
    NSMutableURLRequest *request = self.request ? self.request(action, self.lease ?: @"") : nil;
    if (!request) {
        completion(nil, [NSError errorWithDomain:@"GewuUpdate" code:2 userInfo:@{NSLocalizedDescriptionKey:@"Open your Gewu workspace before installing an update."}]);
        return;
    }
    request.timeoutInterval = 10;
    [[[NSURLSession sharedSession] dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSDictionary *payload = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        if (![payload isKindOfClass:NSDictionary.class]) payload = @{};
        if (!error && (![(NSHTTPURLResponse *)response statusCode] || [(NSHTTPURLResponse *)response statusCode] != 200 || ![payload[@"ok"] boolValue]))
            error = [NSError errorWithDomain:@"GewuUpdate" code:3 userInfo:@{NSLocalizedDescriptionKey:payload[@"error"] ?: @"The workspace could not prepare a safe update. Restart Gewu and try again."}];
        dispatch_async(dispatch_get_main_queue(), ^{ completion(payload, error); });
    }] resume];
}

- (void)failPreparation:(NSString *)message {
    self.preparing = NO;
    self.prepared = NO;
    if (self.preparingChanged) self.preparingChanged(NO);
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"Update postponed";
    alert.informativeText = message ?: @"The workspace is busy. Retry when its tasks have finished.";
    [alert addButtonWithTitle:@"OK"];
    [alert runModal];
    [NSApp replyToApplicationShouldTerminate:NO];
}

- (NSApplicationTerminateReply)applicationShouldTerminate {
    if (!self.pendingInstallation || self.prepared) return NSTerminateNow;
    if (self.preparing) return NSTerminateLater;
    NSString *busy = self.busyReason ? self.busyReason() : nil;
    if (busy.length) {
        NSAlert *alert = [NSAlert new]; alert.messageText = @"Update postponed"; alert.informativeText = busy;
        [alert addButtonWithTitle:@"OK"]; [alert runModal]; return NSTerminateCancel;
    }
    self.preparing = YES;
    if (self.preparingChanged) self.preparingChanged(YES);
    [self sendAction:@"prepare" completion:^(NSDictionary *payload, NSError *error) {
        if (error) { [self failPreparation:error.localizedDescription]; return; }
        self.lease = payload[@"token"];
        NSString *path = GewuUpdateStatePath();
        NSError *writeError = nil;
        [NSFileManager.defaultManager createDirectoryAtPath:path.stringByDeletingLastPathComponent withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:&writeError];
        NSDictionary *marker = @{@"app":NSBundle.mainBundle.bundlePath, @"target":self.targetBuild ?: @"", @"created":[NSDate date]};
        if (writeError || ![marker writeToFile:path atomically:YES]) {
            [self sendAction:@"cancel" completion:^(NSDictionary *ignored, NSError *cancelError) {
                [self failPreparation:@"The update could not reserve its installation. Your App and research files were not replaced."];
            }];
            return;
        }
        [self sendAction:@"stop" completion:^(NSDictionary *stopped, NSError *stopError) {
            if (stopError) {
                [NSFileManager.defaultManager removeItemAtPath:path error:nil];
                [self sendAction:@"cancel" completion:^(NSDictionary *ignored, NSError *cancelError) { [self failPreparation:stopError.localizedDescription]; }];
                return;
            }
            [self waitForDatabaseRelease:[NSDate dateWithTimeIntervalSinceNow:15]];
        }];
    }];
    return NSTerminateLater;
}

- (void)waitForDatabaseRelease:(NSDate *)deadline {
    NSString *root = getenv("GEWU_WORKSPACE_ROOT") ? [NSString stringWithUTF8String:getenv("GEWU_WORKSPACE_ROOT")] : nil;
    NSString *lock = [root stringByAppendingPathComponent:@"data/.gewu-database.lock"];
    int fd = lock ? open(lock.fileSystemRepresentation, O_RDWR | O_NOFOLLOW) : -1;
    BOOL released = fd >= 0 && flock(fd, LOCK_EX | LOCK_NB) == 0;
    if (fd >= 0) close(fd);
    if (released) {
        self.prepared = YES;
        [NSApp replyToApplicationShouldTerminate:YES];
    } else if ([deadline timeIntervalSinceNow] > 0) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.1*NSEC_PER_SEC)), dispatch_get_main_queue(), ^{ [self waitForDatabaseRelease:deadline]; });
    } else {
        [NSFileManager.defaultManager removeItemAtPath:GewuUpdateStatePath() error:nil];
        [self failPreparation:@"The background service has not finished stopping. The update was not installed. Reopen Gewu and try again."];
    }
}

- (void)updater:(SPUUpdater *)updater didAbortWithError:(NSError *)error {
    if (self.preparing || self.prepared) {
        [NSFileManager.defaultManager removeItemAtPath:GewuUpdateStatePath() error:nil];
        self.preparing = NO; self.prepared = NO;
        if (self.preparingChanged) self.preparingChanged(NO);
    }
    self.pendingInstallation = NO;
}
@end
