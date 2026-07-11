# Review Queue — Survival Analysis

> Unresolved risks, divergences, and findings raised during spec or build.
> An item here BLOCKS completion until resolved or explicitly accepted. Append-only; don't delete,
> mark resolved.

| # | Raised by | Finding | Severity | Status |
|---|-----------|---------|----------|--------|
| 1 | spec-author | **Univariate or stage-adjusted?** The abandoned finding F-093 exists precisely because this signal collapsed under stage adjustment. If the live analysis reports a univariate HR without saying so, Breadcrumbs will surface its own recorded failure and then walk straight into it on stage. Biologist 1 must lock the design — signature, split rule, and adjustment — *before* the analysis runs, not after seeing the p-value. | warn | open |
| 2 | spec-author | `schema/seed_findings.json` carries `{{ }}` placeholders for the F-118 effect size, pending this analysis. Until it runs, the demo cannot be rehearsed end to end. This feature is on the critical path for the demo. | warn | open |
