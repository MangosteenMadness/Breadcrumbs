from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ingestion.store import connect
from breadcrumbs.store import CairnStore


def finding(**changes):
    value = {
        "category": "LUAD-immune",
        "disease": "LUAD",
        "hypothesis_text": "High cytotoxic T-cell infiltration predicts better overall survival in LUAD",
        "entities": ["CD8A", "GZMB", "PRF1", "GZMK"],
        "effect": "HR 0.58 (95% CI 0.41-0.82), p=0.002",
        "status": "confirmed",
        "reason": None,
        "author": "Aisha Rahman",
        "created_at": "2027-01-02T03:04:05+00:00",
        "source_session_id": "sess-2027",
    }
    value.update(changes)
    return value


class CairnStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "cairn.db"
        connection = connect(self.path)
        connection.execute(
            "INSERT INTO chat_sessions(id,url,title,scraped_at,raw_json) VALUES (?,?,?,?,?)",
            ("sess-2027", "https://example.test/chat/sess-2027", "test", "2027-01-01T00:00:00Z", "{}"),
        )
        connection.commit()
        connection.close()
        self.store = CairnStore(self.path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_write_and_read_shared_schema(self) -> None:
        written = self.store.write(finding())
        self.assertTrue(written["id"].startswith("F-"))
        rows = self.store.read("disease", "LUAD")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entities"], ["CD8A", "GZMB", "PRF1", "GZMK"])

    def test_normalizes_entities_with_team_writer(self) -> None:
        written = self.store.write(finding(entities=["LKB1", "ajcc stage"]))
        self.assertEqual(written["entities"], ["STK11", "AJCC_STAGE"])

    def test_supports_agent_facing_column_aliases(self) -> None:
        self.store.write(finding())
        self.assertEqual(len(self.store.read("created_at", "2027-01-02T03:04:05+00:00")), 1)
        self.assertEqual(len(self.store.read("source_session", "sess-2027")), 1)

    def test_rejects_unknown_column(self) -> None:
        with self.assertRaises(ValueError):
            self.store.read("disease OR 1=1", "LUAD")

    def test_requires_ingested_source_session(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown source session"):
            self.store.write(finding(source_session_id="missing"))


if __name__ == "__main__":
    unittest.main()
