# Repo Bootstrap Prompt

Use this when a target repo has not adopted setupref yet.

```text
Adopt AgenticFlow setupref spec-driven development for this repo.

Source kit:
<path to AgenticFlow/setupref>

Target repo:
<path to this repo>

Do this end to end:
1. Read setupref/README.md, setupref/manifest.json, setupref/schemas/, setupref/templates/feature/, setupref/agents/, setupref/roles/, and setupref/prompts/.
2. Inspect the target repo structure, package manager, frameworks, test commands, architectural layers, and major feature/folder boundaries.
3. Create repo-local setup artifacts:
   - .spec/repo.json
   - .spec/schemas/
   - root AGENTS.md
   - layer AGENTS.md files where useful
   - specs/features/<feature-id>/ folders
4. Use the active single-spec model only:
   - spec.tech.md
   - components.md
   - feature.json
   - schema.json
   - scenarios.json
   - evidence.json
   - review-queue.md
5. Keep component IDs in the same order across spec.tech.md, components.md, and feature.json.
6. Add public scenarios and holdout-suite pointers. Keep hidden holdout details out of the implementation prompt.
7. Mark existing implementation honestly as built-at-parity, gap, not-built, descoped, unverified, planned, or in_progress.
8. Do not leave target-repo schemas or instructions depending on an absolute AgenticFlow path; copy what the repo needs locally.
9. After bootstrap, write a short handoff explaining how future LLM chats should use the repo-local .spec/, specs/, and AGENTS.md files without pointing back to setupref.
```
