# Codex Deep Literature App

Local UI controller for the `deep-literature-workflow` Codex plugin.

This app does not modify the plugin. It wraps the existing workflow with:

- topic input
- automatic Stage 1/2 start
- Stage 3 confirmation
- manual PDF import action
- automatic resume toward Stage 4/5A/5B
- live `codex exec --json` logs
- researched-topic sidebar with active topic display

## Run

Double-click:

```text
/Users/zhengranwu/Desktop/Deep_research/codex-deep-literature-app/Codex Literature Workflow.app
```

Or run from Terminal:

```bash
cd /Users/zhengranwu/Desktop/Deep_research/codex-deep-literature-app
npm start
```

Then open:

```text
http://127.0.0.1:8787
```

## Current MVP Boundary

The backend uses:

```bash
codex exec --json --sandbox workspace-write --cd /Users/zhengranwu/Desktop/Deep_research "<prompt>"
```

The default path uses the local Codex login and usage. It does not use an OpenAI API key.

## Stage Policy

- Stage 1, Stage 2, Stage 4, Stage 5A, and Stage 5B are intended to run automatically.
- Stage 3 always requires explicit confirmation from the UI.
- Stage 5C is intentionally omitted from the MVP UI.

## Safety Notes

- Do not collect or store ChatGPT/OpenAI credentials.
- Do not package or upload `~/.codex/auth.json`.
- Do not use unauthorized PDF sources.
- Use Chrome only through the authorized literature downloader workflow.
