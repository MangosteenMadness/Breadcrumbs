from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ingestion.store import DEFAULT_DB_PATH, connect
from ingestion.write_findings import write_payload

READABLE_COLUMNS = {
    "id",
    "category",
    "disease",
    "hypothesis_text",
    "signature",
    "effect",
    "n",
    "status",
    "author",
    "timestamp",
    "provenance",
    "reason",
    "note",
    "source_session_id",
}
COLUMN_ALIASES = {
    "created_at": "timestamp",
    "source_session": "source_session_id",
}
Scalar = str | int | float | bool | None


class CairnStore:
    """MCP-facing adapter over the team's canonical Cairn SQLite graph store."""

    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect(self.path)
        connection.close()

    def write(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("record must be a JSON object")
        finding = dict(record)
        if "source_session" in finding:
            if "source_session_id" in finding:
                raise ValueError("use either source_session or source_session_id, not both")
            finding["source_session_id"] = finding.pop("source_session")
        finding.setdefault("id", f"F-{uuid4().hex[:12].upper()}")
        finding.setdefault("created_at", datetime.now(timezone.utc).isoformat())

        connection = connect(self.path)
        try:
            write_payload(connection, {"findings": [finding], "edges": []})
            row = connection.execute("SELECT * FROM findings WHERE id = ?", (finding["id"],)).fetchone()
        finally:
            connection.close()
        if row is None:
            raise RuntimeError("finding was not written")
        return self._decode(row)

    def read(self, column: str, value: Scalar) -> list[dict[str, Any]]:
        physical_column = COLUMN_ALIASES.get(column, column)
        if physical_column not in READABLE_COLUMNS:
            allowed = sorted(READABLE_COLUMNS | set(COLUMN_ALIASES))
            raise ValueError(f"column must be one of: {', '.join(allowed)}")
        # The identifier comes only from the server-owned allowlist; the value is bound.
        query = f"SELECT * FROM findings WHERE {physical_column} IS ? ORDER BY timestamp DESC"
        connection = connect(self.path)
        try:
            rows = connection.execute(query, (value,)).fetchall()
        finally:
            connection.close()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["entities"] = json.loads(item["entities"]) if item.get("entities") else []
        return item
