import { NextResponse } from "next/server";
import { mockCheckDuplication } from "@/lib/duplication";

/* ============================================================
   check_duplication — the one seam between UI and backend.

   Wire the real backend by setting BREADCRUMBS_MCP_URL (e.g. the
   FastAPI SQLite MCP server: http://localhost:8000/check_duplication).
   When set, we POST { hypothesis_text } and return whatever it
   answers. When unset — or if the call fails/times out — we fall
   back to the seeded local mock so the demo never goes dark.

   The backend MUST return the DuplicationResult shape (see lib/data.ts):
   { verdict, matches[], external?, searched }
   ============================================================ */

const MCP_URL = process.env.BREADCRUMBS_MCP_URL;
const TIMEOUT_MS = 8000;

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const hypothesis_text: string = body?.hypothesis_text ?? "";
  const forcedId: string | undefined = body?.forcedId; // mock-only deterministic hint

  if (MCP_URL) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
      const res = await fetch(MCP_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hypothesis_text }),
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (!res.ok) throw new Error(`MCP error ${res.status}`);
      const data = await res.json();
      return NextResponse.json(data, { headers: { "x-breadcrumbs-source": "mcp" } });
    } catch (err) {
      // Network flaked — degrade to the seeded mock rather than break the demo.
      console.warn("[breadcrumbs] MCP call failed, using mock:", String(err));
    }
  }

  const result = mockCheckDuplication(hypothesis_text, forcedId);
  return NextResponse.json(result, {
    headers: { "x-breadcrumbs-source": MCP_URL ? "mock-fallback" : "mock" },
  });
}
