"""Ingest real K Pro chats into Breadcrumbs' local SQLite store.

K Pro is a client-rendered authenticated app. This module observes its JSON traffic
inside a saved Playwright session instead of attempting unauthenticated HTTP fetches.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

from dotenv import load_dotenv
from playwright.sync_api import Response, sync_playwright

try:
    from .store import DEFAULT_DB_PATH, connect, ingested_revisions, record_error, upsert_session
except ImportError:  # Allows `python ingestion/ingest_chat.py ...`.
    from store import DEFAULT_DB_PATH, connect, ingested_revisions, record_error, upsert_session

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


def find_title(payloads: Iterable[CapturedPayload], session_id: str) -> str | None:
    """Read the chat's own title, and only its own.

    An earlier version walked every captured payload and took the first title/name/label it
    found anywhere, which picked up the organization's name ("Default") from /api/user rather
    than the chat's. Only a payload whose URL carries this chat's id may name this chat.
    """
    for captured in payloads:
        if session_id not in captured.url.lower():
            continue
        for node in walk(captured.data):
            if not isinstance(node, dict):
                continue
            identifier = node.get("id") or node.get("chat_id")
            if not (isinstance(identifier, str) and identifier.lower() == session_id):
                continue
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


def capture_page_payloads(page, url: str, session_id: str | None = None, timeout_ms: int = 90_000) -> list[CapturedPayload]:
    """Open a chat and collect its JSON traffic, waiting for the chat's own payload.

    K Pro answers carrying plots and datatables run to hundreds of KB and their
    /api/chats/<id>/messages response can arrive long after network-idle. Waiting a fixed
    couple of seconds dropped exactly those chats — the richest ones — so this polls until
    the payload that actually belongs to this chat has turns in it, and only then stops.
    """
    captured: list[CapturedPayload] = []

    def on_response(response: Response) -> None:
        # Responses are kept only in memory until a matching chat is persisted.
        result = parse_json_response(response)
        if result:
            captured.append(result)

    page.on("response", on_response)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        if session_id is None:
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass  # Long-lived app telemetry often prevents network-idle.
            page.wait_for_timeout(2_000)
        else:
            deadline = time.monotonic() + timeout_ms / 1000
            while time.monotonic() < deadline:
                payload = payload_for_chat(captured, session_id)
                if payload is not None and extract_messages(payload):
                    break
                page.wait_for_timeout(500)
    finally:
        page.remove_listener("response", on_response)
    return captured


def payload_for_chat(payloads: list[CapturedPayload], session_id: str) -> Any | None:
    """Return the richest payload that provably belongs to this chat.

    Only payloads whose URL carries this chat's id qualify. There is deliberately no
    "any payload with turns" fallback: that could file another chat's messages under this
    chat's id — silent cross-contamination in a research-provenance store. A chat whose own
    payload never arrived is recorded as an ingestion error instead.
    """
    matching = [p.data for p in payloads if session_id in p.url.lower()]
    if not matching:
        return None
    return max(matching, key=lambda payload: len(extract_messages(payload)))


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


def stored_token(page) -> tuple[str | None, int | None]:
    """Read the OIDC access token and its expiry from the SPA's localStorage."""
    try:
        entries = page.evaluate("() => Object.fromEntries(Object.entries(localStorage))")
    except Exception:
        return None, None
    for key, value in (entries or {}).items():
        if not key.startswith("oidc.user:"):
            continue
        try:
            record = json.loads(value)
        except Exception:
            continue
        token = record.get("access_token")
        if isinstance(token, str) and token:
            return token, record.get("expires_at")
    return None, None


