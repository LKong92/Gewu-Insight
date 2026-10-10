# Gewu Insight 1.0.0 · Build 1

This document records the original macOS 1.0.0 baseline. For current installers,
requirements and platform status, use the
[macOS release](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.0.0)
and [Windows release](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0-r2).

This is the macOS baseline for everyday research and writing. The release name
marks a settled workflow, with a fully reviewed User Guide, rather than a new
round of feature changes or a guarantee about every external provider.

The Library and Spaces organize shared paper identities and classified Paper
Files. My Publications, Journal Monitor, Subject Monitor, Author Monitor and
Browser connect discovery to the same collection. Refresh Info provides single,
folder, full-Library and import workflows with shared limits. AI Access grants
scoped reads and append-only Markdown analyses through MCP.

The revised Guide explains the configurable Add to Library destination,
Browser's reuse of existing locations, manual DOI/arXiv correction, Default file
placement, fuzzy text search, Markdown Quick Look, and deletion across shared
locations. Metadata refresh now has one workflow chapter, including cooldowns,
partial results and Pause/Continue. The first-session chapter includes a practical
research-to-writing route. Each installer contains the manual from its build;
later changes on `main` do not update an already downloaded App or PDF.
Save to Gewu also adopts the existing flat settings style, with a
smaller title and compact controls; its review and saving behavior is unchanged.

Version and Build are independent of the icon cache checksum. Future small fixes
can use 1.0.1, 1.0.2 and so on; a rebuilt package of the same version increments
Build. No additional version or Git tag is created automatically by this policy.

## Boundaries

- This edition documents the macOS 14+ universal native launcher. Windows has
  a separate native implementation, installer and User Guide; consult its
  current release above for platform requirements.
- Provider access, institutional sign-in and rate limits still apply. A refreshed
  record may be partially complete; the detailed source results remain visible.
- Search supports text/identifier matching, typo tolerance and word variants.
  It does not promise translation, synonym expansion or model-based semantic search.
- This documentation and version change does not rewrite the user's papers,
  identifiers, classification, Default selection, preferences or AI grants.
- Before upgrading, stop the App and its service and back up the complete selected
  Gewu Database, additional managed roots and externally linked originals.
  Copying the program or SQLite alone is insufficient. Browser sessions and
  OS-managed credentials have separate lifecycles documented in the Guide.

See the [User Guide PDF](../paper_monitor/Gewu_Insight_User_Guide.pdf) and
[distribution instructions](../DISTRIBUTION.md). Exact bundled components and
pending notice corrections are recorded in the
[installer inventory](RELEASE_COMPONENT_AUDIT.md).
