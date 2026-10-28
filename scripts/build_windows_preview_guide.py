"""Adapt the shared guide for Windows without changing the approved layout.

Run with --html-only, then build_windows_user_guide_pdf.py for the matching PDF.
Only documentation outputs are written; application code and research data are
untouched. Both editions use the shared manual's layout and chapter structure.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import re
from html import escape
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "windows"
HTML = OUT / "Windows_Preview_Guide.html"
PDF = OUT / "Windows_Preview_Guide.pdf"
EDITION = "October 28, 2026"
# Keep the guide's default edition aligned with both desktop shells.
VERSION = re.search(r'^__version__ = "([^"]+)"',
                    (ROOT / "paper_monitor/__init__.py").read_text(encoding="utf-8"), re.MULTILINE)[1]


def fragment(value):
    return list(BeautifulSoup(value, "html.parser").contents)


def replace_section(article, heading, replacement):
    """Replace a named h2 section; fail rather than silently lose a future edit."""
    start = next((h for h in article.find_all("h2", recursive=False)
                  if h.get_text(" ", strip=True) == heading), None)
    if start is None:
        raise ValueError(f"Missing section {article['id']}: {heading}")
    following = start.next_sibling
    while following is not None:
        nxt = following.next_sibling
        if isinstance(following, Tag) and (following.name == "h2" or "see-also" in following.get("class", [])):
            break
        following.extract()
        following = nxt
    for node in fragment(replacement):
        start.insert_before(node)
    start.extract()


def replace_topic(soup, identifier, title, content):
    article = soup.find("article", id=identifier)
    links = article.select_one(".see-also")
    if links:
        links.extract()
    article.clear()
    article["data-title"] = title
    for node in fragment(f'<p class="topic-kicker">{escape(article["data-group"])}</p><h1>{escape(title)}</h1>' + content):
        article.append(node)
    if links:
        article.append(links)
    for link in soup.select(f'[data-topic="{identifier}"], a[href="#{identifier}"]'):
        link.string = title


def windows_html():
    soup = BeautifulSoup((ROOT / "paper_monitor/user_guide.html").read_text(encoding="utf-8"), "html.parser")
    # Mac captures are retained in the shared source, never presented as Windows UI.
    for figure in soup.select("figure.guide-screenshot"):
        figure.decompose()

    welcome = soup.find("article", id="welcome")
    welcome.select_one(".guide-revision").string = f"Windows {VERSION} · {EDITION}"
    replace_section(welcome, "Cross-platform core, platform-specific integration", f"""<h2>Windows desktop edition</h2>
<p>This manual describes Gewu Insight {VERSION} for Windows. Install the versioned Setup.exe, then open <strong>Gewu Insight</strong> from the Start menu. The installer includes Python, .NET and application dependencies. It reuses Microsoft WebView2 or installs it from Microsoft when needed.</p>
<p>Requires 64-bit Windows 10 version 1607 (build 14393) or later, including 1803, or Windows 11. The x64 package does not support 32-bit Windows or Windows 10 on ARM.</p>
<p>The six workspaces share the same paper identities, file classifications and SQLite records. Windows supplies File Explorer, file associations, Recycle Bin, a built-in PDF reader and a WebView2 Browser. Apple Passwords/AutoFill, Safari source sync and macOS system Quick Look are not Windows features.</p>
<p>Your research files and SQLite records live in the selected <strong>Gewu Database</strong>, independently of the installed program and any development checkout. The default for a new database is <code>%USERPROFILE%\\Gewu Database</code>; an existing database may be elsewhere. Use <strong>File &gt; Open Gewu Database</strong> to locate the actual folder.</p>
<p>The startup selection is recorded in <code>%USERPROFILE%\\.gewu-insight\\database-location.ini</code>. SQLite owns the database identity and research state; the locator only remembers which database to open.</p>
<p>The default program folder is <code>%LOCALAPPDATA%\\Programs\\Gewu Insight</code>. Existing installation and Library selections take precedence. Updating the program does not move your Library; uninstalling retains research data.</p>
""")
    replace_section(welcome, "Open this guide again", """
<h2>Open this guide</h2>
<p>Choose <strong>Help &gt; User Guide</strong> to open this searchable local manual. Search filters topics; Previous and Next follow the reading order. Use <strong>Print Guide</strong> inside the guide to open the complete PDF for reading or printing. Both editions work offline.</p>
<p>Choose <strong>Help &gt; About Gewu Insight</strong> for the application version and build, original artwork, product description, credits, copyright and research-use license summary. Its <strong>User Guide</strong> link opens this manual; <strong>GitHub</strong> opens the project website.</p>
<p>This Windows edition retains all shared topics and the linked Product Identity chapters. macOS screenshots are omitted because their title bars, menus and platform controls do not represent Windows.</p>
""")

    replace_topic(soup, "quick-look", "Preview Files", """
