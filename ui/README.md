# Breadcrumbs — Retrace (UI)

The demo surface for **Breadcrumbs**: an internal research-memory layer for K Pro.
Before a researcher runs a hypothesis, it checks — *internally first* — whether
someone in their org already explored it (including **abandoned** attempts),
then whether the published world has.

This repo is **the UI only**. The MCP server, wiki, SQLite store, ingestor, and
Q&A live in the other teams' repos. This app talks to them through one seam.

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

## Structure

| Path | What |
| --- | --- |
| `app/page.tsx` | The whole UI — sidebar, chat + thinking animation, trail graph |
| `app/globals.css` | Ported styles (fonts wired via `next/font` CSS vars) |
| `app/api/check_duplication/route.ts` | The seam: proxy to MCP, mock fallback |
| `lib/data.ts` | Seeded trail (22 findings), types, the `DuplicationResult` contract |
| `lib/duplication.ts` | Local mock of `check_duplication` |
| `docs/Breadcrumbs-brief.md` | Hackathon brief |
| `docs/original-ui.html` | The original single-file UI this was ported from |

## Feeding real Q&A into history

The left sidebar's **Session history** and **Explore MOSAIC** questions come from
`HIST` and `F` in `lib/data.ts`. Swap those arrays for the real answers/questions
as the ingestor produces them — the UI re-renders from them directly.
