import { NextResponse } from "next/server";

const API_URL = process.env.BREADCRUMBS_API_URL?.replace(/\/$/, "");
const TIMEOUT_MS = 8000;

type KnowledgeRequest =
  | {
      operation: "score";
      prior_samples: unknown;
      posterior_samples: unknown;
      prior_action_samples?: unknown;
      posterior_action_samples?: unknown;
    }
  | { operation: "approve"; candidate: unknown; approved_by?: unknown };

function errorResponse(message: string, status: number) {
  return NextResponse.json({ error: message }, { status });
}

export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as KnowledgeRequest | null;

  if (!body || (body.operation !== "score" && body.operation !== "approve")) {
    return errorResponse("Expected a score or approve operation.", 400);
  }

  if (!API_URL) {
    return errorResponse(
      "Knowledge memory is unavailable because BREADCRUMBS_API_URL is not configured.",
      503,
    );
  }

  if (body.operation === "score") {
    if (!Array.isArray(body.prior_samples) || !Array.isArray(body.posterior_samples)) {
      return errorResponse("prior_samples and posterior_samples must be arrays.", 400);
    }
  } else {
    if (!body.candidate || typeof body.candidate !== "object") {
      return errorResponse("candidate must be an object.", 400);
    }
    if (typeof body.approved_by !== "string" || !body.approved_by.trim()) {
      return errorResponse("approved_by must name the reviewer who clicked approve.", 400);
    }
  }

  const target = body.operation === "score" ? `${API_URL}/knowledge/score` : `${API_URL}/knowledge`;
  const payload =
    body.operation === "score"
      ? {
          prior_samples: body.prior_samples,
          posterior_samples: body.posterior_samples,
          prior_action_samples: body.prior_action_samples,
          posterior_action_samples: body.posterior_action_samples,
        }
      : { candidate: body.candidate, approved_by: body.approved_by };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const upstream = await fetch(target, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: controller.signal,
    });

    const data = await upstream.json().catch(() => null);
    if (!upstream.ok) {
      const detail =
        data && typeof data === "object" && "detail" in data
          ? String(data.detail)
          : `Backend returned ${upstream.status}.`;
      return errorResponse(`Knowledge backend rejected the request: ${detail}`, 502);
    }

    return NextResponse.json(data ?? {}, {
      headers: { "x-breadcrumbs-source": "api" },
    });
  } catch (error) {
    const reason = error instanceof Error && error.name === "AbortError" ? "timed out" : "failed";
    return errorResponse(`Knowledge backend ${reason}; no memory was written.`, 502);
  } finally {
    clearTimeout(timer);
  }
}
