# Breadcrumbs K Pro ingestion

This package stores real K Pro chat prompts and assistant answers locally in
`ingestion/breadcrumbs.db`. It does not send chat text to an external LLM.
Each successfully ingested chat also gets a readable Markdown view in
`ingestion/transcripts/<chat-id>.md`.

## What this populates

Each ingested chat writes to (schema: `schema/graph_schema.sql`):

- `chat_sessions` — one row per chat, with the raw captured JSON payload for provenance and
  K Pro's own `updated_at` stamp (used to skip unchanged chats on the next run).
- `chat_messages` — ordered, role-labelled turns (`user` / `assistant`).
- `chat_message_sections` — K Pro's visible `##`/`###` Markdown sections within an answer,
  pulled out as graph-ready categories without any external LLM call. Sections nest: a `###`
  heading (e.g. a per-indication breakdown) links to the `##` above it via `parent_id`, and
  `path` carries the readable `Parent > Child` label — so topics form a tree, not a flat list.
- `ingestion_errors` — when a chat's page/API shape can't be parsed, the failure is recorded
  here. No placeholder or fabricated turns are ever written.

Requires Python 3.11+. `requirements.txt` is deliberately small (Playwright + python-dotenv
only) — the ingestion path has no LLM dependency; findings are written from **already-reviewed**
JSON via `write_findings.py` below.

## Setup

```powershell
python -m pip install -r ingestion/requirements.txt
python -m playwright install chromium
python ingestion/capture_session.py
```

Complete any Owkin SSO interaction in the browser. The resulting authenticated state
is saved at `ingestion/.secrets/kpro_storage_state.json`; it is intentionally ignored
by Git.

## Ingest

```powershell
# All chats visible to the signed-in user (reads the K Pro chat list from /chat-history;
# --limit N caps how many, default 50)
python ingestion/ingest_chat.py --recent

# One specific K Pro chat
python ingestion/ingest_chat.py https://k.owkin.com/chat/54ecc674-7485-4a18-ac95-a3be5f233ec7

# Recovery from a manually saved JSON, HAR, or structured text capture
python ingestion/ingest_chat.py --from-file capture.har
```

`--recent` walks every page of the K Pro chat list, so all of the signed-in user's chats are
ingested, not just one. Runs are **incremental**: a chat already stored at the same K Pro
revision (its `updated_at`) is skipped, so re-running `--recent` resumes where the last run
stopped and picks up new or changed chats. Pass `--force` to re-ingest everything regardless.
Each chat is stored under its own UUID, so chats never overwrite one another; re-ingesting the
same chat refreshes just that chat's turns.

Pass `--author "Your Name"` (or set `KPRO_RESEARCHER` in `.env`) to record who ran the ingest.
K Pro's own payload never says who a chat's human side is — only a `role` of user/assistant — so
this has to come from you. It's stored on the session and shown at the top of its `.md`
transcript; omitting `--author` on a later re-ingest keeps whatever was already recorded rather
than clearing it. Each turn's `.md` heading also shows its `seq` and, when K Pro supplied one,
its timestamp — e.g. `## Researcher (turn 0 · 2026-01-01T00:00:00Z)`.

To ingest a **colleague's** chats, run `capture_session.py` and have them complete SSO in the
browser window, then run `ingest_chat.py --recent` — it ingests whichever account's session is
currently saved in `.secrets/`.

Messages are read directly from K Pro's authenticated API (`/api/chats/<id>/messages`), with
rendered-page scraping as a fallback. This reaches chats the web UI declines to render (a chat
created by a colleague shows only a "Created by" placeholder in the browser but still serves its
messages over the API). If K Pro changes its API/UI shape, failed imports are recorded in
`ingestion_errors`; no placeholder messages are written.

## Inspect local data

```powershell
sqlite3 ingestion/breadcrumbs.db "SELECT session_id, seq, role, substr(content,1,80) FROM chat_messages ORDER BY session_id, seq;"
```

