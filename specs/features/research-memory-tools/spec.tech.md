---
id: research-memory-tools-tech
title: "Research Memory Tools — technical reference"
type: spec
status: draft
domain: breadcrumbs
audience: engineers, Breadcrumbs team
parity_of: ./components.md
registry: ./components.md
source: ui/lib/data.ts and ui/lib/duplication.ts (demo contract); References/Breadcrumbs-v2.pdf (background)
---

# Breadcrumbs / Research Memory Tools — Technical Reference

**The deliverable *is* an MCP server.** This feature is the moat. Everything else in the repo exists
to feed it or to show it off.

Two rules from Breadcrumbs-v2 govern every component below, and they are the whole product:

1. **Internal research memory only.** A duplication check queries the org's own graph — including
   *abandoned* attempts — and does not call an external literature source. The host agent already
   handles general literature research; Breadcrumbs supplies the organizational evidence it lacks.
2. **Calibrated language, always.** The system says *"no prior work found in [sources]"*. It never
   says *"this is novel"*. It cannot know that, and claiming it is the exact failure mode that makes
   researchers stop trusting the tool.

Findings are extracted **in the host** (K Pro / Claude Desktop) before these tools are called — the
server receives structured arguments, not raw chat. Writes pass a human confirm gate.

Component IDs must stay in the same order as `components.md` and `feature.json`.

## MCP — the server and its tools

### BC-MCP-001 — Server bootstrap and tool registration
- **Behavior:** A Python MCP server exposing the five tools below, connected to Claude Desktop as the
  host (the host stands in for K Pro in the demo). Opens the graph store read-write and surfaces
  errors rather than failing silently mid-demo.
- **Data:** reads/writes `ingestion/breadcrumbs.db` through the existing store module.
- **Source:** `src/breadcrumbs/server.py`.
- **Status:** built-at-parity.
- **REQ-001:** The server starts, registers all five tools, and Claude Desktop lists them.

### BC-MCP-002 — Tool contracts
- **Behavior:** Typed input/output models for every tool, exported to a checked-in JSON Schema. This
  is the boundary the host codes against, and it is where the status and edge vocabularies are
  pinned so they cannot drift from the SQL CHECK constraints.
- **Data:** the shared vocabulary — status `confirmed | in-progress | abandoned | open`, edge
  `duplicate_of | extends | related | contradicts`, UI duplication verdict `match | open`.
- **Source:** `src/breadcrumbs/contracts.py`; `schema/mcp_contracts.schema.json`; `ui/lib/data.ts`.
- **Status:** built-at-parity.
- **REQ-002:** The vocabularies in the tool contracts equal those in the live database DDL.

### BC-MCP-003 — `check_duplication`, stage 1: internal retrieval
- **Behavior:** Fast retrieval over the internal findings graph to produce candidate matches for a
  new hypothesis. The tool has no external literature dependency or fallback.
- **Data:** `findings`, `finding_edges`.
- **Source:** `src/breadcrumbs/store.py:check_duplication`.
- **Status:** built-at-parity.
- **REQ-003:** Duplication output is derived only from the internal graph and carries no external
  literature result field.

### BC-MCP-004 — `check_duplication`, stage 2: local concept match and UI verdict
- **Behavior:** The UI demo contract is authoritative: normalized disease/gene aliases and local
  concept overlap route a question to the strongest internal marker, then append its graph neighbors.
  The boundary returns `match` or `open` exactly as `ui/lib/data.ts` defines. Hypothesis text does not
  leave the local process; an external model is not required for the demo path.
- **Data:** reads `findings` and `finding_edges`.
- **Source:** `src/breadcrumbs/store.py`; `ui/lib/duplication.ts`.
- **Status:** built-at-parity.
- **REQ-004:** Two phrasings of the same hypothesis (LUAD cytotoxic infiltration vs. lung-adeno
  CD8 T-cell infiltration) return `match`; an unrelated hypothesis returns `open`.

### BC-MCP-005 — Abandoned-result surfacing
- **Behavior:** Abandoned prior work is a **first-class result type**, not a filtered-out failure.
  When recall or duplication surfaces an abandoned finding, it is returned with its `reason`
  attached and is never ranked below confirmed work merely for being abandoned. This single
  component is the difference between Breadcrumbs and every published-record tool on the market.
- **Data:** `findings` where `status = 'abandoned'`.
- **Source:** `src/breadcrumbs/store.py:_ui_matches`.
- **Status:** built-at-parity.
- **REQ-005:** A query related to F-093 returns it, flagged abandoned, with its reason text.

### BC-MCP-006 — Calibrated-language layer
- **Behavior:** Every user-facing string the server emits is calibrated. It reports *"no prior work
  found in [sources]"* and names the sources actually searched. The word "novel" is **hard-blocked**
  in tool output.
- **Data:** none.
- **Source:** `src/breadcrumbs/store.py:_duplication_markdown`; `tests/test_mcp_server.py`.
- **Status:** built-at-parity.
- **REQ-006:** No tool output contains the word "novel". Enforced by an executable check, because a
  guideline nobody tests is a guideline nobody keeps.

### BC-MCP-007 — `write_finding`
- **Behavior:** Create or update a finding plus its edges, append-only and provenance-tagged (who,
  when, what data, what effect). Passes the same validation gate the reviewed-write path already
  enforces — abandoned requires a reason, category must be registered, source session must exist.
- **Data:** `findings`, `finding_edges`.
- **Source:** `src/breadcrumbs/server.py:write_finding`; `src/breadcrumbs/store.py:write`, which calls
  `ingestion/write_findings.py:write_payload` rather than reimplementing validation.
- **Status:** built-at-parity.
- **REQ-007:** A finding written through the tool is subject to the identical validation as one
  written through the reviewed-write path.

### BC-MCP-008 — `recall_findings`
- **Behavior:** Given a new question, return semantically-related prior findings and their
  connections, retrievable by topic, entity, or context. This is the read path that makes Session 2
  of the demo work.
- **Data:** `findings`, `finding_edges`.
- **Source:** `src/breadcrumbs/store.py:recall_findings`.
- **Status:** built-at-parity.
- **REQ-008:** A LUSC question about a signature previously tested in LUAD recalls the LUAD finding.

### BC-LIT-001 — Host-managed literature research
- **Behavior:** General literature research remains with the host agent. The Breadcrumbs MCP does
  not call, cache, or claim results from an external literature service.
- **Data:** none.
- **Source:** deliberately absent from `src/breadcrumbs`.
- **Status:** descoped.
- **REQ-009:** The MCP has no external literature client, cache table, or literature result field.

### BC-MCP-009 — `render_wiki`
- **Behavior:** Generate a Markdown wiki page from the graph. The wiki is a **generated,
  one-directional, read-only view** — it is never edited back into the store, and it carries a
  banner saying so. Anything authoritative lives in the graph.
- **Data:** reads `findings`, `finding_edges`.
- **Source:** `src/breadcrumbs/store.py:render_wiki`.
- **Status:** built-at-parity.
- **REQ-010:** The rendered page cites the findings it was generated from and is reproducible from
  the graph alone.
