---
name: paper-broad-reading-analysis
description: Read and interpret academic papers at a broad-reading level with enough evidence to be useful. Use when Codex is asked to read a paper, PDF, supplement, DOI-linked article, or local literature file and produce a Chinese literature interpretation focused on research background, main breakthrough, evidence chain, methods, experiments, computations, limitations, and relevance to the user's research.
---

# Paper Broad Reading Analysis

## Goal

Produce a Chinese broad-reading note that feels like a careful researcher read the full paper and is now explaining it to another researcher. The output should not be a pile of conclusions, figures, and parameters. It should first reveal the paper's central tension, the authors' argumentative move, what the evidence actually proves, what remains uncertain, and why the paper changes how later work should be judged.

The note must be fast to scan, but it should preserve the paper's problem, evidence hierarchy, quantitative anchors, methods, limits, and claim-level traceability. Prefer interpretation that is grounded in evidence over exhaustive but flat coverage.

For PDF-backed papers, use complete PDF layout understanding as the evidence source. Extracted text may be used for search and copying exact values, but it is not sufficient by itself because tables, figures, captions, equations, column order, and visual relationships often carry the argument.

## Workflow

1. Locate the paper and metadata.
   - Use the user-provided path, DOI, title, database record, or report note.
   - If the path is imprecise, search by DOI suffix, title words, local database fields, or nearby PDF/note filenames before asking the user.
   - Include the actual title, journal, date/year, DOI, and local PDF path when available.

2. Build evidence from the full PDF, not only text extraction.
   - Open/render the PDF or otherwise inspect page images when a local PDF exists.
   - Read the abstract, introduction, figures, captions, tables, equations, results text near each figure/table, methods, conclusions, and supplement when available.
   - Use extracted text only as an aid for locating passages, not as a replacement for the page layout.
   - If full PDF layout inspection is blocked, state the limitation explicitly and do not label the result as a full broad-reading analysis.

3. Reconstruct the paper's argument before writing.
   - Identify the central bottleneck or controversy the paper addresses.
   - Identify the prior method/data/model the authors are correcting, extending, or replacing.
   - Identify the paper's core move: the measurement, material design, device architecture, model, control, or comparison that makes the contribution work.
   - Identify which figures/tables prove the central move and which are supporting context.
   - Write from this reconstructed argument, not from the order in which facts were extracted.

4. Build a hierarchy of importance.
   - Separate the paper's main claim, enabling evidence, calibration/control evidence, context/background evidence, and speculative interpretation.
   - Do not give every figure equal weight. Spend more words on figures/tables that change the conclusion, and compress routine setup, inventories, or appendices unless they affect trust in the result.
   - For every dense detail, ask "so what?" and state the answer if the detail remains in the note.

5. Write the evidence chain figure-by-figure or claim-by-claim.
   - For each main figure/table, state: the question it answers, what was measured/computed, the key quantitative anchors, and the conclusion it supports.
   - Explain each figure's role in the overall argument, not just what appears in the panel.
   - Include important negative results, exclusions, failed candidates, artifacts, calibration controls, or uncertainty budgets when they shape the claim.
   - If a figure is mainly methods, write it under methods. If several figures serve one logical point, group them under that point rather than producing a mechanical figure catalog.

6. Separate established facts from inference.
   - Mark whether each important claim is directly demonstrated, indirectly supported, or proposed/speculated by the authors.
   - Distinguish measured values from fitted/interpolated/scaled values.
   - Distinguish mechanism demonstrated by controls from mechanism invoked as interpretation.
   - Do not overclaim computations, simulations, device relevance, biological relevance, or generality if the paper does not actually show them.

7. Explain the paper in the user's requested emphasis.
   - If the user asks for background, breakthrough, and methods, make those sections prominent.
   - If the user asks whether it matters for their work, add a focused relevance section.
   - If the result is for a research vault, prioritize reusable claims and traceable evidence over polished review prose.

8. Write for readability before completeness.
   - Do not start with a standalone abbreviation glossary. Define abbreviations inline at first use, e.g. `纠缠双光子吸收（entangled two-photon absorption, E2PA）`.
   - Prefer clear Chinese explanations over mixed Chinese-English phrase piles. Keep English terms only when they are standard identifiers, paper-specific terms, material names, methods, or formulas.
   - Use short paragraphs, **bold subsection labels**, and numbered or bulleted structure when it makes the reading path clearer.
   - Lead each section with the plain-language point before adding dense quantitative details.
   - Make transitions explicit: after technical evidence, say what it means for the paper's claim.

## Extraction Checklist

Capture these items when present:

- Research problem: what bottleneck or controversy the paper addresses.
- Prior limitation: why previous methods were insufficient.
- Central idea: the one mechanism, design rule, material choice, or measurement that makes the paper work.
- Argumentative move: whether the paper proves a new effect, sets a bound, corrects a prior value, explains a discrepancy, introduces a method, or reframes an application.
- Main results: figure-by-figure claims and the role each figure/table plays in the argument, not just abstract-level claims.
- Quantitative anchors: temperatures, wavelengths, fields, fluence, time scales, efficiencies, energy scales, errors, sample dimensions, thresholds.
- Controls: comparison to conventional preparation, no-pump or no-field baselines, direction/polarization dependence, thermal-cycle checks, damage checks.
- Methods: synthesis/growth, device fabrication, spectroscopy, microscopy, transport, magnetic probes, pump-probe, computation, models, data analysis.
- Computation: method family, software/level of theory if stated, model assumptions, inputs/outputs, and what claim the calculation supports.
- Limitations: operating conditions, sample dependence, unresolved mechanism, scalability, missing controls, or gaps between proof-of-principle and application.
- Evidence quality: uncertainty/error budget, calibration/reference choice, artifact controls, direct vs fitted values, and whether the same conclusion is independently reproduced.
- Reader takeaway: what a future researcher should do differently after reading this paper.

