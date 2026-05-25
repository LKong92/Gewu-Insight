---
name: chrome-literature-downloader
description: Download scholarly article PDFs from a DOI or publisher URL into the user's ~/Downloads folder using direct/API retrieval first and Google Chrome as an authorized browser fallback. Use when the user explicitly wants Chrome for paper/PDF download because Safari or Playwright Chromium triggers Cloudflare, captcha, login, or browser-verification problems. Never bypass paywalls, captchas, or access controls.
---

# Chrome Literature Downloader

## Non-Negotiables

- Use this skill only when the user explicitly requests Chrome-based literature downloading.
- Download every file to `~/Downloads`. Do not save directly into a project, repo, or vault.
- Prefer direct legitimate retrieval first by delegating to the existing `literature-downloader` script with Safari disabled.
- If direct/API retrieval produces a high-confidence article PDF but the lower-level downloader mislabeled it as a supplement, promote it to the main PDF instead of falling back to Chrome.
- Use Google Chrome only as an authorized browser session with the user's normal access. Do not inspect or export Chrome cookies, local storage, profile files, passwords, or session databases.
- Do not bypass paywalls, captchas, Cloudflare, login prompts, browser warnings, or access controls.
- If Chrome shows captcha/verification or cannot download the PDF, stop and report `needs_user_action`.
- Keep Chrome in background by default: open tabs without `activate`, restore Chrome's previous active tab, and return focus to the user's prior foreground app. Use `--foreground-chrome` only for debugging.
- Avoid focus churn: only restore the user's prior foreground app when Chrome is actually frontmost. Do not repeatedly activate the prior app after background-only operations, because that can interrupt typing with rapid window switches.
- Some publishers, especially Optica after `Get PDF`, may still bring Chrome forward as part of the browser download. Treat these as disruptive browser clicks. They are disabled by default; use `--allow-disruptive-browser-clicks` only when the user explicitly accepts a possible foreground flash or the computer is idle.
- Do not use mouse-coordinate clicks or active-window GUI clicks by default. If a PDF viewer requires clicking its toolbar download button, report `needs_user_action` unless the user explicitly opts into `--allow-active-window-click`.
- Close Chrome tabs opened for the DOI after success unless the user asks to keep them.
- Download visible supplemental/supporting material links after the main PDF when Chrome fallback is used.
- For Wiley articles, open the article page first and click the visible PDF/Download PDF control before falling back to raw PDF URLs.
- If Wiley opens a reader without saving, use the authorized Wiley page itself to fetch the same-origin `pdfdirect` PDF and trigger a browser download; do not export or inspect cookies.
- For APS articles, open the APS abstract page first, then use that same-origin page to fetch the official APS PDF and trigger a browser download before trying raw PDF URLs.
- For SciPost and other open article pages, click the visible main `PDF` control on the landing page before returning `needs_user_action`.
- Existing same-title PDFs in `~/Downloads` do not count as success by default; the script should still attempt a fresh download for the current DOI.
- Only reuse an existing matching PDF when the user explicitly asks or the CLI passes `--use-existing-pdf`.
- If any supplement is a PDF, always merge it after the main PDF into `<stem>_combined.pdf` in `~/Downloads`.
- After a combined PDF is created, delete the original main PDF and PDF supplement files by default. Keep non-PDF supplements such as `.zip`, `.xlsx`, or `.cif`.
- Validate downloaded PDFs before reporting success.

## Recommended Chrome Settings

- Prefer Chrome's built-in setting to download PDFs instead of opening them in the browser: `chrome://settings/content/pdfDocuments` -> download PDFs. This is usually positive for the skill because it lets Chrome create files in `~/Downloads` that the script can validate and rename.
- Keep site permission for automatic multiple downloads enabled for publisher domains that may download a main PDF plus supplements, such as `ieeexplore.ieee.org`, `opg.optica.org`, `www.optica.org`, `science.org`, `wiley.com`, and other tested publisher hosts.
- If a publisher that previously worked starts failing after changing the PDF setting, keep the global direct-download setting and add or adjust a publisher-specific rule rather than switching the whole browser back to viewer mode.
- Disabling PDF-reader extensions such as Google Scholar Reader for publisher sites can reduce interference. Do this per-site when possible rather than disabling useful extensions globally.
- These settings only affect Chrome's browser behavior; they do not authorize Codex to read cookies, passwords, local storage, or profile databases.

