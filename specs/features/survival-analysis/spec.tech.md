---
id: survival-analysis-tech
title: "Survival Analysis — technical reference"
type: spec
status: draft
domain: breadcrumbs
audience: engineers, Breadcrumbs team
parity_of: ./components.md
registry: ./components.md
source: References/Breadcrumbs-v2.pdf
---

# Breadcrumbs / Survival Analysis — Technical Reference

**Thin and real.** The pitch asks for exactly one honest analysis: a TCGA slice → survival
stratification → a finding object. Not a platform. One real Kaplan-Meier/Cox on enough patients to
mean something, producing the effect size that Session 1 of the demo writes into the graph.

The output of this feature is not a chart. It is a **finding object** — hypothesis, signature,
effect, n, provenance — that the write path can accept. If the analysis produces numbers a biologist
would not defend, the demo is worse than not running it at all.

Component IDs must stay in the same order as `components.md` and `feature.json`.

## ANLY — data, statistics, and the tool wrapper

### BC-ANLY-001 — TCGA slice fetch and cache
- **Behavior:** Pull the clinical + bulk RNA slice for one indication (TCGA LUAD) from cBioPortal —
  the fastest route to real TCGA data — and cache it on disk. Enough patients to run one real
  survival model, not all 10K.
- **Data:** cached expression matrix + clinical table (overall survival time, event, stage).
- **Source:** not-built.
- **Status:** not-built.
- **REQ-001:** The slice loads from cache without a network call, so the demo cannot be broken by
  venue wifi.

### BC-ANLY-002 — Cytotoxic signature scoring
- **Behavior:** Score each patient on the cytotoxic T-cell signature (CD8A, GZMB, PRF1, GZMK) and
  split the cohort high vs. low. The signature and the split rule are the biologist's call, not the
  builder's — they are locked before the analysis runs, not tuned until the p-value cooperates.
- **Data:** per-patient signature score; high/low group assignment.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-002:** The split is reproducible: the same input produces the same groups and the same n.

### BC-ANLY-003 — Survival stratification
- **Behavior:** Kaplan-Meier with a log-rank test, plus a Cox proportional-hazards model, over the
  high/low split — yielding HR, 95% CI, p, and n per arm.
- **Data:** overall survival time and event from the clinical table.
- **Source:** not-built.
- **Status:** not-built.
- **Known trap, already recorded in the graph:** the abandoned finding F-093 failed precisely here —
  the effect collapsed once stage was adjusted for, because the signal was tracking tumor stage
  rather than independent biology. If this analysis reports a univariate result, it must say so.
  Breadcrumbs surfacing its own prior failure and then repeating it live would be the worst possible demo.
- **REQ-003:** The analysis reports HR, 95% CI, p, and n, and states whether it is univariate or
  stage-adjusted.

### BC-ANLY-004 — `run_analysis` tool
- **Behavior:** Wrap the analysis as an MCP tool that returns a finding object ready for the write
  path — hypothesis text, disease, signature, effect string, n, and provenance naming the data
  source and the method.
- **Data:** produces a `write_finding` payload.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-004:** The tool's output is accepted by the write path without hand-editing.