<p class="lead">Select a local Library or Paper Files item and press Space to inspect it inside Gewu Insight.</p>
<h2>Read and navigate</h2><ol class="steps"><li>Select the resource and press <strong>Space</strong>. Up/Down follows the file list; Escape closes the preview.</li><li>PDFs use continuous pages, a thumbnail rail and native wheel scrolling. Use <strong>Ctrl+wheel</strong> to zoom the PDF. Wider pages can be panned horizontally.</li><li>Use <strong>Open in Default App</strong> for the Windows reader associated with the file. Double-clicking the Library paper row opens its Default file; double-clicking a Paper Files row opens that specific file.</li></ol>
<h2>Read Markdown notes</h2><p>Markdown supports headings, lists, quotations, code, tables and offline mathematical formulas. Leading YAML appears under collapsible <strong>Properties</strong>; analysis provenance appears under <strong>Source record</strong>. These values belong to the note and do not overwrite Paper Details.</p>
<p>Text wraps to the reading area; wide tables and code scroll independently. Nearby images can display locally, remote images remain explicit links, and raw HTML is escaped. Large notes are limited to a 256 KiB preview with a truncation notice; the original file is unchanged. Open the original to read beyond the preview.</p>
<h2>Other files and recovery</h2><p>Supported images, media and text can be inspected in the workspace. Unsupported formats offer an <strong>Open File</strong> action using Windows file associations. If a preview stalls, close it, select the file again and retry; check that the original file exists. There is no macOS system Quick Look mode on Windows.</p>
""")
    replace_topic(soup, "quick-look-settings", "Preview Settings", """
<p class="lead">Open <strong>Settings &gt; Preview Settings</strong> to inspect the built-in preview preference.</p>
<p>Windows offers <strong>Gewu Insight for all files</strong>. The macOS hybrid and all-native options are not shown. Space opens the supported built-in reader or a file card for the selected resource.</p>
<p><strong>Open in Default App</strong> is separate: it follows Windows file associations. Gewu Insight has no separate default-PDF-reader setting. Set the associated application in Windows when needed.</p>
""")
    first = soup.find("article", id="first-session")
    for node in reversed(fragment("""<h2>Open your Gewu Database first</h2>
<ol class="steps"><li>Install the versioned Setup.exe and open <strong>Gewu Insight</strong> from the Start menu. Setup selects the program directory and database directory independently. A configured installation remembers its database.</li><li>During installation or first-start database setup, choose <strong>Use existing Gewu Database</strong> for an existing collection. Select the whole folder containing <code>data/paper_monitor.sqlite</code>, not the SQLite file or the inner data folder.</li><li>Choose <strong>Create new Gewu Database</strong> only for a new collection, using a new or empty folder. This is separate from creating a Space in the current Library.</li><li>Use <strong>File &gt; Open Gewu Database</strong> to reveal the active folder. This reveals the current database in File Explorer; it does not switch databases.</li></ol>
<p>If the remembered database is unavailable, reconnect its disk or locate the intended existing folder. Gewu does not silently replace it with an empty database. A populated database moved to a different path also needs its managed file references and Windows shortcuts verified; selecting a copied folder alone is not a migration.</p>
""")):
        first.select_one(".lead").insert_after(node)
    replace_topic(soup, "backup-migrate", "Back Up and Upgrade", """
<p class="lead">Back up the selected Gewu Database and keep the installer for your current version. The executable alone is not your Library.</p>
<h2 id="source-workspace-migration">Keep the three locations separate</h2><table class="plain-table"><tr><th>Location</th><th>Purpose</th></tr><tr><td>Installed program</td><td>Normally <code>%LOCALAPPDATA%\\Programs\\Gewu Insight</code>. Setup updates the application, bundled runtimes and guide.</td></tr><tr><td>Selected Gewu Database</td><td>Contains <code>data</code>, <code>reports</code>, <code>config</code> and <code>backups</code>, including SQLite, managed Library/Space files and notes. It stays in place during a program update.</td></tr><tr><td>Source checkout</td><td>Development code and build tools. Daily use starts the installed App from the Start menu; editing source does not update the installed App.</td></tr></table>
<h2>Create a consistent backup</h2><ol class="steps"><li>Use <strong>File &gt; Open Gewu Database</strong> to find the selected folder. Save website drafts and finish or stop background tasks.</li><li>Close the Gewu Insight tab in Zotero first, then open the standalone Gewu App and choose <strong>File &gt; Exit</strong>. Wait for the App and service to stop. Copy the entire database folder from this closed state, including hidden files, <code>data/paper_monitor.sqlite</code>, any accompanying WAL/SHM files, managed Library/Space files, Associated Files, notes, configuration and backups.</li><li>Preserve external originals used by Shortcuts separately. Keep Windows .lnk files intact; a shortcut does not contain its target's bytes. Historical import-source paths are provenance and need not be active file dependencies.</li><li>Keep <code>%USERPROFILE%\\.gewu-insight\\database-location.ini</code>, the current installer and relevant AI-client configuration as separate recovery material. Browser profiles are separate from the research folder.</li><li>Verify SQLite integrity, the copied file list and representative files on a separate copy. Store the backup outside the live database and keep the original until the replacement has been checked.</li></ol>
<p>SQLite is authoritative. Copying only JSON exports, the program folder or a database file while it is changing is not a full backup. Do not replace the active database with an older file just to address a display problem.</p>
<h2>Update the installed application</h2><p>After a verified backup, close Gewu Insight and run the newer versioned Setup.exe. Open <strong>Gewu Insight</strong> from the Start menu, then check the selected data folder, existing papers and file access. Check the application version and build in <strong>Help &gt; About Gewu Insight</strong>. Windows <strong>Settings &gt; Apps</strong> also lists the installed version. Keep the previous installer and backup until verification is complete. Do not open the Library with an older incompatible version.</p>
<h2>Move a database</h2><p>For a collection already separate from the program, a routine App update keeps the same folder, identity, Gewu Keys and file classifications. Uninstalling retains research data, the locator and browser sign-ins. A move to another path needs an offline, verified migration of operational file paths and Windows shortcuts; retain the original and do not merge two populated database folders. Do not run the source service and installed App against the same collection.</p>
<h2>Browser and credential boundaries</h2><p>Bookmarks and history are in SQLite. WebView2 website profiles live separately under <code>%LOCALAPPDATA%\\Gewu Insight\\Databases\\&lt;identity&gt;\\Browser</code>; logs and cache use the adjacent <code>Logs</code> and <code>Cache</code> folders. The profile is not a portable sign-in export. Expect to sign in again on another computer. Browser tabs and unsent forms are memory-only and are not restored after quitting.</p>
<p>Metadata API keys and AI Access information can be present in workspace data. Keep full backups private. Exporting bookmarks produces bookmark HTML, not cookies, passwords or browsing history.</p>
<h2>Transfer selected research files</h2><p>Use <a href="#desktop-copy">Make a Portable Desktop Copy</a> for a selected collection. Retain its export manifest and use Folder Loader to restore the file relationships. A portable collection is not a full backup of settings, monitor history and the database. Whole-workspace macOS-to-Windows migration requires separate validation of paths and platform files.</p>
""")

    backup = soup.find("article", id="backup-migrate")
    for node in fragment("""<span id="upgrade-installation"></span><h2 id="windows-software-updates">Update Gewu Insight for Windows</h2>
