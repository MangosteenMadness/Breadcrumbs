import tempfile
import unittest
from pathlib import Path

from ingestion.ingest_chat import (
    CapturedPayload,
    extract_messages,
    find_title,
    humanize_kpro_markdown,
    load_from_file,
    payload_for_chat,
    slim_raw_payload,
)
from ingestion.store import TRANSCRIPTS_DIR, connect, extract_sections, ingested_revisions, upsert_session
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
            connection = connect(Path(directory) / "breadcrumbs.db")
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

    def test_third_level_categories_nest_under_their_second_level_parent(self):
        sections = extract_sections(
            "## Indication-Specific Summary\n### Mesothelioma\nA\n### Non small cell lung cancer\nB\n## Clinical Summary\nC"
        )
        self.assertEqual(
            [(item["heading"], item["level"], item["parent_seq"], item["path"]) for item in sections],
            [
                ("Indication-Specific Summary", 2, None, "Indication-Specific Summary"),
                ("Mesothelioma", 3, 0, "Indication-Specific Summary > Mesothelioma"),
                ("Non small cell lung cancer", 3, 0, "Indication-Specific Summary > Non small cell lung cancer"),
                ("Clinical Summary", 2, None, "Clinical Summary"),
            ],
        )

    def test_section_parent_edges_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "breadcrumbs.db")
            upsert_session(connection, session_id="chat", url="https://example.test/chat/chat", title=None,
                           raw_payload={}, messages=[{"seq": 0, "role": "assistant",
                                                      "content": "## Parent\nintro\n### Child\ndetail"}])
            rows = connection.execute(
                "SELECT heading, level, parent_id, path FROM chat_message_sections ORDER BY seq"
            ).fetchall()
            self.assertEqual(rows[0]["parent_id"], None)
            self.assertEqual(rows[1]["parent_id"], "chat:0:section:0")
            self.assertEqual(rows[1]["path"], "Parent > Child")
            connection.close()

    def test_title_comes_from_the_chat_not_another_endpoint(self):
        # Regression: the organization name ("Default") from /api/user was being stored as
        # every chat's title. Only a payload carrying this chat's own id may name it.
        session_id = "54ecc674-7485-4a18-ac95-a3be5f233ec7"
        payloads = [
            CapturedPayload("https://k.owkin.com/api/user", {"organization": {"name": "Default"}}),
            CapturedPayload(f"https://k.owkin.com/api/chats/{session_id}", {"id": session_id, "name": "SYPL1 across MOSAIC"}),
        ]
        self.assertEqual(find_title(payloads, session_id), "SYPL1 across MOSAIC")

    def test_another_chats_payload_is_never_filed_under_this_chat(self):
        # Regression: a "any payload with turns" fallback could attach chat B's messages to
        # chat A's id. A chat whose own payload never arrived must yield nothing.
        other = {"messages": [{"role": "user", "blocks": [{"type": "text", "content": "someone else's chat"}]}]}
        payloads = [CapturedPayload("https://k.owkin.com/api/chats/bbbbbbbb-0000-0000-0000-000000000000/messages", other)]
        self.assertIsNone(payload_for_chat(payloads, "aaaaaaaa-0000-0000-0000-000000000000"))

    def test_revisions_support_skipping_unchanged_chats(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "breadcrumbs.db")
            upsert_session(connection, session_id="chat", url="https://example.test/chat/chat", title="t",
                           raw_payload={}, messages=[{"seq": 0, "role": "user", "content": "q"}],
                           updated_at="2026-07-11T23:42:18Z")
            self.assertEqual(ingested_revisions(connection), {"chat": "2026-07-11T23:42:18Z"})
            connection.close()

    def test_transcript_includes_turn_seq_timestamp_and_researcher(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "breadcrumbs.db")
            session_id = "transcript-meta-test"
            path = TRANSCRIPTS_DIR / f"{session_id}.md"
            try:
                upsert_session(
                    connection, session_id=session_id, url="https://example.test/chat/transcript-meta-test",
                    title="Meta test", raw_payload={}, messages=[
                        {"seq": 0, "role": "user", "content": "q", "created_at": "2026-01-01T00:00:00Z"},
                        {"seq": 1, "role": "assistant", "content": "a"},
                    ], researcher="Aisha",
                )
                text = path.read_text(encoding="utf-8")
                self.assertIn("Researcher: Aisha", text)
                self.assertIn("## Researcher (turn 0 · 2026-01-01T00:00:00Z)", text)
                self.assertIn("## K Pro (turn 1)", text)
            finally:
                connection.close()
                path.unlink(missing_ok=True)

    def test_researcher_persists_across_reingest_when_omitted(self):
        # A --recent re-run that forgets --author must not blank out who ran the original ingest.
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "breadcrumbs.db")
            session_id = "transcript-persist-test"
            path = TRANSCRIPTS_DIR / f"{session_id}.md"
            try:
                upsert_session(connection, session_id=session_id, url="https://example.test/chat/transcript-persist-test",
                                title=None, raw_payload={}, messages=[{"seq": 0, "role": "user", "content": "first"}],
                                researcher="Aisha")
                upsert_session(connection, session_id=session_id, url="https://example.test/chat/transcript-persist-test",
                                title=None, raw_payload={}, messages=[
                                    {"seq": 0, "role": "user", "content": "first"},
                                    {"seq": 1, "role": "assistant", "content": "second"},
                                ])
                self.assertEqual(
                    connection.execute("SELECT researcher FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()[0],
                    "Aisha",
                )
                self.assertIn("Researcher: Aisha", path.read_text(encoding="utf-8"))
            finally:
                connection.close()
                path.unlink(missing_ok=True)

    def test_ingesting_one_chat_does_not_disturb_another(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "breadcrumbs.db")
            upsert_session(connection, session_id="chat-a", url="https://example.test/chat/chat-a", title="A",
                           raw_payload={}, messages=[{"seq": 0, "role": "user", "content": "first"}])
            upsert_session(connection, session_id="chat-b", url="https://example.test/chat/chat-b", title="B",
                           raw_payload={}, messages=[{"seq": 0, "role": "user", "content": "second"}])
            self.assertEqual(connection.execute("SELECT count(*) FROM chat_sessions").fetchone()[0], 2)
            self.assertEqual(
                connection.execute("SELECT content FROM chat_messages WHERE session_id = 'chat-a'").fetchone()[0],
                "first",
            )
            connection.close()

    def test_heavy_plot_blocks_are_stripped_but_text_is_kept(self):
        payload = {"messages": [{"role": "assistant", "blocks": [
            {"type": "text", "semantic_type": "main", "content": "The key finding is X."},
            {"type": "plot", "semantic_type": "main", "content": {"coords": list(range(200_000))}},
            {"type": "datatable", "semantic_type": "main", "content": {"rows": 3}},
        ]}]}
        slim = slim_raw_payload(payload)
        blocks = slim["messages"][0]["blocks"]
        self.assertEqual(blocks[0]["content"], "The key finding is X.")  # text untouched
        self.assertEqual(blocks[1]["content"]["_stripped"], "plot")     # heavy plot stubbed
        self.assertIn("_original_bytes", blocks[1]["content"])
        self.assertEqual(blocks[2]["content"], {"rows": 3})             # small table untouched
        # The stubbed payload must still yield the same readable turns.
        self.assertEqual(extract_messages(slim)[0]["content"], "The key finding is X.")

    def test_one_session_can_write_multiple_findings_and_an_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "breadcrumbs.db")
            upsert_session(connection, session_id="sess-2027", url="https://example.test/chat/sess-2027", title=None,
                           raw_payload={}, messages=[{"seq": 0, "role": "user", "content": "question"}])
            write_payload(connection, {"findings": [
                {"id": "F-118", "category": "LUAD-immune", "disease": "LUAD", "hypothesis_text": "first",
                 "entities": ["CD8A"], "effect": "HR 0.58", "status": "confirmed", "reason": None,
                 "author": "Aisha", "created_at": "2027-01-01T00:00:00Z", "source_session_id": "sess-2027",
                 "source_type": "internal"},
                {"id": "F-119", "category": "LUAD-immune", "disease": "LUAD", "hypothesis_text": "second",
                 "entities": ["LKB1", "AJCC_stage"], "effect": "HR 0.79", "status": "abandoned", "reason": "stage",
                 "author": "Aisha", "created_at": "2027-01-01T00:00:00Z", "source_session_id": "sess-2027",
                 "source_type": "internal"},
            ], "edges": [{"from_id": "F-119", "to_id": "F-118", "relationship": "extends"}]})
            self.assertEqual(connection.execute("SELECT count(*) FROM findings").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT entities FROM findings WHERE id = 'F-119'").fetchone()[0], '["STK11", "AJCC_STAGE"]')
            self.assertEqual(connection.execute("SELECT count(*) FROM finding_edges").fetchone()[0], 1)
            connection.close()


if __name__ == "__main__":
    unittest.main()
