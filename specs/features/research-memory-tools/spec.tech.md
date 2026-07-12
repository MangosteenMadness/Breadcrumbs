---
id: research-memory-tools-tech
title: "Research Memory Tools — technical reference"
type: spec
status: draft
domain: breadcrumbs
audience: engineers, Breadcrumbs team
parity_of: ./components.md
registry: ./components.md
source: References/Breadcrumbs-v2.pdf
---

# Breadcrumbs / Research Memory Tools — Technical Reference

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

### BC-MCP-001 — Server bootstrap and tool registration
- **Behavior:** A Python MCP server exposing the six built tools below, connected to Claude Desktop as the
  host (the host stands in for K Pro in the demo). Opens the graph store read-write and surfaces
  errors rather than failing silently mid-demo.
- **Data:** reads/writes `ingestion/breadcrumbs.db` through the existing store module.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-001:** The server starts, registers all six tools, and Claude Desktop lists them.

### BC-MCP-002 — Tool contracts
- **Behavior:** Typed input/output models for every tool, exported to a checked-in JSON Schema. This
  is the boundary the host codes against, and it is where the status and edge vocabularies are
  pinned so they cannot drift from the SQL CHECK constraints.
- **Data:** the shared vocabulary — status `confirmed | in-progress | abandoned | open`, edge
  `duplicate_of | extends | related | contradicts`, duplication verdict `matched | possible | no-match`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-002:** The vocabularies in the tool contracts equal those in the live database DDL.

### BC-MCP-003 — `check_duplication`, stage 1: internal retrieval
- **Behavior:** Fast retrieval over the graph store — prior findings *and* already-ingested
  literature — to produce candidate matches for a new hypothesis. This stage runs first, always, and
  it is what "internal-first" means operationally: **if an internal match is found, no external
  source is queried at all.**
- **Data:** `findings`, `finding_edges`, `external_literature`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-003:** When stage 1 returns an internal match, the external literature client is never
  called. This is asserted directly, not assumed.

### BC-MCP-004 — `check_duplication`, stage 2: semantic match and verdict
- **Behavior:** Candidates from stage 1 are passed to Claude with a single question — *are these two
  hypotheses the same question?* — yielding a verdict of `matched`, `possible`, or `no-match`. No
  embedding infrastructure. A `matched` verdict may record a `duplicate_of` edge.
- **Data:** writes `finding_edges` on a confirmed duplicate.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-004:** Two phrasings of the same hypothesis (LUAD cytotoxic infiltration vs. lung-adeno
  CD8 T-cell infiltration) return `matched`; an unrelated hypothesis returns `no-match`.

### BC-MCP-005 — Abandoned-result surfacing
- **Behavior:** Abandoned prior work is a **first-class result type**, not a filtered-out failure.
  When recall or duplication surfaces an abandoned finding, it is returned with its `reason`
  attached and is never ranked below confirmed work merely for being abandoned. This single
  component is the difference between Breadcrumbs and every published-record tool on the market.
- **Data:** `findings` where `status = 'abandoned'`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-005:** A query related to F-093 returns it, flagged abandoned, with its reason text.

### BC-MCP-006 — Calibrated-language layer
- **Behavior:** Every user-facing string the server emits is calibrated. It reports *"no prior work
  found in [sources]"* and names the sources actually searched. The word "novel" is **hard-blocked**
  in tool output.
- **Data:** none.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-006:** No tool output contains the word "novel". Enforced by an executable check, because a
  guideline nobody tests is a guideline nobody keeps.

### BC-MCP-007 — `write_finding`
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

### BC-MCP-008 — `recall_findings`
- **Behavior:** Given a new question, return semantically-related prior findings and their
  connections, retrievable by topic, entity, or context. This is the read path that makes Session 2
  of the demo work.
- **Data:** `findings`, `finding_edges`, `external_literature`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-008:** A LUSC question about a signature previously tested in LUAD recalls the LUAD finding.

### BC-LIT-001 — External literature check
- **Behavior:** Europe PMC REST (no API key) queried **only after** the internal check, with results
  normalized and cached into the graph store so a repeat query costs nothing and the demo cannot be
  broken by venue wifi. A cached fallback serves the demo path offline.
- **Data:** writes `external_literature`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-009:** With the network disabled, a previously-cached literature query still returns results.

### BC-MCP-009 — `render_wiki`
- **Behavior:** Generate a Markdown wiki page from the graph. The wiki is a **generated,
  one-directional, read-only view** — it is never edited back into the store, and it carries a
  banner saying so. Anything authoritative lives in the graph.
- **Data:** reads `findings`, `finding_edges`, `external_literature`.
- **Source:** not-built.
- **Status:** not-built.
- **REQ-010:** The rendered page cites the findings it was generated from and is reproducible from
  the graph alone.

### BC-MCP-010 — `score_surprise`
- **Behavior:** Quantifies how much a conversation changed a candidate belief without asking a
  model for an opaque importance score. The host supplies repeated categorical belief judgments
  from before and after the cited interaction. The tool maps the fixed five-label scale to
  `[0, .25, .5, .75, 1]`, fits Beta distributions with documented pseudo-counts, and returns prior
  and posterior means, signed/absolute belief shift, `KL(posterior || prior)` in bits, entropy
  change, and optional Jensen-Shannon divergence for sampled actions. Given the same samples the
  output is identical. Prior/posterior sample counts must match so Monte Carlo replicate count
  cannot masquerade as evidence or certainty.
