# Spec-Driven Development Prompt

Use this in a fresh LLM chat after setupref has been bootstrapped into the target repo.

```text
This repo uses AgenticFlow setupref spec-driven development.

Read the repo-local instructions and specs first:
1. AGENTS.md
2. .spec/repo.json
3. specs/features/*/spec.tech.md
4. specs/features/*/components.md
5. specs/features/*/feature.json
6. specs/features/*/scenarios.json
7. specs/features/*/evidence.json and review-queue.md

Then proceed with spec-driven development:
- Audit the current repo structure and identify feature/layer boundaries.
- Create or refresh detailed hierarchical feature specs under specs/features/.
- Keep component IDs in the same order across spec.tech.md, components.md, and feature.json.
- For implementation, work in layer order: contract, database, backend, frontend.
- Record deterministic proof in evidence.json using repo-relative pointers to logs/artifacts under .spec/evidence; do not paste full logs into specs.
- Use public scenarios while implementing. Do not read .spec/holdouts before implementation; QA/harnesses run holdout suites after.
- Do not mark a feature complete while any evidence item is unsatisfied or review-queue.md has an open error.
- Use AgenticFlow/setupref only if explicitly upgrading the methodology version; otherwise the repo-local files are the source of truth.
```
