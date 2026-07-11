"""The spec tree must stay valid, and the parity gate must actually bite.

The two regex tests below are not academic. Both cases fail against the upstream AgenticFlow
validator, and both appear throughout Cairn's real specs — findings are named F-093 / F-118,
and spec.tech.md is built out of `file:line` citations.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.setupref_validate import scrape_component_ids, validate

ROOT = Path(__file__).resolve().parents[1]


class SpecTreeTests(unittest.TestCase):
    def test_repo_spec_tree_is_valid(self):
        findings = validate(ROOT)
        self.assertEqual(
            [f"{code}: {where}: {message}" for level, code, where, message in findings.errors],
            [],
        )

    def test_every_feature_is_specified(self):
        features = {d.name for d in (ROOT / "specs" / "features").iterdir() if d.is_dir()}
        self.assertEqual(
            features,
            {"graph-store", "research-memory-tools", "survival-analysis", "demo-flow"},
        )


class ComponentScrapeTests(unittest.TestCase):
    def test_finding_ids_are_not_components(self):
        """F-093 matches the component-ID shape but is a finding. Upstream scrapes it; we must not."""
        self.assertEqual(scrape_component_ids("CRN-GRAPH-001 supersedes F-093 and F-118."), ["CRN-GRAPH-001"])

    def test_line_range_citations_are_not_components(self):
        """`store.py:46-149` matches upstream's regex because its first segment admits bare digits."""
        self.assertEqual(scrape_component_ids("- **Source:** `ingestion/store.py:46-149`"), [])

    def test_requirement_and_scenario_ids_are_not_components(self):
        self.assertEqual(scrape_component_ids("REQ-001 AC-002 SCN-003 HOLDOUT-004"), [])

    def test_components_are_ordered_and_deduped(self):
        text = "CRN-MCP-002 then CRN-MCP-001 then CRN-MCP-002 again"
        self.assertEqual(scrape_component_ids(text), ["CRN-MCP-002", "CRN-MCP-001"])


class ParityGateTests(unittest.TestCase):
    def test_reordered_registry_is_rejected(self):
        """Reorder two components in the registry and the tree must stop validating."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(ROOT / ".spec", repo / ".spec")
            shutil.copytree(ROOT / "specs", repo / "specs")
            (repo / "AGENTS.md").write_text("stub", encoding="utf-8")

            feature = repo / "specs" / "features" / "graph-store"
            declared = json.loads((feature / "feature.json").read_text(encoding="utf-8"))["component_ids"]
            self.assertEqual(validate(repo).errors, [], "the copied tree should start valid")

            registry = feature / "components.md"
            text = registry.read_text(encoding="utf-8")
            swapped = text.replace(declared[0], "TMP-TMP-999").replace(declared[1], declared[0])
            registry.write_text(swapped.replace("TMP-TMP-999", declared[1]), encoding="utf-8")

            codes = {code for _, code, _, _ in validate(repo).errors}
            self.assertIn("component-parity", codes)

    def test_schema_pinned_to_the_wrong_feature_is_rejected(self):
        """The bug upstream ships with: a schema.json pinning another feature's id validates clean."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(ROOT / ".spec", repo / ".spec")
            shutil.copytree(ROOT / "specs", repo / "specs")

            schema_path = repo / "specs" / "features" / "graph-store" / "schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["properties"]["feature_id"]["const"] = "graph-storage"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            codes = {code for _, code, _, _ in validate(repo).errors}
            self.assertIn("schema-id-mismatch", codes)


if __name__ == "__main__":
    unittest.main()
