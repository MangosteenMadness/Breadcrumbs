"""SQLite persistence for raw K Pro chat sessions."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "breadcrumbs.db"
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
    _migrate_chat_tables(connection)
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


def _migrate_chat_tables(connection: sqlite3.Connection) -> None:
    """Add chat columns for databases created before section nesting / incremental re-ingest.

    `executescript` runs CREATE TABLE IF NOT EXISTS, so editing graph_schema.sql alone
    never touches an existing breadcrumbs.db. These are pure ALTER ADD COLUMN migrations — no
    table rebuild, so finding_edges' ON DELETE CASCADE is not at risk (see AGENTS.md).
    """
    additions = {
        "chat_sessions": {"updated_at": "TEXT"},
        "chat_message_sections": {"parent_id": "TEXT", "path": "TEXT"},
    }
    for table, columns in additions.items():
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_message_sections_parent ON chat_message_sections(parent_id)"
    )


def ingested_revisions(connection: sqlite3.Connection) -> dict[str, str | None]:
    """Map session id -> the K Pro updated_at stamp already stored, for incremental runs."""
    return {
        row["id"]: row["updated_at"]
        for row in connection.execute("SELECT id, updated_at FROM chat_sessions")
    }


def upsert_session(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    url: str,
    title: str | None,
    raw_payload: Any,
    messages: Iterable[dict[str, Any]],
    updated_at: str | None = None,
) -> None:
    """Replace one session's turn set atomically, retaining its latest raw payload.

    Scoped to this session_id only — ingesting chat B never disturbs chat A. Re-ingesting
    the same chat replaces its turns, which is how a chat that gained new messages in K Pro
    is brought up to date.
    """
    scraped_at = utc_now()
    raw_json = json.dumps(raw_payload, ensure_ascii=False) if raw_payload is not None else None
    turns = list(messages)
    with connection:
        connection.execute(
            """
            INSERT INTO chat_sessions(id, url, title, scraped_at, raw_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                url = excluded.url,
                title = excluded.title,
                scraped_at = excluded.scraped_at,
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            """,
            (session_id, url, title, scraped_at, raw_json, updated_at),
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
            for section in extract_sections(turn["content"]):
                parent_seq = section["parent_seq"]
                sections.append((
                    f"{message_id}:section:{section['seq']}",
                    message_id,
                    section["seq"],
                    section["heading"],
                    section["level"],
                    section["content"],
                    f"{message_id}:section:{parent_seq}" if parent_seq is not None else None,
                    section["path"],
                ))
        connection.executemany(
            """
            INSERT INTO chat_message_sections(id, message_id, seq, heading, level, content, parent_id, path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sections,
        )
    write_transcript(session_id, url, title, turns)


def extract_sections(content: str) -> list[dict[str, Any]]:
    """Extract K Pro's visible ##/### Markdown categories from one answer, as a tree.

    K Pro nests its answer: a level-2 heading ("Indication-Specific Summary") is followed
    by level-3 headings, one per indication. Each section carries `seq`, the `parent_seq`
    of the level-2 it sits under (None for a level-2), and a readable `path`
    ("Indication-Specific Summary > Non small cell lung cancer") so topic nodes can be
    built without re-parsing the Markdown.
    """
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    parent_seq: int | None = None
    parent_heading: str | None = None

    def close(section: dict[str, Any]) -> None:
        section["content"] = "\n".join(section.pop("lines")).strip()
        sections.append(section)

    for line in content.splitlines():
        match = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if match:
            if current:
                close(current)
            level = len(match.group(1))
            heading = match.group(2)
            seq = len(sections)
            if level == 2:
                parent_seq, parent_heading = seq, heading
                path = heading
            else:
                path = f"{parent_heading} > {heading}" if parent_heading else heading
            current = {
                "seq": seq,
                "heading": heading,
                "level": level,
                "lines": [],
                "parent_seq": parent_seq if level == 3 else None,
                "path": path,
            }
        elif current:
            current["lines"].append(line)
    if current:
        close(current)
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
