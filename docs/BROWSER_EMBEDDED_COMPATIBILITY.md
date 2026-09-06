# Embedded child-document compatibility

## Scope and evidence (September 6, 2026)

The user reported an APS Physical Review page remaining on Cloudflare security
verification in Gewu while Safari could open it. The original App displayed
the verification page and a `challenges.cloudflare.com` frame. That observation
alone does not identify the failing challenge request or prove a particular
cause of the loop.

The pre-change native navigation policy rejected `about:srcdoc`, including in
existing child frames. Its response policy also rejected all non-HTTP(S) URLs.
This is a reproducible compatibility defect: Cloudflare's [WebView integration
requirements](https://developers.cloudflare.com/turnstile/get-started/mobile-implementation/)
explicitly include `about:blank` and `about:srcdoc`. The documentation describes
WebView requirements, not a guarantee that every protected publisher accepts
this desktop embedded browser.

## Narrow correction

- Allow exact `about:blank` and `about:srcdoc` URLs only for existing child-frame
  navigation actions and viewable child responses in a known browsing surface.
- Leave top-level/address-bar `about:srcdoc`, unrelated schemes, local/private
  destinations, unknown/disposed views and the unloaded local Home anchor
  blocked. Existing initial-blank popup behavior is unchanged.
- Let WebKit enforce inherited origins, frame sandboxing and document access.
  Do not inject code into the publisher or its challenge, add a remote native
  bridge, intercept verification tokens, or change core web APIs.
- Preserve the persistent profile, user agent, cookies, passwords, AutoFill,
  proxy/Clash routing, TLS policy, PDF/download behavior and tab history.
  No profile reset, Safari session transfer, signing change or OS upgrade.

This removes an application-side compatibility restriction; it is not a
challenge bypass. The live result below establishes successful loading of the
reported page after rebuilding, not universal publisher acceptance or proof
that this defect was the only cause of the earlier loop.

## Verification

`tests/browser_navigation_probe.m` checks exact URL classification and keeps
internal documents out of public/address-bar destinations.
`tests/browser_home_session_probe.m` executes the real controller's action and
response policies against inert surfaces, including local/private URLs,
top-level/popup attempts, Home/disposed views and unchanged main-tab state.

`tests/browser_internal_frames_webkit_probe.m` uses an ephemeral real WebKit
surface and generated documents only. All 11 checks pass: two actual srcdoc
actions, normal script/postMessage execution, inherited parent access, opaque
sandbox origin, inaccessible sandboxed content, blank child usability, one tab,
no unexpected navigation and no trusted workspace bridge. This WebKit version
emits no response callback for these internal documents; response guards are
covered by the inert-controller tests, not falsely claimed as live callbacks.
The initial fixture incorrectly used synchronous JavaScript evaluation for a
Promise; it was corrected to the public asynchronous evaluator before passing.

Example standalone build/run (macOS, outside the user's browsing profile):

```sh
xcrun clang -fobjc-arc -framework Cocoa -framework WebKit -framework ImageIO \
  -framework UniformTypeIdentifiers -I scripts \
  tests/browser_internal_frames_webkit_probe.m scripts/GewuBrowserFavicons.m \
  scripts/GewuBrowserAutoFill.m -o /private/tmp/gewu-internal-frames
/private/tmp/gewu-internal-frames
```

## Build and original-App result

The prerequisite checkpoint `8adfec8` was committed and pushed before this
compatibility change. All 714 product tests pass (31.667 seconds), together
with 12 real WebKit Home-transition and 25 tab/AppKit checks. Python compile,
diff and code-signature checks pass. The synchronized 78-page PDF and packaged
copy match; changed guide pages were rendered and inspected.

With the user's saved-drafts/restart approval, the original universal App was
restarted (PID 39038, 08:38:42; binary built 08:35:23). Its single local UI
service was healthy. On September 6, 2026, the exact reported PRX recent URL
with its five subject filters loaded the real **Physical Review X - Recent
Articles** page, displaying **1 - 20 of 1,540 Results** and article links.
Those counts are verification evidence at that time, not product constants.
The page was left open. No challenge control, login, password, cookie export,
clearance transfer or network setting was operated. An initial automated text
entry lost punctuation under the active input method; the public URL was then
pasted, inspected and submitted intact before this successful navigation.

PRL/PRB pages were not separately tested. If a publisher later loops again,
do not automate its challenge or treat this one success as a guarantee. Retain
the public URL/time/Ray ID for site support and use explicit Open in Safari.
The user authorized committing and pushing this follow-up after validation.
