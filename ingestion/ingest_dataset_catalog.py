"""Ingest K Pro Explore Data dataset/table/column catalog metadata.

This is a *separate* data source from ingest_chat.py: instead of chat provenance, it
records what a dataset actually has — its tables, and each column's declared possible
values, data type, and completeness — as seen at
https://k.owkin.com/explore-data/patient-data/<DATASET>. That lets a finding's free-text
`provenance` field, and a new hypothesis, be checked against real data availability.

Three ways in, from most to least reliable today:

  1. `overview` / `table` subcommands with `--from-file` — recover from text copy/pasted
     directly out of the browser (what a researcher can do right now, no scraper needed).
  2. `scrape` subcommand — best-effort live Playwright walk of the page, reusing the
     authenticated session saved by capture_session.py. K Pro's CSS classes are not
     stable across releases, so this locates the column grid by its visible "Column Name"
     header rather than a hard-coded selector, and only accepts an ancestor's text once it
     actually parses into columns. It has not been run against the live authenticated page
     by the author of this script — verify it against a real dataset page and adjust
     `find_column_grid_text` if K Pro's layout does not match.
  3. If K Pro's Explore Data page turns out to be backed by its own JSON API (as the chat
     app is, see ingest_chat.py's api_json()), prefer capturing that traffic instead — it
     would be far more robust than any DOM walk. `scrape` also records raw JSON responses
     seen while loading the page into ingestion_errors-adjacent stdout for a human to check.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from .store import (
        DEFAULT_DB_PATH,
        connect,
        parse_available_tables,
        parse_dataset_columns,
        parse_dataset_overview,
        record_error,
        upsert_dataset,
        upsert_dataset_columns,
    )
except ImportError:  # Allows `python ingestion/ingest_dataset_catalog.py ...`.
    from store import (
        DEFAULT_DB_PATH,
        connect,
        parse_available_tables,
        parse_dataset_columns,
        parse_dataset_overview,
        record_error,
        upsert_dataset,
        upsert_dataset_columns,
    )

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path(__file__).resolve().parent / ".secrets" / "kpro_storage_state.json"


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def read_capture(path: Path) -> str:
    """Read a captured file as plain text, unwrapping a HAR's JSON response bodies.

    Mirrors ingest_chat.load_from_file's HAR handling, since a researcher may capture the
    Explore Data page the same way they'd capture a chat: browser devtools -> Network ->
    Save all as HAR.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() != ".har":
        return text
    data = json.loads(text)
    entries = data.get("log", {}).get("entries", [])
    bodies = []
    for entry in entries:
        content = entry.get("response", {}).get("content", {})
        if "text" in content:
            bodies.append(content["text"])
    return "\n\n".join(bodies)


def cmd_overview(args: argparse.Namespace) -> None:
    text = read_capture(args.from_file)
    parsed = parse_dataset_overview(text)
    dataset_id = args.dataset_id or (slug(parsed["name"]) if "name" in parsed else None)
    if not dataset_id:
        raise SystemExit("Could not determine --dataset-id (no 'Name' field found in the capture)")
    connection = connect(args.db)
    try:
        upsert_dataset(
            connection,
            dataset_id=dataset_id,
            name=parsed.get("name") or dataset_id,
            url=args.url,
            source=parsed.get("source"),
            total_patients=parsed.get("total_patients"),
            total_samples=parsed.get("total_samples"),
            description=parsed.get("description"),
            raw_text=text,
        )
        declared_tables = parse_available_tables(text)
        print(f"Ingested dataset '{dataset_id}': {parsed}")
        if declared_tables:
            print(f"Declared tables ({len(declared_tables)}): {declared_tables}")
        else:
            print("No 'Available tables' list found in this capture.")
    finally:
        connection.close()


def cmd_table(args: argparse.Namespace) -> None:
    text = read_capture(args.from_file)
    columns = parse_dataset_columns(text)
    connection = connect(args.db)
    try:
        if not columns:
            record_error(connection, args.dataset_id, str(args.from_file), f"No parseable columns for table {args.table!r}")
            raise SystemExit(f"No columns parsed from {args.from_file}. See ingestion_errors.")
        upsert_dataset_columns(connection, dataset_id=args.dataset_id, table_name=args.table, columns=columns)
        print(f"Ingested {len(columns)} column(s) for {args.dataset_id}.{args.table}")
    finally:
        connection.close()


def find_column_grid_text(page) -> str | None:
    """Return the smallest ancestor's text that contains a parseable column grid.

    K Pro's CSS classes are not stable across releases, so this walks up from the visible
    "Column Name" header instead of hard-coding a selector, and keeps the first ancestor
    whose text actually parses into at least one column via parse_dataset_columns. NOTE:
    this has not been verified against the live authenticated page — if it comes back
    empty, inspect the page's DOM directly and adjust this function.
    """
    header = page.get_by_text("Column Name", exact=True).first
    try:
        header.wait_for(timeout=10_000)
    except Exception:
        return None
    for levels in range(1, 8):
        try:
            container = header.locator(f"xpath=ancestor::*[{levels}]")
            text = container.inner_text(timeout=5_000)
        except Exception:
            continue
        if parse_dataset_columns(text):
            return text
    return None


