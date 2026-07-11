"""SQLite persistence for raw K Pro chat sessions."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "cairn.db"
TRANSCRIPTS_DIR = Path(__file__).resolve().parent / "transcripts"
SCHEMA_PATH = ROOT / "schema" / "graph_schema.sql"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_findings(connection)
    return connection


def _migrate_findings(connection: sqlite3.Connection) -> None:
    """Add graph fields for databases created before the findings extension."""
    existing = {row[1] for row in connection.execute("PRAGMA table_info(findings)")}
    additions = {
        "category": "TEXT",
        "entities": "TEXT",
        "source_session_id": "TEXT",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE findings ADD COLUMN {name} {definition}")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_findings_category ON findings(category)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_findings_source_session ON findings(source_session_id)")


def upsert_session(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    url: str,
    title: str | None,
    raw_payload: Any,
    messages: Iterable[dict[str, Any]],
) -> None:
    """Replace one session's turn set atomically, retaining its latest raw payload."""
    scraped_at = utc_now()
    raw_json = json.dumps(raw_payload, ensure_ascii=False) if raw_payload is not None else None
    turns = list(messages)
    with connection:
        connection.execute(
            """
            INSERT INTO chat_sessions(id, url, title, scraped_at, raw_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                url = excluded.url,
                title = excluded.title,
                scraped_at = excluded.scraped_at,
                raw_json = excluded.raw_json
            """,
            (session_id, url, title, scraped_at, raw_json),
        )
        connection.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        connection.executemany(
            """
            INSERT INTO chat_messages(id, session_id, seq, role, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f"{session_id}:{turn['seq']}",
                    session_id,
                    turn["seq"],
                    turn["role"],
                    turn["content"],
                    turn.get("created_at"),
                )
                for turn in turns
            ],
        )
        sections = []
        for turn in turns:
            message_id = f"{session_id}:{turn['seq']}"
            for section_seq, section in enumerate(extract_sections(turn["content"])):
                sections.append((
                    f"{message_id}:section:{section_seq}",
                    message_id,
                    section_seq,
                    section["heading"],
                    section["level"],
                    section["content"],
                ))
        connection.executemany(
            """
            INSERT INTO chat_message_sections(id, message_id, seq, heading, level, content)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            sections,
        )
    write_transcript(session_id, url, title, turns)


def extract_sections(content: str) -> list[dict[str, Any]]:
    """Extract K Pro's visible ##/### Markdown categories from one answer."""
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in content.splitlines():
        match = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if match:
            if current:
                current["content"] = "\n".join(current.pop("lines")).strip()
                sections.append(current)
            current = {"heading": match.group(2), "level": len(match.group(1)), "lines": []}
        elif current:
            current["lines"].append(line)
    if current:
        current["content"] = "\n".join(current.pop("lines")).strip()
        sections.append(current)
    return sections


def write_transcript(session_id: str, url: str, title: str | None, messages: Iterable[dict[str, Any]]) -> Path:
    """Write a human-readable local view without replacing the canonical database."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    heading = title or f"K Pro chat {session_id}"
    sections = [f"# {heading}", "", f"Source: {url}", ""]
    for message in messages:
        speaker = "Researcher" if message["role"] == "user" else "K Pro"
        sections.extend((f"## {speaker}", "", message["content"].strip(), ""))
    path = TRANSCRIPTS_DIR / f"{session_id}.md"
    path.write_text("\n".join(sections), encoding="utf-8")
    return path


def record_error(connection: sqlite3.Connection, session_id: str | None, url: str, error: str) -> None:
    with connection:
        connection.execute(
            "INSERT INTO ingestion_errors(session_id, url, error, created_at) VALUES (?, ?, ?, ?)",
            (session_id, url, error, utc_now()),
        )
