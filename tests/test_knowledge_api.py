from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


_TEMP = tempfile.TemporaryDirectory()
_ORIGINAL_DB = os.environ.get("BREADCRUMBS_DB")
_ORIGINAL_EMBEDDINGS = os.environ.get("BREADCRUMBS_EMBEDDINGS")
os.environ["BREADCRUMBS_DB"] = str(Path(_TEMP.name) / "server.db")
os.environ["BREADCRUMBS_EMBEDDINGS"] = "0"

# The server constructs its canonical store at import time, so the isolated DB environment must be
# set first. No production or tracked database is touched by these contract tests.
from breadcrumbs.server import app, mcp  # noqa: E402
from ingestion.store import connect  # noqa: E402


QUOTE = "The patient-level cohort is too small for confirmatory inference."


def payload():
    return {
        "kind": "constraint",
        "proposition": "Treat the TP53 comparison as exploratory at patient level.",
        "rationale": "Spot counts are not independent patient replication.",
        "scope": {"disease": "BLCA", "unit": "patient"},
        "aliases": ["patient-level TP53 constraint"],
        "conditions": [
            {"field": "independent_patients", "operator": "lt", "value": 4, "unit": "patients"}
        ],
        "evidence_quote": QUOTE,
        "source_message_id": "api-session:1",
        "prior_samples": ["disbelieve", "uncertain", "uncertain"],
        "posterior_samples": ["believe", "strongly_believe", "believe"],
        "elicitation_model": "claude-sonnet-5",
        "elicitation_run_id": "api-elicitation-001",
        "action_before": {"interpretation": "confirmatory"},
        "action_after": {"interpretation": "exploratory"},
        "author": "Dr. Chen",
    }


class KnowledgeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        connection = connect(os.environ["BREADCRUMBS_DB"])
        connection.execute(
            "INSERT INTO chat_sessions("
            "id,url,title,scraped_at,researcher,raw_json"
            ") VALUES (?,?,?,?,?,?)",
            (
                "api-session",
                "https://example.test/api",
                "API",
                "2027-01-01T00:00:00Z",
                "Dr. Chen",
                "{}",
            ),
        )
        connection.executemany(
            "INSERT INTO chat_messages(id,session_id,seq,role,content) VALUES (?,?,?,?,?)",
            [
                (
                    "api-session:q",
                    "api-session",
                    0,
                    "user",
                    "How should I interpret TP53 at patient level?",
                ),
                ("api-session:1", "api-session", 1, "assistant", QUOTE),
            ],
        )
        connection.commit()
        connection.close()
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        _TEMP.cleanup()
        if _ORIGINAL_DB is None:
            os.environ.pop("BREADCRUMBS_DB", None)
        else:
            os.environ["BREADCRUMBS_DB"] = _ORIGINAL_DB
        if _ORIGINAL_EMBEDDINGS is None:
            os.environ.pop("BREADCRUMBS_EMBEDDINGS", None)
        else:
            os.environ["BREADCRUMBS_EMBEDDINGS"] = _ORIGINAL_EMBEDDINGS

    def test_mcp_registers_surprise_write_and_recall_tools(self) -> None:
        tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
        self.assertTrue(
            {"score_surprise", "write_knowledge", "recall_knowledge", "find_experts"}
            <= set(tools)
        )
        write_schema = tools["write_knowledge"].inputSchema
        self.assertEqual(set(write_schema["required"]), {"record", "approved_by"})
        self.assertNotIn("approved_by", write_schema["properties"]["record"].get("properties", {}))
        recall = tools["recall_knowledge"]
        self.assertTrue(recall.annotations.readOnlyHint)
        self.assertIn("strict_scope", recall.inputSchema["properties"])
        self.assertTrue(tools["find_experts"].annotations.readOnlyHint)
        self.assertIn("evidence_limit", tools["find_experts"].inputSchema["properties"])

    def test_rest_score_uses_flat_ui_contract(self) -> None:
        response = self.client.post(
            "/knowledge/score",
            json={
                "prior_samples": ["disbelieve", "uncertain", "uncertain"],
                "posterior_samples": ["believe", "strongly_believe", "believe"],
            },
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertGreater(result["posterior_mean"], result["prior_mean"])
        self.assertIn("bayesian_surprise_bits", result)

    def test_rest_approve_then_recall(self) -> None:
        approved = self.client.post(
            "/knowledge", json={"candidate": payload(), "approved_by": "Dr. Chen"}
        )
        recalled = self.client.post(
            "/knowledge/recall",
            json={"query": "TP53 patient", "scope": {"disease": "BLCA"}},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(recalled.status_code, 200)
        self.assertEqual(recalled.json()[0]["id"], approved.json()["id"])
        self.assertIn("retrieval_components", recalled.json()[0])

    def test_rest_rejects_unapproved_candidate(self) -> None:
        candidate = payload()
        response = self.client.post(
            "/knowledge", json={"candidate": candidate, "approved_by": ""}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("approved_by", response.json()["detail"])

    def test_rest_finds_expert_with_calibrated_evidence(self) -> None:
        approved = self.client.post(
            "/knowledge", json={"candidate": payload(), "approved_by": "Dr. Chen"}
        )
        response = self.client.post(
            "/experts/find",
            json={"topic": "TP53 patient inference", "scope": {"disease": "BLCA"}},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["experts"][0]["display_name"], "Dr. Chen")
        self.assertEqual(result["experts"][0]["confidence"], "low")
        self.assertEqual(
            result["active_investigators"][0]["display_name"], "Dr. Chen"
        )
        self.assertFalse(result["active_investigators"][0]["signal_is_expertise"])
        self.assertGreater(
            result["experts"][0]["score_components"]["investigation_activity_bonus"],
            0.0,
        )
        self.assertIn("sources searched", result["message"])

    def test_rest_rejects_reviewer_identity_inside_model_candidate(self) -> None:
        candidate = payload()
        candidate["approved_by"] = "Dr. Model"
        response = self.client.post(
            "/knowledge", json={"candidate": candidate, "approved_by": "Dr. Chen"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("separate approval event", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
