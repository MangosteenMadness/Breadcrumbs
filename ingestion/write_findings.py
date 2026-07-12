"""Write reviewed finding nodes and typed edges from a local JSON extraction."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .store import DEFAULT_DB_PATH, connect
except ImportError:
    from store import DEFAULT_DB_PATH, connect

SYNONYMS = {"LKB1": "STK11"}
VALID_STATUSES = {"confirmed", "in-progress", "abandoned", "open"}
VALID_RELATIONSHIPS = {"duplicate_of", "extends", "related", "contradicts"}


def normalize_entities(entities: list[str]) -> list[str]:
    normalized = []
    for entity in entities:
        tag = re.sub(r"\s+", "_", entity.strip().upper())
        tag = SYNONYMS.get(tag, tag)
        if tag and tag not in normalized:
            normalized.append(tag)
    return normalized


def write_payload(connection, payload: dict[str, Any]) -> None:
    findings = payload.get("findings", [])
    edges = payload.get("edges", [])
    with connection:
        approved_categories = {row[0] for row in connection.execute("SELECT id FROM topic_categories")}
        for finding in findings:
            required = {"id", "category", "disease", "hypothesis_text", "entities", "effect", "status", "author", "created_at", "source_session_id", "source_type"}
            missing = required - finding.keys()
            if missing:
                raise ValueError(f"Finding {finding.get('id', '<unknown>')} is missing: {', '.join(sorted(missing))}")
            if finding["category"] not in approved_categories:
                raise ValueError(f"Unknown category {finding['category']!r}; add it to topic_categories first")
            if finding["status"] not in VALID_STATUSES:
                raise ValueError(f"Invalid status {finding['status']!r}")
            if finding["status"] == "abandoned" and not finding.get("reason"):
                raise ValueError(f"Abandoned finding {finding['id']} requires a reason")
            if finding["status"] != "abandoned" and finding.get("reason"):
                raise ValueError(f"Only abandoned finding {finding['id']} may contain a reason")
            if finding["source_type"] not in {"external", "internal"}:
                raise ValueError(f"Invalid source_type {finding.get('source_type')!r} for {finding['id']}")
            if not isinstance(finding.get("markdown", ""), str):
                raise ValueError(f"markdown for {finding['id']} must be a string")
            resources = finding.get("resources") or []
            if finding["source_type"] == "external":
                if not resources:
                    raise ValueError(f"External finding {finding['id']} requires non-empty resources")
                for r in resources:
                    if r.get("type") not in {"paper", "database"} or not r.get("citation"):
                        raise ValueError(f"Bad resource in {finding['id']}: {r!r}")
            else:  # internal
                if resources:
                    raise ValueError(f"Internal finding {finding['id']} must not carry resources")
            resources_json = json.dumps(resources) if resources else None
            if not connection.execute("SELECT 1 FROM chat_sessions WHERE id = ?", (finding["source_session_id"],)).fetchone():
                raise ValueError(f"Unknown source session {finding['source_session_id']!r}")
            entities = normalize_entities(finding["entities"])
            connection.execute(
                """
                INSERT INTO findings(id, disease, hypothesis_text, signature, effect, n, status, author, timestamp,
                                     provenance, reason, note, category, entities, source_session_id,
                                     source_type, markdown, resources)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    disease=excluded.disease, hypothesis_text=excluded.hypothesis_text,
                    signature=excluded.signature, effect=excluded.effect, n=excluded.n,
                    status=excluded.status, author=excluded.author, timestamp=excluded.timestamp,
                    provenance=excluded.provenance, reason=excluded.reason, note=excluded.note,
                    category=excluded.category, entities=excluded.entities, source_session_id=excluded.source_session_id,
                    source_type=excluded.source_type, markdown=excluded.markdown, resources=excluded.resources
                """,
                (finding["id"], finding["disease"], finding["hypothesis_text"], ",".join(entities), finding["effect"],
                 finding.get("n"), finding["status"], finding["author"], finding["created_at"], finding.get("provenance"),
                 finding.get("reason"), finding.get("note"), finding["category"], json.dumps(entities), finding["source_session_id"],
                 finding["source_type"], finding.get("markdown"), resources_json),
            )
        for edge in edges:
            if edge.get("relationship") not in VALID_RELATIONSHIPS:
                raise ValueError(f"Invalid edge relationship {edge.get('relationship')!r}")
            created_at = edge.get("created_at") or datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT OR REPLACE INTO finding_edges(from_id, to_id, relationship, created_at) VALUES (?, ?, ?, ?)",
                (edge["from_id"], edge["to_id"], edge["relationship"], created_at),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Write reviewed multi-finding graph output from JSON.")
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    connection = connect(args.db)
    try:
        write_payload(connection, payload)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
