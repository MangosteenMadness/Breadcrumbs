from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ingestion.store import DEFAULT_DB_PATH

from .store import CairnStore, Scalar

DB_PATH = Path(os.getenv("BREADCRUMBS_DB", str(DEFAULT_DB_PATH)))
store = CairnStore(DB_PATH)

CAIRN_INSTRUCTIONS = """
Cairn is the organization's internal research-memory database. Use its tools directly;
do not stop after merely discovering or listing them.

READING
- Before starting related research, query Cairn for relevant prior work.
- Call read with exactly one allowed column and one exact scalar value. Useful columns
  include category, disease, status, author, and source_session_id. Make multiple read
  calls when more than one exact filter is useful; read is not semantic or fuzzy search.
- An empty result means only that no row matched that exact filter in the current database.
  Never describe an empty result as proof of novelty.

SUMMARIZING READ RESULTS
- Lead with what internal work exists and how directly it bears on the new question.
- Separate confirmed, in-progress, and abandoned findings.
- Preserve effect sizes, confidence intervals, p-values, sample sizes, and caveats exactly
  as stored. Do not strengthen associations into causal claims.
- For abandoned work, prominently state reason and note so the next researcher can avoid
  repeating a failed approach.
- Include disease, category, entities, author, timestamp, and source_session_id so every
  statement remains traceable. Say when a field is absent; never invent it.

WRITING
- Call write only for a reviewed research finding supported by the conversation or source
  session. Write one finding per call and do not fabricate missing evidence.
- Required record fields are category, disease, hypothesis_text, entities (array of strings),
  effect, status, author, and source_session_id. The category must already be registered and
  source_session_id must identify an ingested chat session.
- status must be confirmed, in-progress, or abandoned. reason is required for abandoned
  findings and must be null or omitted for other statuses.
- Optional fields are id, created_at, n, provenance, and note. Cairn supplies id and
  created_at when omitted. Put methodological caveats and future guidance in note.
- After writing, report the stored id and summarize exactly what was persisted.
""".strip()

mcp = FastMCP(
    "Cairn Research Memory",
    instructions=CAIRN_INSTRUCTIONS,
    json_response=True,
    stateless_http=True,
    streamable_http_path="/",
)


@mcp.tool()
def write(
    record: Annotated[
        dict[str, Any],
        Field(
            description=(
                "One reviewed finding. Required: category, disease, hypothesis_text, entities "
                "(string array), effect, status, author, source_session_id. For abandoned status, "
                "reason is required; otherwise reason must be null or omitted. Optional: id, "
                "created_at, n, provenance, note."
            )
        ),
    ],
) -> dict[str, Any]:
    """Persist one reviewed internal finding; never use this for unverified or invented claims."""
    return store.write(record)


@mcp.tool()
def read(
    column: Annotated[
        str,
        Field(
            description=(
                "Exact column to filter: id, category, disease, hypothesis_text, signature, "
                "effect, n, status, author, timestamp/created_at, provenance, reason, note, "
                "or source_session_id/source_session."
            )
        ),
    ],
    value: Annotated[
        Scalar,
        Field(description="Exact scalar value to match. This tool does not perform fuzzy search."),
    ],
) -> list[dict[str, Any]]:
    """Call this tool to retrieve internal findings by one exact field/value filter."""
    return store.read(column, value)


@mcp.prompt()
def cairn_research_memory_workflow(research_question: str) -> str:
    """Guide an agent through checking, summarizing, and updating Cairn research memory."""
    return f"""
Follow the Cairn research-memory workflow for this question:

{research_question}

1. Identify the best exact Cairn column/value filters from the question and call read.
2. If useful, make additional read calls for other exact filters.
3. Summarize internal results by status. Preserve numerical evidence and caveats exactly,
   surface abandoned reasons prominently, and cite author, timestamp, and source session.
4. Treat no exact match as limited database coverage, not proof of novelty.
5. Call write only if this conversation contains a reviewed finding that satisfies Cairn's
   required schema. Never infer or invent missing fields. Report the stored id after writing.
""".strip()


mcp_http_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_http_app.router.lifespan_context(app):
        yield


app = FastAPI(title="Breadcrumbs MCP", version="0.2.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "database": str(DB_PATH), "mcp_endpoint": "/mcp"}


app.mount("/mcp", mcp_http_app)


def main() -> None:
    transport = os.getenv("BREADCRUMBS_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "http":
        import uvicorn

        uvicorn.run(
            "breadcrumbs.server:app",
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8000")),
        )
    else:
        raise SystemExit("BREADCRUMBS_TRANSPORT must be 'stdio' or 'http'")


if __name__ == "__main__":
    main()
