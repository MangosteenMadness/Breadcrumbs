---
id: <feature-id>-tech
title: "<Feature Title> — technical reference"
type: spec
status: draft
domain: <domain>
audience: engineers, AgenticFlow swarm
parity_of: ./components.md
registry: ./components.md
---

# <Feature/Domain> — Technical Reference

The primary feature spec. List each component with grounded `file:line` cites where code exists, mark
missing work honestly as `not-built` or `gap`, and keep component IDs in the same order as `components.md`.

## <AREA> — <area description>

### <DOMAIN>-<AREA>-001 — <short title>
- **Behavior:** <what it does, precisely>
- **Data:** <tables/columns or types involved>
- **Source:** `<path/to/file.ts:LINES>` (or "not-built" if it doesn't exist yet)
- **Status:** planned
- **REQ-001:** <the testable requirement this realizes — mirrors an acceptance_criteria id in feature.json>
