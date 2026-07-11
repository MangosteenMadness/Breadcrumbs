# Cairn K Pro ingestion

This package stores real K Pro chat prompts and assistant answers locally in
`ingestion/cairn.db`. It does not send chat text to an external LLM.
Each successfully ingested chat also gets a readable Markdown view in
`ingestion/transcripts/<chat-id>.md`.

## What this populates

Each ingested chat writes to (schema: `schema/graph_schema.sql`):

- `chat_sessions` — one row per chat, with the raw captured JSON payload for provenance.
- `chat_messages` — ordered, role-labelled turns (`user` / `assistant`).
- `chat_message_sections` — K Pro's visible `##`/`###` Markdown sections within an answer,
  pulled out as graph-ready categories without any external LLM call.
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
# Latest 50 chats visible to the signed-in user (walks the K Pro chat list; --limit N to change the cap)
python ingestion/ingest_chat.py --recent

# One specific K Pro chat
python ingestion/ingest_chat.py https://k.owkin.com/chat/54ecc674-7485-4a18-ac95-a3be5f233ec7

# Recovery from a manually saved JSON, HAR, or structured text capture
python ingestion/ingest_chat.py --from-file capture.har
```

The browser observes K Pro JSON responses after authentication and uses rendered
role-labelled messages only as a fallback. If K Pro changes its API/UI shape, failed
imports are recorded in `ingestion_errors`; no placeholder messages are written.

## Inspect local data

```powershell
sqlite3 ingestion/cairn.db "SELECT session_id, seq, role, substr(content,1,80) FROM chat_messages ORDER BY session_id, seq;"
```

Use this local raw-chat store as the source for a later graph/entity extraction step.

## Write reviewed graph findings

`write_findings.py` accepts a reviewed JSON object with a list of findings and a
list of typed edges. One source session may produce any number of findings.

```powershell
python ingestion/write_findings.py schema/example_finding_extraction.json
```

Replace the example's placeholder `source_session_id` with an ingested session ID.
Categories must already be present in the controlled `topic_categories` registry;
entities are normalized to uppercase tags (`LKB1` becomes `STK11`).

## Tests

```powershell
python -m pytest tests/test_ingest_chat.py
```

Run this before pushing changes to the parser (`ingest_chat.py`'s message/section extraction
is the part most likely to break if K Pro's response shape changes).
