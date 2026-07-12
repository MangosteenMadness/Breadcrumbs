"""Export ingested K Pro sessions to a static JSON the Breadcrumbs UI bundles.

The UI is a standalone Next.js app (see ui/lib/data.ts for how the trail is seeded). Rather
than have it open a live authenticated K Pro session at demo time — which needs an SSO token,
pulls tens of MB of plot payloads over the network, and can stall on exactly the richest
charts — it replays the Plotly figures we already captured during ingest. K Pro hands us the
raw Plotly figure JSON; rendering that stored object with Plotly.js draws the same chart it
drew, with no auth and nothing to break mid-demo.

This reads breadcrumbs.db and emits ui/lib/sessions.json: one entry per session, each an
ordered list of turns, each turn an ordered list of blocks (text, plot, datatable, or an
`omitted` placeholder for the heavy plots slim_raw_payload() stripped at ingest). The block
order is preserved verbatim so charts and tables interleave with the answer text exactly as
K Pro laid them out.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from .store import DEFAULT_DB_PATH, connect
except ImportError:  # Allows `python ingestion/export_sessions.py`.
    from store import DEFAULT_DB_PATH, connect

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "ui" / "lib" / "sessions.json"

# Block semantic_types K Pro uses. Only `main` text is the readable answer; `thought` is the
# model's private reasoning (not shown) and `suggestion` is a follow-up prompt chip.
_LEGEND_DIRECTIVE = re.compile(r":legend-item\[([^\]]+)\]\{[^}]*\}")


def humanize(text: str) -> str:
    """Strip K Pro renderer directives, matching ingest_chat.humanize_kpro_markdown."""
    return _LEGEND_DIRECTIVE.sub(r"\1", text).strip()


def table_from_datatable(content: dict[str, Any]) -> dict[str, Any] | None:
    """Convert K Pro's column-oriented datatable to {columns, rows} the UI renders directly.

    content = {schema: [{name}, ...], data: {col_name: [v, ...]}, options: {...}}. schema gives
    the column order; data is column-major, so a row is one value taken from each column at the
    same index. Ragged columns (shouldn't happen) are padded to the longest so nothing is lost.
    """
    schema = content.get("schema")
    data = content.get("data")
    if not isinstance(schema, list) or not isinstance(data, dict):
        return None
    columns = [col.get("name") for col in schema if isinstance(col, dict) and col.get("name")]
    if not columns:
        return None
    height = max((len(data.get(col) or []) for col in columns), default=0)
    rows = [[(data.get(col) or [None] * height)[i] if i < len(data.get(col) or []) else None
             for col in columns] for i in range(height)]
    table: dict[str, Any] = {"columns": columns, "rows": rows}
    options = content.get("options")
    if isinstance(options, dict) and options.get("name"):
        table["title"] = options["name"]
    return table


def block_to_export(block: dict[str, Any]) -> dict[str, Any] | None:
    """Map one raw K Pro block to a UI block, or None to drop it (thought / empty)."""
    block_type = block.get("type")
    semantic = block.get("semantic_type", "main")
    content = block.get("content")

    if block_type == "text":
        if semantic == "thought":
            return None  # Model's private reasoning — never shown.
        text = humanize(content) if isinstance(content, str) else None
        if not text:
            return None
        return {"kind": "suggestion" if semantic == "suggestion" else "text", "text": text}

    # A heavy plot/table stripped at ingest to keep the committed DB small (see
    # slim_raw_payload). Render a placeholder rather than pretend it wasn't there.
    if isinstance(content, dict) and "_stripped" in content:
        return {"kind": "omitted", "blockType": content.get("_stripped") or block_type,
                "bytes": content.get("_original_bytes")}

    if block_type == "plot" and isinstance(content, dict):
        figure = content.get("plotly_obj")
        if not isinstance(figure, dict) or "data" not in figure:
            return None
        return {"kind": "plot", "title": content.get("title"), "figure": figure}

    if block_type == "datatable" and isinstance(content, dict):
        table = table_from_datatable(content)
        if table is None:
            return None
        return {"kind": "table", **table}

    return None


def turns_from_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ordered turns of exportable blocks from a session's raw payload."""
    turns: list[dict[str, Any]] = []
    for message in raw.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        blocks: list[dict[str, Any]] = []
        raw_blocks = message.get("blocks")
        if isinstance(raw_blocks, list):
            for block in raw_blocks:
                if isinstance(block, dict):
                    exported = block_to_export(block)
                    if exported:
                        blocks.append(exported)
        elif isinstance(message.get("content"), str):
            text = humanize(message["content"])
            if text:
                blocks.append({"kind": "text", "text": text})
        if blocks:
            turns.append({"role": role, "blocks": blocks})
    return turns


def dedupe_templates(sessions: list[dict[str, Any]]) -> list[Any]:
    """Hoist each figure's repeated layout.template into a shared table, replacing it with an
    index. K Pro sends the same ~7 KB Plotly template on every figure (only two distinct ones
    across the whole corpus), so inlining it 63 times tripled the figure payload for no reason.
    Each figure keeps `layout.template = {"$tmpl": i}`; the UI rehydrates it before rendering.
    """
    templates: list[str] = []
    for session in sessions:
        for turn in session["turns"]:
            for block in turn["blocks"]:
                if block["kind"] != "plot":
                    continue
                layout = block["figure"].get("layout")
                if not isinstance(layout, dict) or "template" not in layout:
                    continue
                serialized = json.dumps(layout["template"], ensure_ascii=False, sort_keys=True)
                if serialized not in templates:
                    templates.append(serialized)
                layout["template"] = {"$tmpl": templates.index(serialized)}
    return [json.loads(t) for t in templates]


def build_sessions(connection) -> list[dict[str, Any]]:
    sessions = []
    rows = connection.execute(
        "SELECT id, title, url, researcher, raw_json FROM chat_sessions ORDER BY updated_at DESC, id"
    ).fetchall()
    for row in rows:
        if not row["raw_json"]:
            continue
        try:
            raw = json.loads(row["raw_json"])
        except (ValueError, TypeError):
            continue
        turns = turns_from_raw(raw)
        if not turns:
            continue
        counts = {"plots": 0, "tables": 0, "omitted": 0}
        for turn in turns:
            for block in turn["blocks"]:
                if block["kind"] == "plot":
                    counts["plots"] += 1
                elif block["kind"] == "table":
                    counts["tables"] += 1
                elif block["kind"] == "omitted":
                    counts["omitted"] += 1
        sessions.append({
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "researcher": row["researcher"],
            "turns": turns,
            "counts": counts,
        })
    return sessions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite source")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSON destination")
    args = parser.parse_args()

    connection = connect(args.db)
    try:
        sessions = build_sessions(connection)
    finally:
        connection.close()

    templates = dedupe_templates(sessions)
    payload = {"templates": templates, "sessions": sessions}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    total = {"plots": 0, "tables": 0, "omitted": 0}
    for session in sessions:
        for key in total:
            total[key] += session["counts"][key]
    size_kb = args.out.stat().st_size / 1024
    print(f"Wrote {len(sessions)} sessions to {args.out} ({size_kb:.0f} KB)")
    print(f"  {total['plots']} plots · {total['tables']} tables · {total['omitted']} omitted placeholders")


if __name__ == "__main__":
    main()