<p>Windows 1.0.0 has no in-app updater. Download the newer Windows x64 Setup.exe from the project's Releases page, close Gewu and its Zotero tab, and run Setup over the existing program. Keep <strong>Use existing Gewu Database</strong> and its current folder. You only need this manual upgrade once to obtain the new update feature.</p>
<ol class="steps"><li>In Windows 1.1.0 or later, choose <strong>Help &gt; Check for Updates</strong>. The updater reads the stable Windows channel. Mac releases and prereleases are not Windows update candidates.</li><li>If a newer version is available, choose <strong>Download Update</strong>. Gewu verifies the complete file size and SHA-256 before offering installation. Closing the update window cancels an unfinished download.</li><li>Close the Gewu tab in Zotero, pause a Zotero import if one is running, and let downloads and file operations finish. Choose <strong>Install Update</strong>. If work is still active, Gewu keeps the current App open and asks you to retry later.</li><li>Gewu stops its service and opens Windows Setup. Follow its normal pages, retain the existing program and database locations, and leave <strong>Open Gewu Insight</strong> selected on the final page.</li></ol>
<p><strong>Check automatically once a day</strong> checks when the standalone App starts and the last check was at least 24 hours ago. It announces available updates; it does not automatically download or install them. Turn it off in the Software Update window to use only manual checks. If the network check fails, retry later; a failed check does not mean the App is up to date.</p>
<p>Updating replaces program files, not your Gewu Database or original PDFs. Keep a recovery backup before upgrading. Windows packages remain unsigned; checksum verification checks the downloaded bytes against the project update feed and is not a Windows publisher signature.</p>
<p><strong>Update Plugin</strong> in Plugin &gt; Zotero Integration is a separate action. It installs the companion bundled with your current Gewu App. After a program update, use it only if the integration window offers a newer plugin.</p>
"""):
        backup.select_one('.see-also').insert_before(node) if backup.select_one('.see-also') else backup.append(node)
    connection = soup.find("article", id="zotero-connection")
    for node in connection.find_all(string=True):
        node.replace_with(str(node).replace('Gewu Insight > Database Location…', 'File > Open Gewu Database').replace("standalone App's macOS menu", "standalone App's menu").replace('commonly http://127.0.0.1:8765', 'using an automatically selected loopback port'))
    for node in soup.find("article", id="zotero-save").find_all(string=True):
        node.replace_with(str(node).replace('opens the macOS reader', 'opens the Windows default PDF application'))
    note = soup.find("article",id="zotero-install").select_one('.note')
    note.clear()
    for node in fragment('<span class="callout-title">Companion version</span>This Windows edition bundles companion 0.4.2. The installed App reports the exact bundled and installed versions. Windows and Zotero version compatibility should be checked against the release validation notes.'): note.append(node)

    browser = soup.find("article", id="browser")
    for node in fragment("""<h2>Review PDF identity before saving</h2>
<p>Save to Gewu matches the PDF to the selected article. An article's correction metadata pointing back to its own DOI does not by itself make the article a notice. A genuine correction or other publication notice is reviewed under its original article; check the displayed target and file classification. If the original article cannot be resolved, enter its Gewu Key and confirm the attachment.</p>
<p>If PDF drawing order joins a distant ellipsis to a title-page DOI, Gewu checks the layout of that same page. It accepts the complete DOI only when the evidence is unambiguous. Different article identifiers still require review, and the saved PDF bytes are unchanged.</p>
"""):
        browser.append(node)
    replace_section(browser, "Use macOS Passwords", """
