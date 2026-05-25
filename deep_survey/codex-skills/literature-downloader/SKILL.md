---
name: literature-downloader
description: Download scholarly articles and supplemental files from a DOI into the user's ~/Downloads folder. Use when the user asks Codex to download a paper, article PDF, DOI, manuscript, supporting information, supplementary material, appendix, data supplement, or to combine a main article PDF with PDF supplements. Always prefer curl/API/open-access routes first, fall back to Safari browser downloads when direct retrieval fails, keep all downloaded files in ~/Downloads, and merge PDF supplements with the main PDF.
---

# Literature Downloader

## Non-Negotiables

- Download every file to `~/Downloads`. Do not save directly into a project, repo, or user-provided working directory.
- Treat the DOI as the primary input. If the user provides a URL, resolve or infer the DOI when practical.
- Prefer direct, legitimate retrieval first: publisher PDF links, DOI landing page links, Crossref metadata, Unpaywall, arXiv/PubMed Central, or other open/authorized APIs.
- If direct retrieval returns HTML, a login page, a paywall page, a captcha page, `403`, `401`, or a non-PDF body for the main article, fall back to Safari.
- Use Safari only as an authorized browser session. Do not bypass paywalls, captchas, browser warnings, or access controls.
- Download the main PDF and all visible supplemental/supporting information files.
- If any supplement is a PDF, always merge it after the main PDF into a combined PDF in `~/Downloads`.
- Keep original main PDF and original supplement files unless the user explicitly asks to clean up.

## Default CLI

Run the bundled downloader first instead of improvising the workflow:

```bash
python3 ~/.codex/skills/literature-downloader/scripts/download_literature.py "10.xxxx/yyyy"
```

Use `--unpaywall-email <email>` when the user provides one. Use `--dry-run` to inspect resolved metadata and candidate URLs without downloading. Use `--safari never` only when the user explicitly does not want browser fallback. Safari fallback is background-first by default; use `--foreground-safari` only when the user explicitly allows Safari to come to the foreground and use Save As.

The script:

1. Normalizes the DOI.
2. Reads Crossref, optional Unpaywall, DOI landing page metadata, publisher PDF guesses, and supplement links.
3. Downloads direct/API candidates into `~/Downloads`.
4. Falls back to Safari when direct retrieval fails, without activating Safari by default.
5. If no supplement links were found directly, tries Safari page link extraction when Safari allows JavaScript from Apple Events.
6. During Safari fallback, dismisses common cookie prompts via page JavaScript, refuses to save non-PDF HTML pages as PDFs, and downloads Safari-resolved `.pdf` / `directpdfaccess` URLs directly when possible.
7. Validates file type by magic header/content, rejecting HTML login/error pages.
8. Renames files inside `~/Downloads`.
9. Merges any PDF supplements with the main PDF into `<stem>_combined.pdf`.
10. Emits JSON with `status`, `files`, `main_pdf`, `combined_pdf`, `needs_user_action`, and `errors`.
11. On success, closes Safari tabs opened for the DOI/PDF workflow.

If the script returns `status: needs_user_action`, tell the user exactly what Safari needs (login, captcha, institution access, or manual save) and do not invent another bypass.

## Safari Fallback Notes

- Let `download_literature.py` handle Safari fallback whenever possible.
- Prefer official publisher URLs in Safari rather than copying browser cookies into shell tools.
- Default Safari mode should not steal focus. Do not add `--foreground-safari` unless the user agrees.
- If Safari asks for login, institution selection, captcha, or access approval, stop for the user.
- If JSON includes `needs_safari_javascript_setting: true`, tell the user Safari must enable `Allow JavaScript from Apple Events` before automatic supplement-link discovery can work from logged-in pages.
- If manually assisting a Safari save sheet, save only into `~/Downloads` and validate with `file`.

## Direct Retrieval Hints

- Use `curl -L -A` with a normal browser user agent and `-o ~/Downloads/<candidate>` when access is open.
- Use headers and MIME type checks before trusting a result:
  `Content-Type: application/pdf` is good; `text/html` usually means landing/login/error page.
- For ACS, look for `/doi/pdf/<doi>` for the main PDF and `suppl_file` links for supporting information.
- For Springer/Nature, look for article PDF links and `MOESM` / supplementary material links.
- For Wiley, RSC, ScienceDirect, Optica, and similar publishers, prefer visible article-page links first; avoid undocumented bypasses.

## Merge Script

Use the bundled script to combine a main PDF with one or more PDF supplements:

```bash
python3 ~/.codex/skills/literature-downloader/scripts/merge_pdf_supplements.py \
  --main ~/Downloads/article.pdf \
  --supplement ~/Downloads/article_si_1.pdf \
  --supplement ~/Downloads/article_si_2.pdf \
  --output ~/Downloads/article_combined.pdf
```

The script validates that inputs are PDFs and prefers Python `pypdf`; it falls back to `pdfunite` when available.
