---
id: graph-store-tech
title: "Graph Store — technical reference"
type: spec
status: draft
domain: breadcrumbs
audience: engineers, Breadcrumbs team
parity_of: ./components.md
registry: ./components.md
source: References/Breadcrumbs-v2.pdf
---

# Breadcrumbs / Graph Store — Technical Reference

The SQLite graph store is the **single source of truth** (Breadcrumbs-v2, panel 3). Chat is
unstructured and not authoritative; the wiki is a generated read-only view. Everything
authoritative lives here.

Findings are nodes. Edges are typed ID-to-ID relationships. Ingested literature lives in the same
store and is linked to findings by edge — which is what lets duplication checking be
**internal-first**: one query covers prior internal work *and* already-ingested papers before any
external source is considered.

Component IDs must stay in the same order as `components.md` and `feature.json`.

## GRAPH — findings, edges, literature, provenance

### BC-GRAPH-001 — Findings node table
- **Behavior:** One row per finding, carrying the full provenance tuple the pitch promises —
  `{disease, hypothesis_text, signature, effect, n, status, author, timestamp, provenance}` — so a
  recalled finding can always answer *who found this, when, on what data, with what effect*.
- **Data:** `findings`. Status is a closed vocabulary: `confirmed | in-progress | abandoned | open`.
  `abandoned` is a first-class status, not a soft-delete: an abandoned attempt carries a `reason`,
  and it is the single most valuable row type in this product.
- **Source:** `schema/graph_schema.sql:14-33`.
- **Status:** gap — the table exists, but its CHECK constraint admits only
  `confirmed | in-progress | abandoned`. `open` — a hypothesis logged but not yet run — is missing.
- **REQ-001:** The status vocabulary is identical in the SQL CHECK constraint, in the write path, and
  in the MCP tool contracts.

### BC-GRAPH-002 — Typed finding edges
- **Behavior:** Relationships between findings, so recall can walk from a new question to related
  prior work instead of relying on text matching alone.
- **Data:** `finding_edges`, keyed `(from_id, to_id, relationship)`. Vocabulary:
  `duplicate_of | extends | related | contradicts`.
- **Source:** `schema/graph_schema.sql:36-42`.
- **Status:** gap — the built vocabulary is `extends | contradicts | related-to`. Breadcrumbs-v2
  specifies `duplicate_of | extends | related`. `duplicate_of` is absent entirely, and the
  duplication check needs it to record its verdict; `related-to` must be renamed to `related`.
  `contradicts` is retained as a deliberate superset — see `review-queue.md` row 1.
- **REQ-002:** An edge can be written with `duplicate_of`, and any pre-existing `related-to` edge
  reads back as `related`.

### BC-GRAPH-003 — External literature store
- **Behavior:** Ingested papers persist in the graph store rather than being re-fetched per query.
  This is what makes the internal-first ordering real — a cached paper is *internal* data by the
  time a duplication check runs — and it means a flaky network cannot break the demo.
- **Data:** `external_literature` — `{source, title, authors, year, url, doi, abstract, ingested_at}`,
  linked to findings through the edge table.
- **Source:** not-built.
- **REQ-003:** A finding can be linked to an ingested paper, and recall returns both.

### BC-GRAPH-004 — K Pro chat provenance
- **Behavior:** Raw K Pro sessions are ingested and stored locally, with each answer's visible
  `##`/`###` Markdown sections extracted as graph-ready categories. No chat text is sent to an
  external LLM during ingestion. A finding points back at the session it was drawn from. The
  human-readable `.md` transcript (`write_transcript`) shows each turn's own `seq` and, when K Pro
  supplied one, its `created_at` timestamp, plus the session's `researcher` if one was named at
  ingest time. K Pro's payload never carries a person's identity (only a `role` of user/assistant),
  so `researcher` is supplied by the caller (`ingest_chat.py --author`, or the `KPRO_RESEARCHER` env
  var) — never scraped or guessed. A re-ingest that omits it keeps whatever was already stored
  rather than blanking it.
- **Data:** `chat_sessions` (including `researcher`), `chat_messages`, `chat_message_sections`,
  `ingestion_errors`. Parse failures are recorded, never fabricated into placeholder turns.
- **Source:** `schema/graph_schema.sql:46-89`; `ingestion/store.py` (`upsert_session`,
  `write_transcript`); `ingestion/ingest_chat.py`.
- **Status:** built-at-parity.
- **REQ-004:** The ingestion suite passes.

### BC-GRAPH-005 — Reviewed-write path (the human gate)
- **Behavior:** Findings do not land in the graph because a model said so. A reviewed JSON payload is
  validated and upserted: unknown category rejected, invalid status rejected, `abandoned` without a
  `reason` rejected, non-abandoned *with* a reason rejected, unknown source session rejected, entity
  tags normalized (`LKB1` → `STK11`). This validation **is** the human-confirm gate drawn in panel 2
  of the architecture diagram.
- **Data:** `findings`, `finding_edges`, `topic_categories`.
- **Source:** `ingestion/write_findings.py:31-75`; controlled category registry at
  `schema/graph_schema.sql:6-12`.
- **Status:** built-at-parity — with the caveat that its vocabulary must move in lockstep with the
  migration below.
- **REQ-005:** Writing an abandoned finding with no reason is rejected.

