---
name: paper-broad-reading-analysis
description: Read and interpret academic papers at a broad-reading level with enough evidence to be useful. Use when Codex is asked to read a paper, PDF, supplement, DOI-linked article, or local literature file and produce a Chinese literature interpretation focused on research background, main breakthrough, evidence chain, methods, experiments, computations, limitations, and relevance to the user's research.
---

# Paper Broad Reading Analysis

## Goal

Produce a Chinese broad-reading note that is fast to scan but grounded in the actual paper. Prefer concrete evidence from the title, abstract, figures, captions, methods, supplement, and quantitative results over generic field summaries.

## Workflow

1. Locate the paper and metadata.
   - Use the user-provided path, DOI, title, database record, or report note.
   - If the path is imprecise, search by DOI suffix, title words, or local database fields before asking the user.
   - Include the actual title, journal, date, DOI, and local PDF path when available.

2. Read the evidence layers in this order.
   - Abstract and introduction for the problem statement and why it matters.
   - Figures and captions for the result chain.
   - Results text around each figure for interpretation and quantitative values.
   - Methods for sample, computation, experimental setup, controls, and parameters.
   - Supplement for thresholds, robustness checks, extra controls, and failure modes.

3. Separate established facts from inference.
   - Say when a mechanism is demonstrated directly, inferred from controls, or proposed as a plausible explanation.
   - Do not overclaim computations, simulations, or device relevance if the paper does not actually contain them.

4. Explain the paper in the user's requested emphasis.
   - If the user asks for background, breakthrough, and methods, make those sections prominent.
   - If the user asks whether it matters for their work, add a focused relevance section.

## Extraction Checklist

Capture these items when present:

- Research problem: what bottleneck or controversy the paper addresses.
- Prior limitation: why previous methods were insufficient.
- Central idea: the one mechanism, design rule, material choice, or measurement that makes the paper work.
- Main results: figure-by-figure claims, not just abstract-level claims.
- Quantitative anchors: temperatures, wavelengths, fields, fluence, time scales, efficiencies, energy scales, errors, sample dimensions, thresholds.
- Controls: comparison to conventional preparation, no-pump or no-field baselines, direction/polarization dependence, thermal-cycle checks, damage checks.
- Methods: synthesis/growth, device fabrication, spectroscopy, microscopy, transport, magnetic probes, pump-probe, computation, models, data analysis.
- Computation: method family, software/level of theory if stated, model assumptions, inputs/outputs, and what claim the calculation supports.
- Limitations: operating conditions, sample dependence, unresolved mechanism, scalability, missing controls, or gaps between proof-of-principle and application.

## Output Structure

Use Chinese for the analysis unless the user asks otherwise. Preserve original metadata such as title, journal, DOI, material names, formulas, figure labels, and source identifiers.

Recommended sections:

- **文献概要**: 2-4 sentences identifying the paper and its one-sentence contribution.
- **课题背景**: Explain the field problem, prior route, and why this problem is hard.
- **核心突破**: State what is new, what was demonstrated, and why it changes the framing.
- **证据链**: Walk through the main figures/results in order, including quantitative anchors.
- **方法与技术路线**: Separate experiments, computation/theory, sample/device preparation, and analysis/readout methods.
- **机制理解**: Explain the authors' mechanism and distinguish direct evidence from plausible interpretation.
- **局限与可追问点**: Note practical and conceptual limits without flattening the paper's contribution.
- **与用户课题的关系**: Add only when useful; connect to materials, methods, or research direction.

For shorter requests, compress the same logic into fewer sections while keeping the evidence chain and methods visible.

## Style Rules

- Be specific and calm; avoid hype words unless the evidence justifies them.
- Prefer "这篇证明/显示/提出/暗示" over vague praise.
- Do not translate all technical terms when the English term is standard; use Chinese explanation plus original term on first mention.
- Use formulas sparingly when they clarify the physical or computational idea.
- When discussing methods, name what was actually done and the role it played in the argument.
- If the existing auto-generated note is shallow, say the analysis was rebuilt from the PDF and supplement rather than relying on that note.
