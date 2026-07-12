# Review Queue — Research Memory Tools

> Unresolved risks, divergences, and findings raised during spec or build.
> An item here BLOCKS completion until resolved or explicitly accepted. Append-only; don't delete,
> mark resolved.

| # | Raised by | Finding | Severity | Status |
|---|-----------|---------|----------|--------|
| 1 | spec-author | **Data boundary.** `check_duplication` stage 2 sends researcher hypothesis text to the Claude API for semantic matching. The project owner confirmed on 2026-07-12 that the research data is public; authentication material remains secret. | error | resolved |
| 2 | spec-author | `write_finding` must reuse the validation in `ingestion/write_findings.py` rather than reimplementing it. Two independent write paths means the human gate covers only one of them, and the one it misses is the one the agent uses. | warn | open |
| 3 | spec-author | The MCP endpoint paths recorded in `feature.json.backend` are a fair mapping onto the layer schema's HTTP shape, but MCP is JSON-RPC — the real surface is `tools/call` over a single transport. Do not build literal REST routes from that block. | info | open |
| 4 | spec-author | **The `check_duplication` response shape is already defined in TypeScript.** `ui/lib/data.ts` ships `DuplicationResult` / `Match` / `Finding` / `Relationship`, and `ui/lib/duplication.ts` mocks the tool against them. BC-MCP-002 must adopt that shape rather than invent a second one — the UI is the demo surface, so if the Python contract disagrees, the demo breaks the moment `BREADCRUMBS_MCP_URL` is set. **Read `ui/lib/data.ts` before writing `mcp_server/contracts.py`.** | error | open |
| 5 | codex | **Dense retrieval boundary.** The project owner confirmed on 2026-07-12 that the research data is public. Dense retrieval may use the pinned public local model; the model ID, content hash, dimensions, and exact vector bytes remain recorded for reproducibility. Authentication material is never embedded. | error | resolved |
