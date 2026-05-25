---
name: deep-literature-workflow
description: Run a staged AI literature review workflow from a user-provided research topic into an Obsidian-compatible vault. Use when the user asks to start a new literature review topic, continue the next stage, import manually downloaded PDFs, regenerate deep paper notes, build concept notes, or write a review note.
---

# Deep Literature Workflow

This skill turns a research topic into a staged literature-review project managed by Codex.
It is intentionally Codex-native: the user should be able to invoke short commands or starter prompts instead of copying long prompts.

## Codex-Native UX

This plugin does not provide a Chrome-style custom panel or form UI.
Treat the plugin card's starter prompts as the UI surface.

Preferred interaction:

1. User chooses `新建文献调研，先问我研究课题`.
2. Ask one concise question for the research topic.
3. Initialize state with `dlw.py init --topic "<topic>"`.
4. Continue with `继续` or stage-specific commands.

If the user says only `继续`, inspect the state and continue the next incomplete stage. The completion rule for Stage 4 means "continue the full pending queue across the run", but **the work must still be done strictly one paper at a time**: read one PDF, rebuild that one paper note, record that one paper's progress, then move to the next. Never turn Stage 4 into a bulk extraction, batch text-mining, or "make evidence drafts for all papers first" workflow.
If the user says only `新建`, `新课题`, or `新建文献调研` without a topic, ask for the topic instead of assuming one.

## Multi-Topic Project State

This plugin supports multiple literature topics in one workspace.

Do not use the workspace-root `PROJECT_STATE.md` as a full single-topic handoff. It should be a compact multi-topic index only.

Each new topic vault owns its own handoff:

```text
<VaultRoot>/08_Project_Workflow/PROJECT_STATE.md
```

Workflow rules:

- Before broad exploration, read the workspace-root `PROJECT_STATE.md` only to identify the active topic and topic handoff path.
- Then read the topic-specific handoff path listed in the workspace index for the actual handoff. New topics should use `08_Project_Workflow/PROJECT_STATE.md`; older topics may retain legacy paths.
- When initializing or changing stage status, use `dlw.py init`, `dlw.py mark`, or `dlw.py index`; these commands refresh the workspace index and create/update managed topic handoffs.
- If a topic handoff already exists and is not marked as plugin-managed, preserve it and do not overwrite it casually.
- Never replace another topic's handoff when working on the active topic.

## Core Commands

Recognize these user intents:

- `新建`, `新课题`, `新建文献调研`, `新课题：<topic>`, or `start topic <topic>`: initialize a workflow state for the topic.
- `继续` or `继续下一阶段`: inspect state and continue the next incomplete stage.
- `继续 Stage 1`: discover 200-500 candidate papers.
- `继续 Stage 2`: screen and audit core candidates.
- `继续 Stage 3`: download, import, validate, and rename PDFs.
- `继续 Stage 4`: rebuild all pending PDF-backed paper notes in the Stage 4 queue.
- `继续 Stage 5A`: create concept knowledge notes.
- `继续 Stage 5B`: create the review note.
- `继续 Stage 5C`: create focused evidence matrices and quantitative anchor tables.
- `导入手动下载的 PDF`: identify user-provided PDFs, rename them, validate them, and import them.
- `检查 vault 完整性`: audit file layout, broken links, PDF inventory, note depth, and stage status.

## State File

Use `plugins/deep-literature-workflow/scripts/dlw.py` to maintain state when useful.

Default state path:

```bash
python3 plugins/deep-literature-workflow/scripts/dlw.py status
```

Initialize a topic:

```bash
python3 plugins/deep-literature-workflow/scripts/dlw.py init --topic "<research topic>"
```

Refresh only the multi-topic index and topic handoff paths:

```bash
python3 plugins/deep-literature-workflow/scripts/dlw.py index
```

Clear the manual PDF queue after all manual downloads are successfully imported:

```bash
python3 plugins/deep-literature-workflow/scripts/dlw.py manual-pdf-clear \
  --note "Stage 3 complete: all queued PDFs imported, validated, and Downloads sources cleaned."
```

