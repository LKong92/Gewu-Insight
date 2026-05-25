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

Install bundled Codex dependencies once after cloning:

```bash
deep_survey/scripts/install_codex_deps.sh
```

The app also installs missing bundled dependencies automatically when it starts.

Double-click the bundled app from this repository:

```text
deep_survey/app/Codex Literature Workflow.app
```

Or run from Terminal:

```bash
cd deep_survey/app
npm start
```

Then open:

```text
http://127.0.0.1:8787
```

## Current MVP Boundary

The backend uses:

```bash
codex exec --json --sandbox workspace-write --cd <selected-literature-workspace> "<prompt>"
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
- Bundled skills are copied into `~/.codex/skills`; credentials, browser
  cookies, and Codex auth files are never copied.
