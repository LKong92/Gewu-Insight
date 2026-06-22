# Deep Literature Workflow

Codex-native staged literature review workflow for building an Obsidian-compatible research vault.

Typical commands in Codex:

```text
@Deep Literature Workflow 新建文献调研，先问我研究课题
@Deep Literature Workflow 继续
@Deep Literature Workflow 导入手动 PDF
@Deep Literature Workflow 检查 vault 完整性
```

The plugin keeps a small state file under `.deep-literature-workflow/state.json`.
The state file records the active topic, vault path, current stage, manual PDF queue, and recent notes.

For multi-topic workspaces, the root `PROJECT_STATE.md` is treated as a compact index only. New vaults use this handoff path:

```text
<VaultRoot>/08_Project_Workflow/PROJECT_STATE.md
```

`dlw.py init`, `dlw.py mark`, `dlw.py manual-pdf`, `dlw.py manual-pdf-clear`, and `dlw.py index` refresh the workspace index and create/update plugin-managed topic handoffs.

For direct topic input from a shell:

```bash
python3 plugins/deep-literature-workflow/scripts/dlw.py init --topic "双光子吸收" --slug two-photon-absorption
```

Refresh the workspace index from the active state:

```bash
python3 plugins/deep-literature-workflow/scripts/dlw.py index
```

Stage 3 is manual-download only in PaperMonitor Deep Survey. Stage 2 should
prepare a linked manual queue, then the user opens those links, downloads the
main PDFs, and chooses the PDFs in the app for matching, validation, and import.

Do not start automatic PDF downloaders, browser automation, or batch download
scripts unless the user explicitly asks outside the Stage 3 app workflow.

Record a linked manual PDF queue item:

```bash
python3 plugins/deep-literature-workflow/scripts/dlw.py manual-pdf \
  --title "Paper title" \
  --doi "10.xxxx/yyyy" \
  --doi-url "https://doi.org/10.xxxx/yyyy" \
  --landing-page-url "https://publisher.example/article" \
  --oa-url "https://arxiv.org/pdf/xxxx" \
  --expected-filename "2026_Paper_title.pdf" \
  --reason "Main PDF was not downloaded by direct/OA retrieval."
```

After manual PDFs have been validated and imported:

```bash
python3 plugins/deep-literature-workflow/scripts/dlw.py manual-pdf-clear \
  --note "Stage 3 complete: all manual PDFs imported."
```
