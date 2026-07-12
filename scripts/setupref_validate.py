"""Validate the repo's setupref spec tree.

A Python port of AgenticFlow's `setupref validate` (src/setupref/setupref.ts), so this
Python repo can gate its own specs without a Node toolchain.

The load-bearing check is COMPONENT PARITY: the same component IDs, in the same order,
across spec.tech.md, components.md, and feature.json's component_ids. That is what stops
a spec from quietly drifting away from its own registry.

Usage:
    python scripts/setupref_validate.py            # exit 0 clean, 4 if any error
    python scripts/setupref_validate.py --repo .
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXIT_ERROR = 4

REQUIRED_FEATURE_FILES = (
    "spec.tech.md",
    "components.md",
    "feature.json",
    "schema.json",
    "scenarios.json",
    "evidence.json",
    "review-queue.md",
)

REQUIRED_REPO_FIELDS = (
    "setupRefVersion",
    "repo",
    "owners",
    "data_classification",
    "layers",
    "specConfig",
)

FEATURE_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# A component ID must START WITH A LETTER. Upstream uses `[A-Z0-9]+(?:-[A-Z0-9]+)*-[0-9]{3}`,
# whose first segment admits bare digits — so a line-range citation like `store.py:46-149`
# is scraped as a component named "46-149" and parity fails. spec.tech.md is built out of
# `file:line` cites, so that misfires constantly. Anchoring on `[A-Z]` costs nothing and
# leaves real IDs (CRN-GRAPH-001) matching.
COMPONENT_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-[0-9]{3}\b")
REQUIREMENT_ID_RE = re.compile(r"^(REQ|AC)-[0-9]{3}$")
SCENARIO_ID_RE = re.compile(r"^SCN-[0-9]{3}$")

# Tokens that match COMPONENT_ID_RE but are not component IDs.
#
# `F` is the one that matters here and is absent upstream: Breadcrumbs' findings are named
# F-093 / F-118 and are cited constantly throughout these specs. Without this exclusion,
# every mention of a finding is scraped as a phantom component and parity fails with an
# error that makes no sense to whoever reads it.
NON_COMPONENT_PREFIXES = ("REQ", "AC", "SCN", "HOLDOUT", "F")
NON_COMPONENT_RE = re.compile(
    r"^(" + "|".join(NON_COMPONENT_PREFIXES) + r")-[0-9]{3}$"
)

# A repo-local spec tree must not reach back into the repo it was scaffolded from.
FOREIGN_REF_TOKENS = ("agenticflow", "setupref/schemas", "C:\\", "/Users/", "<repo>")


class Findings:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str, str]] = []

    def error(self, code: str, where: str, message: str) -> None:
        self.items.append(("error", code, where, message))

    def warn(self, code: str, where: str, message: str) -> None:
        self.items.append(("warn", code, where, message))

    @property
    def errors(self) -> list[tuple[str, str, str, str]]:
        return [item for item in self.items if item[0] == "error"]


def scrape_component_ids(text: str) -> list[str]:
    """Ordered component IDs in a spec doc, minus requirement/scenario/finding IDs."""
    ordered: list[str] = []
    for match in COMPONENT_ID_RE.findall(text):
        if NON_COMPONENT_RE.match(match):
            continue
        if match not in ordered:
            ordered.append(match)
    return ordered


def load_json(path: Path, findings: Findings, where: str) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        findings.error("missing-file", where, f"{path.name} does not exist")
    except json.JSONDecodeError as exc:
        findings.error("invalid-json", where, f"{path.name} does not parse: {exc}")
    return None


def validate_repo_config(root: Path, findings: Findings) -> dict[str, Any]:
    repo_json = root / ".spec" / "repo.json"
    where = ".spec/repo.json"
    config = load_json(repo_json, findings, where) or {}
    if not config:
        return {}

    for field in REQUIRED_REPO_FIELDS:
        if field not in config:
            findings.error("missing-field", where, f"required field {field!r} is absent")

    spec_config = config.get("specConfig", {})
    if spec_config.get("parityModel") != "single":
        findings.error(
            "unsupported-parity-model",
            where,
            "specConfig.parityModel must be 'single' (the dual-doc model is archived)",
        )

    if not (root / ".spec" / "schemas" / "root.schema.json").exists():
        findings.error(
            "missing-schemas",
            ".spec/schemas",
            "root.schema.json is absent — the repo must carry its own copy of the schemas",
        )

    if not (root / "AGENTS.md").exists():
        findings.warn("missing-agents", "AGENTS.md", "no root AGENTS.md — agents have no entry point")

    return config


def validate_feature(feature_dir: Path, root: Path, findings: Findings) -> None:
    feature_id = feature_dir.name
    where = f"specs/features/{feature_id}"

    if not FEATURE_ID_RE.match(feature_id):
        findings.error("bad-feature-id", where, f"{feature_id!r} is not kebab-case")

    missing = [name for name in REQUIRED_FEATURE_FILES if not (feature_dir / name).exists()]
    if missing:
        findings.error("missing-artifact", where, f"missing required file(s): {', '.join(missing)}")
        return

    feature = load_json(feature_dir / "feature.json", findings, f"{where}/feature.json")
    scenarios = load_json(feature_dir / "scenarios.json", findings, f"{where}/scenarios.json")
    evidence = load_json(feature_dir / "evidence.json", findings, f"{where}/evidence.json")
    schema = load_json(feature_dir / "schema.json", findings, f"{where}/schema.json")
    if feature is None or scenarios is None or evidence is None or schema is None:
        return

    # The folder name is the feature's identity; every instance file must agree with it.
    for name, doc in (("feature.json", feature), ("scenarios.json", scenarios), ("evidence.json", evidence)):
        if doc.get("feature_id") != feature_id:
            findings.error(
                "feature-id-mismatch",
                f"{where}/{name}",
                f"feature_id is {doc.get('feature_id')!r} but the folder is {feature_id!r}",
            )

    validate_parity(feature_dir, feature, feature_id, where, findings)
    validate_schema_ref(schema, feature_id, where, findings)
    validate_requirements(feature, scenarios, where, findings)
    validate_evidence(feature_dir, evidence, root, where, findings)


def validate_parity(
    feature_dir: Path, feature: dict[str, Any], feature_id: str, where: str, findings: Findings
) -> None:
    declared = feature.get("component_ids", [])
    in_spec = scrape_component_ids((feature_dir / "spec.tech.md").read_text(encoding="utf-8"))
    in_registry = scrape_component_ids((feature_dir / "components.md").read_text(encoding="utf-8"))

    for component_id in declared:
        if NON_COMPONENT_RE.match(component_id) or not COMPONENT_ID_RE.fullmatch(component_id):
            findings.error(
                "bad-component-id",
                f"{where}/feature.json",
                f"{component_id!r} is not a valid <DOMAIN>-<AREA>-NNN component ID",
            )

    if in_spec != declared:
        findings.error(
            "component-parity",
            where,
            f"spec.tech.md components {in_spec} != feature.json component_ids {declared}",
        )
    if in_registry != declared:
        findings.error(
            "component-parity",
            where,
            f"components.md components {in_registry} != feature.json component_ids {declared}",
        )


def validate_schema_ref(schema: dict[str, Any], feature_id: str, where: str, findings: Findings) -> None:
    raw = json.dumps(schema)
    for token in FOREIGN_REF_TOKENS:
        if token in raw:
            findings.error(
                "nonlocal-schema-ref",
                f"{where}/schema.json",
                f"references {token!r} — the spec tree must be self-contained and repo-relative",
            )

    # Upstream does NOT check this, and upstream's own repo has the bug: a feature whose
    # schema.json pins a feature_id const from a different feature still validates clean.
    pinned = schema.get("properties", {}).get("feature_id", {}).get("const")
    if pinned != feature_id:
        findings.error(
            "schema-id-mismatch",
            f"{where}/schema.json",
            f"pins feature_id const {pinned!r} but the folder is {feature_id!r}",
        )


def validate_requirements(
    feature: dict[str, Any], scenarios: dict[str, Any], where: str, findings: Findings
) -> None:
    requirement_ids = set()
    for criterion in feature.get("acceptance_criteria", []):
        req_id = criterion.get("id", "")
        if not REQUIREMENT_ID_RE.match(req_id):
            findings.error(
                "bad-requirement-id", f"{where}/feature.json", f"{req_id!r} is not REQ-NNN or AC-NNN"
            )
        requirement_ids.add(req_id)
        if criterion.get("coverage") == "automated_check" and not criterion.get("command"):
            findings.error(
                "unverifiable-criterion",
                f"{where}/feature.json",
                f"{req_id} claims automated_check but names no command",
            )

    for scenario in scenarios.get("scenarios", []):
        scn_id = scenario.get("id", "")
        if not SCENARIO_ID_RE.match(scn_id):
            findings.error("bad-scenario-id", f"{where}/scenarios.json", f"{scn_id!r} is not SCN-NNN")
        for linked in scenario.get("linked_requirements", []):
            if linked not in requirement_ids:
                findings.error(
                    "dangling-requirement",
                    f"{where}/scenarios.json",
                    f"{scn_id} links {linked}, which no acceptance criterion defines",
                )


def validate_evidence(
    feature_dir: Path, evidence: dict[str, Any], root: Path, where: str, findings: Findings
) -> None:
    max_inline = 500
    items = evidence.get("items", [])

    for item in items:
        item_id = item.get("id", "<unknown>")
        summary = item.get("summary") or ""
        if len(summary) > max_inline:
            findings.error(
                "inline-evidence-too-long",
                f"{where}/evidence.json",
                f"{item_id} inlines {len(summary)} chars; evidence is pointer-based (max {max_inline})",
            )

        for key in ("logPath", "reviewPath"):
            pointer = item.get(key)
            if not pointer:
                continue
            if Path(pointer).is_absolute() or re.match(r"^[A-Za-z]:", pointer):
                findings.error(
                    "absolute-evidence-path",
                    f"{where}/evidence.json",
                    f"{item_id} {key} is absolute; pointers must be repo-relative",
                )
            elif item.get("satisfied") and not (root / pointer).exists():
                findings.error(
                    "missing-evidence-pointer",
                    f"{where}/evidence.json",
                    f"{item_id} is satisfied but its evidence at {pointer} does not exist",
                )

        if item.get("satisfied") and item.get("exitCode") not in (None, 0):
            findings.error(
                "satisfied-with-failure",
                f"{where}/evidence.json",
                f"{item_id} is satisfied but recorded a non-zero exit code",
            )

    if evidence.get("complete"):
        unsatisfied = [i.get("id") for i in items if not i.get("satisfied")]
        if unsatisfied:
            findings.error(
                "incomplete-evidence",
                f"{where}/evidence.json",
                f"complete: true but these items are unsatisfied: {', '.join(map(str, unsatisfied))}",
            )
        if has_open_error(feature_dir / "review-queue.md"):
            findings.error(
                "complete-with-open-error",
                f"{where}/review-queue.md",
                "complete: true while the review queue still holds an open error",
            )


def has_open_error(review_queue: Path) -> bool:
    """A blocking row is a table row carrying both an `error` severity and `open` status."""
    for line in review_queue.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip().lower() for cell in line.split("|")]
        if "error" in cells and "open" in cells:
            return True
    return False


def validate(root: Path) -> Findings:
    findings = Findings()
    config = validate_repo_config(root, findings)
    features_dir = root / config.get("specConfig", {}).get("featuresDir", "specs/features")

    if not features_dir.is_dir():
        findings.error("missing-features-dir", str(features_dir), "no features directory")
        return findings

    feature_dirs = sorted(d for d in features_dir.iterdir() if d.is_dir())
    if not feature_dirs:
        findings.warn("no-features", str(features_dir), "no features are specified yet")

    for feature_dir in feature_dirs:
        validate_feature(feature_dir, root, findings)

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the setupref spec tree.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    root = args.repo.resolve()
    findings = validate(root)

    for level, code, where, message in findings.items:
        print(f"[{level}] {code}: {where}: {message}")

    errors = len(findings.errors)
    warnings = len(findings.items) - errors
    if errors:
        print(f"\nFAIL — {errors} error(s), {warnings} warning(s)")
        return EXIT_ERROR

    print(f"OK — spec tree valid ({warnings} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
