# Gewu Insight 1.0.0

Gewu Insight is a desktop research workspace for collecting papers, organizing
their files and versions, following new literature, and keeping reading notes
with the research they describe.

## Research workspace

- Organize papers in Library folders, Shortcuts and Spaces.
- Keep manuscripts, published articles, supplementary files and notes together
  in Paper Files, with a selected Default file for reading.
- Follow journals, subjects and authors, and manage My Publications.
- Read PDFs and Markdown, browse scholarly websites, and save supported papers
  into the same collection.
- Connect compatible AI clients through MCP with explicitly scoped access to
  selected research and append-only analysis notes.

## Windows

Requires Windows 10 version 1607 or later, or Windows 11, on an Intel/AMD x64 PC.
Download `Gewu-Insight-Windows-1.0.0-x64-Setup.exe`, follow Setup, and open
**Gewu Insight** from the Start menu. Python, .NET and application dependencies
are included. Setup reuses Microsoft WebView2 or installs it from Microsoft
when needed.

Choose the program and Gewu Database folders independently. The default program
folder is `%LOCALAPPDATA%\Programs\Gewu Insight`; a new database defaults to
`%USERPROFILE%\Gewu Database`. Select **Use existing Gewu Database** to keep
using an existing collection. Uninstalling the program retains research data.
The Windows installer is unsigned.

## macOS

Requires macOS 14 or later on Apple Silicon or Intel. Download
`Gewu-Insight-macOS-1.0.0.dmg`, open the disk image, and drag **Gewu Insight.app**
to **Applications**. Open the App from Applications and choose a new or existing
Gewu Database folder. Python and application dependencies are included.
The macOS package uses an ad-hoc integrity signature and is not Developer ID
signed or notarized.

## Data and help

Research data is stored locally in the selected Gewu Database, separately from
the program. Back up that folder and any externally linked originals. Online
literature services require internet access and remain subject to publisher and
institutional access. Optional LibreOffice and TeX tools are installed separately.

Choose **Help > User Guide** for the bundled manual. The Gewu Insight Academic
and Non-Commercial Research License and included third-party notices apply.
