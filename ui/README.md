# Breadcrumbs — Retrace (UI)

The demo surface for **Breadcrumbs**: an internal research-memory layer for K Pro.
Before a researcher runs a hypothesis, it checks — *internally first* — whether
someone in their org already explored it (including **abandoned** attempts),
then whether the published world has.

The UI talks to the shared server through narrow Next.js routes. Duplication lookup can run against
its seeded mock; approved interaction knowledge always uses the real backend.

## Run

```bash
npm run dev      # http://localhost:3000
```

Runs standalone out of the box — it resolves questions against a seeded local
mock (`lib/data.ts` + `lib/duplication.ts`), so there's always something to demo
even with no backend and no network.

## The one seam — wiring the SQLite MCP backend

The UI calls `POST /api/check_duplication` (see `app/api/check_duplication/route.ts`).
That route proxies to the real backend when this env var is set, and silently
falls back to the seeded mock if it's unset or the call fails/times out:

```bash
# .env.local
BREADCRUMBS_MCP_URL=http://localhost:8000/check_duplication
```

The route POSTs `{ "hypothesis_text": "<the question>" }` and expects the backend
to return exactly this shape (typed as `DuplicationResult` in `lib/data.ts`):

```jsonc
{
  "verdict": "match" | "open",
  "matches": [
    {
      "id": "F-218",
      "status": "confirmed" | "in_progress" | "abandoned",
      "relationship": "duplicate_of" | "extends" | "related",
      "hypothesis_text": "...",
      "effect": "...",
      "reason": "..." ,      // string for abandoned findings, else null
      "author": "L. Ortiz",
      "disease": "BLCA"
    }
  ],
  "external": "optional string about the published record",  // may contain <em>
  "searched": 22
}
```

The **first** item in `matches` is rendered as the primary hit. Order the rest
however you want surfaced — the seed puts dead ends first, then in-flight, then
related.

## Memory Diff — human-gated interaction knowledge

The header's **Review memory diff** action shows a source-linked candidate before it enters the
authoritative trail: exact evidence quote, structured scope, repeated before/after belief samples,
Bayesian surprise, certainty gain, action divergence, and the concrete action delta. In the live
agent flow, Claude passes the exact relevant live turns to `prepare_memory_diff`; Breadcrumbs
content-addresses that source snapshot, selects the exact evidence span, and returns the prior and
posterior context packets, fixed labels, approved model, deterministic run ID, and record template.
Those are MCP-provided mechanics: the researcher only discusses the science and approves, edits,
or declines the resulting diff—there is no manual sync step.

The checked-in TP53 example is explicitly an **illustrative UI fixture**: its source quote comes
from the ingested session, but its fixed judgment samples were not logged by that run, so approval
is disabled. A live candidate becomes writable only when the host supplies an observed elicitation
from an approved model with a traceable run ID. The fixture is never presented as authoritative
evidence and cannot pollute the graph.

The checked-in browser fixture does not yet originate its candidate through
`/knowledge/prepare`; that endpoint supports connected agent hosts. The existing browser route
continues to proxy scoring and the explicit approval write, with no mock-success write path.

Configure the REST base alongside the duplication seam:

```bash
# .env.local
BREADCRUMBS_API_URL=http://localhost:8000
```

`POST /api/knowledge` proxies scoring to `/knowledge/score` and explicit approval to `/knowledge`.
The candidate never carries its own reviewer identity; the visible session actor is attached only
when the person clicks approve. Production should replace that demo actor with K Pro's authenticated
identity.
When `BREADCRUMBS_API_URL` is absent or unreachable, scoring/approval reports an error and the UI
does **not** claim that anything was saved. The Python backend verifies the quote against the
ingested message and recomputes every metric; the browser's values are never trusted.

## Structure

| Path | What |
| --- | --- |
| `app/page.tsx` | The whole UI — sidebar, chat + thinking animation, trail graph |
| `app/globals.css` | Ported styles (fonts wired via `next/font` CSS vars) |
| `app/api/check_duplication/route.ts` | The seam: proxy to MCP, mock fallback |
| `app/api/knowledge/route.ts` | Surprise/approval proxy; deliberately no mock-success write path |
| `app/memory-diff.tsx` | Source, belief, action, approve/skip review card |
| `lib/data.ts` | Seeded trail (22 findings), types, the `DuplicationResult` contract |
| `lib/duplication.ts` | Local mock of `check_duplication` |
| `lib/knowledge.ts` | Typed source-linked Memory Diff fixture and action delta |
| `docs/Breadcrumbs-brief.md` | Hackathon brief |
| `docs/original-ui.html` | The original single-file UI this was ported from |

## Feeding real Q&A into history

The left sidebar's **Session history** and **Explore MOSAIC** questions come from
`HIST` and `F` in `lib/data.ts`. Swap those arrays for the real answers/questions
as the ingestor produces them — the UI re-renders from them directly.
