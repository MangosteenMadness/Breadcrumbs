import tempfile
import unittest
from pathlib import Path

from ingestion.ingest_chat import extract_messages, humanize_kpro_markdown, load_from_file
from ingestion.store import connect, extract_sections, upsert_session
from ingestion.write_findings import write_payload


class IngestionTests(unittest.TestCase):
    def test_extracts_ordered_role_labelled_turns(self):
        payload = {"data": {"messages": [
            {"role": "user", "blocks": [{"type": "text", "semantic_type": "main", "content": "Does immune infiltration predict prognosis?"}], "createdAt": "2026-01-01"},
            {"role": "assistant", "blocks": [
                {"type": "text", "semantic_type": "main", "content": "I will analyze it."},
                {"type": "text", "semantic_type": "thought", "content": "Hidden reasoning"},
                {"type": "plot", "semantic_type": "main", "content": {"title": "chart"}},
            ]},
        ]}}
        turns = extract_messages(payload)
        self.assertEqual([(turn["seq"], turn["role"]) for turn in turns], [(0, "user"), (1, "assistant")])
        self.assertEqual(turns[1]["content"], "I will analyze it.")

    def test_upsert_replaces_previous_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "cairn.db")
            upsert_session(connection, session_id="chat", url="https://example.test/chat/chat", title=None, raw_payload={}, messages=[
                {"seq": 0, "role": "user", "content": "old"},
            ])
            upsert_session(connection, session_id="chat", url="https://example.test/chat/chat", title="new", raw_payload={}, messages=[
                {"seq": 0, "role": "user", "content": "new"},
                {"seq": 1, "role": "assistant", "content": "answer"},
            ])
            self.assertEqual(connection.execute("SELECT count(*) FROM chat_messages").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT content FROM chat_messages WHERE seq = 0").fetchone()[0], "new")
            connection.close()

    def test_parses_labelled_text_recovery_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "captured.txt"
            path.write_text("Researcher: Question\nAssistant: Answer", encoding="utf-8")
            _, payload = load_from_file(path)[0]
            self.assertEqual([turn["role"] for turn in extract_messages(payload)], ["user", "assistant"])

    def test_removes_kpro_renderer_directives(self):
        self.assertEqual(humanize_kpro_markdown(":legend-item[breast]{color=#fff}"), "breast")

    def test_extracts_second_and_third_level_categories(self):
        sections = extract_sections("## Population Overview\nTable\n### Breast\nDetails")
        self.assertEqual([(item["heading"], item["level"], item["content"]) for item in sections], [
            ("Population Overview", 2, "Table"),
            ("Breast", 3, "Details"),
        ])

    def test_one_session_can_write_multiple_findings_and_an_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "cairn.db")
            upsert_session(connection, session_id="sess-2027", url="https://example.test/chat/sess-2027", title=None,
                           raw_payload={}, messages=[{"seq": 0, "role": "user", "content": "question"}])
            write_payload(connection, {"findings": [
                {"id": "F-118", "category": "LUAD-immune", "disease": "LUAD", "hypothesis_text": "first",
                 "entities": ["CD8A"], "effect": "HR 0.58", "status": "confirmed", "reason": None,
                 "author": "Aisha", "created_at": "2027-01-01T00:00:00Z", "source_session_id": "sess-2027"},
                {"id": "F-119", "category": "LUAD-immune", "disease": "LUAD", "hypothesis_text": "second",
                 "entities": ["LKB1", "AJCC_stage"], "effect": "HR 0.79", "status": "abandoned", "reason": "stage",
                 "author": "Aisha", "created_at": "2027-01-01T00:00:00Z", "source_session_id": "sess-2027"},
            ], "edges": [{"from_id": "F-119", "to_id": "F-118", "relationship": "extends"}]})
            self.assertEqual(connection.execute("SELECT count(*) FROM findings").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT entities FROM findings WHERE id = 'F-119'").fetchone()[0], '["STK11", "AJCC_STAGE"]')
            self.assertEqual(connection.execute("SELECT count(*) FROM finding_edges").fetchone()[0], 1)
            connection.close()


if __name__ == "__main__":
    unittest.main()
