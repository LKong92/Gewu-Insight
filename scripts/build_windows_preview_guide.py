"""Build matching Windows Preview HTML/PDF instructions from one source."""
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

root = Path(__file__).resolve().parents[1] / "windows"
sections = [
    ("Development status", [
        "This is a Windows Preview for a NEW test Library. It is not the completed macOS-equivalent release. Existing macOS Library databases must not be moved into this build.",
        "The shared Python service, SQLite model and research interface are reused. Native Windows integrations are still being connected and accepted separately. A visible control or a successful service test does not establish full workflow parity."]),
    ("Install and start", [
        "Run the Windows Preview x64 Setup executable. Installation is per user and does not request administrator rights. The app includes Python and .NET; no developer environment is required.",
        "Windows 11 x64 is the current test machine. The package targets Windows 10 version 2004 or later on x64, but Windows 10 and ARM64 have not passed real-device acceptance. Microsoft Edge WebView2 Evergreen Runtime must already be installed.",
        "Open Gewu Insight Preview from the Start menu. The first start creates a new Library. The local server listens only on 127.0.0.1. Research discovery, publisher downloads and API providers may require Internet access and provider settings."]),
    ("Files and Library locations", [
        "File > Open Data Folder shows the actual Library location. New Libraries use %USERPROFILE%\\Gewu Insight Preview. Existing Libraries use the verified physical folder recorded in %USERPROFILE%\\.gewu-insight\\preview-workspace.txt. If that selected database is missing, startup stops instead of creating an empty replacement. SQLite is authoritative.",
        "Windows file opening uses the associated default application. Open in File Explorer or Show in File Explorer opens the file location. Additional Library/Space placements use managed .lnk shortcuts to the same real file; they are not independent PDF copies. Open the shortcuts to work with the same annotations.",
        "Paper Files can remove a non-default attachment to the Windows Recycle Bin. A verified temporary backup and a private SQLite recovery journal protect database failures and interrupted deletion; startup completes pending recovery without overwriting a changed file. Shared files and external originals are retained. Restore a successfully deleted file from Windows Recycle Bin, then add it to Paper Files again to restore its association. Bulk permanent removal from Library Recycle remains blocked. Cross-drive moves still need acceptance."]),
    ("Browser and native controls", [
        "Browser uses separate WebView2 views and a profile separate from the trusted Library interface. Home is local Favorites. Remote pages do not receive the workspace message bridge.",
        "File, Edit, View, Loader, Settings and Help expose the shared workflows. Settings includes Naming Rule, PDF Rename Settings, Preview Settings, Website Links, AI Access, arXiv Scope Settings, Open Source Settings, Field Settings and Font Size. Preview Settings shows Windows-supported choices only. Click the workspace or press Esc to dismiss an open menu. Clear Monitor Cache remains disabled.",
        "Space opens the built-in preview; Up/Down follows the selected Paper File and Esc closes it. Scroll continuously through PDF pages with a mouse wheel or two fingers on the touchpad. Pinch or Ctrl+wheel zooms the PDF; horizontal scrolling pans the enlarged page. Page Up/Page Down scroll, Home/End reach the first/last page, and thumbnails jump to a page. The additional Windows page/zoom/Text toolbar has been removed. Pages render on demand with bounded caching. Use Open in Default App for text selection, full PDF search, links, printing and annotations. This uses Windows file associations; Gewu has no separate default-reader setting.",
        "Get PDF is inside Browser > Save to Gewu > Details, beside PDF link. It retrieves a discovered PDF with the current Browser profile and website session. The source page stays open. Only a readable PDF up to 64 MB is staged; Save to Library adds it after identity, file type and destination review. Show in Library locates the result. Sign-in means your authorized publisher or institution account; it never bypasses a subscription. Downloads accept reviewed publisher/repository hosts and check redirects; unverified sources are stopped, not assumed pirated. Authorized preprints are allowed. No piracy services are used. If an authorized download fails, retry on the website or choose an authorized local PDF. Explicit Save Download, sharing and source synchronization remain disabled.",
        "Browser History supports choosing a time range and confirming Clear History. Bookmarks, files and website sign-ins are kept. Import accepts a bookmarks HTML file exported from your browser. Sync from Safari and Open Passwords are hidden on Windows. Ordinary webpage-initiated downloads use the Windows Save dialog; publisher and session behavior still need broader verification.",
        "Loader > Import Folder opens a Windows folder picker. For an offline import select Skip metadata. Destination Folder shows where files will be copied within the current Library workspace. Drag a Paper Files icon or filename to File Explorer or a compatible application to copy/open the real file; the app never offers moving or deleting the owned source. File Explorer file drops into Library reuse the existing import workflow. Library folder drag-out is not connected. Different target applications and cross-window drops still require broader acceptance.",
        "Images, text and Markdown retain their existing built-in preview. The original file is not rewritten. PDF text extraction, large scanned PDFs, complex publishers and rapid repeated use still need broader real-document acceptance. macOS Passwords, Keychain AutoFill and WebKit sign-in profiles are not migrated."]),
    ("Research updates in Preview 0.1.11", [
        "Subject Monitor keeps saved results and calendar counts when keywords change. New keywords apply to future retrieval. An explicit successful Refresh replaces only its selected window; failed retrieval keeps earlier results. Calendar counts now show numbers without incomplete-discovery asterisks. Discovery, Updates and Errors still explain source progress.",
        "In My Publications, search for an author and use Add All Publications inside the search/add panel. Import follows source pages and saves progress in SQLite. Pause, Continue and Retry recover interrupted work; DOI/arXiv identifier checks have their own progress. Details reopens progress from the bottom bar. Import history is separate from a new author search. PDF downloads remain explicit.",
        "Deleting a My Publications entry keeps its paper and files when Library, Space, Shortcut or Recycle still references them. Removing its last placement removes the canonical record and recycles private managed files with recovery protection. Shared bytes and external originals are retained. Ordinary import continuation does not recreate deleted entries; an explicit recheck can add them again.",
        "Choosing a Default PDF or changing file type keeps the selected PDF in its managed main location. Older versions remain in Associated Files. Browser Save can establish the first article PDF as Default even when its version is Unknown. Manual choices remain sticky. Drop exactly one PDF on the Download PDF/Download button in Library or My Publications to attach or replace it. A missed My Publications drop does not import into an unrelated Library folder."]),
    ("AI Access and MCP", [
        "Open Settings > AI Access. Access is off by default. Enable it and create a named connection for saved papers, a folder and descendants, or specific Gewu Keys. Metadata access is standard; reading file contents and adding Markdown analyses are separate permissions. Choose an expiry. Revoke ends a connection; disabling AI Access pauses all connections.",
        "Copy MCP Configuration into your AI client's local STDIO server settings. Use the generated command, the single script argument, and each environment name/value exactly as provided. Installed Windows builds use their bundled Python and adapter, so no Python installation is needed. Paths may contain spaces and remain single fields. Keep the connection token out of chats and shared files; it is shown only when created.",
        "The Windows configuration includes GEWU_API_URL_FILE, which follows the app's current loopback port after restart. Keep Gewu running on the same PC. If the installation or Library location changes, generate a new configuration. MCP and the local HTTP API use the same collection and operation permissions. Neither enabling access nor opening this panel automatically uploads papers or runs a model.",
        "Identify the paper by Gewu Key, read its permitted PDF pages or text, then explicitly ask the AI client to save a Chinese Markdown analysis to Paper Files. Include source file, SHA-256 and page references. Saved notes append without replacing the PDF, Default or existing notes. A repeated identical request reuses its saved result. Later AI sessions can explicitly retrieve the same paper and note. Gewu does not automatically synchronize conversation memory.",
        "Interface grants control API/MCP access. They are separate from operating-system file permissions held by other software. Revoke a connection in AI Access when it is no longer needed. Review generated analyses against the original paper."]),
    ("Updates, uninstall and recovery", [
        "Close the application before installing an update. The installer updates application files only. Uninstall removes the app and preserves its separate Library, database, reports and browser profiles. Existing personal research data is never included in the installer.",
        "Until backup/restore and old-Library migration pass acceptance, use disposable research files only. The retained data folder is not itself a validated backup. Do not replace a database with an older file or bulk-edit stored paths.",
        "This development installer is unsigned. If Windows policy blocks it, do not disable Windows protection; the package requires an approved distribution/signing route. Startup errors are shown in the app; service diagnostics are under the workspace logs folder."]),
    ("Windows guide", [
        "Help opens these Windows instructions in HTML or PDF. They describe the current Preview and contain no substituted macOS screenshots. Full feature parity is still being implemented and verified."]),
]
title = "Gewu Insight - Windows Preview Guide"
body = "\n".join("<h2>" + escape(heading) + "</h2>" + "".join("<p>" + escape(text) + "</p>" for text in paragraphs) for heading, paragraphs in sections)
html = f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title><style>body{{font:16px/1.6 Segoe UI,Arial,sans-serif;max-width:850px;margin:48px auto;padding:0 24px;color:#243247}}h1{{font-size:30px}}h2{{margin-top:28px;font-size:20px;color:#286095}}.status{{background:#fff1d5;padding:14px;border-left:4px solid #b87c19}}</style><h1>{title}</h1><p class="status">Experimental / Preview - functional parity is not yet accepted.</p>{body}</html>'
(root / "Windows_Preview_Guide.html").write_text(html, encoding="utf-8")
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="GuideBody", fontName="Helvetica", fontSize=10, leading=14, spaceAfter=8, textColor=colors.HexColor("#243247")))
styles["Heading2"].textColor = colors.HexColor("#286095")
styles["Heading2"].keepWithNext = True
story = [Paragraph(title, styles["Title"]), Paragraph("Experimental / Preview - functional parity is not yet accepted.", styles["GuideBody"]), Spacer(1, 8)]
for heading, paragraphs in sections:
    story.append(Paragraph(heading, styles["Heading2"]))
    story.extend(Paragraph(escape(text), styles["GuideBody"]) for text in paragraphs)
def footer(canvas, doc):
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(44, 27, "Gewu Insight | Windows Preview 0.1.11 | 2026-09-10")
    canvas.drawRightString(551, 27, str(doc.page))
doc = SimpleDocTemplate(str(root / "Windows_Preview_Guide.pdf"), pagesize=(595, 842), leftMargin=44, rightMargin=44, topMargin=38, bottomMargin=45, title=title)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(root / "Windows_Preview_Guide.pdf")
