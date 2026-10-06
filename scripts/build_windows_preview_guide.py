"""Build matching Windows Preview HTML/PDF instructions from one source."""
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

root = Path(__file__).resolve().parents[1] / "windows"
sections = [('Start the source desktop',
  ['Double-click Start Gewu Insight.cmd in the repository. Windows Preview 0.1.21 uses '
   'dist/windows-preview-0.1.21 and the local .venv Python environment. Close the Gewu window to stop its '
   'service. Native code changes require a matching shell; Python and interface changes load after '
   'restarting.',
   'Your existing Library remains at %USERPROFILE%\\Gewu Insight Preview. Its selection is recorded in '
   '%USERPROFILE%\\.gewu-insight\\preview-workspace.txt. File > Open Data Folder shows the actual location. '
   'A missing selected database stops startup instead of silently creating an empty replacement. SQLite is '
   'authoritative.',
   'This local source delivery does not use an installer. Installed Preview 0.1.19 has been removed; its '
   'archived copy is for recovery only. Windows 11 x64 and WebView2 are the validated environment. New '
   'computers require a compatible shell, Python dependencies and WebView2.']),
 ('Library and Paper Files',
  ['The shared product now includes the macOS updates through 8a27895: canonical paper identities and '
   'old-key aliases, publication notices, resource deduplication, unified metadata tasks and 20 Paper Files '
   'types. Corrections, retractions and related notices keep their own identifiers and links to the original '
   'research paper.',
   'Library, Spaces and Shortcuts share the same managed files. Additional placements use Windows .lnk '
   'shortcuts, not duplicate PDFs. Paper Files offers Move to Another Paper and Create Paper from File. '
   'Identical bytes are reused while import sources remain recorded; different versions and annotations '
   'remain distinct. Manual Default choices are preserved.',
   'Use column headers to sort Title, Authors, Year, Journal or Time added. Settings > Add to Library '
   'chooses the default destination. File and folder moves update their references together; interrupted '
   'moves are recovered from a journal. Startup does not scan or reorganize the whole historical Library.',
   'Library Recycle and removal of private managed files use Windows Shell recovery with a verified backup. '
   'Other active Library, Space and Publications references and external originals are retained. The '
   'operating-system Recycle Bin can restore successfully deleted bytes; add a restored file again to '
   'reattach it.']),
 ('Refresh Info and research monitors',
  ['Refresh Info is shared by individual papers, folders, the whole Library and imports. Quick and Full '
   'refresh use persistent progress with Pause, Continue, Stop and history. Manual DOI/arXiv corrections '
   'record their history. Network failures remain visible and can be retried.',
   'Author Monitor shows cached papers immediately and refreshes in the background. Metadata work is limited '
   'to the author scope and rotates through unfinished papers. Temporary access failures back off and '
   'recover without treating an abnormal response as an empty publication list.',
   'Subject Monitor preserves earlier results when settings change; an explicit successful refresh replaces '
   'its window. Calendar counts use numbers only. My Publications import remains resumable, and deleting a '
   'placement protects papers still referenced elsewhere. PDF downloads remain explicit.']),
 ('Loader and file handling',
  ['File > Library Loader opens an independent window. Closing hides it and retains the source, draft and '
   'task. Refresh Info and identifier recovery use the same window. Show in Library in a log locates the '
   'paper in the main window while retaining the task result.',
   'Drag a Paper Files icon or name to File Explorer or a compatible app to copy/open the real file. Drop '
   'files into Library to import them. Paper Files accepts drops across its column; internal managed-file '
   'drops use the move/ownership workflow and duplicate gestures are ignored. Cross-application behavior '
   'depends on the receiving application.',
   'Folder renames, managed shortcuts, long filenames, copy races and interrupted transactions have '
   'Windows-specific handling. Open in Default App follows Windows file associations; Show in File Explorer '
   'reveals the file. There is no separate default-reader setting.']),
 ('Browser and PDFs',
  ['Browser keeps its own website session. Home is local Favorites; tabs and Back/Forward retain '
   'browser-owned documents where available. Ctrl+L focuses the address bar, Ctrl+F opens Find, Ctrl+T '
   'creates a tab, Ctrl+W closes it, Ctrl+R reloads and Ctrl+[ returns to the research workspace. Address '
   'suggestions use local history.',
   'Save to Gewu reviews metadata, identity, file type and destination. A loaded PDF, including an embedded '
   'PDF, can be saved from its original response bytes. Use Loaded PDF never silently requests the file '
   'again. If those bytes are no longer available, reopen the PDF or explicitly use Get PDF. Supported '
   'download-type PDFs preview in the same tab.',
   'PDF capture supports up to 128 MB. Save Download uses retained bytes for a loaded PDF; other explicit '
   'downloads use the current Browser session. The original publisher filename and main/supplement '
   'classification are retained. Science main-text validation and First Release classification are shared '
   'with macOS.',
   'Only verified publisher or authorized repository sources are accepted for paper downloads; every '
   'redirect is checked. Sign in with your own publisher or institution account in Browser. Unknown sources '
   'and unsupported routes stop. These features do not bypass subscriptions or website verification.',
   'Bookmarks supports HTML import/export and manual Sync from Chrome for one selected subtree. Existing '
   'local changes and source deletions are preserved and Chrome is not modified. Clear Monitor Cache affects '
   'the local research view, not Browser cookies or sign-ins.']),
 ('Reading and AI Access',
  ['Space opens the built-in preview; Up/Down follows Paper Files and Esc closes it. PDFs scroll '
   'continuously, Ctrl+wheel zooms, and thumbnails jump to pages. Open in Default App provides the reader '
   'associated with Windows. Markdown supports collapsed YAML/source properties, wide tables/code and '
   'offline mathematical formulas without changing the original file.',
   'Settings > AI Access is off by default. Create a named connection with explicit collection and operation '
   'permissions. The MCP adapter defines 24 tools, including folder browsing, read-only file delivery, '
   'delivery release, separately authorized uploads/imports, metadata and file/folder organization. Tools '
   'available to a connection depend on its grant.',
   'Copy the generated MCP Configuration into your local AI client. The source desktop uses its .venv and '
   'local adapter; keep the App running. The URL file follows port changes after restart. Tokens are '
   'displayed only at creation and should not be shared.',
   'get_paper_file supplies an authorized read-only client copy, never direct Library or SQLite access. Use '
   'delivery status/release to manage quotas. save_analysis appends a classified Markdown note and cannot '
   'edit earlier files or analyses. New write operations require separate permissions and writable folders. '
   'Upgrading does not expand an existing grant.',
   'External authorized changes refresh the visible Library while preserving selection and reading position '
   'where possible. Gewu does not run an AI model or upload papers merely because AI Access is enabled. '
   'Review generated notes against the original sources.']),
 ('Updates, recovery and platform scope',
  ['Before updating, close the App and retain a verified SQLite/file backup plus the matching source and '
   'shell. This upgrade preserves the existing Windows Library while adding schema 22. Do not open an '
   'upgraded Library with an older shell/source or substitute an older database.',
   'The local service and workspace renderer have bounded recovery. Browser tabs and unsent website forms '
   'are kept when their separate browser process remains alive. Repeated failures stop and show a recovery '
   'message. An operating-system crash and unsaved research-form edits cannot be guaranteed recoverable.',
   'Apple Passwords/AutoFill, Safari sync and macOS system Quick Look are outside the requested Windows '
   'scope. Real institution-authenticated publisher routes, every third-party drag target and other Windows '
   'hardware still require field validation.',
   'Help > Contact Us opens info@gewu-insight.com; Help also links the product website. Logs are under the '
   'Library logs folder. This source desktop is a local development delivery; formal installer signing and '
   'distribution remain separate.'])]

