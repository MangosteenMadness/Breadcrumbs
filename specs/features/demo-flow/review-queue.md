# Review Queue — Demo Flow

> Unresolved risks, divergences, and findings raised during spec or build.
> An item here BLOCKS completion until resolved or explicitly accepted. Append-only; don't delete,
> mark resolved.

| # | Raised by | Finding | Severity | Status |
|---|-----------|---------|----------|--------|
| 1 | spec-author | **Critical path.** Session 1 has no real number to write until `survival-analysis` produces one, and `schema/seed_findings.json` still holds `{{ }}` placeholders. If the TCGA run slips, the demo either shows a fabricated effect size — which is disqualifying for a research-integrity product — or shows nothing. Decide a fallback *before* it is 03:00. | warn | open |
| 2 | spec-author | The backup video is listed as P2-adjacent in the pitch but is a **hard submission requirement** (demo video, under five minutes, mp4/mov). It is the only truly mandatory artifact. Record it the night before against whatever works, not on demo morning. | warn | open |
| 3 | spec-author | Session 2 must run in a genuinely fresh session with no shared context. Demoing it in the same chat window would silently prove nothing — the recall could be coming from the conversation rather than from the graph, and a judge will ask. | warn | open |