## Output Structure

Use Chinese for the analysis unless the user asks otherwise. Preserve original metadata such as title, journal, DOI, material names, formulas, figure labels, and source identifiers.

Recommended sections:

- **文献概要**: 2-4 sentences identifying the paper, the central tension, and the one-sentence contribution.
- **课题背景**: Explain the field problem, prior route, why this problem is hard, and what uncertainty or controversy the old approach left unresolved.
- **核心突破**: State the authors' argumentative move: what they proved, bounded, corrected, ruled out, reframed, or made measurable. Say why this changes interpretation of the field.
- **证据链**: Walk through the main figures/tables in order. For each, include the question, experiment/computation, conclusion, and key quantitative values.
- **方法与技术路线**: Use clear method blocks, each with what was done and why it matters. Prefer labels such as **样品与材料选择**、**光源与表征**、**实验装置/测量设置**、**对照与校准**、**数据处理与上界/参数计算**、**光谱/收集效率校正** when applicable.
- **机制理解**: Explain the authors' mechanism and distinguish direct evidence, indirect support, and plausible interpretation.
- **局限与可追问点**: Note practical and conceptual limits without flattening the paper's contribution.
- **与用户课题的关系**: Add only when useful; connect to materials, methods, or research direction.
- **Claim-evidence table**: Add when the task is a deep-read note or when the paper will feed an evidence matrix.

For shorter requests, compress the same logic into fewer sections while keeping the evidence chain and methods visible.

## Interpretation Standard

The analysis should read as an explanation, not an inventory. Before finalizing, make sure these elements are visible:

1. **主线**: The reader can say in one sentence what problem the paper is really about.
2. **动作**: The reader can say what the authors did to resolve, constrain, or reframe that problem.
3. **证据权重**: The reader can tell which evidence is decisive and which evidence is merely supporting.
4. **可信边界**: The reader can tell what was directly shown, what was inferred through models or fits, and what remains unproven.
5. **研究后果**: The reader can tell how this paper should change future citation, experiment design, screening, or skepticism.

If a paragraph only lists facts and does not advance one of these five purposes, compress it or connect it to the argument.

## Methods Section Template

When the methods are important, make **方法与技术路线** concrete and easy to scan. Use only the blocks that fit the paper:

1. **样品与材料选择**: What samples/materials/devices were used, their preparation or source, and why they are appropriate controls or targets.
2. **光源、仪器或计算体系**: What excitation source, microscope, spectrometer, fabrication route, simulation level, or model system was used.
3. **实验装置/测量设置**: How the measurement was physically or computationally arranged; include geometry, wavelengths, fields, pulse parameters, detector/readout, or boundary conditions when they matter.
4. **对照与校准**: What baselines, references, background subtraction, standards, alignment checks, damage checks, or reproducibility checks make the result trustworthy.
5. **数据处理与参数计算**: How raw observations became the reported quantity; distinguish measured, fitted, scaled, inferred, upper-bound, or simulated values.
6. **光谱/空间/时间/效率校正**: Add this block when detector response, collection efficiency, beam profile, spectral overlap, pulse duration, entanglement time/area, or other instrument functions control the conclusion.

Each block should end with a short **作用** sentence when useful: explain what this method block contributes to the paper's argument. Avoid long equipment inventories unless the exact component is evidence.

## Claim-Evidence Table

For deep-reading notes, end with a compact table:

| Claim | Evidence/source citation | Figure/section | Evidence type | Confidence 1-5 |
| --- | --- | --- | --- | --- |

Use these evidence types:

- `直接证明`: the paper measures/computes/controls the claim directly.
- `间接支持`: the claim follows from multiple results but is not directly isolated.
- `作者推测`: the paper proposes a plausible cause or mechanism without decisive proof.
- `背景/方法依据`: the claim is a methodological premise, definition, or literature-grounded setup.

Keep the table selective: include claims that a future literature review, evidence matrix, or research decision would actually reuse.

## Quality Bar

Before finishing, check the note against these questions:

- Could a researcher explain why this paper mattered without reopening the PDF?
- Does the note have a clear human-readable throughline, or does it feel like extracted notes pasted together?
- Does each major technical detail answer "why does this matter for the claim?"
- Are the strongest claims tied to specific figures, tables, sections, or quoted/paraphrased evidence?
- Are direct measurements separated from fitted/scaled/interpolated values?
- Are author interpretations separated from demonstrated results?
- Are methods described by what was actually done and why it supports the argument?
- Are limitations and artifact risks specific rather than generic?
- Does the relevance section say how this paper changes evaluation of later papers, not just that it is "important"?

## Style Rules

- Be specific and calm; avoid hype words unless the evidence justifies them.
- Prefer "这篇证明/显示/提出/暗示" over vague praise.
- Do not translate all technical terms when the English term is standard; use Chinese explanation plus original term on first mention.
- Do not create a separate abbreviation list unless the user asks. Introduce abbreviations naturally in the relevant sentence.
- Avoid heavy Chinese-English mixing. A sentence should remain readable in Chinese even when it contains necessary English terms, symbols, or material names.
- Use **bold** labels and numbered steps sparingly but deliberately to improve scanability in dense sections, especially methods and evidence chains.
- Use formulas sparingly when they clarify the physical or computational idea.
- When discussing methods, name what was actually done and the role it played in the argument.
- If the existing auto-generated note is shallow, say the analysis was rebuilt from the PDF and supplement rather than relying on that note.
- Write with enough synthesis that the reader can see the paper's internal logic; avoid a flat checklist tone, figure-by-figure bookkeeping, and conclusion dumping.