def cmd_scrape(args: argparse.Namespace) -> None:
    from playwright.sync_api import sync_playwright

    if not STATE_PATH.exists():
        raise SystemExit(f"Missing {STATE_PATH}. Run capture_session.py first.")

    connection = connect(args.db)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=args.headless)
            context = browser.new_context(storage_state=str(STATE_PATH))
            page = context.new_page()

            json_seen: list[str] = []
            page.on("response", lambda response: (
                json_seen.append(response.url)
                if "json" in (response.headers.get("content-type") or "").lower()
                else None
            ))

            page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            page.wait_for_timeout(2_000)

            if json_seen:
                print(
                    f"Note: {len(json_seen)} JSON response(s) observed while loading this page "
                    f"(e.g. {json_seen[0]}). If one of these carries the column grid, prefer "
                    f"capturing it directly (see ingest_chat.py's api_json pattern) over this "
                    f"DOM walk — it would be far more robust."
                )

            full_text = page.inner_text("body")
            overview = parse_dataset_overview(full_text)
            dataset_id = args.dataset_id or (slug(overview["name"]) if "name" in overview else None)
            if not dataset_id:
                raise SystemExit("Could not determine --dataset-id (no 'Name' field found on the page)")
            upsert_dataset(
                connection,
                dataset_id=dataset_id,
                name=overview.get("name") or dataset_id,
                url=args.url,
                source=overview.get("source"),
                total_patients=overview.get("total_patients"),
                total_samples=overview.get("total_samples"),
                description=overview.get("description"),
                raw_text=full_text,
            )
            declared_tables = parse_available_tables(full_text)
            if not declared_tables:
                raise SystemExit(
                    "No 'Available tables' list found on the page. The page layout may not "
                    "match this script's expectations — inspect it manually."
                )
            print(f"Found {len(declared_tables)} declared table(s): {list(declared_tables)}")

            wanted = set(args.tables) if args.tables else set(declared_tables)
            ingested = failed = 0
            for table_name, declared_count in declared_tables.items():
                if table_name not in wanted:
                    continue
                try:
                    page.get_by_text(table_name, exact=True).first.click(timeout=10_000)
                    page.wait_for_timeout(1_000)
                    grid_text = find_column_grid_text(page)
                    columns = parse_dataset_columns(grid_text) if grid_text else []
                    if not columns:
                        record_error(connection, dataset_id, args.url, f"No parseable columns for table {table_name!r}")
                        failed += 1
                        continue
                    upsert_dataset_columns(connection, dataset_id=dataset_id, table_name=table_name, columns=columns)
                    ingested += 1
                    note = "" if len(columns) == declared_count else f" (page declares {declared_count})"
                    print(f"Ingested {len(columns)} column(s) for {dataset_id}.{table_name}{note}")
                except Exception as exc:
                    failed += 1
                    record_error(connection, dataset_id, args.url, f"{table_name}: {type(exc).__name__}: {exc}")
                    print(f"Could not ingest table {table_name!r}: {exc}")

            browser.close()
            summary = f"Done. {ingested} table(s) ingested, {failed} failed."
            if failed:
                summary += " See the ingestion_errors table for detail."
            print(summary)
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest K Pro Explore Data dataset/table/column catalog metadata.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite destination")
    subparsers = parser.add_subparsers(dest="command", required=True)

    overview = subparsers.add_parser("overview", help="Ingest a dataset's overview panel from a captured file")
    overview.add_argument("--from-file", type=Path, required=True, help="Text/HAR captured from the dataset's overview panel")
    overview.add_argument("--url", required=True, help="Canonical Explore Data URL for this dataset")
    overview.add_argument("--dataset-id", help="Override the id derived from the capture's 'Name' field (e.g. mosaic_window)")
    overview.set_defaults(func=cmd_overview)

    table = subparsers.add_parser("table", help="Ingest one table's column grid from a captured file")
    table.add_argument("--from-file", type=Path, required=True, help="Text/HAR captured from one table's column grid")
    table.add_argument("--dataset-id", required=True, help="Dataset this table belongs to (must already be ingested via 'overview')")
    table.add_argument("--table", required=True, help="Table name, e.g. clinical_data_table")
    table.set_defaults(func=cmd_table)

    scrape = subparsers.add_parser("scrape", help="Best-effort live scrape of the Explore Data page (unverified against production)")
    scrape.add_argument("--url", required=True, help="Explore Data URL, e.g. https://k.owkin.com/explore-data/patient-data/MOSAIC_WINDOW")
    scrape.add_argument("--dataset-id", help="Override the id derived from the page's 'Name' field")
    scrape.add_argument("--tables", nargs="*", help="Limit to these table names (default: every declared table)")
    scrape.add_argument("--headless", action="store_true", default=True)
    scrape.add_argument("--headed", dest="headless", action="store_false", help="Show the browser window (useful while verifying selectors)")
    scrape.set_defaults(func=cmd_scrape)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
