"""Ingest real K Pro chats into Cairn's local SQLite store.

K Pro is a client-rendered authenticated app. This module observes its JSON traffic
inside a saved Playwright session instead of attempting unauthenticated HTTP fetches.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

from dotenv import load_dotenv
from playwright.sync_api import Response, sync_playwright

try:
    from .store import DEFAULT_DB_PATH, connect, record_error, upsert_session
except ImportError:  # Allows `python ingestion/ingest_chat.py ...`.
    from store import DEFAULT_DB_PATH, connect, record_error, upsert_session

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path(__file__).resolve().parent / ".secrets" / "kpro_storage_state.json"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
ROLE_KEYS = ("role", "author_role", "sender", "speaker", "type")
CONTENT_KEYS = ("content", "text", "message", "body", "markdown", "value", "blocks")
TIME_KEYS = ("created_at", "createdAt", "timestamp", "time")
TITLE_KEYS = ("title", "name", "label")


@dataclass
class CapturedPayload:
    url: str
    data: Any


def chat_id(value: str) -> str | None:
    match = UUID_RE.search(value)
    return match.group(0).lower() if match else None


def clean_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return humanize_kpro_markdown(text) or None
    if isinstance(value, list):
        parts = [clean_text(item) for item in value]
        text = "\n".join(part for part in parts if part)
        return text or None
    if isinstance(value, dict):
        for key in CONTENT_KEYS:
            if key in value:
                text = clean_text(value[key])
                if text:
                    return text
    return None


def humanize_kpro_markdown(text: str) -> str:
    """Remove K Pro renderer directives while retaining normal Markdown tables/text."""
    text = re.sub(r":legend-item\[([^\]]+)\]\{[^}]*\}", r"\1", text)
    return text


def normalized_role(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.lower().strip()
    if value in {"user", "human", "researcher", "customer"}:
        return "user"
    if value in {"assistant", "ai", "bot", "model", "agent"}:
        return "assistant"
    return None


def message_from_dict(item: dict[str, Any]) -> dict[str, Any] | None:
    role = next((normalized_role(item.get(key)) for key in ROLE_KEYS if normalized_role(item.get(key))), None)
    if role is None and isinstance(item.get("author"), dict):
        role = normalized_role(item["author"].get("role") or item["author"].get("type"))
    # K Pro messages are block-based. Only visible main text belongs in the
    # readable transcript; thought, suggestion, plot, and table blocks remain in
    # the session's raw JSON for provenance but are not mashed into the answer.
    blocks = item.get("blocks")
    if isinstance(blocks, list):
        visible_blocks = [
            clean_text(block.get("content"))
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "text"
            and block.get("semantic_type", "main") == "main"
        ]
        content = "\n\n".join(text for text in visible_blocks if text) or None
    else:
        content = next((clean_text(item.get(key)) for key in CONTENT_KEYS if clean_text(item.get(key))), None)
    if not role or not content:
        return None
    created_at = next((item.get(key) for key in TIME_KEYS if item.get(key) is not None), None)
    return {"role": role, "content": content, "created_at": str(created_at) if created_at else None}


def walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def extract_messages(payload: Any) -> list[dict[str, Any]]:
    """Choose the largest coherent ordered list of role-labelled message objects."""
    candidates: list[list[dict[str, Any]]] = []
    for node in walk(payload):
        if not isinstance(node, list):
            continue
        turns = [message_from_dict(item) for item in node if isinstance(item, dict)]
        turns = [turn for turn in turns if turn]
        if turns:
            candidates.append(turns)
    if not candidates:
        return []
    best = max(candidates, key=len)
    return [{**turn, "seq": seq} for seq, turn in enumerate(best)]


def find_title(payloads: Iterable[CapturedPayload]) -> str | None:
    for captured in payloads:
        for node in walk(captured.data):
            if isinstance(node, dict):
                for key in TITLE_KEYS:
                    value = clean_text(node.get(key))
                    if value and len(value) < 500:
                        return value
    return None


def parse_json_response(response: Response) -> CapturedPayload | None:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        return None
    try:
        return CapturedPayload(response.url, response.json())
    except Exception:
        return None


def capture_page_payloads(page, url: str) -> list[CapturedPayload]:
    captured: list[CapturedPayload] = []

    def on_response(response: Response) -> None:
        # Responses are kept only in memory until a matching chat is persisted.
        result = parse_json_response(response)
        if result:
            captured.append(result)

    page.on("response", on_response)
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass  # Long-lived app telemetry often prevents network-idle.
    page.wait_for_timeout(2_000)
    page.remove_listener("response", on_response)
    return captured


def payload_for_chat(payloads: list[CapturedPayload], session_id: str) -> Any | None:
    matching = [p.data for p in payloads if session_id in p.url.lower()]
    if matching:
        return max(matching, key=lambda payload: len(extract_messages(payload)))
    with_turns = [p.data for p in payloads if extract_messages(p.data)]
    return max(with_turns, key=lambda payload: len(extract_messages(payload)), default=None)


def rendered_messages(page) -> list[dict[str, Any]]:
    selectors = (
        "[data-message-author-role]",
        "[data-role]",
        "[data-testid*=message i]",
    )
    for selector in selectors:
        rows = page.locator(selector)
        try:
            count = rows.count()
        except Exception:
            continue
        turns: list[dict[str, Any]] = []
        for index in range(count):
            row = rows.nth(index)
            role = normalized_role(row.get_attribute("data-message-author-role") or row.get_attribute("data-role"))
            content = clean_text(row.inner_text())
            if role and content:
                turns.append({"seq": len(turns), "role": role, "content": content, "created_at": None})
        if turns:
            return turns
    return []


def recent_urls(page, base_url: str, payloads: list[CapturedPayload], limit: int) -> list[str]:
    ids: list[str] = []
    for captured in payloads:
        # Only the collection endpoint is a chat-list source. Other payloads include
        # organization, artifact, and tool UUIDs that must never become chat URLs.
        if not re.search(r"/api/chats(?:\?.*)?$", captured.url):
            continue
        for node in walk(captured.data):
            if isinstance(node, dict):
                for key in ("id", "chat_id", "chatId", "conversation_id", "conversationId"):
                    value = node.get(key)
                    if isinstance(value, str) and UUID_RE.fullmatch(value):
                        ids.append(value.lower())
    try:
        ids.extend((chat_id(href) for href in page.locator('a[href*="/chat/"]').evaluate_all("els => els.map(e => e.href)")))
    except Exception:
        pass
    unique = list(dict.fromkeys(identifier for identifier in ids if identifier))
    return [urljoin(base_url, f"/chat/{identifier}") for identifier in unique[:limit]]


def load_from_file(path: Path) -> list[tuple[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".txt":
        identifier = chat_id(path.stem) or f"file-{path.stem}"
        turns: list[dict[str, str]] = []
        current_role: str | None = None
        buffer: list[str] = []
        for line in text.splitlines():
            match = re.match(r"^\s*(user|researcher|assistant|agent)\s*:\s*(.*)$", line, re.I)
            if match:
                if current_role and clean_text("\n".join(buffer)):
                    turns.append({"role": current_role, "content": "\n".join(buffer).strip()})
                current_role = normalized_role(match.group(1))
                buffer = [match.group(2)]
            elif current_role:
                buffer.append(line)
        if current_role and clean_text("\n".join(buffer)):
            turns.append({"role": current_role, "content": "\n".join(buffer).strip()})
        return [(identifier, {"messages": turns})]
    data = json.loads(text)
    if isinstance(data, dict) and "log" in data:  # HAR
        entries = data.get("log", {}).get("entries", [])
        data = [
            json.loads(entry["response"]["content"].get("text", "{}"))
            for entry in entries
            if entry.get("response", {}).get("content", {}).get("mimeType", "").find("json") >= 0
        ]
    payloads = data if isinstance(data, list) else [data]
    results = []
    for index, payload in enumerate(payloads):
        identifier = chat_id(json.dumps(payload)) or f"file-{path.stem}-{index}"
        results.append((identifier, payload))
    return results


def ingest_one(page, connection, url: str) -> bool:
    session_id = chat_id(url)
    if not session_id:
        record_error(connection, None, url, "URL does not contain a K Pro chat UUID")
        return False
    payloads = capture_page_payloads(page, url)
    payload = payload_for_chat(payloads, session_id)
    messages = extract_messages(payload) if payload is not None else []
    if not messages:
        messages = rendered_messages(page)
    if not messages:
        record_error(connection, session_id, url, "No role-labelled user/assistant turns found")
        return False
    upsert_session(connection, session_id=session_id, url=url, title=find_title(payloads), raw_payload=payload, messages=messages)
    print(f"Ingested {session_id}: {len(messages)} turns")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest authenticated K Pro chats into a local SQLite store.")
    parser.add_argument("urls", nargs="*", help="K Pro chat URLs or UUIDs")
    parser.add_argument("--recent", action="store_true", help="Ingest recent chats visible in K Pro")
    parser.add_argument("--limit", type=int, default=50, help="Maximum chats for --recent (default: 50)")
    parser.add_argument("--from-file", type=Path, help="Recover JSON, HAR, or text captured outside the browser")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite destination")
    args = parser.parse_args()
    if not args.urls and not args.recent and not args.from_file:
        parser.error("provide a chat URL/UUID, --recent, or --from-file")

    load_dotenv(ROOT / ".env")
    base_url = os.getenv("KPRO_BASE_URL", "https://k.owkin.com").rstrip("/")
    connection = connect(args.db)
    try:
        if args.from_file:
            for identifier, payload in load_from_file(args.from_file):
                messages = extract_messages(payload)
                if messages:
                    url = f"file://{args.from_file}#{identifier}"
                    upsert_session(connection, session_id=identifier, url=url, title=None, raw_payload=payload, messages=messages)
                    print(f"Ingested {identifier}: {len(messages)} turns")
                else:
                    record_error(connection, identifier, str(args.from_file), "No role-labelled user/assistant turns found in file")
            return
        if not STATE_PATH.exists():
            raise SystemExit(f"Missing {STATE_PATH}. Run capture_session.py first.")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(STATE_PATH))
            page = context.new_page()
            urls = []
            if args.recent:
                home_payloads = capture_page_payloads(page, base_url)
                urls.extend(recent_urls(page, base_url, home_payloads, args.limit))
            for value in args.urls:
                urls.append(value if value.startswith("http") else f"{base_url}/chat/{value}")
            for url in dict.fromkeys(urls):
                try:
                    ingest_one(page, connection, url)
                except Exception as exc:
                    record_error(connection, chat_id(url), url, f"{type(exc).__name__}: {exc}")
                    print(f"Could not ingest {url}: {exc}")
            browser.close()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