## Default CLI

Run the bundled script:

```bash
python3 ~/.codex/skills/chrome-literature-downloader/scripts/download_literature_chrome.py "10.xxxx/yyyy"
```

The script:

1. Normalizes the DOI or publisher URL.
2. Calls the existing direct/API downloader with `--safari never`.
3. If the direct route succeeds, returns that result; if it produced a high-confidence fulltext PDF mislabeled as a supplement, promotes it to `main_pdf`.
4. If the direct route fails, opens official publisher PDF/landing URLs in Google Chrome; for Wiley, it clicks the article-page PDF control.
5. Waits for Chrome's normal main-PDF download to appear in `~/Downloads`.
6. If no new download appears, returns `needs_user_action` unless `--use-existing-pdf` is explicitly set.
7. Opens the publisher landing page in Chrome, extracts visible supplement/supporting-material links, and downloads them to `~/Downloads`.
8. Merges PDF supplements with the main PDF into `<stem>_combined.pdf`.
9. Deletes the original main PDF and PDF supplements after successful merge unless `--keep-original-pdfs` is set.
10. Rejects non-PDF main results and stops on Cloudflare/captcha/human verification.
11. Renames files using the same metadata stem when available.
12. Closes related Chrome tabs at the end unless `--keep-tabs` is set.
13. Emits JSON with `status`, `main_pdf`, `main_pdf_existing_match` when applicable, `main_pdf_deleted`, `combined_pdf`, `files`, `deleted_files`, `needs_user_action`, `errors`, and logs.

Useful options:

- `--foreground-chrome`: bring Chrome to the foreground while testing or debugging.
- `--focus-restore auto|always|never`: control focus restoration after Chrome automation. Default `auto` restores only if Chrome is actually frontmost; use `always` only for debugging old behavior.
- `--allow-disruptive-browser-clicks`: opt into publisher page clicks that can bring Chrome to the foreground, such as Optica `Get PDF`. This is disabled by default.
- `--allow-active-window-click`: opt into a last-resort Chrome PDF-viewer toolbar click. This is disabled by default because it requires Chrome to become active and uses GUI coordinates.
- `--keep-tabs`: leave opened Chrome tabs visible for the user.
- `--keep-original-pdfs`: keep main/supplement PDFs after a combined PDF is created.
- `--use-existing-pdf`: explicitly allow a high-confidence existing PDF in `~/Downloads` to satisfy the main PDF when no new download occurs.
- `--max-chrome-candidates 1`: avoid multiple browser attempts on sensitive sites.
- `--max-supplement-candidates 3`: limit supplement download attempts on sensitive sites.
- `--supplement-timeout 20`: keep supplement attempts short when a link opens a page instead of downloading.
- `--dry-run`: run direct metadata/candidate discovery without Chrome downloading.

## Batch CLI

For multiple DOI downloads, prefer the publisher-aware batch runner:

```bash
python3 ~/.codex/skills/chrome-literature-downloader/scripts/batch_download_literature_chrome.py \
  --input-file dois.txt
```

It uses the single-paper downloader for each DOI, but chooses timing and retry budgets by `publisher_strategy`:

- APS: short first pass, because direct/API harvest or same-origin APS fetch is usually fast.
- Science/SciPost: medium first pass, with enough supplement time for Science `DOWNLOAD` links and SciPost page-based PDF fetch.
- Wiley/ACS/PNAS: longer first pass and retry budgets, because authenticated PDF controls and supplements are more variable.
- Generic: conservative fallback profile.

Batch behavior:

