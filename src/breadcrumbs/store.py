from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ingestion.store import DEFAULT_DB_PATH, connect
from ingestion.write_findings import write_payload

from .contracts import DuplicationResult, Match, RecallFinding, RecallFindingsResult, RenderWikiResult

READABLE_COLUMNS = {
    "id", "category", "disease", "hypothesis_text", "signature", "effect", "n", "status",
    "author", "timestamp", "provenance", "reason", "note", "source_session_id", "source_type",
    "markdown", "resources",
}
COLUMN_ALIASES = {"created_at": "timestamp", "source_session": "source_session_id"}
Scalar = str | int | float | bool | None

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "has",
    "have", "how", "in", "is", "it", "of", "on", "or", "the", "their", "this", "to", "was",
    "what", "when", "where", "which", "with", "vs", "versus",
}
_PHRASE_ALIASES = {
    "lung adenocarcinoma": "luad",
    "lung adeno": "luad",
    "lung squamous cell carcinoma": "lusc",
    "non small cell lung cancer": "nsclc",
    "non-small cell lung cancer": "nsclc",
    "lkb1": "stk11",
    "cd8 t cell": "cytotoxic cd8a",
    "cd8 t-cell": "cytotoxic cd8a",
    "cytotoxic t cell": "cytotoxic cd8a",
    "cytotoxic t-cell": "cytotoxic cd8a",
}
_STATUS_TO_UI = {"confirmed": "confirmed", "in-progress": "in_progress", "abandoned": "abandoned"}
_RELATIONSHIP_TO_UI = {
    "duplicate_of": "duplicate_of", "extends": "extends", "related": "related",
    "related-to": "related", "contradicts": "contradicts",
}
_RELATIONSHIP_FOR_UI = {**_RELATIONSHIP_TO_UI, "contradicts": "related"}


