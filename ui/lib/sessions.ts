/* ============================================================
   K Pro session transcripts — the replayed real runs.

   sessions.json is produced by ingestion/export_sessions.py from breadcrumbs.db. Each session
   is the actual K Pro chat: ordered turns, each an ordered list of blocks (answer text, a
   Plotly figure, a datatable, or an `omitted` placeholder for a heavy plot stripped at ingest).
   Rendering the stored figure with Plotly.js redraws the exact chart K Pro drew — no auth, no
   network, nothing to stall mid-demo. See lib/data.ts for the seeded duplication trail this
   sits alongside; a matched finding links here via sessionForFinding().
   ============================================================ */

import raw from "./sessions.json";

export type Block =
  | { kind: "text"; text: string }
  | { kind: "suggestion"; text: string }
  | { kind: "plot"; title?: string | null; figure: PlotFigure }
  | { kind: "table"; title?: string; columns: string[]; rows: (string | number | null)[][] }
  | { kind: "omitted"; blockType: string; bytes?: number | null };

export interface PlotFigure {
  data: unknown[];
  layout?: Record<string, unknown> & { template?: unknown };
}

export interface Turn {
  role: "user" | "assistant";
  blocks: Block[];
}

export interface Session {
  id: string;
  title: string | null;
  url: string;
  researcher: string | null;
  turns: Turn[];
  counts: { plots: number; tables: number; omitted: number };
}

interface SessionsFile {
  templates: unknown[];
  sessions: Session[];
}

const file = raw as unknown as SessionsFile;

export const SESSIONS: Session[] = file.sessions;

export const sessionById: Record<string, Session> = Object.fromEntries(
  SESSIONS.map((s) => [s.id, s]),
);

/**
 * Return a render-ready copy of a figure with its layout.template rehydrated.
 * The export hoists the (only two) distinct Plotly templates into a shared table and leaves
 * `layout.template = { $tmpl: i }` on each figure; swap the reference back for the real object.
 */
export function hydrateFigure(figure: PlotFigure): PlotFigure {
  const layout = figure.layout;
  const ref = layout?.template as { $tmpl?: number } | undefined;
  if (ref && typeof ref.$tmpl === "number") {
    return { ...figure, layout: { ...layout, template: file.templates[ref.$tmpl] } };
  }
  return figure;
}

const norm = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/**
 * Map a duplication-trail question to the real K Pro session that answered it, if one exists.
 * Session titles are K Pro's own chat names, often a truncated echo of the question — so a
 * prefix match on the normalized text is what links the seeded finding to its actual run.
 */
export function sessionForFinding(question: string): Session | null {
  const q = norm(question);
  if (q.length < 20) return null;
  let best: Session | null = null;
  let bestLen = 0;
  for (const s of SESSIONS) {
    if (!s.title) continue;
    const t = norm(s.title);
    if (t.length < 20) continue;
    const overlap = q.startsWith(t) || t.startsWith(q);
    if (overlap && t.length > bestLen) {
      best = s;
      bestLen = t.length;
    }
  }
  return best;
}

/** Sessions worth surfacing in the demo — those that actually carry charts or tables. */
export const SESSIONS_WITH_CHARTS: Session[] = SESSIONS.filter(
  (s) => s.counts.plots + s.counts.tables > 0,
);