title = "Gewu Insight - Windows Preview Guide"
body = "\n".join("<h2>" + escape(heading) + "</h2>" + "".join("<p>" + escape(text) + "</p>" for text in paragraphs) for heading, paragraphs in sections)
html = f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title><style>body{{font:16px/1.6 Segoe UI,Arial,sans-serif;max-width:850px;margin:48px auto;padding:0 24px;color:#243247}}h1{{font-size:30px}}h2{{margin-top:28px;font-size:20px;color:#286095}}.status{{background:#fff1d5;padding:14px;border-left:4px solid #b87c19}}</style><h1>{title}</h1><p class="status">Windows Preview 0.1.21 - desktop from local source.</p>{body}</html>'
(root / "Windows_Preview_Guide.html").write_text(html, encoding="utf-8")
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="GuideBody", fontName="Helvetica", fontSize=10, leading=14, spaceAfter=8, textColor=colors.HexColor("#243247")))
styles["Heading2"].textColor = colors.HexColor("#286095")
styles["Heading2"].keepWithNext = True
story = [Paragraph(title, styles["Title"]), Paragraph("Windows Preview 0.1.21 - desktop from local source.", styles["GuideBody"]), Spacer(1, 8)]
for heading, paragraphs in sections:
    story.append(Paragraph(heading, styles["Heading2"]))
    story.extend(Paragraph(escape(text), styles["GuideBody"]) for text in paragraphs)
def footer(canvas, doc):
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(44, 27, "Gewu Insight | Windows Preview 0.1.21 | 2026-09-29")
    canvas.drawRightString(551, 27, str(doc.page))
doc = SimpleDocTemplate(str(root / "Windows_Preview_Guide.pdf"), pagesize=(595, 842), leftMargin=44, rightMargin=44, topMargin=38, bottomMargin=45, title=title)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(root / "Windows_Preview_Guide.pdf")
