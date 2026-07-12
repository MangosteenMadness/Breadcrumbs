# Breadcrumbs / Research Memory Tools — Component Registry

> The ordered list of components. The same IDs, in the same order, must appear in `spec.tech.md`
> and `feature.json.component_ids`.
> Status vocabulary: built-at-parity | gap | not-built | descoped | unverified | planned | in_progress

## MCP — the server and its tools

| ID | Component | Status |
|----|-----------|--------|
| BC-MCP-001 | Server bootstrap and tool registration (Claude Desktop as host) | not-built |
| BC-MCP-002 | Tool contracts — typed I/O, pinned status/edge/verdict vocabularies | not-built |
| BC-MCP-003 | `check_duplication` stage 1 — internal retrieval, before any external source | not-built |
| BC-MCP-004 | `check_duplication` stage 2 — Claude semantic match → matched / possible / no-match | not-built |
| BC-MCP-005 | Abandoned-result surfacing as a first-class result type — **the differentiator** | not-built |
| BC-MCP-006 | Calibrated-language layer — never "novel" | not-built |
| BC-MCP-007 | `write_finding` — append-only, provenance-tagged, human-gated | not-built |
| BC-MCP-008 | `recall_findings` — by topic, entity, or context | not-built |
| BC-LIT-001 | External literature check — Europe PMC, cached, internal-first | not-built |
| BC-MCP-009 | `render_wiki` — generated, read-only Markdown view | not-built |
| BC-MCP-010 | `score_surprise` — reproducible Bayesian belief shift in bits | built-at-parity |
| BC-MCP-011 | `write_knowledge` — source-verified human approval gate | built-at-parity |
| BC-MCP-012 | `recall_knowledge` — BM25+dense rank fusion with constraint-aware active-patch recall | built-at-parity |
| BC-MCP-013 | `find_experts` — calibrated evidence aggregation over canonical people | built-at-parity |
