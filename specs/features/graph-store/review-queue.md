# Review Queue — Graph Store

> Unresolved risks, divergences, and findings raised during spec or build.
> An item here BLOCKS completion until resolved or explicitly accepted. Append-only; don't delete,
> mark resolved.

| # | Raised by | Finding | Severity | Status |
|---|-----------|---------|----------|--------|
| 1 | spec-author | Edge vocabulary diverges from the pitch. Breadcrumbs-v2 specifies `duplicate_of / extends / related`; the built schema has `extends / contradicts / related-to`. Proposed: implement all three from the pitch and **retain `contradicts` as a superset** — a prior result that contradicts the current hypothesis is exactly what this product exists to surface, and dropping it would destroy information already in the schema. Needs a human accept. | warn | open |
| 2 | spec-author | The committed `ingestion/breadcrumbs.db` cannot be migrated by editing `graph_schema.sql`: `connect()` runs `executescript` with `CREATE TABLE IF NOT EXISTS`, so the old CHECK constraints survive. A table rebuild is required, and `finding_edges` cascades on delete from `findings` — a rebuild with foreign keys enabled would silently destroy every edge. Back the DB up before the first run. | warn | open |
| 3 | spec-author | `schema/seed_findings.json` still carries `{{ }}` placeholders for F-118 (HR, CI, p, n, medians), pending the real TCGA LUAD run. The demo cannot be rehearsed end-to-end until they are filled. | warn | open |
