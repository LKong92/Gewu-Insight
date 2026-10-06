"""Build the complete Windows guide from the shared manual and explicit adapters.

Run with the project .venv. Only documentation outputs are written. The shared
macOS HTML/TeX/PDF, application binaries, settings and research data are untouched.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import re
from html import escape
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "windows"
HTML = OUT / "Windows_Preview_Guide.html"
PDF = OUT / "Windows_Preview_Guide.pdf"
EDITION = "October 6, 2026"
VERSION = "0.1.23"


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
<p>The six workspaces share the same paper identities, file classifications and SQLite records. Windows supplies File Explorer, file associations, Recycle Bin, a built-in PDF reader and a WebView2 Browser. Apple Passwords/AutoFill, Safari source sync and macOS system Quick Look are not Windows features.</p>
<p>Your existing workspace is normally <code>%USERPROFILE%\\Gewu Insight Preview</code>. Use <strong>File &gt; Open Data Folder</strong> to locate the actual selected workspace. The selection is recorded in <code>%USERPROFILE%\\.gewu-insight\\preview-workspace.txt</code>. Program files and research data are separate.</p>
<p>The default program folder is <code>%LOCALAPPDATA%\\Programs\\Gewu Insight</code>. Existing installation and Library selections take precedence. Updating the program does not move your Library; uninstalling retains research data.</p>
""")
    replace_section(welcome, "Open this guide again", """
<h2>Open this guide</h2>
<p>Choose <strong>Help &gt; User Guide</strong> to open this searchable local manual. Search filters topics; Previous and Next follow the reading order. Use <strong>Print Guide</strong> inside the guide to open the complete PDF for reading or printing. Both editions work offline.</p>
<p>This Windows edition retains all 49 shared topics and the linked Product Identity chapters. macOS screenshots are omitted because their title bars, menus and platform controls do not represent Windows.</p>
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
    replace_topic(soup, "backup-migrate", "Back Up and Upgrade", """
<p class="lead">Back up the selected workspace and keep the installer for your current version. The executable alone is not your Library.</p>
<h2>Create a consistent backup</h2><ol class="steps"><li>Use <strong>File &gt; Open Data Folder</strong> to find the selected workspace. Save website drafts and finish or stop background tasks.</li><li>Close the main Gewu window or choose <strong>File &gt; Exit</strong>. This stops its local service. Copy the entire workspace while it is closed, including <code>data/paper_monitor.sqlite</code>, any accompanying WAL/SHM files, managed Library/Space files, Associated Files and notes.</li><li>Preserve external folders used by Shortcuts separately. Keep the workspace-selection file and the installer for the current version as recovery material.</li><li>Verify the backup opens on a separate copy before relying on it. Keep the original unchanged until the replacement has been checked.</li></ol>
<p>SQLite is authoritative. Copying only JSON exports, the program folder or a database file while it is changing is not a full backup. Do not replace the active database with an older file just to address a display problem.</p>
<h2>Update the installed application</h2><p>After a verified backup, close Gewu Insight and run the newer versioned Setup.exe. Open <strong>Gewu Insight</strong> from the Start menu, then check the selected data folder, existing papers and file access. Check the installed version in Windows <strong>Settings &gt; Apps &gt; Installed apps</strong>. Keep the previous installer and backup until verification is complete. Do not open the Library with an older incompatible version.</p>
<h2>Browser and credential boundaries</h2><p>Bookmarks and history are in SQLite. WebView2 website data is separate, under <code>webview/browser</code> in the workspace; it is not a portable sign-in export. Expect to sign in again on another computer. Browser tabs and unsent forms are memory-only and are not restored after quitting.</p>
<p>Metadata API keys and AI Access information can be present in workspace data. Keep full backups private. Exporting bookmarks produces bookmark HTML, not cookies, passwords or browsing history.</p>
<h2>Transfer selected research files</h2><p>Use <a href="#desktop-copy">Make a Portable Desktop Copy</a> for a selected collection. Retain its export manifest and use Folder Loader to restore the file relationships. A portable collection is not a full backup of settings, monitor history and the database. Whole-workspace macOS-to-Windows migration requires separate validation of paths and platform files.</p>
""")

    browser = soup.find("article", id="browser")
    replace_section(browser, "Use macOS Passwords", """
<h2>Website sign-in on Windows</h2><p>Complete normal publisher or institutional sign-in yourself in Browser. Its WebView2 profile is separate from Chrome and Edge. Gewu does not import their cookies or credentials. Apple Passwords and its AutoFill trigger are not available in this Windows application.</p>
""")
    # The Mac-specific client tutorial is not a valid Windows connection recipe.
    ai = soup.find("article", id="ai-access")
    replace_section(ai, "Example: connect Codex on macOS", """
<h2>Connect a local MCP client on Windows</h2><ol class="steps"><li>Keep Gewu Insight running. In <strong>Settings &gt; AI Access</strong>, enable access and create a named connection with only the required collections and operations.</li><li>Use <strong>Copy MCP Configuration</strong>. Copy the generated command, arguments and environment values into your client's local STDIO server configuration. Keep each path, including spaces, as one argument.</li><li>The installed application provides its own Python runtime and MCP adapter. Use the exact generated paths; no separate Python installation is needed.</li><li>Preserve <code>GEWU_API_URL_FILE</code> when generated. It follows the current local port after an App restart. Keep <code>GEWU_API_TOKEN</code> private; do not paste it into a chat. The token is shown only at creation.</li><li>Reload the client's MCP connection. Verify a permitted collection before requesting files or writes. Moving the application or Library requires a newly generated configuration.</li></ol>
<p>The client must run where it can access the adapter's local files. A returned file path is not a cloud attachment. This manual does not change your AI client's configuration or its model settings.</p>
""")
    # Remaining h2 after the replaced tutorial is retained (where present).
    replace_topic(soup, "keyboard", "Keyboard Shortcuts", """
<p class="lead">Shortcuts depend on the focused workspace, file list, webpage or text field.</p>
<table class="plain-table"><tr><th>Shortcut or control</th><th>Action and scope</th></tr>
<tr><td>Arrow keys / Enter</td><td>Navigate the focused Library columns, Paper Files, calendars and author list. In text inputs and webpages, editing and page navigation retain their normal meaning.</td></tr>
<tr><td>Space / Escape</td><td>Open or close the selected local file preview; Escape dismisses an active transient control. Space does not open a preview while typing.</td></tr>
<tr><td>Ctrl+F</td><td>Search the current research workspace, or Find on Page in Browser. In this guide, focus topic search.</td></tr>
<tr><td>Ctrl+L</td><td>Focus Browser's address field. Use File &gt; Library Loader or Loader &gt; Open Loader outside Browser.</td></tr>
<tr><td>Ctrl+D / Ctrl+R</td><td>Bookmark or reload the current Browser page.</td></tr>
<tr><td>Ctrl+T / Ctrl+W</td><td>Create or close a Browser tab. Closing the last tab creates Home.</td></tr>
<tr><td>Ctrl+[</td><td>Return from a research link opened in Browser to its source workspace. Direct Browser entry has no return checkpoint.</td></tr>
<tr><td>Ctrl+wheel</td><td>Zoom the built-in PDF reader.</td></tr>
<tr><td>Ctrl+C / Ctrl+X / Ctrl+V / Ctrl+A</td><td>Copy, cut, paste or select all in the focused supported context. A Library placement action differs from editing text.</td></tr>
<tr><td>View &gt; List View / Table View</td><td>Switch Library presentation.</td></tr>
<tr><td>Right-click</td><td>Open the context menu for the selected item or blank area.</td></tr>
<tr><td>File &gt; Exit</td><td>Close the Windows application and stop its service. Save webpage drafts first; tabs are not restored after quit.</td></tr></table>
<h2>Monitor navigation</h2><p>In Journal or Subject calendars, Left/Right moves a day and Up/Down a week. Enter selects the date. In the paper area, Up/Down selects papers and Escape returns to the calendar. Author Monitor uses Left/Right between its author and paper panes. Arrow commands do not apply while typing in an input.</p>
""")
    startup = soup.find("article", id="startup")
    startup.select_one(".lead").string = "The Windows shell starts a local service for your selected workspace and opens the research interface when it is ready."
    replace_section(startup, "Normal startup", """
<h2>Normal startup</h2><p>Open <strong>Gewu Insight</strong> from the Start menu and wait for the startup screen to finish. Use one window for a workspace; its lock prevents a second desktop process from writing to the same Library. If the selected database is missing, startup stops instead of silently creating an empty replacement.</p>
<p>The installed application includes its runtime dependencies. Keep the selected Library available. If startup fails after an interrupted installation, close the application and rerun its versioned Setup.exe.</p>
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

    # Platform-independent facts use the exact Windows labels; platform-specific
    # claims above receive explicit replacements rather than blind word swaps.
    substitutions = [
        ("Back Up or Move to Another Mac", "Back Up and Upgrade"),
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
        ("Browser website data and its disposable favicon cache are managed", "Browser website data is under webview/browser in the selected Windows workspace. It is separate from SQLite bookmarks/history and Monitor caches. Do not assume that copying it transfers usable sign-ins to another computer."),
        ("A failed database deletion restores the moved file when macOS", ""),
        ("Choose Help > Contact Us", "Choose Help > Contact Us to open info@gewu-insight.com in your default email application. Include the installed version, affected workflow and steps to reproduce; omit passwords, tokens and private research data. Review and send the message yourself."),
        ("A Library copy creates another reference", "A Library copy creates another placement of the same paper. Windows secondary main-file locations use .lnk shortcuts, and secondary Associated Files locations point to the canonical bundle. Versions and attachments remain associated with that paper; a placement copy does not create another unrelated identity."),
        ("Drag a card's file icon or filename", "Drag a Paper Files icon or filename to File Explorer or a compatible application to copy or open the real file. Library file icons use the same native drag. The receiving application determines its accepted formats and drag behavior; not every external destination has been verified."),
        ("Local PDFs still open in Preview", "Local files open through Windows file associations; File Explorer, the built-in preview and downloads keep their own actions. Browser's explicit Open in Default Browser opens the Windows default browser with its separate website session. Changing Website Links does not transfer cookies or existing tabs."),
        ("When the same Gewu Key appears in several folders", "When one Gewu Key appears in several folders, it shares one Paper Files bundle. The main file stays at its canonical location. Other Windows placements use .lnk shortcuts and their associated directories point to the canonical bundle. Make Copy Desktop resolves these pointers into real files for a portable export."),
        ("Automatic monitoring runs inside the local UI service", "Automatic monitoring runs inside the local UI service with startup delays, periodic checks and saved completion/retry state. Keep Windows awake and Gewu Insight running. Closing the main Windows window stops its service. A late launch checks due work; it does not guarantee a run at the exact scheduled minute."),
        ("The UI server listens on the local loopback address", "The Windows desktop starts its local service on a free loopback port. Its current address is recorded for MCP discovery; do not assume port 8765. The service is local to this computer."),
        ("The built-in preview can flash as it loads another PDF", "Switching files can briefly expose loading while a new document is prepared. Let it finish or use Open in Default App to read the file separately. Windows has no macOS system Quick Look mode; Preview Settings cannot switch to it."),
        ("A verification loop does not establish", "An embedded Browser can still be rejected by a publisher's verification. Reload once; if it repeats, use Open in Default Browser and complete the site's normal access steps yourself. The external browser has a separate session. Do not repeatedly retry or bypass the challenge."),
        ("Right-click links for Open Link in New Tab", "Right-click a webpage link and choose Open Link in New Tab. Bookmarks, Favorites and History provide Open in New Tab in their context menus. Ordinary clicks open in the current tab; new-window links can create another tab."),
        ("Ctrl+F opens Find on Page", "Ctrl+F opens Find on Page. Enter selects the next match and Shift+Enter the previous match. Browser is part of the Windows desktop application; a separately hosted web UI does not embed a second browser engine."),
        ("Choose Loader > Open Loader . Outside Browser", "Choose File > Library Loader or Loader > Open Loader. In Browser, Ctrl+L focuses its address field; use the menu to open Loader."),
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
            ("another Mac", "another computer"),
            ("sleeping Mac", "sleeping computer"),
            ("the Mac's local time zone", "the computer's local time zone"),
            ("selected in macOS", "selected in Windows"),
            ("macOS launcher diagnostics", "Windows launcher diagnostics"),
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
            li.string = "Close the existing Gewu Insight window normally before reopening the selected workspace. If startup still fails, inspect logs/windows-launcher.log in the data folder; do not remove the database or start an older Preview."

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


def fonts():
    """Use installed Windows fonts; no font download or installation."""
    folder = Path("C:/Windows/Fonts")
    for name, file in [("Guide", "arial.ttf"), ("GuideBold", "arialbd.ttf"),
                       ("GuideItalic", "ariali.ttf"), ("GuideBoldItalic", "arialbi.ttf"),
                       ("GuideCJK", "simsun.ttc"), ("GuideSymbols", "seguisym.ttf")]:
        pdfmetrics.registerFont(TTFont(name, str(folder / file)))
    pdfmetrics.registerFontFamily("Guide", normal="Guide", bold="GuideBold", italic="GuideItalic", boldItalic="GuideBoldItalic")


def pdf_text(value):
    value = re.sub(r"GEWU[A-Z]+(?:START|END)", "", value)
    value = value.replace("\u2011", "-").replace("\u00a0", " ")
    value = escape(value)
    value = re.sub(r"([\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]+)", r'<font name="GuideCJK">\1</font>', value)
    return value.replace("↺", '<font name="GuideSymbols">↺</font>')


def inline(node):
    if isinstance(node, NavigableString):
        return pdf_text(str(node))
    if not isinstance(node, Tag):
        return ""
    inner = "".join(inline(n) for n in node.children)
    if node.name in {"b", "strong"}:
        return f"<b>{inner}</b>"
    if node.name in {"i", "em"}:
        return f"<i>{inner}</i>"
    if node.name == "br":
        return "<br/>"
    if node.name == "small" and re.search(r"[\u2e80-\u9fff]", node.get_text()):
        return "<br/>" + inner
    if node.name == "a" and node.get("href"):
        href = node["href"]
        if href.startswith(("#", "http:", "https:", "mailto:")):
            return f'<a href="{escape(href, quote=True)}" color="#1769c2">{inner}</a>'
    return inner


class GuidePDF(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if hasattr(flowable, "guide_bookmark"):
            key, title, level = flowable.guide_bookmark
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key, level=level, closed=level > 0)
            if getattr(flowable, "guide_toc", False):
                self.notify("TOCEntry", (level, escape(title), self.page, key))


def build_pdf(soup, common):
    fonts()
    base = dict(fontName="Guide", fontSize=10, leading=14, textColor=colors.HexColor("#243247"), spaceAfter=8)
    body = ParagraphStyle("GuideBody", **base)
    small = ParagraphStyle("GuideSmall", parent=body, fontSize=8.5, leading=12)
    headings = {
        1: ParagraphStyle("GuidePart", parent=body, fontName="GuideBold", fontSize=25, leading=30, spaceAfter=20, keepWithNext=True),
        2: ParagraphStyle("GuideChapter", parent=body, fontName="GuideBold", fontSize=19, leading=24, spaceBefore=16, spaceAfter=12, keepWithNext=True),
        3: ParagraphStyle("GuideSection", parent=body, fontName="GuideBold", fontSize=14, leading=19, spaceBefore=13, spaceAfter=9, keepWithNext=True),
        4: ParagraphStyle("GuideHeading", parent=body, fontName="GuideBold", fontSize=11, leading=15, spaceBefore=10, spaceAfter=7, keepWithNext=True),
    }
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle(f"TOC{i}", parent=small, leftIndent=i*13,
                                      firstLineIndent=0, spaceBefore=7 if i == 0 else 3,
                                      fontName="GuideBold" if i < 2 else "Guide") for i in range(3)]
    story = [Spacer(1, 55), Paragraph("Gewu Insight", headings[1]),
             Paragraph("User Guide", headings[1]),
             Paragraph(f"Windows {VERSION}", headings[2]),
             Paragraph(EDITION, body),
             Spacer(1, 24), Paragraph("Library · Paper Files · Publications<br/>Journal · Subject · Author · Browser · AI Access", body),
             Spacer(1, 18), Paragraph("A complete Windows edition of the shared 49-topic manual. Interface names match the Windows application. The HTML edition supports topic search; this PDF has linked contents and bookmarks.", body),
             PageBreak(), Paragraph("Contents", headings[1]), toc, PageBreak()]

    # Reuse the established semantic hierarchy and diagram/table conversion.
    # The temporary source is documentation-only and lives in the ignored QA dir.
    work = ROOT / "tmp/windows-user-guide"
    work.mkdir(parents=True, exist_ok=True)
    semantic_source = BeautifulSoup(str(soup), "html.parser")
    for img in semantic_source.select("img[data-pdf-image]"):
        img["src"] = str(ROOT / img["data-pdf-image"])
    input_path = work / "windows-semantic-source.html"
    input_path.write_text(str(semantic_source), encoding="utf-8")
    common.HTML_SOURCE = input_path
    semantic = BeautifulSoup(common.clean_guide_html(), "html.parser")
    counters = [0, 0, 0, 0]
    anchors = set()
    part_number = 0
    topic_ids = {node["id"] for node in soup.select("article.guide-topic")}

    def paragraph(node, style=body):
        content = inline(node).strip()
        key = node.get("id") if isinstance(node, Tag) else None
        if key and key not in anchors:
            anchors.add(key)
            content = f'<a name="{escape(key)}"/>' + content
        return Paragraph(content or " ", style)

    def blocks(parent):
        nonlocal part_number
        output = []
        # Preserve inline runs in callouts. The shared semantic converter may
        # leave text, strong and span siblings directly inside a blockquote.
        # Treating each text node as a paragraph fragments warning sentences.
        nodes, run = [], []
        block_names = {"p", "pre", "div", "section", "blockquote", "figure", "figcaption", "table", "ul", "ol", "img"}
        def flush_inline():
            if run and any(str(n).strip() for n in run):
                nodes.append(BeautifulSoup("<p>" + "".join(str(n) for n in run) + "</p>", "html.parser").p)
            run.clear()
        for child in parent.children:
            if isinstance(child, Tag) and (child.name in block_names or re.fullmatch("h[1-6]", child.name)):
                flush_inline()
                nodes.append(child)
            else:
                run.append(child)
        flush_inline()
        for node in nodes:
            if isinstance(node, NavigableString):
                if node.strip():
                    output.append(paragraph(node))
                continue
            if not isinstance(node, Tag):
                continue
            if re.fullmatch("h[1-6]", node.name):
                level = int(node.name[1])
                if level == 1:
                    if part_number:
                        output.append(PageBreak())
                    part_number += 1
                    counters[:] = [part_number, 0, 0, 0]
                    prefix = str(part_number)
                else:
                    slot = min(level-1, 3)
                    counters[slot] += 1
                    for index in range(slot+1, 4):
                        counters[index] = 0
                    prefix = f"{counters[0]}-{counters[1]}" + (f".{counters[2]}" if level == 3 else "") if level <= 3 else ""
                title = node.get_text(" ", strip=True)
                p = Paragraph(pdf_text(f"{prefix}  {title}".strip()), headings[min(level, 4)])
                key = node.get("id") or f"heading-{len(anchors)}"
                if key not in anchors:
                    anchors.add(key)
                    if level <= 3:
                        p.guide_bookmark = (key, f"{prefix}  {title}".strip(), level-1)
                        p.guide_toc = level <= 2 or key in topic_ids
                    else:
                        p = Paragraph(f'<a name="{escape(key)}"/>' + pdf_text(title), headings[4])
                # Chapters 4-1 through 4-4 intentionally have no forced breaks.
                output.append(p)
            elif node.name == "table":
                rows = [[paragraph(cell, small) for cell in row.find_all(["td", "th"], recursive=False)] for row in node.find_all("tr")]
                rows = [row for row in rows if row]
                if rows:
                    count = max(map(len, rows))
                    for row in rows:
                        row.extend([""] * (count-len(row)))
                    widths = [142, 365] if count == 2 else [507/count]*count
                    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
                    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8f2ff")),
                        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f6f8fb")]),
                        ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0),(-1,-1),7),
                        ("RIGHTPADDING", (0,0),(-1,-1),7), ("TOPPADDING",(0,0),(-1,-1),7),
                        ("BOTTOMPADDING",(0,0),(-1,-1),7), ("LINEBELOW", (0,0),(-1,0),.5,colors.HexColor("#b9cfe6"))]))
                    output.extend([table, Spacer(1, 9)])
            elif node.name in {"ul", "ol"}:
                for index, li in enumerate(node.find_all("li", recursive=False), 1):
                    output.append(Paragraph((f"{index}. " if node.name == "ol" else "• ") + inline(li), body))
            elif node.name == "img":
                path = node.get("src", "")
                if Path(path).is_file():
                    img = Image(path)
                    factor = min(400/img.imageWidth, 220/img.imageHeight, 1)
                    img.drawWidth = img.imageWidth * factor
                    img.drawHeight = img.imageHeight * factor
                    img.hAlign = "CENTER"
                    output.extend([img, Spacer(1, 9)])
            elif node.find("img"):
                output.extend(blocks(node))
            elif node.name in {"p", "pre", "figcaption"}:
                if node.get_text(strip=True) and not re.fullmatch(r"GEWU[A-Z]+", node.get_text(strip=True)):
                    related = "GEWURELATEDSTART" in node.get_text()
                    item = paragraph(node, small if related else body)
                    if related and output and isinstance(output[-1], Paragraph):
                        output.append(KeepTogether([output.pop(), item]))
                    else:
                        output.append(item)
            else:
                output.extend(blocks(node))
        return output

    story.extend(blocks(semantic.body))
    doc = GuidePDF(str(PDF), pagesize=(595,842), leftMargin=44, rightMargin=44,
                   topMargin=43, bottomMargin=43, title=f"Gewu Insight User Guide - Windows {VERSION}",
                   author="Gewu Insight", allowSplitting=True)
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Guide", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(44, 23, f"Gewu Insight | Windows {VERSION} | {EDITION}")
        canvas.drawRightString(551, 23, str(document.page))
        canvas.restoreState()
    doc.addPageTemplates(PageTemplate(id="guide", frames=Frame(44,43,507,756,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0), onPage=footer))
    doc.multiBuild(story)


def main():
    global VERSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=VERSION)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        parser.error("--version must have the form major.minor.patch")
    VERSION = args.version
    soup, common = windows_html()
    HTML.write_text(str(soup), encoding="utf-8")
    build_pdf(soup, common)
    print(HTML)
    print(PDF)


if __name__ == "__main__":
    main()
