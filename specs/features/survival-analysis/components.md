# Cairn / Survival Analysis — Component Registry

> The ordered list of components. The same IDs, in the same order, must appear in `spec.tech.md`
> and `feature.json.component_ids`.
> Status vocabulary: built-at-parity | gap | not-built | descoped | unverified | planned | in_progress

## ANLY — data, statistics, and the tool wrapper

| ID | Component | Status |
|----|-----------|--------|
| CRN-ANLY-001 | TCGA LUAD slice fetch from cBioPortal, cached to disk | not-built |
| CRN-ANLY-002 | Cytotoxic signature scoring (CD8A, GZMB, PRF1, GZMK) and high/low split | not-built |
| CRN-ANLY-003 | Survival stratification — Kaplan-Meier + log-rank + Cox | not-built |
| CRN-ANLY-004 | `run_analysis` tool — emits a finding object for the write path | not-built |