<h2>Website sign-in on Windows</h2><p>Complete normal publisher or institutional sign-in yourself in Browser. Its WebView2 profile is separate from Chrome and Edge. Gewu does not import their cookies or credentials. Apple Passwords and its AutoFill trigger are not available in this Windows application.</p>
""")
    # The Mac-specific client tutorial is not a valid Windows connection recipe.
    ai = soup.find("article", id="ai-access")
    replace_section(ai, "Example: connect Codex on macOS", """
<h2>Connect a local MCP client on Windows</h2><ol class="steps"><li>Keep Gewu Insight running on the intended database. In <strong>Settings &gt; AI Access</strong>, enable access and create a named connection with only the required collections and operations.</li><li>Use <strong>Copy MCP Configuration</strong>. Copy the generated command, arguments and environment values into your client's local STDIO server configuration. Keep each path, including spaces, as one argument.</li><li>The installed application provides its own Python runtime and MCP adapter. Use the exact generated paths; no separate Python installation is needed.</li><li>Preserve <code>GEWU_API_URL_FILE</code> and <code>GEWU_DATABASE_IDENTITY</code> when generated. They follow the current local port and bind the connection to the selected database. Keep <code>GEWU_API_TOKEN</code> private; the token is shown only at creation.</li><li>Reload the client's MCP connection, list tools and check a familiar authorized Gewu Key and its Paper Files before requesting writes.</li></ol>
<p>Codex, DeepSeek Harness, Claude Code and other clients supporting a local STDIO MCP server can use this adapter. Map the generated command, arguments and environment into that client's configuration format. Create a separate named Gewu connection for each client. Client model login or API keys are separate from the Gewu token; <code>GEWU_API_URL</code> is a local API address, not a remote MCP server URL.</p>
<h2>Reconnect after an App or database move</h2><p>A verified migration preserves connection permissions and scope; moving the folder does not itself require a new token. Keep the installed App open on the intended database. Update changed runtime, adapter or endpoint paths from its generated configuration, retaining the existing client's own token and unrelated settings. Preserve the database identity and URL-file fields. If these values did not change, keep them. The adapter command points to the installed program, not the research folder.</p>
<p>The client must run where it can access the adapter's local files. A returned file path is not a cloud attachment. This manual does not change your AI client's configuration or its model settings.</p>
""")
    # Remaining h2 after the replaced tutorial is retained (where present).
    replace_topic(soup, "keyboard", "Keyboard Shortcuts", """
