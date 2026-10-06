// Standalone first-launch location selection. No database bytes are changed here.
static BOOL GewuConfigureDatabaseLocation(void) {
    NSBundle *bundle = NSBundle.mainBundle;
    NSString *entry = [bundle.resourcePath stringByAppendingPathComponent:@"macos_standalone_entry.py"];
    if (![NSFileManager.defaultManager fileExistsAtPath:entry]) return YES;
    setenv("GEWU_APP_PATH", bundle.bundlePath.fileSystemRepresentation, 1);
    setenv("GEWU_STANDALONE", "1", 1);
    setenv("GEWU_INSTANCE_ID", NSUUID.UUID.UUIDString.UTF8String, 1);
    NSString *logs = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/Gewu Insight"];
    if (!getenv("GEWU_LOG_ROOT")) setenv("GEWU_LOG_ROOT", logs.fileSystemRepresentation, 1);
    if (getenv("GEWU_WORKSPACE_ROOT")) {
        NSString *root = [NSString stringWithUTF8String:getenv("GEWU_WORKSPACE_ROOT")];
        if (!getenv("GEWU_DATA_ROOT")) setenv("GEWU_DATA_ROOT", [root stringByAppendingPathComponent:@"data"].fileSystemRepresentation, 1);
        return YES;
    }
    NSString *locator = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/Gewu Insight/database-location.plist"];
    NSDictionary *saved = [NSDictionary dictionaryWithContentsOfFile:locator];
    NSString *root = [saved[@"workspace"] isKindOfClass:NSString.class] ? saved[@"workspace"] : nil;
    NSString *identity = [saved[@"database_uuid"] isKindOfClass:NSString.class] ? saved[@"database_uuid"] : nil;
    BOOL unavailable = root.length && ![NSFileManager.defaultManager fileExistsAtPath:[root stringByAppendingPathComponent:@"data/paper_monitor.sqlite"]];
    if (unavailable) root = nil;
    while (!root.length) {
        NSAlert *choice = [NSAlert new];
        choice.messageText = unavailable ? @"Locate Your Gewu Database" : @"Choose Your Gewu Database";
        choice.informativeText = unavailable
            ? @"The saved database is unavailable. Reconnect its disk or select its existing folder. Your saved location will be retained until another database opens successfully."
            : @"Keep your papers, files and reports in one folder, separate from the App. Open an existing database or create a new one at a location you choose.";
        [choice addButtonWithTitle:@"Open Existing Database"];
        if (!unavailable) [choice addButtonWithTitle:@"Create New Database"];
        [choice addButtonWithTitle:@"Quit"];
        NSModalResponse response = [choice runModal];
        BOOL create = !unavailable && response == NSAlertSecondButtonReturn;
        if ((!unavailable && response == NSAlertThirdButtonReturn) || (unavailable && response != NSAlertFirstButtonReturn)) return NO;
        NSString *selected = nil;
        if (create) {
            NSSavePanel *panel = [NSSavePanel savePanel];
            panel.title = @"Create New Database";
            panel.nameFieldStringValue = @"Gewu Database";
            panel.message = @"Choose a new folder for your database and research files.";
            panel.canCreateDirectories = YES;
            if ([panel runModal] == NSModalResponseOK) selected = panel.URL.path;
            if (selected && [NSFileManager.defaultManager fileExistsAtPath:selected]) {
                NSAlert *error = [NSAlert new]; error.messageText = @"Choose a new folder name";
                error.informativeText = @"Existing folders are never replaced. Use Open Existing Database to open a database you already have.";
                [error runModal]; continue;
            }
        } else {
            NSOpenPanel *panel = [NSOpenPanel openPanel];
            panel.title = @"Open Existing Database";
            panel.message = @"Select the folder containing data/paper_monitor.sqlite.";
            panel.canChooseDirectories = YES; panel.canChooseFiles = NO; panel.allowsMultipleSelection = NO;
            if ([panel runModal] == NSModalResponseOK) selected = panel.URL.path;
            if (selected && ![NSFileManager.defaultManager fileExistsAtPath:[selected stringByAppendingPathComponent:@"data/paper_monitor.sqlite"]]) {
                NSAlert *error = [NSAlert new]; error.messageText = @"No Gewu database found";
                error.informativeText = @"Choose the database folder containing data/paper_monitor.sqlite.";
                [error runModal]; continue;
            }
        }
        if (!selected) continue;
        root = selected; identity = nil;
        if (create) setenv("GEWU_CREATE_DATABASE", "1", 1);
    }
    setenv("GEWU_WORKSPACE_ROOT", root.fileSystemRepresentation, 1);
    setenv("GEWU_DATA_ROOT", [root stringByAppendingPathComponent:@"data"].fileSystemRepresentation, 1);
    setenv("GEWU_REMEMBER_DATABASE", "1", 1);
    if (identity.length) setenv("GEWU_DATABASE_UUID", identity.UTF8String, 1);
    return YES;
}
