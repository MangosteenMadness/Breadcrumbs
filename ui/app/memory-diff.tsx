"use client";

import { useEffect, useMemo, useState } from "react";
import {
  TP53_CONSTRAINT_CANDIDATE,
  CURRENT_REVIEWER,
  actionDelta,
  type KnowledgeCandidate,
  type SurpriseScore,
} from "@/lib/knowledge";

type RequestState = "loading" | "ready" | "approving" | "approved" | "error";

interface MemoryDiffCardProps {
  open: boolean;
  onClose: () => void;
  candidate?: KnowledgeCandidate;
  reviewer?: string;
}

function asFiniteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function normaliseScore(payload: unknown): SurpriseScore {
  const root = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const nested =
    (root.metrics && typeof root.metrics === "object" ? root.metrics : undefined) ??
    (root.score && typeof root.score === "object" ? root.score : undefined) ??
    (root.result && typeof root.result === "object" ? root.result : undefined) ??
    (root.data && typeof root.data === "object" ? root.data : undefined) ??
    root;
  const score = nested as Record<string, unknown>;

  const priorMean = asFiniteNumber(score.prior_mean);
  const posteriorMean = asFiniteNumber(score.posterior_mean);
  const surprise = asFiniteNumber(score.bayesian_surprise_bits);
  const certaintyGain = asFiniteNumber(score.certainty_gain_bits);

  if (
    priorMean === undefined ||
    posteriorMean === undefined ||
    surprise === undefined ||
    certaintyGain === undefined
  ) {
    throw new Error("The knowledge backend returned an incomplete surprise score.");
  }

  return {
    prior_mean: priorMean,
    posterior_mean: posteriorMean,
    belief_shift: asFiniteNumber(score.belief_shift) ?? posteriorMean - priorMean,
    bayesian_surprise_bits: surprise,
    certainty_gain_bits: certaintyGain,
    action_surprise_bits:
      asFiniteNumber(score.action_surprise_bits) ?? asFiniteNumber(score.action_js_bits),
  };
}

async function requestKnowledge(body: unknown) {
  const response = await fetch("/api/knowledge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const message =
      data && typeof data === "object" && "error" in data
        ? String(data.error)
        : `Knowledge API returned ${response.status}.`;
    throw new Error(message);
  }
  return data;
}

function scoreCandidate(candidate: KnowledgeCandidate) {
  return requestKnowledge({
    operation: "score",
    prior_samples: candidate.prior_samples,
    posterior_samples: candidate.posterior_samples,
    prior_action_samples: candidate.prior_action_samples,
    posterior_action_samples: candidate.posterior_action_samples,
  }).then(normaliseScore);
}

function label(value: string) {
  return value.replaceAll("_", " ");
}