1. Runs serially by default so Chrome downloads into `~/Downloads` cannot be misattributed across simultaneous DOI jobs.
2. Retries unresolved DOI once with a longer strategy-specific profile.
3. Continues after ordinary failures by default. Do not challenge or bypass captcha/verification/Cloudflare; mark that DOI unresolved and move to the next DOI.
4. Writes `summary.json` plus per-attempt stdout/stderr logs to `/private/tmp/chrome_literature_batch_<timestamp>/` unless `--outdir` is provided.
5. Records per-DOI `publisher_strategy`, `attempt_profile`, `elapsed_seconds`, output files, deleted PDF originals, and errors.
6. For Optica, use a longer inter-paper delay in batch mode. The default batch runner waits at least 180 seconds between Optica DOI attempts; override with `--optica-delay-seconds N` only when intentionally testing. If Optica reports heavy usage/downloading timeout/PerfDrive/BotManager or a suspiciously small PDF, place Optica in publisher cooldown and skip later Optica DOI in that batch.

Useful batch options:

- `--stop-on-failure`: stop after any unresolved DOI.
- `--stop-on-verification`: stop the whole batch when captcha/verification is detected.
- `--outdir /path`: choose a log directory.
- `--optica-delay-seconds N`: choose the minimum delay between Optica DOI attempts; default is 180 seconds.
- `--foreground-chrome`, `--focus-restore`, `--allow-disruptive-browser-clicks`, `--keep-tabs`, `--keep-original-pdfs`, and `--use-existing-pdf`: passed through to the single-paper downloader.

## Chrome Fallback Notes

- Chrome must already be installed and signed into whatever institutional/publisher session the user wants to use.
- Chrome direct-PDF-download mode is recommended. Most successful publisher paths either trigger a direct file download or can be adapted to one; the script's validation layer rejects HTML/error pages saved with `.pdf` names.
- The script never copies Chrome cookies into curl or Python requests; it only lets Chrome itself trigger authorized downloads.
- If a page says the user has subscription access but PDF download does not start, report the page state and stop.
- Wiley often opens a reader/viewer without creating a download; the script should click the Wiley PDF/supplement controls, then use same-origin `pdfdirect` or `downloadSupplement` fetch from the authorized page. Reuse an existing PDF only when `--use-existing-pdf` is set.
- APS can challenge direct `/pdf/` navigation; prefer same-origin fetch from the APS abstract page before falling back to raw PDF navigation.
- SciPost may protect raw HTTP clients with Anubis; prefer real Chrome landing-page interaction and the visible `pdf` link.
- IEEE Xplore can show the real PDF through `stamp.jsp` while same-origin fetches return HTML. Open only the DOI landing page once, click the visible PDF control, extract the official `stampPDF/getPDF.jsp` URL from the `stamp.jsp` page, then navigate the same Chrome tab to that URL and wait for Chrome's normal download. Do not default to mouse-coordinate toolbar clicks in the viewer; if `getPDF.jsp` does not create a valid PDF, return `needs_user_action` unless the user explicitly opts into `--allow-active-window-click`.
- Optica / OSA must be treated as both rate-limit sensitive and foreground-disruptive. Wait for the Optica `Please wait...` page to finish and detect the visible `Get PDF` button, but do not click it by default because the site/download flow can bring Chrome forward. Return `needs_user_action` with a clear message unless the user explicitly passes `--allow-disruptive-browser-clicks`, preferably while the computer is idle. In batch runs, space different Optica articles apart by several minutes; the bundled batch default is 180 seconds. Do not guess multiple `viewmedia` URLs or repeatedly retry; one DOI landing attempt only, then publisher cooldown on timeout/fake-PDF signals.
- AIP Publishing has a validated Chrome path: DOI landing page -> visible `article-pdf` link -> Chrome PDF viewer token URL; keep zip supplements.
- If Cloudflare appears in Chrome, do not try to solve it automatically; ask the user to complete the page manually or use another browser.
- For Science, ACS, Wiley, PNAS, and APS, prefer official `/doi/pdf/<doi>` / APS `/pdf/<doi>` or publisher landing URLs.