class BreadcrumbsStore:
    """MCP-facing adapter over the team's canonical SQLite research-memory store."""

    def __init__(
        self,
        path: str | Path = DEFAULT_DB_PATH,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect(self.path)
        connection.close()

    def write(self, record: dict[str, Any]) -> dict[str, Any]:
        """Write through the same reviewed gate as the ingestion workflow."""

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
        query = f"SELECT * FROM findings WHERE {physical_column} IS ? ORDER BY timestamp DESC"
        connection = connect(self.path)
        try:
            rows = connection.execute(query, (value,)).fetchall()
        finally:
            connection.close()
        return [self._decode(row) for row in rows]

    def check_duplication(self, hypothesis_text: str, *, limit: int = 5) -> dict[str, Any]:
        """Search the internal Breadcrumbs graph for prior organizational work."""

        hypothesis_text = _required_text(hypothesis_text, "hypothesis_text")
        findings, searched = self._semantic_findings(hypothesis_text, limit=limit)
        matches = self._ui_matches(findings, limit=limit)
        if matches:
            result = DuplicationResult(
                verdict="match",
                matches=matches,
                searched=searched,
                markdown=self._duplication_markdown(hypothesis_text, matches),
            )
            return result.model_dump(exclude_none=True)

        result = DuplicationResult(
            verdict="open",
            matches=[],
            searched=searched,
            markdown=self._duplication_markdown(hypothesis_text, []),
        )
        return result.model_dump(exclude_none=True)

    def recall_findings(self, query: str, *, limit: int = 10) -> dict[str, Any]:
        """Recall related internal findings and their graph edges."""

        query = _required_text(query, "query")
        rows, searched = self._semantic_findings(query, limit=limit)
        connection = connect(self.path)
        try:
            decoded = []
            for row, score in rows:
                item = self._decode(row)
                edges = connection.execute(
                    """
                    SELECT CASE WHEN from_id = ? THEN to_id ELSE from_id END AS finding_id,
                           relationship
                    FROM finding_edges WHERE from_id = ? OR to_id = ?
                    ORDER BY created_at, finding_id
                    """,
                    (item["id"], item["id"], item["id"]),
                ).fetchall()
                item["relationships"] = [
                    {
                        "finding_id": edge["finding_id"],
                        "relationship": _RELATIONSHIP_TO_UI.get(edge["relationship"], "related"),
                    }
                    for edge in edges
                ]
                item["score"] = round(score, 6)
                decoded.append(RecallFinding.model_validate(item))
        finally:
            connection.close()
        result = RecallFindingsResult(
            query=query,
            findings=decoded,
            searched=searched,
            sources_searched=["internal Breadcrumbs graph"],
        )
        return result.model_dump()

    def render_wiki(
        self,
        *,
        finding_ids: list[str] | None = None,
        title: str = "Breadcrumbs research memory",
    ) -> dict[str, Any]:
        """Render a deterministic, one-way Markdown view of the authoritative graph."""

        connection = connect(self.path)
        try:
            if finding_ids is None:
                rows = connection.execute("SELECT * FROM findings ORDER BY id").fetchall()
            elif not finding_ids:
                rows = []
            else:
                placeholders = ",".join("?" for _ in finding_ids)
                rows = connection.execute(
                    f"SELECT * FROM findings WHERE id IN ({placeholders}) ORDER BY id", finding_ids
                ).fetchall()
        finally:
            connection.close()
        findings = [self._decode(row) for row in rows]
        lines = [
            f"# {title.strip() or 'Breadcrumbs research memory'}",
            "",
            "> Generated read-only view. The SQLite Breadcrumbs graph is authoritative; edit the graph, not this page.",
            "",
        ]
        for finding in findings:
            lines.extend(
                [
                    f"## {finding['id']} — {finding['hypothesis_text']}",
                    "",
                    f"- **Status:** {finding['status']}",
                    f"- **Disease:** {finding['disease']}",
                    f"- **Author:** {finding['author']}",
                    f"- **Timestamp:** {finding['timestamp']}",
                    f"- **Finding:** {finding.get('effect') or 'Not recorded'}",
                ]
            )
            if finding.get("reason"):
                lines.append(f"- **Reason:** {finding['reason']}")
            if finding.get("provenance"):
                lines.append(f"- **Provenance:** {finding['provenance']}")
            lines.extend([f"- **Graph citation:** `{finding['id']}`", ""])
        result = RenderWikiResult(markdown="\n".join(lines).rstrip() + "\n", finding_ids=[f["id"] for f in findings])
        return result.model_dump()

    def _semantic_findings(self, query: str, *, limit: int) -> tuple[list[tuple[sqlite3.Row, float]], int]:
        query_tokens = _tokens(query)
        connection = connect(self.path)
        try:
            rows = connection.execute("SELECT * FROM findings").fetchall()
        finally:
            connection.close()
        scored: list[tuple[sqlite3.Row, float]] = []
        for row in rows:
            if row["status"] == "open":
                continue
            text = " ".join(
                str(row[name] or "")
                for name in ("disease", "hypothesis_text", "signature", "category", "entities")
            )
            candidate_tokens = _tokens(text)
            overlap = query_tokens & candidate_tokens
            if not overlap:
                continue
            score = sum(2.0 if token in {str(row["disease"] or "").lower()} else 1.0 for token in overlap)
            score /= math.sqrt(max(len(query_tokens), 1))
            if len(overlap) >= 2 or score >= 1.5:
                scored.append((row, score))
        status_order = {"abandoned": 0, "in-progress": 1, "confirmed": 2}
        scored.sort(key=lambda item: (-item[1], status_order.get(item[0]["status"], 3), item[0]["id"]))
        return scored[:limit], len(rows)

    def _ui_matches(self, findings: list[tuple[sqlite3.Row, float]], *, limit: int) -> list[Match]:
        if not findings:
            return []

        def to_match(row: sqlite3.Row, relationship: str) -> Match | None:
            status = _STATUS_TO_UI.get(row["status"])
            if status is None:
                return None
            return Match(
                id=row["id"], status=status,
                relationship=_RELATIONSHIP_FOR_UI.get(relationship, "related"),
                hypothesis_text=row["hypothesis_text"], effect=row["effect"] or "",
                reason=row["reason"], author=row["author"], disease=row["disease"],
            )

        primary = findings[0][0]
        first = to_match(primary, "duplicate_of")
        if first is None:
            return []
        matches = [first]
        seen = {primary["id"]}
        connection = connect(self.path)
        try:
            neighbor_rows = connection.execute(
                """
                SELECT neighbor.*, edge.relationship AS _relationship
                FROM finding_edges edge
                JOIN findings neighbor ON neighbor.id = CASE
                    WHEN edge.from_id = ? THEN edge.to_id ELSE edge.from_id END
                WHERE edge.from_id = ? OR edge.to_id = ?
                """,
                (primary["id"], primary["id"], primary["id"]),
            ).fetchall()
        finally:
            connection.close()
        status_order = {"abandoned": 0, "in-progress": 1, "confirmed": 2}
        neighbor_rows.sort(key=lambda row: (status_order.get(row["status"], 3), row["id"]))
        for row in neighbor_rows:
            match = to_match(row, row["_relationship"])
            if match is not None and row["id"] not in seen:
                matches.append(match)
                seen.add(row["id"])
                if len(matches) >= limit:
                    return matches
        for row, _ in findings[1:]:
            match = to_match(row, "related")
            if match is not None and row["id"] not in seen:
                matches.append(match)
                seen.add(row["id"])
                if len(matches) >= limit:
                    break
        return matches

    @staticmethod
    def _duplication_markdown(
        question: str,
        matches: list[Match],
    ) -> str:
        if matches:
            lines = ["## Prior internal work found", "", f"Question checked: _{question}_", ""]
            for match in matches:
                lines.extend(
                    [
                        f"### {match.id} — {match.status}",
                        f"- **Question:** {match.hypothesis_text}",
                        f"- **Who:** {match.author} · {match.disease}",
                        f"- **Finding:** {match.effect or 'Not recorded'}",
                    ]
                )
                if match.reason:
                    lines.append(f"- **Reason:** {match.reason}")
                lines.append("")
            lines.append("_Source searched: internal Breadcrumbs graph._")
            return "\n".join(lines)
        lines = ["## No prior work found", "", f"Question checked: _{question}_", ""]
        lines.append("No prior work was found in the internal Breadcrumbs graph.")
        lines.append("")
        lines.append("_Source searched: internal Breadcrumbs graph._")
        return "\n".join(lines)

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["entities"] = json.loads(item["entities"]) if item.get("entities") else []
        item["resources"] = json.loads(item["resources"]) if item.get("resources") else []
        return item

def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _tokens(text: str) -> set[str]:
    normalized = text.lower()
    for phrase, replacement in _PHRASE_ALIASES.items():
        normalized = normalized.replace(phrase, replacement)
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) > 1 and token not in _STOPWORDS
    }
