# macOS software updates

Gewu Insight 1.1.0 introduces **Gewu Insight → Check for Updates**. Existing
1.0.x installations need one manual replacement with the 1.1.0 App. Later Mac
updates can be downloaded, verified, installed and relaunched from this menu.
The same menu contains **Automatically Check for Updates** (daily by default).
Installation always requires the user's choice; silent automatic installation
and system profiling are disabled.

The Mac updater reads only the signed stable feed at
`https://raw.githubusercontent.com/LKong92/Gewu-Insight/main/updates/macos/appcast.xml`.
It never follows the repository-wide latest release, source branch commits,
Windows installers or test releases. No GitHub account is required.

## Data and running work

Updates replace the App bundle. They do not replace the selected Gewu Database,
its location preference, PDFs, Associated Files, settings or browser storage.
Existing startup identity/schema checks and pre-schema SQLite snapshots remain
in force. Keep full backups of the database folder, other managed roots and
linked originals; a SQLite snapshot is not a full research-file backup.

Before installing, close the Gewu tab in Zotero and finish or pause its import.
Downloads, file changes and active background work postpone installation.
The install-only service barrier prevents new operations, waits for a quiet
boundary, stops the backend, and checks that it released the database lock.
The original App continues working when preparation is refused. No force-kill
or file-management migration is used. Idle schedulers resume if preparation is
cancelled or expires. The helper cannot restart while the App is being replaced.

The downloaded update is retained according to Sparkle's normal retry behavior.
If an installation is interrupted after the App closes, replace the App with
the latest official Mac DMG and reopen it. Keep the same database folder;
never create a replacement database to repair an interrupted software update.
Database schema changes can prevent opening the database with an older App;
replacing the program with an older version is not a database rollback.

**Update Plugin** in Zotero Integration remains a separate action: it installs
the companion bundled with the current Gewu App. Updating the App does not
silently change Zotero's plugin registration or source library.

## Maintainer release sequence

1. Test the product and updater with isolated databases, including real
   Sparkle download/install/relaunch, a busy backend, signature failure and
   old-version database preservation. Never publish test feeds/packages.
2. Increment the public version and the monotonically increasing numeric
   build in `paper_monitor/__init__.py`. Commit and push reviewed source.
3. Build with `scripts/package_macos_dmg.py --ref EXACT_PUSHED_COMMIT` and
   **without** `--working-tree`. Pin all runtime and Sparkle inputs. Mount,
   verify and test the actual installation package.
4. Create `macos-VERSION`, publish the corresponding Release with the DMG,
   checksum, build manifest, validation and upgrade instructions. Verify the
   remote downloads match the local files. Do not replace old release assets.
5. Use `scripts/build_macos_appcast.py` with that DMG, its manifest and release
   notes. It signs the archive and feed using the dedicated Keychain account
   named in `config/macos-updates.json`. Review, commit and push the generated
   `updates/macos/appcast.xml` **after** the installer is available. Verify the
   public feed and its referenced download. A feed-only commit after the build
   does not change the source revision recorded in the installer.

The embedded public Ed25519 key verifies both feed and archive. Private signing
keys remain in Keychain and must never enter Git, logs, manifests or App bundles.
Maintain a secure owner-controlled key backup; losing this key can require a
manual upgrade to establish a new trust key. Apple Developer ID/notarization
and Sparkle update signatures are different: these builds still use ad-hoc App
signing and must not be advertised as Developer ID signed or notarized.

Sparkle 2.10.1 is fetched at build time from its official Release, pinned by
SHA-256. Its original framework/helper signatures and complete license are
retained. Sparkle owns archive verification, App replacement and relaunch;
Gewu owns only the preparation of its running workspace. Windows is unchanged.
