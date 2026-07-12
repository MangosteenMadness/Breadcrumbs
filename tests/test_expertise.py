from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from breadcrumbs.store import BreadcrumbsStore
from ingestion.store import connect


class ExpertiseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "expertise.db"
        connection = connect(self.path)
        sessions = [
            ("expert-s1", "https://example.test/1", "One", "2027-01-01T00:00:00Z", "{}"),
            ("expert-s2", "https://example.test/2", "Two", "2027-01-02T00:00:00Z", "{}"),
            ("expert-s3", "https://example.test/3", "Three", "2027-01-03T00:00:00Z", "{}"),
        ]
        connection.executemany(
            "INSERT INTO chat_sessions(id,url,title,scraped_at,raw_json) VALUES (?,?,?,?,?)",
            sessions,
        )
        self.quotes = {
            "expert-s1:1": "Use independent patients for TP53 inference, not spot counts alone.",
            "expert-s1:2": "The TP53 patient model should include cohort-level covariates.",
            "expert-s2:1": "We abandoned spot-count-only TP53 inference because patients confound it.",
            "expert-s3:1": "Replicate TP53 patient inference in an independent BLCA cohort.",
        }
        connection.executemany(
            "INSERT INTO chat_messages(id,session_id,seq,role,content) VALUES (?,?,?,?,?)",
            [
                (message_id, message_id.split(":")[0], int(message_id.split(":")[1]), "assistant", quote)
                for message_id, quote in self.quotes.items()
            ],
        )
        connection.commit()
        connection.close()
        self.store = BreadcrumbsStore(self.path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def knowledge(self, message_id: str, proposition: str, *, author: str, **changes):
        record = {
            "kind": "decision",
            "proposition": proposition,
            "rationale": "Independent patient evidence changes whether the TP53 result generalizes.",
            "scope": {"disease": "BLCA", "comparison": "TP53"},
            "aliases": [],
            "conditions": [],
            "evidence_quote": self.quotes[message_id],
            "source_message_id": message_id,
            "prior_samples": ["uncertain", "uncertain", "disbelieve"],
            "posterior_samples": ["believe", "strongly_believe", "believe"],
            "elicitation_model": "claude-sonnet-5",
            "elicitation_run_id": f"expertise-{message_id}",
            "action_before": {"interpretation": "confirmatory"},
            "action_after": {"interpretation": "patient-qualified"},
            "author": author,
            "approved_by": "Dr. Reviewer",
        }
        record.update(changes)
        return self.store.write_knowledge(record)

    def seed_expertise(self) -> None:
        self.knowledge(
            "expert-s1:1",
            "Require independent patients for TP53 inference rather than relying on spot counts.",
            author="Dr. Chen",
        )
        self.knowledge(
            "expert-s1:2",
            "Include cohort-level covariates in the TP53 patient model.",
            author="Dr. Chen",
        )
        self.knowledge(
            "expert-s2:1",
            "Do not use spot-count-only TP53 patient inference.",
            author="  dr.   chen ",
            kind="abandoned",
            reason="Patient-level confounding invalidated the approach.",
        )
        self.knowledge(
            "expert-s3:1",
            "Replicate TP53 patient inference in an independent BLCA cohort.",
            author="Dr. Alvarez",
        )
        self.store.write(
            {
                "id": "F-EXPERT-1",
                "category": "LUAD-immune",
                "disease": "BLCA",
                "hypothesis_text": "Test TP53 patient inference in an independent cohort.",
                "entities": ["TP53"],
                "effect": "No effect size was calculated in this synthetic fixture.",
                "status": "in-progress",
                "author": "Dr. Alvarez",
                "source_session_id": "expert-s3",
                "source_type": "internal",
            }
        )

    def test_storage_canonicalizes_people_and_backfills_contribution_roles(self) -> None:
        self.seed_expertise()
        connection = connect(self.path)
        try:
            chen = connection.execute(
                "SELECT id, display_name, identity_status FROM people "
                "WHERE normalized_name = 'dr. chen'"
            ).fetchall()
            roles = connection.execute(
                "SELECT role, COUNT(*) AS n FROM person_contributions "
                "GROUP BY role ORDER BY role"
            ).fetchall()
            with connection:
                connection.execute("DELETE FROM person_contributions")
                connection.execute("DELETE FROM people")
        finally:
            connection.close()

        self.assertEqual(len(chen), 1)
        self.assertEqual(chen[0]["identity_status"], "provisional")
        self.assertEqual(
            {row["role"]: row["n"] for row in roles},
            {"finding_author": 1, "knowledge_author": 4, "knowledge_reviewer": 4},
        )

        BreadcrumbsStore(self.path)
        BreadcrumbsStore(self.path)
        connection = connect(self.path)
        try:
            people_count = connection.execute("SELECT COUNT(*) FROM people").fetchone()[0]
            edge_count = connection.execute(
                "SELECT COUNT(*) FROM person_contributions"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(people_count, 3)
        self.assertEqual(edge_count, 9)

    def test_find_experts_caps_sessions_keeps_abandoned_and_excludes_review_only(self) -> None:
        self.seed_expertise()

        result = self.store.find_experts(
            "TP53 patient inference", scope={"disease": "BLCA"}
        )

        self.assertEqual(result["ranking_method"]["id"], "expertise_evidence_v1")
        self.assertFalse(result["ranking_method"]["score_is_probability"])
        self.assertEqual(
            [person["display_name"] for person in result["experts"]],
            ["Dr. Chen", "Dr. Alvarez"],
        )
        chen = result["experts"][0]
        self.assertEqual(chen["distinct_sessions"], 2)
        self.assertEqual(chen["primary_evidence_count"], 3)
        self.assertEqual(chen["confidence"], "moderate")
        self.assertLessEqual(chen["score_components"]["session_capped_evidence"], 2.0)
        abandoned = [item for item in chen["evidence"] if item["kind"] == "abandoned"]
        self.assertEqual(len(abandoned), 1)
        self.assertIn("confounding", abandoned[0]["reason"])
        self.assertNotIn("Dr. Reviewer", [p["display_name"] for p in result["experts"]])
        self.assertIn("strongest demonstrated experience", result["message"])
        self.assertIn("not a definitive organizational title", result["message"])
        natural_question = self.store.find_experts(
            "Who is the TP53 patient-inference expert at our company?",
            scope={"disease": "BLCA"},
        )
        self.assertEqual(natural_question["experts"][0]["display_name"], "Dr. Chen")

    def test_find_experts_empty_result_is_calibrated_and_validates_limits(self) -> None:
        result = self.store.find_experts("metabolomics instrument calibration")
        self.assertEqual(result["experts"], [])
        self.assertEqual(result["searched_sources"], ["knowledge_items", "findings"])
        self.assertIn("sources searched", result["message"])
        with self.assertRaisesRegex(ValueError, "topic"):
            self.store.find_experts("...")
        with self.assertRaisesRegex(ValueError, "limit"):
            self.store.find_experts("TP53", limit=0)


if __name__ == "__main__":
    unittest.main()
