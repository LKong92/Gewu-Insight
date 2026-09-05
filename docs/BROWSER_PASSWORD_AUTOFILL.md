# Browser password AutoFill: integration status

Historical checkpoint notice (2026-09-05): this note is restored to the state
at 21:13:01.970 Asia/Shanghai, when the assistant asked the user to test native
username/password filling. It had not yet been updated for the native-menu
attempt or the user's later username-success report. Runtime sources match that
question-time version. Further AutoFill work is paused by the user; the proposals
below are historical research, not an instruction to continue, upgrade, obtain
certificates, contact Apple, or ask for another credential test. Restoring code
does not establish a newly successful credential fill.

Status: **not implemented**. A system-wide password picker is not the requested
website-scoped integration. Do not mark this work complete on the basis of the
existing Open Passwords button or the native AutoFill context menu.

## Required behavior

- The system/password provider matches the current login website before offering
  saved accounts. Only matching accounts appear; multiple accounts for that site
  may require a choice, but the user must not search the whole vault.
- No credential is filled before explicit user consent and system authentication.
- Gewu must not enumerate or import the password vault, maintain another vault,
  obtain unrelated credentials and filter them afterward, or persist credentials
  in SQLite, files, logs, diagnostics, or the workspace WebView.
- Origin matching must use the actual HTTPS login document, not its title, a
  user-supplied hostname, or an untrusted message from a different frame. Redirects
  and navigation during authorization must invalidate a pending fill. The system
  provider must determine legitimate cross-domain credential relationships.
- Filling is not permission to submit a login form automatically.

## Verified local facts (2026-09-05)

- The installed OS is macOS 15.1.1 (24B91); the Command Line Tools SDK is 15.2.
- The formal App has identifier `com.zhengranwu.gewuinsight`, an ad-hoc signature,
  and no TeamIdentifier. No signing identity was changed or private key accessed.
- Browser uses a separate persistent `WKWebView`, not Safari's browser UI or a
  Chrome/Firefox extension host. External pages have no workspace script bridge.
- Google login's native context menu includes AutoFill > Passwords. Invoking it
  started the system AutoFillPanelService and authentication UI. The user confirmed
  the panel appeared and dismissed it without selecting a credential. There is
  **no successful credential-fill result** from that check. The generic picker is
  explicitly rejected as the product solution.
- A small compiled, read-only native probe linked WebKit and
  AuthenticationServices successfully. `WKWebExtension`, `WKWebExtensionContext`,
  and `WKWebExtensionController` were all absent at runtime. This probe made no
  credential request, opened no window, and used no network or product database.
- The current SDK's public `ASAuthorizationPasswordRequest` has no arbitrary
  website/domain parameter. The older `SecRequestSharedWebCredential` has a domain
  argument but explicitly requires the corresponding associated-domain entitlement.
  Neither is a general third-party-website password API.

## Public integration routes and their limits

1. **App/website association.** Apple's ordinary App AutoFill matching relies on
   a trusted website association. Gewu cannot claim Google, Nature, or Overleaf
   as its own associated website. Merely adding these domains locally is not a
   valid solution. [Apple associated-domain documentation](https://developer.apple.com/documentation/xcode/supporting-associated-domains)
2. **iCloud Passwords browser extension.** This is a candidate for website-scoped
   matching, but extension compatibility alone is insufficient. Apple documents
   browser-identity restrictions in its native messaging host from macOS 15.5;
   registering an additional browser requires Apple ingestion and an OS update.
   This restriction must not be presented as a measured restriction of 15.1.1.
   [Apple browser distribution and admission rules](https://github.com/apple/password-manager-resources#how-apple-uses-web-browser-extension-distribution-information)
3. **WebKit extension hosting.** Public hosting APIs were added in macOS 15.4 and
   are absent on this machine. Hosting Apple's extension and its authenticated
   native messaging channel remains unimplemented and unverified. An OS upgrade
   alone does not establish compatibility or grant browser admission.
   [Apple macOS 15.4 release notes](https://developer.apple.com/go/?id=macos-15_4-rn)
4. **Passkeys.** Browser public-key credential APIs concern WebAuthn/passkeys;
   they must not be presented as a replacement for saved username/password filling.

Apple's system chooser displays credentials outside the application process;
displaying a list is not itself a grant of whole-vault access. Nevertheless, its
generic selection workflow does not meet the user's site-matching requirement.
[Apple Password AutoFill security](https://support.apple.com/guide/security/password-autofill-security-sec7aefe77c3/web)

## Next decision and work

The current runtime cannot be declared capable of this feature using the reviewed
public interfaces. The candidate extension route needs a user-approved system/SDK
upgrade plan, a stable developer signing identity, and clarification/admission
from Apple for this research App's embedded browser. No purchase, OS upgrade,
certificate change, public issue, pull request, or contact with Apple is authorized
by this document. Do not promise that admission or identical Safari behavior will
follow automatically.

After these prerequisites are resolved, prototype the actual extension/provider
channel before building any credential UI. Verify exact-site matching, multiple
accounts, no-match, cancellation, cross-origin frames, navigation races, absence
of pre-consent disclosure, and no credential persistence using synthetic test
accounts. The user, not an agent, performs final authentication with real accounts.

Current work did not modify Browser runtime behavior, production SQLite, website
sessions, passwords, or the App bundle. No build, full product test run, commit,
push, or benchmark execution is claimed for this investigation.
