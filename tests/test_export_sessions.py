import unittest

from ingestion.export_sessions import (
    block_to_export,
    dedupe_templates,
    table_from_datatable,
    turns_from_raw,
)


class ExportSessionsTests(unittest.TestCase):
    def test_main_text_kept_thought_dropped_suggestion_tagged(self):
        self.assertEqual(
            block_to_export({"type": "text", "semantic_type": "main", "content": "Answer."}),
            {"kind": "text", "text": "Answer."},
        )
        self.assertIsNone(
            block_to_export({"type": "text", "semantic_type": "thought", "content": "hidden"})
        )
        self.assertEqual(
            block_to_export({"type": "text", "semantic_type": "suggestion", "content": "Try X?"}),
            {"kind": "suggestion", "text": "Try X?"},
        )

    def test_text_legend_directive_humanized(self):
        block = {"type": "text", "semantic_type": "main",
                 "content": "See :legend-item[B cell]{color=blue} here"}
        self.assertEqual(block_to_export(block), {"kind": "text", "text": "See B cell here"})

    def test_plot_carries_figure(self):
        figure = {"data": [{"type": "scatter", "y": [1, 2]}], "layout": {"title": "OS"}}
        block = {"type": "plot", "content": {"title": "Overall Survival", "plotly_obj": figure}}
        self.assertEqual(
            block_to_export(block),
            {"kind": "plot", "title": "Overall Survival", "figure": figure},
        )

    def test_stripped_block_becomes_omitted_placeholder(self):
        block = {"type": "plot", "content": {"_stripped": "plot", "_original_bytes": 120000}}
        self.assertEqual(
            block_to_export(block),
            {"kind": "omitted", "blockType": "plot", "bytes": 120000},
        )

    def test_datatable_column_major_to_rows(self):
        content = {
            "schema": [{"name": "gene"}, {"name": "value"}],
            "data": {"gene": ["A", "B"], "value": [1, 2]},
            "options": {"name": "Expression"},
        }
        self.assertEqual(
            table_from_datatable(content),
            {"columns": ["gene", "value"], "rows": [["A", 1], ["B", 2]], "title": "Expression"},
        )

    def test_turns_skip_empty_and_preserve_block_order(self):
        raw = {"messages": [
            {"role": "user", "blocks": [{"type": "text", "semantic_type": "main", "content": "Q?"}]},
            {"role": "assistant", "blocks": [
                {"type": "text", "semantic_type": "main", "content": "A."},
                {"type": "plot", "content": {"title": "c", "plotly_obj": {"data": []}}},
                {"type": "text", "semantic_type": "thought", "content": "drop me"},
            ]},
            {"role": "assistant", "blocks": [{"type": "text", "semantic_type": "thought", "content": "all hidden"}]},
        ]}
        turns = turns_from_raw(raw)
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])  # 3rd turn all-thought → dropped
        self.assertEqual([b["kind"] for b in turns[1]["blocks"]], ["text", "plot"])

    def test_dedupe_templates_hoists_and_references(self):
        shared = {"layout": {"font": {"family": "x"}}}
        sessions = [{
            "turns": [{"role": "assistant", "blocks": [
                {"kind": "plot", "figure": {"data": [], "layout": {"template": dict(shared)}}},
                {"kind": "plot", "figure": {"data": [], "layout": {"template": dict(shared)}}},
            ]}],
        }]
        templates = dedupe_templates(sessions)
        self.assertEqual(len(templates), 1)
        refs = [b["figure"]["layout"]["template"] for b in sessions[0]["turns"][0]["blocks"]]
        self.assertEqual(refs, [{"$tmpl": 0}, {"$tmpl": 0}])
        self.assertEqual(templates[0], shared)


if __name__ == "__main__":
    unittest.main()