If the user gives a topic in chat, pass it directly to `--topic`.
If no topic is given, ask for the topic in plain language before running `init`.

## Stage Semantics

### Stage 1: Discovery

Goal: pull a broad first candidate set from legal metadata sources such as OpenAlex and Semantic Scholar.

Outputs should include:

- candidate table, ideally 200-500 papers
- search log
- scoring fields for relevance, citation influence, recency, method centrality, and review utility
- deduplicated core candidate table, ideally 40-80 papers

### Stage 2: Audit

Goal: manually or semi-automatically audit the core candidates.

Outputs should include:

- keep/background/exclude decisions
- exclusion reasons for broad or generic papers
- 15-25 paper queue for deep reading
- numbered starter paper notes in `05_Papers/` and expected/imported PDF filenames in `06_PDFs/`, using the same `01_...`, `02_...`, etc. recommended deep-reading queue order

### Stage 3: PDF Acquisition And Import

Always use the `chrome-literature-downloader` skill for article/PDF downloads. The PaperMonitor Deep Survey app bundles this skill and installs it into `~/.codex/skills` when missing. The user has explicitly authorized this workflow to use Chrome for literature downloads. The skill still tries direct/API retrieval first with Safari disabled, then falls back to Google Chrome as the user's authorized browser session.

Rules:

- Use only legal or user-provided access.
- Do not use Sci-Hub or other unauthorized sources.
- Downloads must land in `~/Downloads` first when using `chrome-literature-downloader`.
- Use the bundled command by default: `python3 ~/.codex/skills/chrome-literature-downloader/scripts/download_literature_chrome.py "<doi-or-url>"`.
- If the skill is not installed, stop and ask the user to reopen PaperMonitor Deep Survey or run `deep_survey/scripts/install_codex_deps.sh`; do not substitute a different PDF acquisition route.
- Do not inspect, export, or reuse Chrome cookies, profile files, passwords, local storage, or session databases.
- If Chrome shows captcha, Cloudflare, human verification, login/access problems, browser warnings, or a publisher save/download flow that cannot be completed safely, stop and mark the item as needing user action.
- If the Chrome downloader reports `needs_user_action`, no new valid main PDF, or a non-PDF main result, write the paper to the manual download queue rather than improvising another route.
- Validate PDFs with `file` and, when available, `pdfinfo`.
- If a PDF cannot be automatically downloaded, write it to a manual download queue with direct helper links. The queue must include DOI link, publisher/DOI landing link, OA/PDF candidate link when known, expected filename, title, and failure reason.
- Track linked manual queue entries in plugin state with `dlw.py manual-pdf`; pass `--doi-url`, `--landing-page-url`, `--oa-url`, `--expected-filename`, and `--reason` when known. Repeated DOI/filename entries should update existing state rather than create duplicates.
- When the user manually downloads PDFs, identify the paper from `~/Downloads`, tolerate minor filename issues such as leading/trailing whitespace, rename it to the expected filename, validate it, and import it into the vault.
- After a PDF is validated and imported into the vault, delete only the corresponding source file(s) from `~/Downloads`. Do not clear the whole Downloads folder. Record a cleanup log in the vault.
- When all manual downloads are imported, update the manual queue file to say no downloads are needed and run `dlw.py manual-pdf-clear` so plugin state no longer shows stale manual items.
- Do not require or create a `07_PDF_Text` directory for new topics. PDF text extraction is an optional legacy/debug aid, not a Stage 3 done criterion, because Stage 4 deep reading reads PDFs directly.

Recommended Stage 3 artifacts:

- `04_Evidence_Tables/08_stage3_pdf_inventory.csv` with DOI URL, landing page URL, OA/PDF URL, expected filename, download/import status, imported PDF path, and validation summary.
- `04_Evidence_Tables/09_manual_pdf_download_queue.md` with clickable DOI, site, and OA/PDF links.
- `04_Evidence_Tables/10_stage3_download_attempts.csv` or `.json` for `chrome-literature-downloader` outcomes.
- `04_Evidence_Tables/11_stage3_deleted_download_sources.json` listing exactly which `~/Downloads` files were removed after successful import.

