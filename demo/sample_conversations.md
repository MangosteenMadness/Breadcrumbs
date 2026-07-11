# Cairn — Sample Demo Conversations

Source: `References/Breadcrumbs.pdf` (Demo Script). These are the literal chat turns for
rehearsal / to drive a thin chat UI, with the `{{ }}` slots left for Builder 1 to fill from the real
TCGA LUAD cBioPortal run (see `schema/seed_findings.json`). Calibration rule: the agent never
says "this is novel" — only "no prior internal work found" / "published record shows related work."

---

## Pre-demo state

- Graph pre-loaded with **Finding #F-093** (abandoned) — see `schema/seed_findings.json`.
- Graph otherwise empty of Finding #F-118 — it is written live in Session 1 below.

---

## Session 1 — a finding is born

**Researcher (chat):**
> In lung adenocarcinoma, is high cytotoxic T-cell infiltration associated with better overall survival?

**Cairn agent:**
> Ran a high-vs-low split on a cytotoxic signature (CD8A, GZMB, PRF1, GZMK) across TCGA LUAD.
>
> **Result:** high-infiltration patients (n={{N_HIGH}}) showed better overall survival than low
> (n={{N_LOW}}). HR {{HR}} (95% CI {{CI}}), log-rank p={{P}}. Median OS {{MEDIAN_HIGH}} vs
> {{MEDIAN_LOW}} months.
>
> **Novelty check:** no prior internal work found in this workspace. Published record shows
> related work on immune infiltration and NSCLC prognosis — this is consistent with, not new
> to, the field.
>
> **Written to memory** as finding #F-118 — attributed to Researcher A, {{date}}, with the
> effect size, cohort, and method. Anyone who asks a related question will now see this first.

---

## Session 2 — the save (new chat, no shared context)

> New session. Different researcher. Nothing in context.

**Researcher (chat, deliberately different wording):**
> Does immune infiltration predict prognosis in lung cancer?

**Cairn agent:**
> Before you run this — a related question has already been explored in your org.
>
> **Internal match (finding #F-118):** Researcher A tested whether a cytotoxic T-cell signature
> predicts overall survival in LUAD and found HR {{HR}}, p={{P}}. Your question ("immune
> infiltration / prognosis / lung cancer") is the same hypothesis in different terms. Running it
> would largely repeat their work.
>
> **⚑ Related abandoned attempt (finding #F-093):** a colleague tried to turn this immune
> signature into a stage-independent prognostic model in Q2 and abandoned it — the effect
> collapsed after adjusting for tumor stage, i.e. the signal was largely tracking stage, not
> independent biology. Their note: "do not re-run without a multivariate, stage-adjusted design."
>
> **Published record:** consistent with both. No internal work found on the stage-adjusted
> question since it was abandoned — that remains genuinely open.

---

## Fallback hypothesis (if the immune split doesn't separate cleanly)

Swap nouns, same arc — same gene, different name, bonus semantic-match demo:

- Session 1: "Is STK11 mutation associated with worse survival in LUAD?"
- Session 2: "Does LKB1 loss affect lung cancer outcomes?"
- Update Finding #F-093 to a mutation-based framing (STK11/LKB1 instead of the cytotoxic signature).

---

## Number-fill checklist (Builder 1, lock by 19:00)

- `{{N_HIGH}}` / `{{N_LOW}}` — cohort sizes of the high/low split
- `{{HR}}` + `{{CI}}` — hazard ratio and confidence interval
- `{{P}}` — log-rank p-value
- `{{MEDIAN_HIGH}}` / `{{MEDIAN_LOW}}` — median OS in months
- `{{date}}` — Session-1 timestamp