function actionValue(value: string | boolean) {
  return typeof value === "boolean" ? (value ? "yes" : "no") : label(value);
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function bits(value: number | undefined) {
  return value === undefined ? "—" : `${value.toFixed(2)} bits`;
}

export function MemoryDiffCard({
  open,
  onClose,
  candidate = TP53_CONSTRAINT_CANDIDATE,
  reviewer = CURRENT_REVIEWER,
}: MemoryDiffCardProps) {
  if (!open) return null;

  return <MemoryDiffDialog onClose={onClose} candidate={candidate} reviewer={reviewer} />;
}

function MemoryDiffDialog({
  onClose,
  candidate,
  reviewer,
}: Required<Pick<MemoryDiffCardProps, "onClose" | "candidate" | "reviewer">>) {
  const delta = useMemo(() => actionDelta(candidate), [candidate]);
  const writable =
    candidate.elicitation.status === "observed" &&
    Boolean(candidate.elicitation.model) &&
    Boolean(candidate.elicitation.run_id);
  const [state, setState] = useState<RequestState>("loading");
  const [score, setScore] = useState<SurpriseScore | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    scoreCandidate(candidate)
      .then((next) => {
        if (!active) return;
        setScore(next);
        setState("ready");
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : String(reason));
        setState("error");
      });

    return () => {
      active = false;
    };
  }, [candidate]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && state !== "approving") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, state]);

  async function approve() {
    if (!score || state !== "ready" || !writable) return;
    const { elicitation, ...candidateRecord } = candidate;
    setState("approving");
    setError("");
    try {
      await requestKnowledge({
        operation: "approve",
        candidate: {
          ...candidateRecord,
          elicitation_model: elicitation.model,
          elicitation_run_id: elicitation.run_id,
        },
        approved_by: reviewer,
      });
      setState("approved");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setState("ready");
    }
  }

  return (
    <div
      className="memory-overlay"
      role="presentation"
      onMouseDown={() => {
        if (state !== "approving") onClose();
      }}
    >
      <section
        className="memory-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="memory-diff-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="memory-head">
          <div>
            <div className="memory-eyebrow">
              {writable
                ? "Candidate knowledge · human review required"
                : "Illustrative candidate · authoritative write disabled"}
            </div>
            <h2 id="memory-diff-title">Memory Diff</h2>
          </div>
          <button
            className="memory-close"
            onClick={onClose}
            disabled={state === "approving"}
            aria-label="Close memory review"
          >
            ×
          </button>
        </header>

        <div className="memory-body">
          <div className="memory-kind">
            <span>{candidate.kind}</span>
            <span>
              {writable
                ? "proposed from a logged K Pro elicitation · not yet in the trail"
                : "UI fixture · source quote real, judgments illustrative"}
            </span>
          </div>

          <h3>{candidate.proposition}</h3>
          <p className="memory-rationale">{candidate.rationale}</p>

          <div className="memory-scope" aria-label="Knowledge scope">
            {Object.entries(candidate.scope).map(([key, value]) => (
              <span key={key}>
                <b>{key}</b> {label(value)}
              </span>
            ))}
          </div>

          <figure className="memory-source">
            <figcaption>
              Source evidence · K Pro message {candidate.source_message_id}
            </figcaption>
            <blockquote>“{candidate.evidence_quote}”</blockquote>
          </figure>

          {!writable && (
            <div className="memory-warning" role="note">
              Preview only. These fixed judgment samples validate the interface; they were not
              logged by the cited K Pro run and cannot enter organizational memory. A live host
              must supply an approved model and elicitation run ID.
            </div>
          )}

          <div className="memory-section-label">
            Belief update · {candidate.prior_samples.length} prior / {candidate.posterior_samples.length} posterior model judgments
          </div>
          {state === "loading" ? (
            <div className="memory-loading">
              <span className="spin" /> Calculating from supplied before/after samples…
            </div>
          ) : score ? (
            <div>
              <div className="belief-flow">
                <div className="belief-state">
                  <span>Before evidence</span>
                  <strong>{percent(score.prior_mean)}</strong>
                  <i style={{ width: percent(score.prior_mean) }} />
                </div>
                <div className="belief-arrow" aria-hidden>
                  →
                </div>
                <div className="belief-state after">
                  <span>After evidence</span>
                  <strong>{percent(score.posterior_mean)}</strong>
                  <i style={{ width: percent(score.posterior_mean) }} />
                </div>
              </div>
              <div className="surprise-grid">
                <div className="surprise-metric">
                  <span>Bayesian surprise</span>
                  <strong>{bits(score.bayesian_surprise_bits)}</strong>
                </div>
                <div className="surprise-metric">
                  <span>Belief shift</span>
                  <strong>{score.belief_shift >= 0 ? "+" : ""}{percent(score.belief_shift)}</strong>
                </div>
                <div className="surprise-metric">
                  <span>Certainty gain</span>
                  <strong>{bits(score.certainty_gain_bits)}</strong>
                </div>
                <div className="surprise-metric">
                  <span>Action surprise</span>
                  <strong>{bits(score.action_surprise_bits)}</strong>
                </div>
              </div>
            </div>
          ) : null}

          <div className="memory-section-label">What changes in practice</div>
          <div className="action-delta">
            {delta.map((change) => (
              <div className="action-row" key={change.key}>
                <span className="action-key">{label(change.key)}</span>
                <span className="action-before">{actionValue(change.before)}</span>
                <span className="action-arrow" aria-hidden>→</span>
                <span className="action-after">{actionValue(change.after)}</span>
              </div>
            ))}
          </div>

          {error && (
            <div className="memory-error" role="alert">
              <strong>Memory not saved.</strong> {error}
            </div>
          )}
          {state === "approved" && (
            <div className="memory-success" role="status">
              Approved by {reviewer}. This source-linked constraint is now available
              for future recall.
            </div>
          )}

          <p className="memory-note">
            Surprise measures how much the sampled belief distribution moved. It establishes
            neither biological importance nor originality.
          </p>
        </div>

        <footer className="memory-actions">
          <button className="memory-skip" onClick={onClose} disabled={state === "approving"}>
            {state === "approved" ? "Close" : "Skip"}
          </button>
          {state !== "approved" && (
            <button
              className="memory-approve"
              onClick={approve}
              disabled={state !== "ready" || !score || !writable}
            >
              {state === "approving"
                ? "Saving…"
                : writable
                  ? "Approve & add to trail"
                  : "Live elicitation required"}
            </button>
          )}
        </footer>
      </section>
    </div>
  );
}
