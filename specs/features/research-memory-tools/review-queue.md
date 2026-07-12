# Review Queue — Research Memory Tools

> Unresolved risks, divergences, and findings raised during spec or build.
> An item here BLOCKS completion until resolved or explicitly accepted. Append-only; don't delete,
> mark resolved.

| # | Raised by | Finding | Severity | Status |
|---|-----------|---------|----------|--------|
| 1 | spec-author | **Data boundary.** `check_duplication` stage 2 sends researcher hypothesis text to the Claude API for semantic matching. This repo is classified `confidential` and ingests real Owkin K Pro sessions. A human must confirm that routing hypothesis text (not patient-level data) to an external model is acceptable, and pin `specConfig.approvedModels` in `.spec/repo.json`. Resolution: the UI-aligned demo path uses the local matcher in `src/breadcrumbs/store.py`; hypothesis text is not sent to an external model. | error | resolved |
| 2 | spec-author | `write_finding` must reuse the validation in `ingestion/write_findings.py` rather than reimplementing it. Resolution: `BreadcrumbsStore.write` calls `write_payload` directly and the shared-gate test exercises both paths. | warn | resolved |
| 3 | spec-author | The MCP endpoint paths recorded in `feature.json.backend` are a fair mapping onto the layer schema's HTTP shape, but MCP is JSON-RPC — the real surface is `tools/call` over a single transport. Resolution: tools use FastMCP; only `/check_duplication` is also exposed as the deliberate UI REST seam. | info | resolved |
| 4 | spec-author | **The `check_duplication` response shape is already defined in TypeScript.** Resolution: `src/breadcrumbs/contracts.py` mirrors the UI boundary, generates `schema/mcp_contracts.schema.json`, and the contract test pins the UI enums and checked schema. | error | resolved |