## Verified Browser Rules

### IEEE Xplore

Use this rule for `10.1109/...` DOI.

1. Open only the DOI landing page in Chrome.
2. Wait for the IEEE article page to load and confirm institutional access if visible.
3. Click the article-page `PDF` / `Download PDF` control.
4. Wait for `stamp.jsp` to load.
5. Extract the official `stampPDF/getPDF.jsp?...` URL from the `stamp.jsp` page.
6. Navigate the same Chrome tab to that `getPDF.jsp` URL and wait for Chrome's normal download.
7. Validate that the downloaded file starts with PDF magic, is not a small HTML fake, then rename to the metadata stem.

Do not use raw `curl`, Python `fetch`, repeated `stamp.jsp` guesses, search pages, or mouse-coordinate clicks for IEEE. Raw HTTP/script fetches can return HTML or create an 8 KB fake `.pdf`; browser navigation to the official `getPDF.jsp` is the verified path.

Verified success: `10.1109/3.53394` downloaded and renamed to `1990_Sensitive_measurement_of_optical_nonlinearities_using_a_single_beam.pdf`.

### Optica / OSA

Use this rule for `10.1364/...` DOI.

1. Open only the DOI landing page in Chrome.
2. Wait for the Optica `Please wait...` page to finish and for the fulltext article page to show.
3. Detect the visible `Get PDF` / `PDF Article` control on the article page.
4. In default background mode, do not click it; return `needs_user_action` because this site-initiated download can bring Chrome to the foreground and interrupt typing.
5. If the user explicitly passed `--allow-disruptive-browser-clicks`, click that control once and wait for Chrome's normal download.
6. Validate that the downloaded file is a real PDF, not an Optica timeout/error page or suspiciously small PDF, then rename to the metadata stem.
7. Only if the visible control path fails in the opt-in disruptive mode, extract the actual `uri=` from the resolved Optica URL and use that exact `uri` for one fallback attempt.

Do not infer Optica `viewmedia` paths from DOI alone because DOI forms may omit issue numbers, for example `10.1364/josab.15.000817` resolves to `josab-15-2-817`. Do not try multiple guessed `viewmedia` URLs or retry Optica aggressively; on `heavy usage`, `downloading timeout`, PerfDrive, BotManager, captcha, or small fake PDF signals, stop Optica attempts and let the publisher cool down.

When downloading multiple Optica articles, wait several minutes between different DOI attempts. The batch runner enforces a 180-second default delay between Optica DOI attempts and records `pre_attempt_delay_seconds` in `summary.json`.

Verified success: `10.1364/josab.15.000817` downloaded via `Get PDF` and renamed to `1998_Femtosecond_Z-scan_and_degenerate_four-wave_mixing_measurements_of_real_and_imaginary_parts_of_the_third-order_nonl.pdf`.

## Publisher Strategies

Keep publisher-specific download behavior explicit in the script's `PUBLISHER_STRATEGIES` registry and in this table. When a DOI fails, update the matching strategy with the smallest legal fix that prevents repeated trial-and-error.

