from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ingestion.store import connect


class GraphMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "legacy.db"
        connection = sqlite3.connect(self.path)
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE topic_categories(id TEXT PRIMARY KEY, description TEXT);
            INSERT INTO topic_categories VALUES ('LUAD-immune', 'test');
            CREATE TABLE chat_sessions(
                id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT, scraped_at TEXT NOT NULL,
                raw_json TEXT, updated_at TEXT, researcher TEXT
            );
            INSERT INTO chat_sessions VALUES ('s1', 'https://example.test', 't', 'now', '{}', NULL, NULL);
            CREATE TABLE findings(
                id TEXT PRIMARY KEY, disease TEXT NOT NULL, hypothesis_text TEXT NOT NULL,
                signature TEXT, effect TEXT, n INTEGER,
                status TEXT NOT NULL CHECK(status IN ('confirmed','in-progress','abandoned')),
                author TEXT NOT NULL, timestamp TEXT NOT NULL, provenance TEXT, reason TEXT,
                note TEXT, category TEXT, entities TEXT, source_session_id TEXT, source_type TEXT,
                markdown TEXT, resources TEXT
            );
            CREATE TABLE finding_edges(
                from_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
                to_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
                relationship TEXT NOT NULL CHECK(relationship IN ('extends','contradicts','related-to')),
                created_at TEXT NOT NULL,
                PRIMARY KEY(from_id,to_id,relationship)
            );
            INSERT INTO findings VALUES
                ('F-1','LUAD','q1',NULL,'e1',1,'confirmed','a','now',NULL,NULL,NULL,
                 'LUAD-immune','[]','s1','internal',NULL,NULL),
                ('F-2','LUAD','q2',NULL,'e2',1,'abandoned','a','now',NULL,'because',NULL,
                 'LUAD-immune','[]','s1','internal',NULL,NULL);
            INSERT INTO finding_edges VALUES ('F-1','F-2','related-to','now');
            """
        )
        connection.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_vocabularies_and_edges_are_migrated(self) -> None:
        connection = connect(self.path)
        try:
            findings_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='findings'"
            ).fetchone()[0]
            edges_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='finding_edges'"
            ).fetchone()[0]
            self.assertIn("'open'", findings_sql)
            self.assertIn("'duplicate_of'", edges_sql)
            self.assertNotIn("'related-to'", edges_sql)
            self.assertEqual(connection.execute("SELECT count(*) FROM findings").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT count(*) FROM finding_edges").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT relationship FROM finding_edges").fetchone()[0], "related"
            )
            connection.execute(
                "INSERT INTO finding_edges VALUES ('F-2','F-1','duplicate_of','later')"
            )
            connection.commit()
        finally:
            connection.close()

    def test_migration_is_idempotent_and_preserves_rows(self) -> None:
        for _ in range(2):
            connection = connect(self.path)
            try:
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(connection.execute("SELECT count(*) FROM findings").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT count(*) FROM finding_edges").fetchone()[0], 1)
            finally:
                connection.close()

    def test_external_literature_table_is_not_created(self) -> None:
        connection = connect(self.path)
        try:
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='external_literature'"
                ).fetchone()
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