<p class="lead">Shortcuts depend on the focused workspace, file list, webpage or text field.</p>
<table class="plain-table"><tr><th>Shortcut or control</th><th>Action and scope</th></tr>
<tr><td>Arrow keys / Enter</td><td>Navigate the focused Library columns, Paper Files, calendars and author list. In text inputs and webpages, editing and page navigation retain their normal meaning.</td></tr>
<tr><td>Space / Escape</td><td>Open or close the selected local file preview; Escape dismisses an active transient control. Space does not open a preview while typing.</td></tr>
<tr><td>Ctrl+F</td><td>Search the current research workspace, or Find on Page in Browser. In this guide, focus topic search.</td></tr>
<tr><td>Ctrl+L</td><td>Focus Browser's address field. Use Loader &gt; Open Loader outside Browser.</td></tr>
<tr><td>Ctrl+D / Ctrl+R</td><td>Bookmark or reload the current Browser page.</td></tr>
<tr><td>Ctrl+T / Ctrl+W</td><td>Create or close a Browser tab. Closing the last tab creates Home.</td></tr>
<tr><td>Ctrl+[</td><td>Return from a research link opened in Browser to its source workspace. Direct Browser entry has no return checkpoint.</td></tr>
<tr><td>Ctrl+wheel</td><td>Zoom the built-in PDF reader.</td></tr>
<tr><td>Ctrl+C / Ctrl+X / Ctrl+V / Ctrl+A</td><td>Copy, cut, paste or select all in the focused supported context. A Library placement action differs from editing text.</td></tr>
<tr><td>View &gt; List View / Table View</td><td>Switch Library presentation.</td></tr>
<tr><td>Right-click</td><td>Open the context menu for the selected item or blank area.</td></tr>
<tr><td>File &gt; Exit</td><td>Close the Windows application; a connected Gewu tab in Zotero keeps its shared service running. Save webpage drafts first; tabs are not restored after quit.</td></tr></table>
<h2>Monitor navigation</h2><p>In Journal or Subject calendars, Left/Right moves a day and Up/Down a week. Enter selects the date. In the paper area, Up/Down selects papers and Escape returns to the calendar. Author Monitor uses Left/Right between its author and paper panes. Arrow commands do not apply while typing in an input.</p>
""")
    startup = soup.find("article", id="startup")
    startup.select_one(".lead").string = "The Windows shell starts a local service for your selected workspace and opens the research interface when it is ready."
    replace_section(startup, "Normal startup", """
<h2>Normal startup</h2><p>Open <strong>Gewu Insight</strong> from the Start menu and wait for the startup screen to finish. Use one window for a workspace; its lock prevents a second desktop process from writing to the same Library. If the selected database is missing, startup stops instead of silently creating an empty replacement.</p>
<p>The installed application includes its runtime dependencies. Keep the selected Library available. If startup fails after an interrupted installation, close the application and rerun its versioned Setup.exe.</p>
<p>Missing, read-only, identity-mismatched or newer-schema databases stop startup with an explanation. Locate the correct database or use the required newer App; do not delete the database to clear an error. When closing, Gewu waits for active requests and database work before releasing its locks.</p>
""")
    replace_section(startup, "Automatic local-server recovery", """
<h2>Automatic local-server recovery</h2><p>The Windows shell retries an unexpectedly stopped service within a bounded restart budget. Workspace-renderer recovery is also bounded. Repeated failures show a recovery message instead of restarting indefinitely.</p>
<p>The separate Browser process can keep tabs and unsent website forms during service recovery while it stays alive. This does not guarantee recovery after an operating-system crash or App exit. Unsaved research-form edits can be lost when the workspace reloads.</p>
""")
    trouble = soup.find("article", id="troubleshooting")
    replace_section(trouble, "AutoFill does not appear or does not fill", """
<h2>Website sign-in is unavailable</h2><p>Apple Passwords and the macOS AutoFill trigger are not part of Windows Preview. Complete sign-in yourself in Browser. If a website rejects the embedded browser, use Open in Default Browser; its sign-in session is separate. Do not copy cookies or credentials into the research interface.</p>
""")
    download = soup.find("article", id="download-sync")
    download.select_one(".lead").insert_after(BeautifulSoup('<p>Paper downloads accept verified publisher or authorized repository sources and check redirects. Unverified destinations stop. Use your legitimate institutional or publisher access; Gewu does not bypass subscriptions or website verification.</p>', "html.parser").p)

    # Replace new Mac-only instructions explicitly instead of renaming APIs.
    replace_section(browser, "Website keys and macOS authorization", """<h2 id="browser-website-keys">Website data on Windows</h2><p>Browser uses its own WebView2 profile. It does not use Apple's Keychain or transfer sign-in cookies from another browser. Complete normal sign-in yourself; use Open in Default Browser if a site does not support this embedded browser.</p>""")
    replace_section(browser, "Share article access with background downloads", """<h2>Share article access with background downloads</h2><p>Supported Windows publisher downloads use a bounded background WebView2 page with Gewu Browser's website session. Complete required sign-in or verification yourself in Browser, then retry Download. External browsers and Zotero have separate website sessions. Access controls and verified source restrictions still apply.</p>""")
    replace_section(download, "Direct download and background webpage fallback", """<h2>Direct download and background webpage fallback</h2><p>Downloads try the configured direct routes first. Supported publisher requests can then use Gewu's background WebView2 page to discover the article PDF without replacing your visible workspace. It shares the standalone Gewu Browser session. Missing access or an unsupported route remains an error; use an authorized publisher page to obtain the PDF.</p>""")
    replace_section(ai, "Example: connect DeepSeek Harness on macOS", """<h2>Connect another local MCP client</h2><p>Use Settings &gt; AI Access &gt; Copy MCP Configuration and enter that generated configuration in your Windows client's local STDIO MCP settings. Use the installed Python and adapter paths exactly, preserve the database identity and endpoint-file fields, and keep the generated token private. Do not paste a macOS path or assume a fixed port.</p>""")
    replace_section(startup, "Before the first launch", """<h2>Before the first launch</h2><p>Install the Windows x64 Setup.exe. Open Gewu Insight from the Start menu. No separate Python or .NET installation is required for daily use. Keep the program and your selected Gewu Database in separate folders.</p>""")
    replace_section(startup, "Find the database you are using", """<h2 id="database-location">Find the database you are using</h2><p>Choose <strong>File &gt; Open Gewu Database</strong> to open the active research folder in File Explorer. This command reveals the current database; it does not create or move one. If startup reports a missing folder or identity mismatch, locate the intended database before changing anything.</p>""")
    replace_section(startup, "Keep the current App in the Dock", """<h2 id="dock-entry">Use the installed shortcut</h2><p>Open <strong>Gewu Insight</strong> from the Windows Start menu. You can pin that installed shortcut to your taskbar. An old development checkout is not the daily application. Upgrading the program retains the existing database selection.</p>""")
    replace_section(trouble, "An upgrade appears to open a different or empty Library", """<h2>An upgrade appears to open a different or empty Library</h2><p>Use File &gt; Open Gewu Database to check the selected folder. Do not import again or recreate records before confirming that it is your intended database. Preserve both locations if they differ. The default program folder and the research data folder are separate.</p>""")
    replace_section(trouble, "A WebCrypto keychain prompt keeps appearing", """<h2 id="browser-key-prompt">Website sign-in differs between interfaces</h2><p>The Windows App and Zotero use separate website sessions. Sign in normally in the interface you are using. Neither Windows interface needs the Mac Keychain or the project's Mac update-signing private key.</p>""")
    replace_section(soup.find("article",id="storage-reference"), "App and machine locations", """<h2>App and machine locations</h2><ul><li><code>%LOCALAPPDATA%/Programs/Gewu Insight</code>: installed program and bundled resources.</li><li><code>%USERPROFILE%/.gewu-insight/database-location.ini</code>: selected database folder and identity; not the database itself.</li><li><code>%LOCALAPPDATA%/Gewu Insight/Databases/&lt;identity&gt;/Logs</code>: startup and background-service diagnostics.</li><li><code>%LOCALAPPDATA%/Gewu Insight/Databases/&lt;identity&gt;/Cache</code>: rebuildable cache; not research originals.</li><li><code>%LOCALAPPDATA%/Gewu Insight/Databases/&lt;identity&gt;/Browser</code>: separate website profile.</li><li><code>%LOCALAPPDATA%/Gewu Insight/Updates</code>: downloaded program updates and per-computer check preferences.</li></ul>""")
    for node in soup.find("article",id="zotero-import").find_all(string=True):
        value=str(node).replace('macOS menu:', 'Windows menu:')
        value=value.replace('This preview has been exercised with Zotero 10.0.6 on macOS; older Zotero versions, Windows and every third-party plugin configuration are not covered by that validation.', 'Check the Windows release notes for tested Zotero versions. Third-party plugin configurations and missing external attachments may need individual review.')
        node.replace_with(value)
    for node in list(soup.select('article p, article li')):
        if "Apple Passwords stays under macOS control" in node.get_text():
            node.string = "Windows Browser uses a separate WebView2 profile. Zotero has its own website session. Gewu does not copy credentials from other browsers or grant AI connections access to website passwords."
        elif "~/Library/Logs/Gewu Insight/paper_monitor_launcher.log" in node.get_text():
            node.string = "For startup errors, inspect %LOCALAPPDATA%/Gewu Insight/Databases/<identity>/Logs/windows-launcher.log and windows-service.log. Keep credentials out of any report you share."

    # Platform-independent facts use the exact Windows labels; platform-specific
    # claims above receive explicit replacements rather than blind word swaps.
    substitutions = [
        ("Back Up or Move to Another Mac", "Back Up and Upgrade"),
        ("mac-software-updates", "windows-software-updates"),
        ("Gewu Insight > About Gewu Insight", "the guide's About Gewu Insight section"),
        ("Setting >", "Settings >"),
        ("Literature Data Source", "Literature Data Sources"),
        ("Open in Preview", "Open in Default App"),
        ("Quick Look Settings", "Preview Settings"),
        ("Quick Look", "Preview"),
        ("Control-click", "Right-click"), ("control-click", "right-click"),
        ("Command-click", "Ctrl-click"), ("Command-left bracket", "Ctrl+left bracket"),
        ("Command-", "Ctrl+"),
        ("native Finder alias", "Windows .lnk shortcut"),
        ("Finder aliases", "Windows .lnk shortcuts"),
        ("Finder alias", "Windows .lnk shortcut"),
        ("directory alias", "directory shortcut"),
        ("Finder", "File Explorer"),
        ("Dock, startup identity", "taskbar, startup identity"),
        ("macOS Trash", "Windows Recycle Bin"),
        ("macOS Preview", "the Windows default PDF application"),
        ("macOS application", "Windows application"),
        ("Preview, Download and Website first", "Open in Default App, Download and Open Website first"),
        ("local project", "selected local workspace"),
        ("managed project layout", "selected workspace layout"),
        ("and inside the App resources", "and in the application folder"),
        ("macOS default browser", "Windows default browser"),
        ("default web browser selected in macOS", "default web browser selected in Windows"),
        ("Open in Safari", "Open in Default Browser"),
        ("WebKit", "WebView2"),
        ("WKDownload", "Browser download"),
        ("Gewu Insight.app", "Gewu Insight from the Start menu"),
        ("logs/paper_monitor_launcher.log", "logs/windows-launcher.log"),
        ("⌘Q", "File > Exit"), ("⌘L", "Ctrl+L"), ("⌘F", "Ctrl+F"),
        ("⌘", "Ctrl+"), ("⇧", "Shift+"),
    ]
    for node in list(soup.find_all(string=True)):
        if node.parent.name in {"script", "style"}:
            continue
        value = str(node)
        for old, new in substitutions:
            value = value.replace(old, new)
        node.replace_with(value)
    for node in soup.select("[data-title]"):
        for old, new in substitutions:
            node["data-title"] = node["data-title"].replace(old, new)

    # Mac integration paragraphs that cannot be generalized safely are replaced
    # individually below; each pattern must still match the shared source.
    corrections = [
        ("The compact, flat search control", "The top-right search control expands on hover or focus. Each research workspace retains its query; clear it with ×. Use the Windows title bar to move, maximize or restore the window."),
        ("Drag the same blank top area", "Window movement, snapping and virtual desktops follow your Windows configuration. Start a drag from the native title bar; tabs and search controls have their own actions."),
        ("The desktop window presents a local interface", "The desktop window presents the local Python service and SQLite workspace. The Windows shell supplies File Explorer, file associations, Recycle Bin, PDF reading and WebView2 browsing. Network sources contribute metadata and files while the durable workspace stays local."),
        ("If macOS denies Safari file access", "Windows supports manual Sync from Chrome using one selected local bookmark file and subtree. Safari source sync is not offered. Import an exported bookmark HTML file when no supported local source is available; source files are not modified."),
        ("WebView2 follows macOS networking", "Browser uses WebView2 and the current system network configuration. Gewu does not change proxies or Clash rules. Verify the actual route for publisher, PDF, login and CDN hosts independently; institutional access remains subject to the website."),
        ("A secure-connection error such as", "A secure-connection error can reflect network, VPN, routing, system time or certificate problems. Restore the connection, then reload once. The error alone does not prove an expired site certificate. Certificate verification remains enabled."),
        ("A failed database deletion restores the moved file when macOS", ""),
        ("Choose Help > Contact Us", "Choose Help > Contact Us to open info@gewu-insight.com in your default email application. Include the installed version, affected workflow and steps to reproduce; omit passwords, tokens and private research data. Review and send the message yourself."),
        ("A Library copy creates another reference", "A Library copy creates another placement of the same paper. Windows secondary main-file locations use .lnk shortcuts, and secondary Associated Files locations point to the canonical bundle. Versions and attachments remain associated with that paper; a placement copy does not create another unrelated identity."),
        ("Drag a card's file icon or filename", "Drag a Paper Files icon or filename to File Explorer or a compatible application to copy or open the real file. Library file icons use the same native drag. The receiving application determines its accepted formats and drag behavior; not every external destination has been verified."),
        ("Local PDFs still open in Preview", "Local files open through Windows file associations; File Explorer, the built-in preview and downloads keep their own actions. Browser's explicit Open in Default Browser opens the Windows default browser with its separate website session. Changing Website Links does not transfer cookies or existing tabs."),
        ("When the same Gewu Key appears in several folders", "When one Gewu Key appears in several folders, it shares one Paper Files bundle. The main file stays at its canonical location. Other Windows placements use .lnk shortcuts and their associated directories point to the canonical bundle. Make Copy Desktop resolves these pointers into real files for a portable export."),
        ("Automatic monitoring runs inside the local UI service", "Automatic monitoring runs inside the local UI service with startup delays, periodic checks and saved completion/retry state. Keep Windows awake and Gewu Insight running. Closing the standalone window stops its service unless a connected Gewu tab in Zotero still needs it. A late launch checks due work; it does not guarantee a run at the exact scheduled minute."),
        ("The UI server listens on the local loopback address", "The Windows desktop starts its local service on a free loopback port. Its current address is recorded for MCP discovery; do not assume port 8765. The service is local to this computer."),
        ("The built-in preview can flash as it loads another PDF", "Switching files can briefly expose loading while a new document is prepared. Let it finish or use Open in Default App to read the file separately. Windows has no macOS system Quick Look mode; Preview Settings cannot switch to it."),
        ("A verification loop does not establish", "An embedded Browser can still be rejected by a publisher's verification. Reload once; if it repeats, use Open in Default Browser and complete the site's normal access steps yourself. The external browser has a separate session. Do not repeatedly retry or bypass the challenge."),
        ("Right-click links for Open Link in New Tab", "Right-click a webpage link and choose Open Link in New Tab. Bookmarks, Favorites and History provide Open in New Tab in their context menus. Ordinary clicks open in the current tab; new-window links can create another tab."),
        ("Ctrl+F opens Find on Page", "Ctrl+F opens Find on Page. Enter selects the next match and Shift+Enter the previous match. Browser is part of the Windows desktop application; a separately hosted web UI does not embed a second browser engine."),
        ("Choose Loader > Open Loader . Outside Browser", "Choose Loader > Open Loader. In Browser, Ctrl+L focuses its address field; use the menu to open Loader."),
        ("Help > Contact Us opens your default email application's draft", "Help > Contact Us opens info@gewu-insight.com in the Windows default email application. If none is configured, use your preferred mail service. Include the installed version, operation and error; omit passwords and tokens. Review and send the message yourself."),
        ("Choose Settings > Literature Data Sources , or press", "Choose Settings > Literature Data Sources. The dialog provides provider settings and separate connection tests."),
    ]
    for prefix, replacement in corrections:
        matches = [p for p in soup.select("article p, article li") if prefix in p.get_text(" ", strip=True)]
        if not matches:
            if prefix.startswith("A failed database"):
                continue
            raise ValueError(f"Missing platform paragraph: {prefix}")
        for p in matches:
            if prefix.startswith("A failed database"):
                p.string = "Deleting a private managed attachment uses Windows Recycle Bin and a verified recovery backup before its file registration is removed. Shared files and external originals remain protected. A failed operation stays visible; do not assume a failure deleted the file."
            else:
                p.string = replacement

    # Finish literal platform references, including table cells and list items.
    for node in list(soup.find_all(string=True)):
        if node.parent.name in {"script", "style"}:
            continue
        value = str(node)
        for old, new in [
            ("on your Mac", "on your Windows computer"),
            ("on this Mac", "on this Windows computer"),
            ("another Mac", "another computer"),
            ("sleeping Mac", "sleeping computer"),
            ("the Mac's local time zone", "the computer's local time zone"),
            ("selected in macOS", "selected in Windows"),
            ("macOS launcher diagnostics", "Windows launcher diagnostics"),
            ("logs/windows-launcher.log", "%LOCALAPPDATA%/Gewu Insight/Databases/<identity>/Logs/windows-launcher.log"),
            ("native Start Gewu Insight.cmd", "Windows desktop application"),
            ("macOS system Preview", "macOS system Quick Look"),
            ("not shared with Safari", "not shared with Chrome or Edge"),
            ("not Safari synchronization", "not Chrome synchronization"),
            ("or Apple Passwords", "or external browser data"),
        ]:
            value = value.replace(old, new)
        node.replace_with(value)
    for li in soup.select("article li"):
        value = li.get_text(" ", strip=True)
        if "~/Library/Safari/Bookmarks.plist" in value:
            li.string = "Select Chrome's Bookmarks file from the intended local profile, normally under %LOCALAPPDATA%/Google/Chrome/User Data/Default/ or a Profile directory. Only that selected file is read. Choose its folder/subtree, then confirm the manual one-way sync."
        elif "earlier local server may still own port 8765" in value:
            li.string = "Close the existing Gewu Insight window normally before reopening the selected database. If startup still fails, inspect %LOCALAPPDATA%/Gewu Insight/Databases/<identity>/Logs/windows-launcher.log; do not remove the database or start an older incompatible App."

    # Remove Mac-only bookmark/menu instructions and native keyboard promises.
    for node in list(soup.select("article p, article li, article tr")):
        value = node.get_text(" ", strip=True)
        if "Sync from Safari" in value:
            node.string = "Choose B > Sync from Chrome. This is a manual, one-way operation; it does not watch the source or write changes back to Chrome."
        if "AutoFill only triggers" in value:
            for text_node in list(node.find_all(string=True)):
                text_node.replace_with(str(text_node).replace("AutoFill only triggers in the visible page.", ""))
        if "Open Passwords" in value or "Passkey" in value or "Dock tile" in value:
            node.decompose()

    # Genuine installed Windows captures, separate from the shared Mac edition.
    # Keep their file paths for the matching PDF and inline bytes for offline HTML.
    importer = soup.find("article", id="zotero-import")
    scope_heading = next(h for h in importer.find_all("h2") if h.get_text(strip=True) == "Choose scope and destination")
    scope_heading["id"] = "windows-zotero-import-scope"
    preview_heading = next(h for h in importer.find_all("h2") if h.get_text(strip=True) == "Preview, then start the copy")
    preview_heading["id"] = "windows-zotero-import-preview"
    screenshots = [
        ("windows-zotero-import-preview", "zotero-import-preview.png",
         "Preview Import reads the selected Zotero library before copying. This empty library correctly shows zero items and attachments. Your counts depend on the selected source; no import was started for this capture."),
        ("windows-zotero-import-scope", "zotero-import-scope.png",
         "The installed Windows App connected to Zotero. Choose the source and Gewu destination, then use Preview Import. Connecting alone does not copy papers."),
        ("windows-software-updates", "software-update.png",
         "Help > Check for Updates opens the Windows update window. Automatic checks do not install updates without your action."),
    ]
    for anchor, filename, caption in screenshots:
        path = ROOT / "assets/user-guide/windows" / filename
        if not path.is_file():
            raise ValueError("Missing installed Windows screenshot: " + filename)
        figure = soup.new_tag("figure", attrs={"class": "guide-screenshot"})
        image = soup.new_tag("img", attrs={"src": "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii"),
            "data-pdf-image": str(path.relative_to(ROOT)), "alt": caption})
        figure.append(image)
        label = soup.new_tag("figcaption"); label.string = caption; figure.append(label)
        heading = soup.find(id=anchor)
        if heading is None:
            raise ValueError("Missing Windows screenshot section: " + anchor)
        heading.insert_after(figure)

    # Local standalone HTML must not request service-only image/PDF endpoints.
    spec = importlib.util.spec_from_file_location("guide_common", ROOT / "scripts/build_user_guide_pdf.py")
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    for img in soup.select("img[src]"):
        path = common.IMAGE_ROUTES.get(img["src"])
        if path:
            img["data-pdf-image"] = str(path.relative_to(ROOT))
            img["src"] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    script = soup.find("script")
    javascript = script.string
    javascript = javascript.replace("window.open('/user-guide.pdf', '_blank', 'noopener');", "window.open('Windows_Preview_Guide.pdf', '_blank', 'noopener');")
    # Resolve subsection links into their owning topic instead of falling home.
    javascript = javascript.replace("return topicById.has(id) ? id : 'welcome';", "return topicById.has(id) ? id : (document.getElementById(id)?.closest('.help-topic')?.id || 'welcome');")
    script.string = javascript
    soup.title.string = f"Gewu Insight User Guide - Windows {VERSION}"
    return soup, common