| Publisher | Main PDF strategy | Supplement strategy | Known failure signals / tested examples |
|---|---|---|---|
| APS / Physical Review | Prefer direct/API harvest. If Chrome fallback is needed, open the APS abstract page and same-origin fetch the official APS `/pdf/` DOI URL before trying raw PDF navigation. | Usually no supplement; inspect the abstract/landing page for visible supporting-material links. | Raw `/pdf/` navigation may show verification; direct harvest can be mislabeled as supplement. Tested: `10.1103/physrevb.61.10267`, `10.1103/physrevlett.86.268`, `10.1103/physrevresearch.2.013377`. |
| Science / AAAS | Use Chrome-authorized official `/doi/pdf/<doi>?download=true`; direct HTTP often returns 403. | Open the article page, extract visible `DOWNLOAD` supplement links, download through Chrome, merge PDF supplements, keep non-PDF supplements such as zip. | Supplement files may be versioned `_sm.vN.pdf` or zip. Tested: `10.1126/science.1222360`, `10.1126/science.aav3392`, `10.1126/science.aao1797`. |
| SciPost | Open the SciPost article page in real Chrome, click/read the visible `pdf` control, then same-origin fetch the official `/pdf` URL from that page. | Usually no supplement; inspect visible article-page links. | Raw HTTP may show Anubis; Chrome PDF viewer may open without saving. Tested: `10.21468/scipostphys.7.5.061`. |
| Wiley | Open the article page first and click PDF/Download PDF. If a reader opens without saving, same-origin fetch `/doi/pdfdirect/<doi>` from the authorized Wiley page. | Use visible `downloadSupplement` links; for PDF supplements, fetch from the same authorized page and merge. | Direct PDF/XML often returns 403; existing same-title PDFs do not count unless `--use-existing-pdf` is set. Tested: `10.1002/anie.202101120`, `10.1002/anie.200805257`. |
| ACS | Try official `/doi/pdf/<doi>?download=true` through Chrome authorization, then article-page PDF controls. | Extract Supporting Information links from the article page; merge PDF SI and keep non-PDF SI. | Cloudflare/browser verification can appear; stop immediately on captcha. Tested: `10.1021/jacs.0c02808`. |
| PNAS | Try official `/doi/pdf/<doi>` and landing-page PDF controls through Chrome authorization. | Extract Supporting Information links from the article page; merge PDF SI and keep non-PDF SI. | Browser may open a PDF without creating a download. Tested: `10.1073/pnas.0504892102`. |
| IEEE Xplore | Open only the DOI landing page once. Do not repeatedly try search pages or multiple candidates. Click the visible PDF control, extract the page's official `stampPDF/getPDF.jsp` URL, navigate Chrome to it, and validate the downloaded PDF. | Usually no PDF supplements; do not run supplement discovery unless a valid main PDF was saved. | IEEE pages may show institutional access and a PDF button, but raw HTTP/script fetches can return HTML. Browser navigation to `getPDF.jsp` can download the real PDF when Chrome is allowed to download PDFs; fake HTML `.pdf` files must be deleted. Tested: `10.1109/3.53394`. |
| Optica / OSA | Open only the DOI landing page, wait past `Please wait...`, and detect the visible `Get PDF`/`PDF Article` control. Do not click it by default because Optica can bring Chrome forward; require `--allow-disruptive-browser-clicks` for the one allowed click/fallback attempt. Do not infer `viewmedia` paths from DOI alone because issue numbers may be omitted from the DOI. | Try visible supplement links only after a valid main PDF. | Optica may impose IP downloading timeout after heavy usage and may steal foreground on `Get PDF`. On timeout/PerfDrive/BotManager or suspiciously small PDFs, stop Optica attempts for the batch and try again later. One valid success: `10.1364/josab.9.000405`; `10.1364/josab.15.000817` resolves to `josab-15-2-817` and may pause at an Optica `Please wait...` page before showing `Get PDF`. |
| AIP Publishing | Open DOI landing page, extract visible `article-pdf` link, and save Chrome PDF viewer token URL when available. | AIP supplementary material can be a zip; keep non-PDF supplements and merge PDF supplements if present. | Direct HTTP often returns 403 but Chrome-authorized article page works. Tested success: `10.1063/5.0188658`, `10.1063/1.1848192`, `10.1063/5.0089925`, `10.1063/1.5085504`. |

The script emits the selected `publisher_strategy` in its JSON output. Use that field when debugging failed downloads or deciding whether a new publisher rule is needed.

## Supplements

- Always try to download visible supplemental/supporting-material links after the main PDF.
- For Science articles, also try the common official `_SM.pdf` supplement URL pattern.
- After `combined_pdf` is created, delete the original main PDF and PDF supplements by default.
- Keep non-PDF supplement files.
- If one or more supplement files are PDFs, merge them with the main article PDF and report `combined_pdf`.
- If supplement discovery hits verification/login/captcha, stop and report `needs_user_action` rather than retrying aggressively.
