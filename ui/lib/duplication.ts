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
const STATUS_LABEL: Record<string, string> = {
  abandoned: "⚑ dead end",
  in_progress: "◉ in progress",
  confirmed: "already explored",
};

/** Build a wiki-style markdown write-up from a resolved result. */
function buildMarkdown(question: string, matches: Match[]): string {
  const n = matches.length;
  const lines: string[] = [];
  lines.push(`## Retrace — you're not the first here`);
  lines.push("");
  lines.push(
    `**${n} marker${n > 1 ? "s" : ""}** on your org's trail match _${question.trim()}_.`,
  );
  lines.push("");
  matches.forEach((m) => {
    lines.push(`### ${m.id} · ${STATUS_LABEL[m.status] || m.status}`);
    lines.push(`- **Question:** ${m.hypothesis_text}`);
    lines.push(`- **Who:** ${m.author}${m.disease ? ` · ${m.disease}` : ""}`);
    if (m.effect) lines.push(`- **Finding:** ${m.effect}`);
    if (m.reason) lines.push(`- **Why it was dropped:** ${m.reason}`);
    lines.push("");
  });
  lines.push("---");
  lines.push(`#### Published record`);
  lines.push(
    `Related literature exists on this topic. What's above is _internal_ — work inside your org that no published search could surface.`,
  );
  lines.push("");
  lines.push(
    `_Internal trail checked first · ${F.length} markers searched · published record checked second._`,
  );
  lines.push("");
  lines.push(
    `_No claim of novelty — Breadcrumbs reports what it found on your trail, and what it didn't._`,
  );
  return lines.join("\n");
}

export function mockCheckDuplication(question: string, forcedId?: string): DuplicationResult {
  const hitId = forcedId || route(question);
  if (!hitId) {
    return {
      verdict: "open",
      matches: [],
      searched: F.length,
      markdown: [
        `## Open trail — you're the first here`,
        "",
        `Nothing on your org's trail matches _${question.trim()}_, and nothing in the published record searched.`,
        "",
        `As you explore it, Breadcrumbs drops a marker — so the next person who asks finds **you**.`,
      ].join("\n"),
    };
  }

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
    markdown: buildMarkdown(question, matches),
  };
}
