# Workspace website-entry audit

## Routing contract

In the native App, a website action from the five research workspaces selects
Browser and opens a foreground webpage tab. Existing Browser pages, drafts and
per-tab navigation sessions are not replaced. On the first website action, the
unused initial tab opens the destination directly without requesting Google
Home first. Repeated clicks deliberately create separate tabs. The existing
32-tab limit reports an error rather than replacing a page.

The workspace's paper selection, author selection, date and Library placement
are not changed by this routing. Normal mode switching retains the source
surface; no paper reload or database mutation is added by the link handler.
Normal Browser visits still enter local history after navigation commits.

## Return to the source workspace

After an outbound research link, **Command-left bracket (⌘[)** returns from
Browser to the retained source workspace, including My Publications within
Library mode. It restores viewport geometry and focus without calling the
workspace loaders, fetching papers, rebuilding its DOM, closing Browser tabs,
or traversing webpage history. Journal/Subject surfaces stay attached while
Browser covers them. Native key handling works with either webpage or chrome
focus, excludes other windows/modifiers/sheets, and emits only a trusted
workspace return event. Remote websites receive no new bridge.

The checkpoint is one-shot and memory-only. Navigation/new tabs inside Browser
keep it; manually leaving Browser clears it. Direct Browser entry has no source
checkpoint. A visible dialog must be dismissed before returning. This command
does not change Preview shortcuts or Browser's Back/Forward toolbar actions.

## Audited entries

| Surface | Website entries routed into Browser |
| --- | --- |
| Library | Paper Details Open Website and Google Scholar; preprint identifier's open action; shared citation/source links |
| My Publications | Paper Details Open Website and Google Scholar; saved Scholar-profile entry; preprint open action; Overleaf Project export's website entry; shared citation/source links |
| Journal Monitor | Card's arrow/Open Website; shared Paper Details actions and citation/source links |
| Subject Monitor | Shared report-card arrow/Open Website; shared Paper Details actions and citation/source links |
| Author Monitor | Paper Open Website and Google Scholar; author profile/homepage buttons; clickable author avatars (homepage first, profile fallback); shared details/preprint/source links |
| Shared citation and metadata panels | Citing-paper titles, Semantic Scholar, Open PDF (remote URL), ADS, PubMed and PMC |
| Note/analysis drawer | Rendered HTTP(S) Markdown links, including dynamically inserted notes |
| Legacy publisher overlay | Its legacy opener delegates to Browser; it no longer loads the retired proxy iframe |

Buttons use `openWebsite` / `openLibraryWebsiteURL` in `ui_server.py` and the
`gewuBrowser.openURL` entry in `browser_ui.js`. Delegated click and middle-click
handling catches ordinary and dynamically generated external anchors, including
Command-click, without also selecting the surrounding paper row. Native
workspace navigation/popup delegates cover right-click Open Link in New Window
and future plain links/window.open calls that bypass those handlers.

## Intentional boundaries and exceptions

- Local PDF/Open in Preview, file double-click, Finder reveal/folder opening,
  Quick Look, import/export files, and download-to-Library workflows are unchanged.
- A remote PDF is a Browser navigation. Existing MIME-aware inline PDF/download
  handling decides how it is displayed/saved; this does not import a Library paper.
- Local API links, in-page anchors, explicit download anchors and Browser's own
  chrome are excluded from the delegated DOM handler. Native navigation policy
  still applies to external main-frame/pop-up requests.
- Browser's explicit **Open in Safari** escape hatch remains external. The Help
  menu's repository link and separate User Guide/Loader windows are outside the
  five-workspace routing change. User Guide PDFs continue to open in Preview.
- The CLI/browser-hosted UI has no embedded WebKit bridge: website actions open
  ordinary tabs in that same browser. Popup restrictions can still apply. They
  no longer call `/api/open-url` to launch Safari on the server. The legacy API
  and CLI `--open` startup behavior remain for compatibility, without research
  workspace callers.
- Only public HTTP(S) URLs are navigable in the native Browser. Local/private
  addresses, unsupported schemes and embedded URL credentials remain blocked.
  The native workspace fallback requires a trusted main-frame source and a
  body-free GET; it never replays popup forms or transfers request headers.
- Remote Browser pages receive their existing isolated configuration, not the
  privileged workspace's supplied popup configuration. No workspace file,
  credential or API bridge is installed in them. Browser-internal website
  popups keep their existing WebKit configuration/opener semantics.
- No changes to passwords/AutoFill, cookies/profile, engine, proxy/Clash rules,
  PDF downloading, database schema or benchmark code.

## Regression coverage

`test_workspace_web_links.py` executes the real routing functions and button
bindings with synthetic destinations; it checks cold/warm routing, five-mode
state boundaries, dynamic anchors, middle/Command clicks, local/download
exceptions and browser-hosted fallback. `browser_navigation_probe.m` executes
the native source/origin/method/destination policy without network or profiles.
`browser_workspace_links_probe.cjs` exercises actual DOM events and Browser
chrome in an ephemeral headless page with all network access intercepted.
These checks do not claim live publisher/login success.
