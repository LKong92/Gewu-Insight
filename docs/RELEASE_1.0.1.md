# Gewu Insight 1.0.1 · Build 1 · macOS

This patch release fixes Library placement, article links and Paper Files
deletion. It requires macOS 14 or later and includes Apple silicon and Intel
runtimes. Windows remains on its separate 1.0.0 release.

## Changes

- Paper copying, moving and folder moves can recover from empty directories
  left behind in Associated Files. Directories containing files remain protected
  from replacement.
- Open Website uses an article or DOI link instead of recognized metadata API
  URLs. AI-supplied API URLs remain recorded as source evidence.
- Right-click Open Website and choose **Edit Website Link…** to save a manual
  HTTP(S) link. **Use Automatic Link** restores automatic selection. Refresh Info
  retains the saved link and still uses DOI/arXiv to retrieve metadata.
- Refresh Info can repair a title mistakenly imported from an arXiv page header
  when the DOI and author evidence agree. Genuine identity conflicts still
  require review.
- Paper Files permits deleting the Default or only file. The paper's metadata,
  Gewu Key and folder placements remain. A private managed copy goes to macOS
  Trash; shared files and externally linked originals are preserved.

## Installation and scope

Download **Gewu-Insight-macOS-1.0.1.dmg** from the release assets. Quit Gewu Insight,
back up the complete selected Gewu Database and any separately stored managed or
linked files, then drag the App to Applications to replace the old program.
The update reuses the existing database and does not require another import.

The User Guide is intentionally unchanged from the 1.0.0 edition. Its statement
that the current Default cannot be deleted is superseded by this release, and
the website editor is described above. No new guide screenshots or PDF were
generated. The package includes current notices and contribution documents.

The App has a local ad-hoc integrity signature, without Developer ID signing or
Apple notarization. Follow the release Read Me and macOS per-app opening flow;
do not disable Gatekeeper. Optional LibreOffice and TeX tools remain separate.

Scoped regressions cover placement recovery, file preservation and rollback,
metadata identity checks, website override persistence and deletion controls.
Native drag probes and a browser workflow exercised paper/folder drag, link
editing and sole-file deletion. See the accompanying validation JSON for checks
of the actual DMG. The full repository suite and Windows runtime were not tested;
this release does not update the Windows installer.

The release includes the DMG, SHA-256 checksum, exact source/runtime build
manifest, first-launch Read Me and package validation record. Existing release
tags and assets are retained.