def bearer_token(page, timeout_ms: int = 60_000) -> str | None:
    """Return a non-expired K Pro access token, waiting for the SPA to renew if needed.

    K Pro's API is not cookie-authenticated — /api/chats returns 401 on cookies alone; the app
    sends `Authorization: Bearer <access_token>`, which oidc-client keeps under an
    `oidc.user:<issuer>:<client>` key. That token lives only ~15 minutes, so the one inside a
    saved storage_state is almost always stale by the time we run. The SPA silently renews it
    a few seconds after the page loads, so poll until the stored token is actually in date
    rather than firing a request that would come back "Signature has expired".
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        token, expires_at = stored_token(page)
        if token and (not isinstance(expires_at, int) or expires_at > time.time() + 30):
            return token
        if time.monotonic() >= deadline:
            return token  # Expired or unknown; let the caller surface the API's own error.
        page.wait_for_timeout(2_000)


def api_json(context, page, url: str, timeout_ms: int = 90_000) -> Any | None:
    """GET a K Pro API endpoint with a bearer token, renewing once if it is rejected."""
    for attempt in range(2):
        token = bearer_token(page)
        if not token:
            return None
        response = context.request.get(
            url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout_ms
        )
        if response.ok:
            try:
                return response.json()
            except Exception:
                return None
        if response.status not in (401, 403) or attempt:
            return None
        page.wait_for_timeout(3_000)  # Token rejected — give the SPA a beat to renew, then retry.
    return None


def list_chats(context, page, base_url: str, limit: int) -> list[dict[str, Any]]:
    """List the signed-in user's chats, newest first, following pagination.

    The chat list is NOT loaded on the home page — K Pro fetches it only on /chat-history,
    via GET /api/chats?page=N. Walking the home page (the previous behaviour) therefore found
    zero chats and silently ingested nothing. Deleted chats are skipped.
    """
    page_size = min(100, max(1, limit))
    chats: list[dict[str, Any]] = []
    page_number = 1
    while len(chats) < limit:
        body = api_json(
            context, page, f"{base_url}/api/chats?search=&page_size={page_size}&page={page_number}"
        )
        if not isinstance(body, dict):
            break
        batch = body.get("chats") or []
        if not batch:
            break
        for item in batch:
            identifier = item.get("id")
            if not isinstance(identifier, str) or not UUID_RE.fullmatch(identifier):
                continue
            if item.get("is_deleted"):
                continue
            chats.append({
                "id": identifier.lower(),
                "title": item.get("name"),
                "updated_at": item.get("updated_at") or item.get("last_message_created_at"),
            })
        total = body.get("total")
        if isinstance(total, int) and len(chats) >= total:
            break
        page_number += 1

    if not chats:
        # Fallback: render /chat-history and scrape its links, in case the API shape moves.
        try:
            page.goto(f"{base_url}/chat-history", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5_000)
            hrefs = page.locator('a[href*="/chat/"]').evaluate_all("els => els.map(e => e.href)")
        except Exception:
            hrefs = []
        seen = dict.fromkeys(identifier for identifier in (chat_id(href) for href in hrefs) if identifier)
        chats = [{"id": identifier, "title": None, "updated_at": None} for identifier in seen]

    return chats[:limit]


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


def ingest_one(
    context,
    page,
    connection,
    base_url: str,
    url: str,
    *,
    title: str | None = None,
    updated_at: str | None = None,
) -> bool:
    session_id = chat_id(url)
    if not session_id:
        record_error(connection, None, url, "URL does not contain a K Pro chat UUID")
        return False

    # API first: /api/chats/<id>/messages returns the chat verbatim. It is faster than
    # rendering the page, it cannot pick up another chat's payload, and it reaches chats the
    # UI declines to render (a chat created by a colleague shows a "Created by" placeholder
    # in the browser but still serves its messages over the API).
    payload = api_json(context, page, f"{base_url}/api/chats/{session_id}/messages")
    messages = extract_messages(payload) if payload is not None else []
    payloads: list[CapturedPayload] = []
    if not messages:
        payloads = capture_page_payloads(page, url, session_id)
        payload = payload_for_chat(payloads, session_id)
        messages = extract_messages(payload) if payload is not None else []
    if not messages:
        messages = rendered_messages(page)
    if not messages:
        record_error(connection, session_id, url, "No role-labelled user/assistant turns found")
        return False
    # The chat list is the authoritative source of a chat's name. When ingesting a bare URL
    # outside a --recent run there is no list, so ask the chat's own metadata endpoint.
    resolved_title = title or find_title(payloads, session_id)
    if not resolved_title:
        metadata = api_json(context, page, f"{base_url}/api/chats/{session_id}")
        if isinstance(metadata, dict):
            resolved_title = clean_text(metadata.get("name"))
    upsert_session(
        connection,
        session_id=session_id,
        url=url,
        title=resolved_title,
        raw_payload=payload,
        messages=messages,
        updated_at=updated_at,
    )
    label = f" — {resolved_title[:60]}" if resolved_title else ""
    print(f"Ingested {session_id}: {len(messages)} turns{label}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest authenticated K Pro chats into a local SQLite store.")
    parser.add_argument("urls", nargs="*", help="K Pro chat URLs or UUIDs")
    parser.add_argument("--recent", action="store_true", help="Ingest recent chats visible in K Pro")
    parser.add_argument("--limit", type=int, default=50, help="Maximum chats for --recent (default: 50)")
    parser.add_argument("--from-file", type=Path, help="Recover JSON, HAR, or text captured outside the browser")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite destination")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest chats already stored and unchanged since the last run (default: skip them)",
    )
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

            # The API needs a bearer token that only the running SPA can mint, so a page must
            # be open before any request — including when ingesting explicit URLs.
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)

            targets: dict[str, dict[str, Any]] = {}
            if args.recent:
                discovered = list_chats(context, page, base_url, args.limit)
                if not discovered:
                    raise SystemExit(
                        "No chats found. The saved session may have expired — re-run capture_session.py."
                    )
                print(f"Found {len(discovered)} chat(s) in K Pro history.")
                for chat in discovered:
                    targets[chat["id"]] = chat
            for value in args.urls:
                identifier = chat_id(value)
                if not identifier:
                    record_error(connection, None, value, "URL does not contain a K Pro chat UUID")
                    print(f"Skipping {value}: not a K Pro chat UUID")
                    continue
                targets.setdefault(identifier, {"id": identifier, "title": None, "updated_at": None})

            # Incremental by default: a chat already stored at the same K Pro revision is left
            # alone, so re-running --recent continues where the last run stopped instead of
            # re-scraping the whole history. --force overrides.
            stored = ingested_revisions(connection)
            ingested = skipped = failed = 0
            for identifier, chat in targets.items():
                revision = chat.get("updated_at")
                if (
                    not args.force
                    and identifier in stored
                    and revision is not None
                    and stored[identifier] == revision
                ):
                    skipped += 1
                    continue
                url = urljoin(base_url, f"/chat/{identifier}")
                try:
                    if ingest_one(
                        context,
                        page,
                        connection,
                        base_url,
                        url,
                        title=chat.get("title"),
                        updated_at=revision,
                    ):
                        ingested += 1
                    else:
                        failed += 1
                except Exception as exc:
                    failed += 1
                    record_error(connection, identifier, url, f"{type(exc).__name__}: {exc}")
                    print(f"Could not ingest {url}: {exc}")

            summary = f"Done. {ingested} ingested, {skipped} unchanged (skipped), {failed} failed."
            if failed:
                summary += " See the ingestion_errors table for detail."
            print(summary)
            browser.close()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
