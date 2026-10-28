# Gewu Insight

**A research workspace that keeps papers, their versions, and research context connected—from discovery to reuse.**

Gewu Insight brings literature discovery, organization and reading into one
workspace. Papers retain a shared identity as metadata, versions, supporting
files and notes accumulate, so research context can be revisited and reused.

**Version 1.0.0 · Build 1 · Windows desktop**

[Website](https://gewu-insight.com) · [Install](#quick-start-on-windows) ·
[User Guide](windows/Windows_Preview_Guide.pdf) · [AI & MCP](docs/AI_ACCESS.md) ·
[Contributing](CONTRIBUTING.md) · [License](LICENSE)

This is the `Windows` development branch. The macOS implementation is maintained
on [main](https://github.com/LKong92/Gewu-Insight/tree/main).
The repository and release downloads are publicly available.

<p align="center"><img src="assets/gewu-insight-app-icon.png" width="96" alt="Gewu Insight app icon"></p>

## Quick start on Windows

**Requirements:** Windows 10 version 1607 (build 14393) or later, or Windows 11,
on an Intel/AMD x64 PC. Windows 10 ARM and 32-bit Windows are not supported.

1. Download `Gewu-Insight-Windows-1.0.0-x64-Setup.exe` from the
   [Windows release](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0).
   Python, .NET and application dependencies are included. Setup reuses
   Microsoft WebView2 or installs it from Microsoft when needed.
2. Run Setup and choose the program and **Gewu Database** folders independently.
   Select **Use existing Gewu Database** to retain an existing collection.
3. Open **Gewu Insight** from the Start menu. `Start Gewu Insight.cmd` in this
   repository also opens that installed shortcut; it does not run source code.
4. Import a PDF into Library, inspect **Paper Files** and **Paper Details**, and
   create a Space for your project. Open **Help → User Guide** for daily workflows.

The installer is unsigned and may show a publisher warning. Setup does not
change Windows security settings. A source ZIP is not an installer; pulling
source does not update the installed App. See [distribution](DISTRIBUTION.md)
and [development](docs/DEVELOPMENT.md) for build and verification instructions.

For macOS, use the separate [macOS installer](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.1.0).

## Windows 1.1.0 candidate

Windows 1.1.0 / Build 11001 is under validation and has not been published yet.
The download link above still points to the released 1.0.0 installer. Candidate
features below describe this source branch; they are not present in 1.0.0.

- **Help → Check for Updates** checks a separate stable Windows channel and
  verifies the downloaded installer. Checks may run automatically once a day;
  downloading and installing remain explicit actions. Existing 1.0.0 users will
  need to install the next verified Setup.exe manually once to obtain the updater.
- **Plugin → Zotero Integration** guides installation of the bundled 0.4.2
  companion. Zotero displays the same Gewu Library, Paper Files, monitors and
  settings through the existing Gewu installation and background service.
  **Save to Zotero** explicitly copies a paper into Zotero's separate library.
- **Loader → Import from Zotero** previews and copies a library or selected
  collections, retaining hierarchy and empty disk folders while following
  Gewu's Default/Associated Files rules. Zotero records and originals remain
  unchanged. These transfers are explicit copies, not continuous synchronization.

The public update channel currently advertises only the verified 1.0.0 release.
It will point to 1.1.0 only after the final installer is published and checked.

## Explore the workspace

Six tabs connect discovery, reading, organization and your own publications.
The images below are original macOS screenshots illustrating shared concepts;
they are not Windows screenshots or evidence of complete platform parity.

| Workspace | What it does | Illustration |
| --- | --- | --- |
| Library & Spaces | Organize papers and standalone files in folders and project Spaces; inspect versions and choose a Default. | [Library and Paper Files](assets/user-guide/screenshots/library-paper-files.png) · [Spaces](assets/user-guide/screenshots/space-workspace.png) |
| My Publications | Maintain publications, authorship roles and citation evidence; export research records. | [My Publications](assets/user-guide/screenshots/my-publications.png) |
| Journal Monitor | Follow selected journals and arXiv sources, browse dated results, and save relevant papers. | [Journal Monitor](assets/user-guide/screenshots/journal-monitor.png) |
| Subject Monitor | Save research topics and inspect their dated search results and fetch status. | [Subject Monitor](assets/user-guide/screenshots/subject-monitor.png) |
| Author Monitor | Follow supported scholarly profiles and review new papers with source pacing. | [Author Monitor](assets/user-guide/screenshots/author-monitor.png) |
| Browser | Browse publisher pages and PDFs using WebView2; review identity and destination with Save to Gewu. | [Browser](assets/user-guide/screenshots/browser.png) |

Windows provides native menus, file integration and PDF preview. Local PDFs
open in the registered Windows PDF application. Apple Passwords/AutoFill,
Safari source sync and macOS system Quick Look are outside Windows scope.

## One paper, connected files and evidence

A **Gewu Key** connects a paper's identifiers, metadata, files and placements.
Adding it to another folder or Space reuses its shared record. **Paper Files**
keeps published articles, preprints, supplements, annotations and other files
associated with that paper. Manual **Default** choices survive later imports.

Files remain ordinary files on disk. Move, rename and reclassify managed files
through Gewu so their records and paths stay coordinated. Additional Windows
placements use native shortcuts where needed. **Folder Loader** imports a tree;
portable folder export retains file relationships in a manifest. It does not
replace a complete database backup.

Gewu is developed and tested primarily on macOS, with a separate Windows port.
Windows testing is limited; current installed-App checks use a Parallels Windows
11 virtual machine. Windows 10 corrections have relied on external tester reports
and have not received comprehensive in-house testing.

## Work with an AI client

AI Access is optional and off by default. In **Settings → AI Access**, create a
named connection, select its collections and expiry, and grant only the required
operations. Enabling access does not call a model or start an analysis.

Authorized clients can read metadata and explicitly permitted files, append
Markdown analyses with source references, and separately request organization
or imports within granted roots. Analysis saves never overwrite existing Paper
Files or earlier analyses. Existing connections do not acquire new permissions
on upgrade. My Publications write access is not exposed.

The client may send authorized content to its model provider. API grants do
not restrict a program's independent operating-system file access. Review
analyses against their sources; see [AI Access setup](docs/AI_ACCESS.md).

## Your database and online services

**SQLite is the source of truth.** Research data belongs in the selected Gewu
Database, separate from the installed program and source checkout. Defaults are
`%LOCALAPPDATA%\Programs\Gewu Insight` for the program and
`%USERPROFILE%\Gewu Database` for a new database. Setup lets you choose both.

With the App and service stopped, back up the entire selected database folder,
additional managed roots and externally linked originals together. Backing up
the source checkout alone does not protect your collection. Uninstalling the
App retains research data. See [backup and update guidance](docs/DEVELOPMENT.md#safe-updates-and-backups).

Online discovery, citation and publisher services require network access and
remain subject to provider limits and institutional entitlements. Gewu uses
pacing and cooldowns; it does not bypass paywalls or access controls. Optional
service keys belong in **Settings → Literature Data Sources**.

## Documentation

| Document | Purpose |
| --- | --- |
| [Windows User Guide](windows/Windows_Preview_Guide.pdf) · [HTML edition](windows/Windows_Preview_Guide.html) | Installed-app workflows and Help; the compatibility filenames retain `Preview`. |
| [Distribution](DISTRIBUTION.md) | Installer requirements, release source provenance and package contents. |
| [Development](docs/DEVELOPMENT.md) | Isolated Windows setup, builds, tests, backups and local acceptance. |
| [AI Access](docs/AI_ACCESS.md) | MCP client configuration and permission boundaries. |
| [Browser capture](docs/BROWSER_CAPTURE.md) | Paper identity, files and import destinations; native details vary by platform. |
| [File layout](docs/MANAGED_FILE_LAYOUT.md) | Shared storage contracts; Windows uses native shortcuts instead of Finder aliases. |
| [Licensing](docs/LICENSING.md) · [Contributing](CONTRIBUTING.md) | Research sharing and contribution authorization. |
| [Component audit](docs/RELEASE_COMPONENT_AUDIT.md) | Current release metadata and separately identified historical package inspection. |

## Citation

If you use Gewu in research, please cite the accompanying paper:

> Kong, L. & Wu, Z. A stateful research information infrastructure for scientific
> discovery. [arXiv:2610.14538](https://arxiv.org/abs/2610.14538) (2026).

GitHub citation metadata is in [CITATION.cff](CITATION.cff).

## Name and Chinese origin

**格物洞见** draws on **格物致知**: begin with experimental phenomena and seek
insight through physical pictures and intuition. Gewu keeps the supporting
research connected; interpretation and scientific judgment remain yours.

## Copyright and license

Designed and developed by **Lingyuan Kong** and **Zhengran Wu**, with coding
assistance from **OpenAI Codex**. Copyright © 2026 Lingyuan Kong and Zhengran Wu.

Gewu is source-available research software under the custom
[Academic and Non-Commercial Research License 1.1](LICENSE), not an open-source
license. It permits academic/non-commercial research use and sharing of original
or modified versions under its terms. Commercial use requires separate prior
written authorization. Research outputs do not inherit the software license
merely because Gewu was used. Third-party materials retain their own terms;
see [third-party notices](THIRD_PARTY_NOTICES.md).

Contact: [info@gewu-insight.com](mailto:info@gewu-insight.com).