### BC-GRAPH-006 — Schema migration
- **Behavior:** Bring an existing database up to the Breadcrumbs-v2 vocabulary without losing data.
- **Data:** rebuilds `findings` and `finding_edges`; creates `external_literature`.
- **Source:** not-built.
- **Why this is not a one-line edit:** `ingestion/store.py:26` runs `executescript(graph_schema.sql)`
  on *every* connect, and every statement is `CREATE TABLE IF NOT EXISTS`. **Editing the CHECK
  constraints in `graph_schema.sql` therefore has no effect on the already-committed
  `ingestion/breadcrumbs.db`** — the one database that matters. SQLite cannot `ALTER` a CHECK constraint,
  so this needs a table rebuild:
  `PRAGMA foreign_keys = OFF` (outside the transaction — `finding_edges` declares
  `ON DELETE CASCADE` onto `findings`, so dropping the old table with foreign keys still on would
  cascade-delete every edge) → `BEGIN` → create the new table with the new CHECK → `INSERT … SELECT`
  with an explicit column list → `DROP` → `RENAME` → recreate the indexes → `PRAGMA foreign_key_check`
  → `COMMIT` → `PRAGMA foreign_keys = ON`.
  Decide whether to migrate by **reading the live DDL out of `sqlite_master`**, not by stamping
  `PRAGMA user_version`: a `user_version` set inside `graph_schema.sql` would be applied by
  `executescript` *before* the migration ever inspected it, marking old databases as already done.
- **Status:** not-built.
- **REQ-006:** The migration is idempotent — it runs twice with the same result — and row counts in
  `breadcrumbs.db` are unchanged afterwards.

### BC-GRAPH-007 — Dataset catalog
- **Behavior:** Records what a K Pro-hosted dataset actually has — its tables, and each column's
  declared possible values, data type, and completeness %, as shown at
  `https://k.owkin.com/explore-data/patient-data/<DATASET>`. This is data-availability provenance,
  distinct from a finding: it lets a finding's free-text `provenance` field, and a new hypothesis,
  be checked against real data availability instead of trusted as prose.
- **Data:** `datasets`, `dataset_columns`.
- **Source:** `schema/graph_schema.sql` (dataset catalog tables); `ingestion/store.py`
  (`parse_dataset_overview`, `parse_available_tables`, `parse_dataset_columns`, `upsert_dataset`,
  `upsert_dataset_columns`); `ingestion/ingest_dataset_catalog.py`.
- **Status:** gap — the `overview`/`table` file-recovery path is built and tested against a real
  captured MOSAIC Window page (`tests/test_dataset_catalog.py`). The `scrape` subcommand's live
  Playwright DOM walk has **not been run against the authenticated production page** and its
  selectors (`find_column_grid_text`'s ancestor walk from the "Column Name" header) are unverified
  — see `review-queue.md`.
- **REQ-008:** `parse_dataset_overview`/`parse_available_tables`/`parse_dataset_columns` round-trip
  a real captured K Pro Explore Data page's text into `datasets`/`dataset_columns` rows, and
  re-ingesting one table's grid replaces only that table's columns.

### BC-GRAPH-008 — Approved interaction knowledge
- **Behavior:** Stores durable decisions, constraints, exceptions, abandoned approaches, and belief
  revisions extracted from researcher-agent interactions. A row exists only after a named human
  approves it. Every row contains an exact quote, a deferred foreign key to its source message, and
  that message's SHA256 digest so re-ingest remains compatible without hiding source drift. The exact
  prior/posterior belief samples, approved elicitation model/run ID, and versioned scoring method,
  deterministic information-theoretic metrics, a structured before/after action delta, approved
  lexical aliases, and typed applicability conditions (`field`, optional approved field aliases,
  comparison operator, value, optional unit). SQLite FTS5 indexes the approved retrieval fields and
  model-versioned dense vectors are stored with their content hashes in `knowledge_embeddings`.
  Both are derived indexes, never authorities separate from `knowledge_items`. Corrections are append-only patches linked through
  `supersedes_id`; prior rows remain auditable and each row has at most one successor, so active
  organizational memory is a sequence rather than an ambiguous branch.
- **Data:** `knowledge_items`, `knowledge_fts`, and `knowledge_embeddings`, with kind vocabulary
  `decision | constraint | exception | abandoned | belief_revision`.
- **Source:** `schema/graph_schema.sql`; `src/breadcrumbs/store.py`.
- **Status:** built-at-parity.
- **REQ-009:** An approved item round-trips with source provenance, aliases, typed conditions, scoring inputs, and a model-versioned dense vector intact; an
  unapproved or misquoted item is rejected without writing a row. Re-ingesting the source session
  may replace the same message ID transactionally but may not silently remove an approved source;
  a same-ID content edit reads back with `source_drifted: true`, and the derived FTS5 and embedding rows remain synchronized with the authoritative patch.

### BC-GRAPH-009 — People and contribution edges
- **Behavior:** Normalizes exact person names with Unicode NFKC, whitespace collapse, and case-folding
  into stable `P-...` IDs. Automatically discovered names are explicitly `provisional`; no fuzzy
  identity merge is guessed. `person_contributions` records whether a person authored a finding,
  authored approved interaction knowledge, or reviewed a knowledge patch, together with its source
  session. The links are derived from authoritative artifact provenance and are backfilled on
  connection so existing stores gain the expertise view without rewriting findings or knowledge.
- **Data:** `people` and `person_contributions`; contribution vocabulary
  `finding_author | knowledge_author | knowledge_reviewer`.
- **Source:** `schema/graph_schema.sql`; `src/breadcrumbs/people.py`;
  `src/breadcrumbs/store.py`.
- **Status:** built-at-parity.
- **REQ-010:** Case/whitespace variants resolve to one stable provisional person; existing and new
  findings/knowledge produce idempotent role-labelled contribution edges; every edge names its
  artifact and source session; and no reviewer-only edge is mislabeled as authorship.
