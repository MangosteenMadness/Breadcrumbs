/* ============================================================
   Local mock of the MCP `check_duplication` tool.

   This resolves a question against the seeded trail in data.ts and
   returns the EXACT shape the real SQLite MCP server must return.
   The API route (app/api/check_duplication/route.ts) uses this as an
   automatic fallback whenever the real MCP is unset or unreachable,
   so the demo can't be broken by a flaky network.
   ============================================================ */

import {
  F,
  byId,
  neighborsOf,
  type DuplicationResult,
  type Match,
  type Finding,
  type Relationship,
} from "./data";

/** Keyword/entity routing for a free-typed question → a seeded finding id. */
export function route(text: string): string | null {
  const t = text.toLowerCase();
  let best: string | null = null;
  let score = 0;
  F.forEach((f) => {
    const words = f.q.toLowerCase().split(/\W+/).filter((w) => w.length > 4);
    const ents = f.ent.map((e) => e.toLowerCase());
    let s = 0;
    words.forEach((w) => {
      if (t.includes(w)) s++;
    });
    ents.forEach((e) => {
      if (t.includes(e.replace("_", " ")) || t.includes(e)) s += 3;
    });
    if (s > score) {
      score = s;
      best = f.id;
    }
  });
  return score >= 3 ? best : null;
}

function toMatch(f: Finding, rel: Relationship): Match {
  return {
    id: f.id,
    status: f.st,
    relationship: rel,
    hypothesis_text: f.q,
    effect: f.eff,
    reason: f.rz ?? null,
    author: f.au,
    disease: f.dis,
  };
}

/**
 * Resolve a question from the seeded graph.
 * @param forcedId mock-only deterministic hint (canned questions); ignored by the real MCP.
 */
export function mockCheckDuplication(question: string, forcedId?: string): DuplicationResult {
  const hitId = forcedId || route(question);
  if (!hitId) return { verdict: "open", matches: [], searched: F.length };

  const hit = byId[hitId];
  const nb = neighborsOf(hitId);
  const matches: Match[] = [toMatch(hit, "duplicate_of")];

  // order: dead ends first (most valuable), then in-flight, then related
  nb
    .map((n) => ({ f: byId[n.id], rel: n.rel }))
    .sort((a, b) => {
      const w = (s: string) => (s === "abandoned" ? 0 : s === "in_progress" ? 1 : 2);
      return w(a.f.st) - w(b.f.st);
    })
    .forEach(({ f, rel }) => matches.push(toMatch(f, rel)));

  return {
    verdict: "match",
    matches,
    external:
      "Related literature exists on this topic. What's above is <em>internal</em> — work inside your org that no published search could surface.",
    searched: F.length,
  };
}
