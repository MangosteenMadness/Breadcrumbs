---
id: research-memory-tools-tech
title: "Research Memory Tools — technical reference"
type: spec
status: draft
domain: cairn
audience: engineers, Cairn team
parity_of: ./components.md
registry: ./components.md
source: References/Breadcrumbs-v2.pdf
---

# Cairn / Research Memory Tools — Technical Reference

**The deliverable *is* an MCP server.** This feature is the moat. Everything else in the repo exists
to feed it or to show it off.

Two rules from Breadcrumbs-v2 govern every component below, and they are the whole product:

1. **Internal-first.** A duplication check queries the org's own graph — including *abandoned*
   attempts and already-ingested literature — before it considers any external source. Owl and the
   published-record knowledge graphs structurally cannot do this, because failures never reach the
   published record.
2. **Calibrated language, always.** The system says *"no prior work found in [sources]"*. It never
   says *"this is novel"*. It cannot know that, and claiming it is the exact failure mode that makes
   researchers stop trusting the tool.

Findings are extracted **in the host** (K Pro / Claude Desktop) before these tools are called — the
server receives structured arguments, not raw chat. Writes pass a human confirm gate.

Component IDs must stay in the same order as `components.md` and `feature.json`.

## MCP — the server and its tools

### CRN-MCP-001 — Server bootstrap and tool registration
- **Behavior:** A Python MCP server exposing the five tools below, connected to Claude Desktop as the
  host (the host stands in for K Pro in the demo). Opens the graph store read-write and surfaces
  errors rather than failing silently mid-demo.
- **Data:** reads/writes `ingestion/cairn.db` through the existing store module.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-001:** The server starts, registers all five tools, and Claude Desktop lists them.

### CRN-MCP-002 — Tool contracts
- **Behavior:** Typed input/output models for every tool, exported to a checked-in JSON Schema. This
  is the boundary the host codes against, and it is where the status and edge vocabularies are
  pinned so they cannot drift from the SQL CHECK constraints.
- **Data:** the shared vocabulary — status `confirmed | in-progress | abandoned | open`, edge
  `duplicate_of | extends | related | contradicts`, duplication verdict `matched | possible | no-match`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-002:** The vocabularies in the tool contracts equal those in the live database DDL.

### CRN-MCP-003 — `check_duplication`, stage 1: internal retrieval
- **Behavior:** Fast retrieval over the graph store — prior findings *and* already-ingested
  literature — to produce candidate matches for a new hypothesis. This stage runs first, always, and
  it is what "internal-first" means operationally: **if an internal match is found, no external
  source is queried at all.**
- **Data:** `findings`, `finding_edges`, `external_literature`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-003:** When stage 1 returns an internal match, the external literature client is never
  called. This is asserted directly, not assumed.

### CRN-MCP-004 — `check_duplication`, stage 2: semantic match and verdict
- **Behavior:** Candidates from stage 1 are passed to Claude with a single question — *are these two
  hypotheses the same question?* — yielding a verdict of `matched`, `possible`, or `no-match`. No
  embedding infrastructure. A `matched` verdict may record a `duplicate_of` edge.
- **Data:** writes `finding_edges` on a confirmed duplicate.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-004:** Two phrasings of the same hypothesis (LUAD cytotoxic infiltration vs. lung-adeno
  CD8 T-cell infiltration) return `matched`; an unrelated hypothesis returns `no-match`.

### CRN-MCP-005 — Abandoned-result surfacing
- **Behavior:** Abandoned prior work is a **first-class result type**, not a filtered-out failure.
  When recall or duplication surfaces an abandoned finding, it is returned with its `reason`
  attached and is never ranked below confirmed work merely for being abandoned. This single
  component is the difference between Cairn and every published-record tool on the market.
- **Data:** `findings` where `status = 'abandoned'`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-005:** A query related to F-093 returns it, flagged abandoned, with its reason text.

### CRN-MCP-006 — Calibrated-language layer
- **Behavior:** Every user-facing string the server emits is calibrated. It reports *"no prior work
  found in [sources]"* and names the sources actually searched. The word "novel" is **hard-blocked**
  in tool output.
- **Data:** none.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-006:** No tool output contains the word "novel". Enforced by an executable check, because a
  guideline nobody tests is a guideline nobody keeps.

### CRN-MCP-007 — `write_finding`
- **Behavior:** Create or update a finding plus its edges, append-only and provenance-tagged (who,
  when, what data, what effect). Passes the same validation gate the reviewed-write path already
  enforces — abandoned requires a reason, category must be registered, source session must exist.
- **Data:** `findings`, `finding_edges`.
- **Source:** not-built — but it must reuse the existing validation in
  `ingestion/write_findings.py:31-75` rather than reimplementing it, or the two write paths will
  drift and the human gate will only cover one of them.
- **Status:** not-built.
- **REQ-007:** A finding written through the tool is subject to the identical validation as one
  written through the reviewed-write path.

### CRN-MCP-008 — `recall_findings`
- **Behavior:** Given a new question, return semantically-related prior findings and their
  connections, retrievable by topic, entity, or context. This is the read path that makes Session 2
  of the demo work.
- **Data:** `findings`, `finding_edges`, `external_literature`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-008:** A LUSC question about a signature previously tested in LUAD recalls the LUAD finding.

### CRN-LIT-001 — External literature check
- **Behavior:** Europe PMC REST (no API key) queried **only after** the internal check, with results
  normalized and cached into the graph store so a repeat query costs nothing and the demo cannot be
  broken by venue wifi. A cached fallback serves the demo path offline.
- **Data:** writes `external_literature`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-009:** With the network disabled, a previously-cached literature query still returns results.

### CRN-MCP-009 — `render_wiki`
- **Behavior:** Generate a Markdown wiki page from the graph. The wiki is a **generated,
  one-directional, read-only view** — it is never edited back into the store, and it carries a
  banner saying so. Anything authoritative lives in the graph.
- **Data:** reads `findings`, `finding_edges`, `external_literature`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-010:** The rendered page cites the findings it was generated from and is reproducible from
  the graph alone.
