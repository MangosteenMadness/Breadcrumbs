# Spec Refresh Prompt

Use this when a repo already has setupref specs and you want the LLM to update them before or during work.

```text
Refresh this repo's setupref specs from the current code and requested change.

Read AGENTS.md, .spec/repo.json, and the relevant specs/features/<feature-id>/ folder.
Update spec.tech.md, components.md, feature.json, and public scenarios.json together so component IDs, layer blocks, scenarios, and acceptance criteria stay in parity.
If code behavior differs from the spec, record the difference honestly as built-at-parity, gap, not-built, descoped, unverified, planned, or in_progress.
Update evidence.json only with proof you actually ran or reviewed. Use repo-relative pointers to full logs/artifacts under .spec/evidence and keep summaries short.
Add review-queue.md items for unresolved drift, missing evidence, or design ambiguity.
```
