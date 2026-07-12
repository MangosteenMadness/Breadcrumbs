from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ingestion.store import DEFAULT_DB_PATH

from .contracts import CheckDuplicationInput, RenderWikiInput, WriteFindingInput
from .store import BreadcrumbsStore, Scalar

DB_PATH = Path(os.getenv("BREADCRUMBS_DB", str(DEFAULT_DB_PATH)))
store = BreadcrumbsStore(DB_PATH)

BREADCRUMBS_INSTRUCTIONS = """
Breadcrumbs is the organization's internal research-memory database. Use its tools directly;
do not stop after merely discovering or listing them.

READING
- Before starting related research, call check_duplication or recall_findings.
- Use read only when an exact stored field/value filter is required.
- An empty result means only that no row matched that exact filter in the current database.
  Never describe an empty result as proof that the work is new.

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
- Call write_finding only for a reviewed research finding supported by the conversation or source
  session. Write one finding per call and do not fabricate missing evidence.
- Required record fields are category, disease, hypothesis_text, entities (array of strings),
  effect, status, author, source_session_id, and source_type. The category must already be
  registered and source_session_id must identify an ingested chat session. source_type must
  be internal for organization-generated work or external for published evidence.
- External findings require non-empty resources containing a paper or database citation.
  Internal findings must not contain resources. markdown is optional for both source types.
- status must be confirmed, in-progress, or abandoned. reason is required for abandoned
  findings and must be null or omitted for other statuses.
- Optional fields are id, created_at, n, provenance, note, markdown, and resources where
  allowed by source_type. Breadcrumbs supplies id and created_at when omitted. Put
  methodological caveats and future guidance in note. The status open is allowed for a reviewed
  hypothesis that has been logged but not run.
- After writing, report the stored id and summarize exactly what was persisted.
""".strip()

mcp = FastMCP(
    "Breadcrumbs — Internal Biomedical Research Memory",
    instructions=BREADCRUMBS_INSTRUCTIONS,
    json_response=True,
    stateless_http=True,
    streamable_http_path="/",
)

READ_ONLY_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


@mcp.tool(annotations=READ_ONLY_TOOL)
def check_duplication(
    hypothesis_text: Annotated[str, Field(min_length=1, description="Hypothesis to check.")],
    limit: Annotated[int, Field(ge=1, le=20, description="Maximum internal matches.")] = 5,
) -> dict[str, Any]:
    """Check the internal Breadcrumbs graph for prior organizational work."""
    request = CheckDuplicationInput(hypothesis_text=hypothesis_text, limit=limit)
    return store.check_duplication(request.hypothesis_text, limit=request.limit)


@mcp.tool()
def write_finding(
    record: Annotated[
        WriteFindingInput,
        Field(
            description=(
                "One reviewed finding. Required: category, disease, hypothesis_text, entities "
                "(string array), effect, status, author, source_session_id, and source_type "
                "(internal or external). External findings require resources with paper/database "
                "citations; internal findings must not include resources. For abandoned status, "
                "reason is required; otherwise reason must be null or omitted. Optional: id, "
                "created_at, n, provenance, note, markdown, and resources when external."
            )
        ),
    ],
) -> dict[str, Any]:
    """Persist one reviewed internal finding; never use this for unverified or invented claims."""
    return store.write(record.model_dump(exclude_none=True))


@mcp.tool(annotations=READ_ONLY_TOOL)
def recall_findings(
    query: Annotated[str, Field(min_length=1, description="Question, topic, entity, or context.")],
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum findings.")] = 10,
) -> dict[str, Any]:
    """Recall semantically related internal findings and graph edges."""
    return store.recall_findings(query, limit=limit)


@mcp.tool(annotations=READ_ONLY_TOOL)
def render_wiki(
    finding_ids: Annotated[
        list[str] | None,
        Field(description="Optional finding IDs; omit to render the full graph."),
    ] = None,
    title: Annotated[str, Field(description="Wiki page title.")] = "Breadcrumbs research memory",
) -> dict[str, Any]:
    """Render a reproducible read-only Markdown view whose citations point to graph finding IDs."""
    request = RenderWikiInput(finding_ids=finding_ids, title=title)
    return store.render_wiki(finding_ids=request.finding_ids, title=request.title)


@mcp.tool(annotations=READ_ONLY_TOOL)
def read(
    column: Annotated[
        str,
        Field(
            description=(
                "Exact column to filter: id, category, disease, hypothesis_text, signature, "
                "effect, n, status, author, timestamp/created_at, provenance, reason, note, "
                "source_session_id/source_session, source_type, markdown, or resources."
            )
        ),
    ],
    value: Annotated[
        Scalar,
        Field(description="Exact scalar value to match. This tool does not perform fuzzy search."),
    ],
) -> list[dict[str, Any]]:
    """Before biomedical research planning or interpretation, retrieve internal findings by one exact field/value filter."""
    return store.read(column, value)


mcp_http_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_http_app.router.lifespan_context(app):
        yield


app = FastAPI(title="Breadcrumbs MCP", version="0.3.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "database": str(DB_PATH), "mcp_endpoint": "/mcp"}


@app.post("/check_duplication")
def check_duplication_http(payload: dict[str, Any]) -> dict[str, Any]:
    """UI seam; the response is the same DuplicationResult contract as the MCP tool."""
    try:
        request = CheckDuplicationInput.model_validate(payload)
        return store.check_duplication(request.hypothesis_text, limit=request.limit)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
