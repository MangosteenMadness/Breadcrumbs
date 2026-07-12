export type BeliefLabel =
  | "strongly_disbelieve"
  | "disbelieve"
  | "uncertain"
  | "believe"
  | "strongly_believe";

export interface KnowledgeCandidate {
  kind: "decision" | "constraint" | "exception" | "abandoned" | "belief_revision";
  proposition: string;
  rationale: string;
  scope: Record<string, string>;
  evidence_quote: string;
  source_message_id: string;
  author: string;
  prior_samples: BeliefLabel[];
  posterior_samples: BeliefLabel[];
  prior_action_samples: string[];
  posterior_action_samples: string[];
  action_before: Record<string, string | boolean>;
  action_after: Record<string, string | boolean>;
  elicitation: {
    status: "illustrative" | "observed";
    model?: string;
    run_id?: string;
  };
}

export const CURRENT_REVIEWER = "Dr. Chen";

export interface SurpriseScore {
  prior_mean: number;
  posterior_mean: number;
  belief_shift: number;
  bayesian_surprise_bits: number;
  certainty_gain_bits: number;
  action_surprise_bits?: number;
}

/**
 * A source-linked UI fixture from the ingested MOSAIC BLCA session. The source quote is real; the
 * judgment samples are illustrative, so this preview cannot write authoritative memory.
 */
export const TP53_CONSTRAINT_CANDIDATE: KnowledgeCandidate = {
  kind: "constraint",
  proposition:
    "Treat spot-level TP53 differences in MOSAIC BLCA as exploratory until the patient-level cohort is larger.",
  rationale:
    "The interaction changed how the result should be interpreted and what should happen next, despite strong spot-level power.",
  scope: {
    dataset: "MOSAIC_WINDOW",
    disease: "BLCA",
    comparison: "TP53_mutant_vs_wild_type",
    unit: "patient",
  },
  evidence_quote:
    "only 3 TP53-mutant patients are available — spot-level results are highly powered (14,054 vs 54,315 spots), but patient-level confounders cannot be excluded without a larger cohort.",
  source_message_id: "d783a283-74d0-48e2-80ab-42857be73106:5",
  author: "Dr. Chen",
  prior_samples: ["uncertain", "disbelieve", "uncertain", "believe", "uncertain"],
  posterior_samples: [
    "strongly_believe",
    "believe",
    "strongly_believe",
    "believe",
    "strongly_believe",
  ],
  prior_action_samples: [
    "interpret_as_confirmatory",
    "interpret_as_confirmatory",
    "proceed_without_patient_caveat",
    "interpret_as_confirmatory",
    "flag_patient_limit",
  ],
  posterior_action_samples: [
    "interpret_as_exploratory",
    "expand_patient_cohort",
    "interpret_as_exploratory",
    "flag_patient_limit",
    "interpret_as_exploratory",
  ],
  action_before: {
    interpretation: "confirmatory",
    next_step: "proceed_with_spot_level_result",
    patient_level_caveat: false,
  },
  action_after: {
    interpretation: "exploratory",
    next_step: "expand_patient_cohort",
    patient_level_caveat: true,
  },
  elicitation: { status: "illustrative" },
};

export function actionDelta(candidate: KnowledgeCandidate) {
  return Object.keys(candidate.action_after)
    .filter((key) => candidate.action_before[key] !== candidate.action_after[key])
    .map((key) => ({
      key,
      before: candidate.action_before[key],
      after: candidate.action_after[key],
    }));
}
