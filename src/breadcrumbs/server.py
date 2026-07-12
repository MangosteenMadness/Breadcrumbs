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

from .embeddings import backend_from_environment
from .store import BreadcrumbsStore, Scalar

DB_PATH = Path(os.getenv("BREADCRUMBS_DB", str(DEFAULT_DB_PATH)))
store = BreadcrumbsStore(DB_PATH, embedding_backend=backend_from_environment())

BREADCRUMBS_INSTRUCTIONS = """
Breadcrumbs is the organization's internal research-memory database. Use its tools directly;
do not stop after merely discovering or listing them.

READING
- Before starting related research, query Breadcrumbs for relevant prior work.
- Call read with exactly one allowed column and one exact scalar value. Useful columns
  include category, disease, status, author, and source_session_id. Make multiple read
  calls when more than one exact filter is useful; read is not semantic or fuzzy search.
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
- Call write only for a reviewed research finding supported by the conversation or source
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
  methodological caveats and future guidance in note.
- After writing, report the stored id and summarize exactly what was persisted.

INTERACTION KNOWLEDGE / MEMORY DIFF
- Recall approved interaction knowledge before planning related work: call recall_knowledge with a
  short query plus scope fields actually stated by the researcher (for example disease, dataset,
  population, assay, or method). Do not invent scope merely to make the query look structured.
  Retrieval fuses local BM25 and local dense embeddings, then compatibility-ranks scope: unknown
  inferred keys do not erase a semantic match, and typed numeric conditions are evaluated. Use strict_scope only when the researcher explicitly
  requests an exact structured subset. Treat returned constraints, decisions, exceptions, abandoned approaches, and
  belief revisions as scoped guidance, not universal truth. Follow source_message_id when stakes
  are high. If source_drifted is true, say that the ingested source changed after approval and
  re-review the stored quote before acting. Superseded patches are hidden by default.
- Propose a knowledge candidate when an exchange changes a future belief or action: immediately
  after an explicit correction, decision, exception, or abandoned approach, and once more at the
  end of a substantive session. Propose no more than three. Do not extract generic summaries,
  unsupported implications, or facts that do not change what a future researcher should believe
  or do. Every candidate needs one exact quote from an ingested source message.
- To quantify a candidate, elicit the same number of prior and posterior independent judgments (at
  least three on each side; five is preferred) on the
  fixed labels strongly_disbelieve, disbelieve, uncertain, believe, strongly_believe. The prior
  judgments must use only the transcript prefix before the evidence quote plus previously recalled
  memory; the posterior judgments may use the quote and subsequent context. Keep the candidate
  proposition identical. Call score_surprise with those samples. If actions are also sampled,
  supply both prior_action_samples and posterior_action_samples. Keep the approved-model run log;
  write_knowledge requires its elicitation_model and elicitation_run_id.
- Present a Memory Diff before writing: kind, proposition, scope, rationale, exact source quote,
  approved retrieval aliases, typed applicability conditions when present, belief before/after,
  Bayesian surprise in bits, certainty gain, and structured action_before / action_after. A typed
  condition has field, optional approved field_aliases, operator (eq/ne/lt/lte/gt/gte/in), value,
  and optional unit. Explain that
  surprise measures belief movement; it establishes neither biological importance nor originality.
- Call write_knowledge only after a person explicitly approves or edits that Memory Diff.
  approved_by is a separate approval-event argument: populate it from the authenticated host actor
  when available, or from the exact reviewer confirmation, never from the candidate generator. The
  demo records the visible session actor at the button click; identity authentication remains a
  production integration responsibility. The server derives the source session, recomputes all
  metrics, and rejects paraphrased evidence. Use supersedes_id for a correction to approved memory
  so the prior version stays auditable. If the person skips, persist nothing.

EXPERTISE QUESTIONS
- For questions such as "who has expertise in X?", call find_experts with the topic and only scope
  the researcher actually stated. Report the ranked people, evidence confidence, and cited findings
  or knowledge patches. Say "strongest demonstrated experience among the sources searched," not
  that somebody is definitively the organization's expert. A provisional identity is an exact
  normalized-name grouping, not a verified identity merge. Reviewer activity alone is not expertise.
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


@mcp.tool()
def write(
    record: Annotated[
        dict[str, Any],
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
    return store.write(record)


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


@mcp.tool(annotations=READ_ONLY_TOOL)
def score_surprise(
    prior_samples: Annotated[
        list[str | float],
        Field(
            description=(
                "At least three repeated judgments of the unchanged proposition using numbers in "
                "[0,1] or strongly_disbelieve/disbelieve/uncertain/believe/strongly_believe, "
                "evaluated using only context before the evidence."
            )
        ),
    ],
    posterior_samples: Annotated[
        list[str | float],
        Field(
            description=(
                "At least three repeated judgments of the same proposition after the evidence."
            )
        ),
    ],
    prior_action_samples: Annotated[
        list[str] | None,
        Field(description="Optional categorical action samples before the evidence."),
    ] = None,
    posterior_action_samples: Annotated[
        list[str] | None,
        Field(description="Optional categorical action samples after the evidence."),
    ] = None,
) -> dict[str, Any]:
    """Quantify belief movement reproducibly; this score is not importance or originality."""

    return store.score_surprise(
        prior_samples,
        posterior_samples,
        prior_action_samples=prior_action_samples,
        posterior_action_samples=posterior_action_samples,
    )


@mcp.tool()
def write_knowledge(
    record: Annotated[
        dict[str, Any],
        Field(
            description=(
                "One candidate presented with a separate explicit approval event. Required: kind, proposition, "
                "rationale, non-empty scope object, exact evidence_quote, source_message_id, "
                "prior_samples, posterior_samples, elicitation_model, elicitation_run_id, and "
                "author. Optional approved aliases (string array), typed conditions (field, "
                "optional field_aliases, operator, value, optional unit), paired "
                "action_before/action_after objects, paired prior/posterior action samples, reason "
                "(required only for abandoned), and supersedes_id. Never supply calculated fields."
            )
        ),
    ],
    approved_by: Annotated[
        str,
        Field(
            description=(
                "The person who explicitly approved this exact Memory Diff, supplied separately "
                "by the approval event or authenticated host identity."
            )
        ),
    ],
) -> dict[str, Any]:
    """Persist one reviewed Memory Diff; never call before explicit human approval."""

    if "approved_by" in record:
        raise ValueError("approved_by must come from the separate approval event argument")
    return store.write_knowledge({**record, "approved_by": approved_by})


@mcp.tool(annotations=READ_ONLY_TOOL)
def recall_knowledge(
    query: Annotated[
        str,
        Field(description="Short natural-language description of the decision, constraint, or topic."),
    ] = "",
    scope: Annotated[
        dict[str, Any] | None,
        Field(description="Optional structured scope subset, e.g. disease, dataset, assay, method."),
    ] = None,
    kinds: Annotated[
        list[str] | None,
        Field(
            description=(
                "Optional kinds: decision, constraint, exception, abandoned, belief_revision."
            )
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum results.")] = 10,
    include_superseded: Annotated[
        bool,
        Field(description="Include historical patches superseded by newer approved knowledge."),
    ] = False,
    strict_scope: Annotated[
        bool,
        Field(
            description=(
                "Require the stored flat scope to contain every requested scope field exactly. "
                "Leave false for normal compatibility-ranked recall, especially for inferred scope."
            )
        ),
    ] = False,
) -> list[dict[str, Any]]:
    """Recall approved internal knowledge with local hybrid search and applicability."""

    return store.recall_knowledge(
        query,
        scope=scope,
        kinds=kinds,
        limit=limit,
        include_superseded=include_superseded,
        strict_scope=strict_scope,
    )


@mcp.tool(annotations=READ_ONLY_TOOL)
def find_experts(
    topic: Annotated[
        str,
        Field(description="Natural-language scientific, methodological, or operational topic."),
    ],
    scope: Annotated[
        dict[str, Any] | None,
        Field(description="Optional stated scope, e.g. disease, dataset, assay, or method."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=20, description="Maximum ranked people.")] = 5,
    evidence_limit: Annotated[
        int,
        Field(ge=1, le=20, description="Maximum cited evidence artifacts per person."),
    ] = 5,
) -> dict[str, Any]:
    """Rank demonstrated experience from source-linked work; never assert a definitive expert."""

    return store.find_experts(
        topic,
        scope=scope,
        limit=limit,
        evidence_limit=evidence_limit,
    )


mcp_http_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_http_app.router.lifespan_context(app):
        yield


app = FastAPI(title="Breadcrumbs MCP", version="0.4.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "database": str(DB_PATH), "mcp_endpoint": "/mcp"}


@app.post("/knowledge/score")
def score_surprise_http(payload: dict[str, Any]) -> dict[str, Any]:
    """REST seam used by the demo UI; calculation is identical to the MCP tool."""

    try:
        return store.score_surprise(
            payload.get("prior_samples"),
            payload.get("posterior_samples"),
            prior_action_samples=payload.get("prior_action_samples"),
            posterior_action_samples=payload.get("posterior_action_samples"),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/knowledge")
def write_knowledge_http(payload: dict[str, Any]) -> dict[str, Any]:
    """REST approval seam used by the demo UI; there is deliberately no mock-success fallback."""

    try:
        candidate = payload.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be a JSON object")
        if "approved_by" in candidate:
            raise ValueError("approved_by must be supplied by the separate approval event")
        return store.write_knowledge(
            {**candidate, "approved_by": payload.get("approved_by")}
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/knowledge/recall")
def recall_knowledge_http(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Structured REST recall for hosts that are not MCP clients."""

    try:
        return store.recall_knowledge(
            payload.get("query", ""),
            scope=payload.get("scope"),
            kinds=payload.get("kinds"),
            limit=payload.get("limit", 10),
            include_superseded=payload.get("include_superseded", False),
            strict_scope=payload.get("strict_scope", False),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/experts/find")
def find_experts_http(payload: dict[str, Any]) -> dict[str, Any]:
    """REST seam for evidence-backed expertise lookup."""

    try:
        return store.find_experts(
            payload.get("topic"),
            scope=payload.get("scope"),
            limit=payload.get("limit", 5),
            evidence_limit=payload.get("evidence_limit", 5),
        )
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