def main():
    global VERSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--check", action="store_true", help="Verify the existing HTML/PDF match the build version without rewriting them.")
    parser.add_argument("--html-only", action="store_true", help="Update HTML only; preserve the approved PDF's fonts, layout and pagination.")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        parser.error("--version must have the form major.minor.patch")
    VERSION = args.version
    if args.check:
        from pypdf import PdfReader
        title = f"Gewu Insight User Guide - Windows {VERSION}"
        soup = BeautifulSoup(HTML.read_text(encoding="utf-8"), "html.parser")
        reader = PdfReader(PDF)
        if (soup.title.get_text() != title or
                not soup.select_one(".guide-revision").get_text().startswith(f"Windows {VERSION} ·") or
                reader.metadata.title != title or f"Windows {VERSION}" not in reader.pages[0].extract_text()):
            parser.error("User Guide version mismatch; regenerate HTML and build its PDF with scripts/build_windows_user_guide_pdf.py.")
        print(f"HTML and PDF User Guide match Windows {VERSION}.")
        return
    if not args.html_only:
        parser.error("Use --html-only to update HTML, then scripts/build_windows_user_guide_pdf.py to generate the matching PDF with the shared LaTeX layout.")
    soup, _ = windows_html()
    HTML.write_text(str(soup), encoding="utf-8")
    print(HTML)
    print(f"Preserved approved PDF: {PDF}")


if __name__ == "__main__":
    main()
