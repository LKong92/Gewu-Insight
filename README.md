# Gewu Insight

**A research workspace that keeps papers, their versions, and research context
connected—from discovery to reuse.**

Gewu Insight brings continuous literature discovery, organization, and reading
into one workspace. It organizes scientific works as persistent, stateful
research objects: each paper retains a shared identity as metadata, publication
versions, supporting files, project associations, and analyses accumulate.
Researchers and authorized AI clients can return to the same record, inspect
earlier materials, and continue their work. This provides an inspectable
scientific memory layer, with questions and scientific judgment directed by
the researcher.

**Keep research objects visible, evidence traceable, and insight cumulative.**

[Website](https://gewu-insight.com) · [Quick start](#quick-start) ·
[Explore the workspace](#explore-the-workspace) ·
[User Guide](paper_monitor/Gewu_Insight_User_Guide.pdf) ·
[AI & MCP](#work-with-an-ai-client) · [Citation](#citation) ·
[License](#copyright-and-license)

**Version 1.0.0** · macOS and Windows · Source-available research software

Academic/non-commercial research use is permitted under the custom
[LICENSE](LICENSE). Commercial use requires separate prior written authorization.

<p align="center">
  <img src="assets/gewu-insight-app-icon.png" width="96" alt="Gewu Insight app icon">
</p>

<p align="center">
  <a href="assets/user-guide/screenshots/library-paper-files.png"><img src="assets/user-guide/screenshots/library-paper-files.png" width="920" alt="Library folders, a selected paper's Published version and Preprint in Paper Files, and Paper Details"></a>
</p>

<p align="center"><em>One paper, connected files: inspect its versions, choose a Default, and read its metadata alongside your Library.</em></p>

## Why Gewu Insight

- **Follow the literature.** Track journals, research topics, and authors through
  three complementary monitors. Save relevant papers into your own collections.
- **Organize around your research.** Use Library folders and project Spaces;
  the same paper can appear in several contexts with one shared identity.
- **Keep the evidence together.** Read PDFs and Markdown notes, compare versions,
  and retain supplements, annotations, data, and code in Paper Files.
- **Continue with context.** Revisit saved reading material, maintain your own
  publication record, and optionally let an authorized AI client read papers
  and append analyses with source references.

## Quick start

Download the installer for your platform from the release page's **Assets**.
Both packages include Python and application dependencies. GitHub's **Source
code ZIP** is for source-based setup, not an App installer.

| Platform | Requirements | Download |
| --- | --- | --- |
| macOS | macOS 14 or later; Apple silicon or Intel | [macOS 1.0.0 DMG](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.0.0) |
| Windows | Windows 10 version 1607+ (build 14393+) or Windows 11; Intel/AMD x64 | [Windows 1.0.0 Revision 2 Setup](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0-r2) |

### macOS

1. Download **Gewu-Insight-macOS-1.0.0.dmg** and open it.
2. Drag **Gewu Insight.app** to **Applications**, eject the disk image, and open
   the installed App.
3. Choose **Create New Database** or **Open Existing Database**. Keep your
   **Gewu Database** in a separate folder outside the App. The App menu's
   **Database Location…** shows the active folder.

### Windows

1. Download **Gewu-Insight-Windows-1.0.0-x64-Setup.exe** and run Setup.
2. Choose the program and **Gewu Database** folders. To retain an existing
   collection, select **Use existing Gewu Database** and its root folder.
3. Open **Gewu Insight** from the Start menu. Python and .NET are bundled;
   Setup needs internet access if Microsoft WebView2 must be installed.

Read the release's checksum and first-launch notes. The macOS package uses
ad-hoc integrity signing and is not Apple-notarized; the Windows installer is
unsigned. Optional LibreOffice and TeX tools are installed separately.

**Try one paper:** drag a PDF into a Library folder, or visit an article in
**Browser** and choose **Save to Gewu**. Inspect **Paper Files** and **Paper
Details**, then create a Space for a project. Open **Help → User Guide** for
the manual bundled with your platform. The [website](https://gewu-insight.com)
also provides both platform guides.

**Updating an existing installation:** close the App and back up the selected
Gewu Database and its files first. Replacing the App preserves the separate
database location. Older source-folder installations should follow the
[migration instructions](docs/SOURCE_DATA_MIGRATION.md) before updating.
For source-based setup, use [Manual setup](docs/DEVELOPMENT.md#manual-setup).

If startup fails, follow your platform's release notes and User Guide. Installed
macOS App logs are in `~/Library/Logs/Gewu Insight`; do not delete the database
to repair startup.

## Explore the workspace

Six main tabs connect discovery, reading, organization, and your own publications.
The Library tab provides access to Library, independent Spaces, and shortcuts.
Spaces are project roots at the same organizational level as Library. These
screenshots show the real macOS App; select an image to inspect it at full size.

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="assets/user-guide/screenshots/space-workspace.png"><img src="assets/user-guide/screenshots/space-workspace.png" alt="A project Space in the Library workspace"></a>
      <br><strong>Library &amp; Spaces</strong><br>
      Organize papers and standalone files in folders and project Spaces.
      Browse List or Table View, search a collection, and sort by Time added.
      Shortcuts provide another route to existing folders.
    </td>
    <td width="50%" valign="top">
      <a href="assets/user-guide/screenshots/my-publications.png"><img src="assets/user-guide/screenshots/my-publications.png" alt="My Publications with authorship roles and citation metrics"></a>
      <br><strong>My Publications</strong><br>
      Maintain your publication list, authorship roles, ordering, and citation
      evidence. Export to Word, LaTeX, PDF, or an Overleaf project. Manual roles
      and ordering survive metric refreshes.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="assets/user-guide/screenshots/journal-monitor.png"><img src="assets/user-guide/screenshots/journal-monitor.png" alt="Journal Monitor displaying Nature papers, a calendar, and article figures"></a>
      <br><strong>Journal Monitor</strong><br>
      Follow selected journals and arXiv updates. Browse by date, venue, and
      field, inspect figures and abstracts, and save papers with their source
      information. Your subscription choices persist across updates.
    </td>
    <td width="50%" valign="top">
      <a href="assets/user-guide/screenshots/subject-monitor.png"><img src="assets/user-guide/screenshots/subject-monitor.png" alt="Subject Monitor with a saved research topic and dated results"></a>
      <br><strong>Subject Monitor</strong><br>
      Build reusable topics from search terms and review their dated results.
      Selecting a calendar date opens saved results; refreshing a topic is a
      separate action, with its status visible.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="assets/user-guide/screenshots/author-monitor.png"><img src="assets/user-guide/screenshots/author-monitor.png" alt="Author Monitor displaying Hong Ding's profile and publications"></a>
      <br><strong>Author Monitor</strong><br>
      Follow selected researchers through supported scholarly profiles, browse
      their publications, and identify new unread papers. Refreshes respect
      source limits and show cooldowns when a service restricts access.
    </td>
    <td width="50%" valign="top">
      <a href="assets/user-guide/screenshots/browser.png"><img src="assets/user-guide/screenshots/browser.png" alt="The built-in Browser displaying a publisher PDF with Save to Gewu"></a>
      <br><strong>Browser</strong><br>
      Read publisher pages and PDFs in the built-in WebKit browser, with tabs,
      bookmarks, and local history. Save to Gewu lets you review the paper's
      identity, destination, and file type before importing it.
    </td>
  </tr>
</table>

For an existing collection, **Folder Loader** imports a directory tree. Portable
folder export includes files and a manifest for importing their relationships
into another Gewu workspace; see the [User Guide](paper_monitor/Gewu_Insight_User_Guide.pdf).

Browser tab controls, bookmark import and sync, downloads, and system Passwords
behavior are covered in the [User Guide](paper_monitor/Gewu_Insight_User_Guide.pdf)
and [Browser documentation](#documentation). Website links from the other
workspaces open in Browser; on macOS, local PDFs open in Preview.

## One paper, connected files and evidence

A paper's **Gewu Key** connects its identifiers, metadata, files, and placements
across the workspace. Adding that paper to another folder or Space reuses the
shared record. A paper can begin as a metadata-only record and acquire files
later under the same Key. An ordinary standalone non-PDF file can also be stored
in the Library, without being assigned a public Gewu Key.

**Paper Files** keeps the Published version, accepted manuscript, preprints,
supplements, annotated copies, and other attachments associated with that paper.
You can inspect classifications and choose which file is **Default**. An explicit
Default is retained when other versions arrive; supplements do not automatically
replace the main article simply because they are PDFs.

Supported corrections, retractions, and other publication notices stay linked
to the original article, with their own notice metadata and any saved files.
They do not create a separate research-paper identity or become the automatic
Default. A corrected full article is a separate publication version. **Refresh
Info** checks explicit Crossref update relations for papers with a DOI; it does
not automatically download notice PDFs. Coverage depends on the supplied
relations, and saved papers are not periodically checked merely because they
are in the Library. See [publication updates](paper_monitor/user_guide.html#paper-publication-updates).

Use in-app **Quick Look** to preview PDFs and Markdown notes, or open a local PDF
in **Preview** on macOS. Managed documents remain real files: the Default occupies the
main managed location, and other Paper Files belong in **Associated Files**.
On macOS, additional placements can use Finder aliases to the same originals. Move,
rename, and reassign managed files through the App so records and disk paths
stay coordinated. See [managed file layout](docs/MANAGED_FILE_LAYOUT.md).

## Work with an AI client

AI Access is **optional and off by default**. Gewu provides a local API and an
MCP adapter so an AI client can work with explicitly authorized collections.
Enabling access does not itself call a model, upload a library, or start an
analysis job.

Use the generated connection configuration with a client that supports local
stdio MCP. **Codex** and **DeepSeek Harness** are working examples documented in
the setup guide; other compatible clients, including **Claude Code**, can use
the same connection method and permission model. Model inference runs through
the external client.

A typical workflow is: select a paper → read its authorized source files and
earlier analyses → save a new Markdown analysis → review it in Paper Files.
A later authorized session can retrieve the same record and continue from
the retained sources and notes. Saving is an explicit client action; there is
no automatic synchronization of AI conversations.

Analyses may link to a source file. When a link is supplied, both its file ID
and SHA-256 hash are required; page references are optional. A new file-linked
save checks the source bytes and rejects a changed file until the client reads
it again. Notes without a source-file link do not receive this check. These
records support source inspection; researchers assess the interpretation.

In **Setting** (macOS) or **Settings** (Windows) **→ AI Access**, create a named
connection, choose its collection and expiry, and grant the operations it needs:

- **Read:** metadata, directory browsing, and file contents have defined access
  boundaries; file reading and directory browsing are separately enabled.
- **Save analyses:** append Markdown notes with source references without
  overwriting existing Paper Files or earlier analyses.
- **Organize and import:** separately allow Space/folder creation, prepared
  paper or standalone-file imports, Paper Files attachment, moves, or renames
  within selected Library and Space roots. My Publications write access is
  not exposed.

Paper imports require metadata supplied by the AI client and reuse matching
DOI/arXiv identities. **A PDF is optional:** import the prepared metadata first,
then attach a file under the same Gewu Key when it becomes available. Imports
do **not** automatically download a PDF or run Resolve; resolving an existing
paper is a separate permission and call. Connections can expire or be revoked,
and existing connections do not gain new write permissions on upgrade.

Your AI client may send authorized content to its chosen model provider. These
grants govern API/MCP access; they do not restrict a program's independent
operating-system access to local files. Review generated analyses against their
sources. See [AI Access setup, tools, and permissions](docs/AI_ACCESS.md).

## Local data and online services

**SQLite is the source of truth** for paper identities, relationships, file
records, and workspace state. PDFs and attachments remain on disk; reports and
exports do not replace the database.

The installed App and your **Gewu Database** are stored separately. With the App
and its service stopped, back up the **complete selected database folder**,
any additional managed file roots, and externally linked originals. Copying the
App or source checkout alone does not back up your research. A pre-upgrade
SQLite snapshot or a portable folder export does not replace this full backup.
See [backup and recovery](paper_monitor/user_guide.html#backup-migrate) and the
platform's bundled User Guide.

The workspace uses a local-first architecture, with online services supporting
discovery, metadata, citation counts, and publisher access. Availability can depend on a
service's limits, the network or VPN exit address, and institutional access.
Gewu uses pacing and cooldowns; it does not bypass paywalls or access controls.
Configure optional service keys in **Setting → Literature Data Source**.

## Platform support

- **macOS** — a standalone desktop release with Finder, Preview, Quick Look,
  Dock, and native drag-and-drop integration. The manuscript's reported
  evaluation was performed on macOS.
- **Windows** — a separately packaged desktop release for Windows 10/11 x64,
  with its own installer and User Guide. See the
  [Windows release notes](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0-r2)
  for requirements and platform details.

The Python, SQLite, and web-interface core is separated from native desktop
integration. Screenshots in this README show macOS; use your platform's release
notes and User Guide for installation and native behavior.

## Documentation

| Start here | What it covers |
| --- | --- |
| [macOS User Guide](paper_monitor/Gewu_Insight_User_Guide.pdf) · [Both platform guides](https://gewu-insight.com/#resources) | Daily workflows, settings, shortcuts, backup, and troubleshooting; each App includes its own guide under Help → User Guide. |
| [AI Access & MCP](docs/AI_ACCESS.md) | Client setup, collection grants, reading, analysis saves, imports, moves, and renames. |
| [Browser: Save to Gewu](docs/BROWSER_CAPTURE.md) | Reviewing article identity, PDF candidates, file types, and import destinations. |
| [Browser: keyboard & bookmarks](docs/BROWSER_KEYBOARD_AND_BOOKMARK_SYNC.md) | Navigation, bookmark import/export, and explicit one-way sync. |
| [Browser: PDFs](docs/BROWSER_PDF_PREVIEW.md) · [Passwords](docs/BROWSER_PASSWORD_AUTOFILL.md) | PDF viewing and the boundaries of system password integration. |
| [Managed file layout](docs/MANAGED_FILE_LAYOUT.md) | Default files, Associated Files, aliases, and recovery boundaries. |
| [macOS release & installation](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.0.0) · [Windows release & installation](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0-r2) | Current installers, requirements, checksums, and first-launch notes. |
| [Older source-installation migration](docs/SOURCE_DATA_MIGRATION.md) | Back up and separate research data from a legacy source checkout before updating. |
| [Development guide](docs/DEVELOPMENT.md) | Manual setup, architecture, CLI commands, builds, updates, and verification. |
| [Licensing explained](docs/LICENSING.md) · [Contributing](CONTRIBUTING.md) | Research use and sharing, reserved commercial rights, and contribution terms. |

The [HTML manual](paper_monitor/user_guide.html) is the source for the bundled
PDF. [Guide coverage and screenshot provenance](docs/USER_GUIDE_AUDIT.md) are
recorded separately from the product overview.

## Citation

If you use Gewu Insight in your research, please cite the accompanying paper.
The manuscript is being prepared for arXiv; its identifier and link will be added
here after it is posted. Until then, the provisional reference is:

> Kong, L. & Wu, Z. A stateful research information infrastructure for scientific
> discovery. Manuscript in preparation (2026).

Citation metadata is also available in [CITATION.cff](CITATION.cff) for GitHub's
**Cite this repository** feature.

The manuscript's evaluation uses the fixed software snapshot
[commit `539d00d`](https://github.com/LKong92/Gewu-Insight/tree/539d00dd1a3b0f5857912223868ca232d56680c9).
Use that snapshot when reproducing the reported results.

<!-- After arXiv posting, update this reference and CITATION.cff together with
     the confirmed author list, title, year, arXiv identifier and canonical URL. -->

## Name and Chinese origin

Gewu Insight is known in Chinese as **格物洞见**. The name draws on **格物致知**
and expresses a research outlook shaped by the practice of physics.

- **格物 · Gewu** — begin with concrete phenomena, experimental observations,
  and questions from nature; keep research in contact with the world it seeks
  to understand.
- **洞见 · Insight** — seek the patterns and mechanisms behind phenomena
  through physical pictures, intuition, imagination, and insightful guesses.
  Mathematics serves as a tool for developing and expressing that understanding.

The workspace supports this practice by keeping papers, versions, supporting
files, and notes connected, so researchers can revisit experimental results,
compare physical pictures, and pursue emerging ideas. Questions, interpretation,
and scientific judgment remain with the researcher. Read more in the
[User Guide's explanation of the name](paper_monitor/user_guide.html#visual-identity).

**Investigate nature through experimental phenomena; seek insight through
physical pictures and intuition.**

（从实验现象中格物，以物理图像和直觉求洞见。）

## Copyright and license

Designed and developed by **Lingyuan Kong** and **Zhengran Wu**.<br>
Developed with coding assistance from **OpenAI Codex**.

Copyright © 2026 Lingyuan Kong and Zhengran Wu. All rights reserved.

Gewu Insight is **source-available research software** under the custom
**Gewu Insight Academic and Non-Commercial Research License**, not an
open-source license. The [LICENSE](LICENSE) permits academic/non-commercial
research use, including downloading, installing, running, studying, and modifying
it. Original and modified versions, derivatives, and patches may be shared free
of charge for permitted research under the same terms, retaining notices and
identifying modifications. This includes public research forks and pull requests.

Commercial use, commercial redistribution, sublicensing, and integration into
commercial products or services require **separate prior written authorization**.
Contact [info@gewu-insight.com](mailto:info@gewu-insight.com).
Independent research outputs do not inherit the software license merely by using
Gewu. A pull request does not transfer its author's copyright or grant additional
commercial rights; see the [contribution policy](CONTRIBUTING.md).

Third-party components, scholarly content, and services retain their own terms.
See [third-party notices](THIRD_PARTY_NOTICES.md) and the
[dependency and asset audit](docs/DEPENDENCY_LICENSE_AUDIT.md), including
outstanding font and artwork permissions.