- **Data:** no persistence; only structured samples enter the deterministic calculator.
- **Source:** `src/breadcrumbs/surprise.py`; `src/breadcrumbs/server.py`.
- **Status:** built-at-parity.
- **REQ-012:** Fixed fixtures produce stable belief-shift, Bayesian-surprise, entropy, and action
  divergence values without third-party numerical dependencies.

### BC-MCP-011 — `write_knowledge`
- **Behavior:** Persists at most one already-reviewed candidate per call. `approved_by` is mandatory;
  the evidence quote must occur verbatim in the referenced chat message; the source session is
  derived from that message; and all surprise fields are recomputed from the supplied samples
  rather than trusted from the host. `abandoned` requires a reason. A revision may point to the
  approved item it supersedes, preserving an append-only patch history.
- **Data:** writes `knowledge_items` only after validation.
- **Source:** `src/breadcrumbs/store.py`; `src/breadcrumbs/server.py`.
- **Status:** built-at-parity.
- **REQ-013:** Missing approval, an unknown source message, a non-verbatim quote, and an abandoned
  item without a reason are each rejected without changing the database. The write also requires a
  logged elicitation run from a model permitted by `.spec/repo.json`.

### BC-MCP-012 — `recall_knowledge`
- **Behavior:** Retrieves only approved internal knowledge with a local, constraint-aware hybrid
  ranker. SQLite FTS5/BM25, deterministic field-weighted token coverage, and dense embeddings from
  the pinned `BAAI/bge-small-en-v1.5` FastEmbed model generate candidates from
  the proposition, rationale, approved aliases, typed conditions, scope, action, reason, and source
  quote. Structured scope is an applicability feature by default, not a model-invented hard gate:
  exact facet matches and satisfied numeric conditions boost a patch; approved condition-field
  aliases map host wording such as `pH` to a canonical field such as `buffer_pH`; contradictions lower it; and
  unknown keys do not remove it. `strict_scope=true` preserves exact-subset filtering for a caller
  that explicitly needs it. Each result reports the BM25/token components and compatible,
  incompatible, and unknown scope fields. Bayesian surprise remains only a tie-breaker; it is not a
  relevance or importance score. BM25 and exact-cosine dense rankings are fused with reciprocal
  rank fusion; exact cosine is deliberate at this store size so an approximate index cannot trade
  away recall. Dense-only candidates must meet the pinned `0.55` cosine floor. Query and passage
  embeddings are computed locally in the organization's runtime; only public model weights are
  downloaded. Every result reports the model, dense similarity/rank, BM25 rank, field coverage,
  fusion score, and scope compatibility. Superseded rows are excluded by default but remain available for
  audit. A match to historical wording resolves forward to the active patch head and reports
  `matched_via_history`, so corrections do not erase old retrieval aliases.
- **Data:** reads `knowledge_items`, `knowledge_fts`, and `knowledge_embeddings`; returns source identifiers, scoring inputs and metrics,
  action deltas, and patch links.
- **Source:** `src/breadcrumbs/store.py`; `src/breadcrumbs/server.py`.
- **Status:** built-at-parity.
- **REQ-014:** A query with an inferred unknown scope key and a numeric value satisfying a stored
  typed condition returns the relevant active approved item; an approved alias is searchable;
  dense-only paraphrases are candidates; the BM25 and dense ranks are fused and exposed;
  `strict_scope=true` retains exact-subset behavior; superseded items remain hidden by default and historical wording resolves to the active patch.

### BC-MCP-013 — `find_experts`
- **Behavior:** Answers expertise questions by retrieving topic-relevant approved knowledge and
  reviewed findings, resolving their author/reviewer contribution edges to canonical provisional
  people, and aggregating demonstrated evidence. Authorship and finding ownership count as primary
  evidence; review is supporting evidence and cannot qualify a person by itself. Repeated evidence
  from one source session is capped so verbosity cannot dominate, abandoned attempts are not
  penalized, and every ranked person includes the concrete artifacts that support the result. The
  deterministic `expertise_evidence_v1` score is a ranking score, never a probability. Confidence is
  `low | moderate | high` based on independent source-session and primary-evidence counts. Output
  says "strongest demonstrated experience among the sources searched," never that someone is the
  organization's definitive expert.
- **Data:** reads `people`, `person_contributions`, `knowledge_items`, `knowledge_embeddings`, and
  `findings`; returns canonical/provisional identity status, role-labelled evidence, distinct
  session counts, score components, confidence, and searched sources.
- **Source:** `src/breadcrumbs/store.py`; `src/breadcrumbs/server.py`.
- **Status:** built-at-parity.
- **REQ-015:** Independent relevant authored contributions rank above repeated same-session work;
  review-only people are excluded; abandoned work remains evidence; names differing only in case or
  whitespace resolve to one provisional person; and empty results name the stores searched without
  claiming a definitive absence of expertise.