Use this local raw-chat store as the source for a later graph/entity extraction step.

## Export sessions for the UI

`export_sessions.py` writes the ingested chats — including their captured Plotly figures and
datatables — to `ui/lib/sessions.json`, the static file the Breadcrumbs UI bundles and replays.
K Pro hands us each plot as a raw Plotly figure object during ingest; rendering that stored
object with Plotly.js in the browser redraws the exact chart K Pro drew, with no auth and no
live network call to stall mid-demo.

```powershell
python ingestion/export_sessions.py
```

Each session becomes an ordered list of turns, each an ordered list of blocks (answer text, a
plot, a datatable, or an `omitted` placeholder for a heavy plot that `slim_raw_payload` stripped
at ingest to keep the committed DB small). Block order is preserved verbatim, so charts and
tables interleave with the answer text exactly as K Pro laid them out. The two distinct Plotly
templates K Pro reuses across every figure are hoisted into a shared table and referenced by
index, which keeps the exported JSON small. Re-run this after any `ingest_chat.py` run so the UI
reflects the latest chats.

## Write reviewed graph findings

`write_findings.py` accepts a reviewed JSON object with a list of findings and a
list of typed edges. One source session may produce any number of findings.

```powershell
python ingestion/write_findings.py schema/example_finding_extraction.json
```

Replace the example's placeholder `source_session_id` with an ingested session ID.
Categories must already be present in the controlled `topic_categories` registry;
entities are normalized to uppercase tags (`LKB1` becomes `STK11`).

## Ingest a dataset's table/column catalog

`ingest_dataset_catalog.py` is a separate ingestion path from the chat pipeline above: instead of
chat provenance, it records what a K Pro-hosted dataset (e.g. MOSAIC Window at
`k.owkin.com/explore-data/patient-data/MOSAIC_WINDOW`) actually has — its tables, and each column's
declared possible values, data type, and completeness %. It writes to `datasets` and
`dataset_columns` (schema: `schema/graph_schema.sql`).

Today the reliable path is file recovery — copy the relevant panel's text straight out of the
browser (or a devtools HAR) and feed it in:

```powershell
# The dataset's overview panel (Name/Source/Total patients/.../Description)
python ingestion/ingest_dataset_catalog.py overview `
  --from-file mosaic_window_overview.txt `
  --url https://k.owkin.com/explore-data/patient-data/MOSAIC_WINDOW

# One table's column grid (Column Name/Possible values/Data Type/Completeness)
python ingestion/ingest_dataset_catalog.py table `
  --from-file mosaic_window_clinical_data_table.txt `
  --dataset-id mosaic_window --table clinical_data_table
```

Repeat the `table` command once per table shown in the dataset's "Available tables" list.
Re-ingesting a table replaces only that table's columns; other tables in the same dataset are
untouched.

There is also a best-effort live scrape:

```powershell
python ingestion/ingest_dataset_catalog.py scrape --url https://k.owkin.com/explore-data/patient-data/MOSAIC_WINDOW
```

**This has not been verified against the live authenticated page** — its DOM-ancestor walk
(`find_column_grid_text` in `ingest_dataset_catalog.py`) is a best-effort guess at how K Pro lays
out the column grid, not a confirmed selector. Run it with `--headed` first and check the output;
see `specs/features/graph-store/review-queue.md` row 4 for the open question of whether Explore
Data has its own JSON API worth capturing instead (as `/api/chats` is for chat — see `api_json()`
in `ingest_chat.py`), which would be far more robust than any DOM walk.

## Tests

```powershell
python -m pytest tests/test_ingest_chat.py tests/test_dataset_catalog.py
```

Run this before pushing changes to either parser (`ingest_chat.py`'s message/section extraction and
`store.py`'s dataset-catalog parsers are the parts most likely to break if K Pro's page/response
shape changes).
