# Cairn

An internal research-memory layer for Owkin's K Pro AI-scientist platform: before a researcher
runs a hypothesis, Cairn checks — internally first — whether someone in the org already
explored it (including abandoned attempts), then whether the published world has. Full pitch,
demo script, and role breakdown: [`References/Breadcrumbs.pdf`](References/Breadcrumbs.pdf).

## Repo map

- **`ingestion/`** — pulls real K Pro chat sessions (prompts + answers) into a local SQLite
  store. This is the source material the graph is built from. See
  [`ingestion/README.md`](ingestion/README.md) for full setup and usage.
- **`schema/`** — the SQLite schema (`graph_schema.sql`) for the raw chat store and the
  findings graph, plus a worked example of a reviewed finding-extraction file
  (`example_finding_extraction.json`).
- **`demo/`** — sample Session 1 / Session 2 conversation transcripts matching the pitch's
  demo script, for rehearsal or driving a thin chat UI.

## Get the chat ingestor running

`.env` already has the Owkin credentials the ingestor needs — nothing to configure beyond
installing dependencies.

```powershell
python -m pip install -r ingestion/requirements.txt
python -m playwright install chromium
python ingestion/capture_session.py                 # one-time: log in, save session
python ingestion/ingest_chat.py --recent             # pull recent chats into SQLite
sqlite3 ingestion/cairn.db "SELECT session_id, role, substr(content,1,80) FROM chat_messages;"
```

Full detail (single-chat ingestion, recovery from a saved HAR/JSON, troubleshooting): see
[`ingestion/README.md`](ingestion/README.md).

## Writing findings into the graph

Ingestion only stores raw chat turns — it does not call an LLM or write graph findings
automatically. To add a reviewed finding, write a JSON file shaped like
[`schema/example_finding_extraction.json`](schema/example_finding_extraction.json) (findings +
typed edges, `source_session_id` pointing at an ingested chat) and run:

```powershell
python ingestion/write_findings.py path/to/your_findings.json
```