### Stage 4: Paper Deep Reading

Use the `paper-broad-reading-analysis` skill for reading PDFs and regenerating paper notes.

Paper note filenames in `05_Papers/` and imported PDF filenames in `06_PDFs/` should include the same recommended deep-reading order from the Stage 2/Stage 4 queue: `01_...`, `02_...`, etc. Preserve those prefixes when rebuilding notes, updating queue CSVs/inventories, or creating links from concept notes and the review.

When Stage 4 is the active stage and the user says `继续`, process the full pending deep-reading queue **sequentially, one complete paper at a time**. Do not stop after one paper unless a PDF is missing, a paper is unreadable, the user interrupts, or the stage is too large to complete safely in the current run. Track per-paper progress so the next `继续` resumes the remaining papers.

Non-negotiable Stage 4 sequencing:

- Do one paper end-to-end before touching the next paper's analysis.
- For each paper: inspect the PDF layout/figures/tables, reconstruct the argument, rebuild the note body from the PDF, update that note's `read_depth`, and update Stage 4 progress.
- Do not batch-extract text, figure captions, abstracts, snippets, or "evidence drafts" for multiple papers as a preparation step.
- Do not create a shared corpus, bulk text directory, or all-paper evidence cache as a substitute for per-paper reading.
- Do not generate paper notes by filling a common template from batch-extracted fragments.
- Batch completion means repeated sequential deep reads, not batch processing.

A paper note counts as deep-read only when it:

- is rebuilt from the PDF, not append-only upgraded
- has no placeholder, `待核查`, or shallow starter sections
- explains the paper's central question and main contribution
- reconstructs methods, figures/results, quantitative anchors, limitations, and claim-evidence links
- is specific to the actual paper rather than template-like

### Stage 5A: Concept Notes

Concept notes are knowledge notes, not paper-note deep reads.

Use numbered concept filenames so the reading route is visible in the directory listing. Use `03_Concepts/01_Concept_Index.md` for the concept index, then `02_...`, `03_...`, etc. for the recommended concept reading order.

They should explain:

- definition and physical meaning
- formulas, units, and measurement assumptions
- where the concept appears in the field
- adjacent-concept boundaries
- common misconceptions
- representative reading route

Do not force paper-note sections such as central tension or claim-evidence tables into concept explanations unless the user explicitly asks for an evidence matrix.

### Stage 5B: Review Writing

Write as a domain review or knowledge synthesis, not a project audit. Numbering follows reader order, not generation order: Stage 5B may be generated late, but its reader-facing review should live at `02_Review.md` near the vault entrance. Avoid naming it "synthesis" for materials-science-adjacent topics because that can be misread as material preparation. If `07_PDF_Text` is not used, templates and project workflow should be numbered `07_Templates/` and `08_Project_Workflow/`.

The review should explain:

- basic concepts
- major research directions
- methods and measurement system
- material/application landscape
- controversies and open boundaries
- next literature expansion route

Project-management explanations belong in state files, indexes, or workflow notes, not in the main domain review.

### Stage 5C: Evidence Matrices And Quantitative Anchors

Use Stage 5C for focused cross-paper extraction after the domain review exists.

Typical outputs:

- controversy matrices
- method comparability tables
- quantitative anchor CSV files
- application metric tables
- next-batch literature expansion targets

Stage 5C can use claim-evidence tables, because its purpose is structured cross-paper evidence extraction.

## Quality Defaults

- Prefer Obsidian-compatible Markdown and stable wiki links.
- Keep workflow metadata separate from domain narrative.
- Use LaTeX formulas for inline math.
- Preserve user edits and do not revert unrelated workspace changes.
- Do not commit automatically. Commit only when the user asks or a milestone/risky transition needs it.
