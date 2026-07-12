from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ingestion.store import DEFAULT_DB_PATH, connect
from ingestion.write_findings import write_payload

from .embeddings import (
    DENSE_MIN_SIMILARITY,
    EmbeddingBackend,
    RRF_K,
    content_hash,
    cosine_similarity,
    knowledge_search_text,
    pack_vector,
    unpack_vector,
    utc_now,
)
from .knowledge import (
    APPROVED_ELICITATION_MODELS,
    DERIVED_FIELDS,
    KNOWLEDGE_KINDS,
    action_delta,
    alias_list,
    condition_list,
    json_dumps,
    json_object,
    lexical_score,
    nonempty_text,
    sample_list,
    scope_compatibility,
    scope_matches,
    score_samples,
    tokens,
)
from .people import (
    EXPERTISE_METHOD,
    PRIMARY_ROLES,
    ROLE_WEIGHTS,
    clean_person_name,
    evidence_confidence,
    normalize_person_name,
    provisional_person_id,
)

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
    "source_type",
    "markdown",
    "resources",
}
COLUMN_ALIASES = {
    "created_at": "timestamp",
    "source_session": "source_session_id",
}
Scalar = str | int | float | bool | None

KNOWLEDGE_INPUT_FIELDS = frozenset(
    {
        "kind",
        "proposition",
        "rationale",
        "scope",
        "aliases",
        "conditions",
        "evidence_quote",
        "source_message_id",
        "prior_samples",
        "posterior_samples",
        "elicitation_model",
        "elicitation_run_id",
        "action_before",
        "action_after",
        "prior_action_samples",
        "posterior_action_samples",
        "reason",
        "author",
        "approved_by",
        "supersedes_id",
    }
)

KNOWLEDGE_JSON_FIELDS = frozenset(
    {
        "scope",
        "aliases",
        "conditions",
        "prior_samples",
        "posterior_samples",
        "action_before",
        "action_after",
        "action_delta",
        "prior_action_samples",
        "posterior_action_samples",
    }
)


class BreadcrumbsStore:
    """MCP-facing adapter over the team's canonical SQLite research-memory store."""

    def __init__(
        self,
        path: str | Path = DEFAULT_DB_PATH,
        *,
        embedding_backend: EmbeddingBackend | None = None,
    ):
        self.path = Path(path)
        self.embedding_backend = embedding_backend
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect(self.path)
        connection.close()
        self._backfill_people()

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
        decoded = self._decode(row)
        self._sync_artifact_contributions(
            artifact_type="finding",
            artifact_id=decoded["id"],
            contributions=[(decoded["author"], "finding_author")],
            source_session_id=decoded.get("source_session_id"),
            created_at=decoded["timestamp"],
        )
        return decoded

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

    def score_surprise(
        self,
        prior_samples: Any,
        posterior_samples: Any,
        *,
        prior_action_samples: Any = None,
        posterior_action_samples: Any = None,
    ) -> dict[str, Any]:
        """Return reproducible information-theoretic metrics without persisting anything."""

        return score_samples(
            prior_samples,
            posterior_samples,
            prior_action_samples=prior_action_samples,
            posterior_action_samples=posterior_action_samples,
        )

    def write_knowledge(self, record: dict[str, Any]) -> dict[str, Any]:
        """Validate and persist one explicitly approved, source-linked knowledge item."""

        if not isinstance(record, dict):
            raise ValueError("record must be a JSON object")
        unexpected = set(record) - KNOWLEDGE_INPUT_FIELDS
        if unexpected:
            derived = sorted(unexpected & DERIVED_FIELDS)
            if derived:
                raise ValueError(
                    "calculated fields must not be supplied: " + ", ".join(derived)
                )
            raise ValueError("unknown knowledge field(s): " + ", ".join(sorted(unexpected)))

        kind = nonempty_text(record.get("kind"), "kind")
        if kind not in KNOWLEDGE_KINDS:
            raise ValueError("kind must be one of: " + ", ".join(sorted(KNOWLEDGE_KINDS)))
        proposition = nonempty_text(record.get("proposition"), "proposition")
        rationale = nonempty_text(record.get("rationale"), "rationale")
        scope = json_object(record.get("scope"), "scope")
        aliases = alias_list(record.get("aliases"))
        conditions = condition_list(record.get("conditions"))
        evidence_quote = nonempty_text(record.get("evidence_quote"), "evidence_quote")
        source_message_id = nonempty_text(record.get("source_message_id"), "source_message_id")
        author = nonempty_text(record.get("author"), "author")
        approved_by = nonempty_text(record.get("approved_by"), "approved_by")
        elicitation_model = nonempty_text(
            record.get("elicitation_model"), "elicitation_model"
        )
        if elicitation_model not in APPROVED_ELICITATION_MODELS:
            raise ValueError(
                "elicitation_model must be approved for reproducible elicitation: "
                + ", ".join(sorted(APPROVED_ELICITATION_MODELS))
            )
        elicitation_run_id = nonempty_text(
            record.get("elicitation_run_id"), "elicitation_run_id"
        )

        reason_value = record.get("reason")
        if kind == "abandoned":
            reason = nonempty_text(reason_value, "reason")
        elif reason_value is not None:
            raise ValueError("reason is allowed only when kind is abandoned")
        else:
            reason = None

        prior_samples = sample_list(record.get("prior_samples"), "prior_samples")
        posterior_samples = sample_list(record.get("posterior_samples"), "posterior_samples")
        prior_action_samples = record.get("prior_action_samples")
        posterior_action_samples = record.get("posterior_action_samples")
        metrics = score_samples(
            prior_samples,
            posterior_samples,
            prior_action_samples=prior_action_samples,
            posterior_action_samples=posterior_action_samples,
        )
        if prior_action_samples is not None:
            prior_action_samples = sample_list(
                prior_action_samples, "prior_action_samples", minimum=1
            )
            posterior_action_samples = sample_list(
                posterior_action_samples, "posterior_action_samples", minimum=1
            )

        action_before = record.get("action_before")
        action_after = record.get("action_after")
        if (action_before is None) != (action_after is None):
            raise ValueError("action_before and action_after must be supplied together")
        if action_before is not None:
            action_before = json_object(action_before, "action_before")
            action_after = json_object(action_after, "action_after")
        delta = action_delta(action_before, action_after)

        supersedes_id = record.get("supersedes_id")
        if supersedes_id is not None:
            supersedes_id = nonempty_text(supersedes_id, "supersedes_id")

        key = "\x1f".join((source_message_id, kind, proposition))
        item_id = "K-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12].upper()
        created_at = datetime.now(timezone.utc).isoformat()
        reviewed_payload = {
            "kind": kind,
            "proposition": proposition,
            "rationale": rationale,
            "scope": scope,
            "aliases": aliases,
            "conditions": conditions,
            "evidence_quote": evidence_quote,
            "source_message_id": source_message_id,
            "prior_samples": prior_samples,
            "posterior_samples": posterior_samples,
            "elicitation_model": elicitation_model,
            "elicitation_run_id": elicitation_run_id,
            "action_before": action_before,
            "action_after": action_after,
            "prior_action_samples": prior_action_samples,
            "posterior_action_samples": posterior_action_samples,
            "reason": reason,
            "author": author,
            "approved_by": approved_by,
            "supersedes_id": supersedes_id,
        }

        connection = connect(self.path)
        try:
            source = connection.execute(
                "SELECT id, session_id, content FROM chat_messages WHERE id = ?",
                (source_message_id,),
            ).fetchone()
            if source is None:
                raise ValueError(f"Unknown source message: {source_message_id}")
            if evidence_quote not in source["content"]:
                raise ValueError("evidence_quote must occur verbatim in the source message")

            existing = connection.execute(
                "SELECT knowledge_items.*, chat_messages.content AS _current_source_content, "
                "EXISTS(SELECT 1 FROM knowledge_items newer "
                "WHERE newer.supersedes_id = knowledge_items.id) AS is_superseded "
                "FROM knowledge_items JOIN chat_messages "
                "ON chat_messages.id = knowledge_items.source_message_id "
                "WHERE knowledge_items.id = ?",
                (item_id,),
            ).fetchone()
            if existing is not None:
                decoded = self._decode_knowledge(existing)
                conflicts = [
                    field
                    for field, expected in reviewed_payload.items()
                    if decoded.get(field) != expected
                ]
                if conflicts:
                    raise ValueError(
                        f"knowledge item {item_id} already exists with different reviewed field(s): "
                        + ", ".join(conflicts)
                        + "; create a new source-linked superseding patch"
                    )
                # A prior write can have committed before a transient embedding failure. Closing
                # this read connection first lets an idempotent retry repair the derived index.
                connection.close()
                self._ensure_embeddings([decoded])
                self._sync_knowledge_contributions(decoded)
                return decoded

            if supersedes_id is not None:
                if supersedes_id == item_id:
                    raise ValueError("a knowledge item cannot supersede itself")
                prior_item = connection.execute(
                    "SELECT k.id, EXISTS(SELECT 1 FROM knowledge_items successor "
                    "WHERE successor.supersedes_id = k.id) AS has_successor "
                    "FROM knowledge_items k WHERE k.id = ?",
                    (supersedes_id,),
                ).fetchone()
                if prior_item is None:
                    raise ValueError(f"Unknown superseded knowledge item: {supersedes_id}")
                if prior_item["has_successor"]:
                    raise ValueError(
                        f"knowledge item {supersedes_id} already has a successor; "
                        "supersede the active head instead"
                    )

            with connection:
                try:
                    connection.execute(
                        """
                        INSERT INTO knowledge_items(
                            id, kind, proposition, rationale, scope, aliases, conditions,
                            evidence_quote,
                            source_message_id, source_message_hash, source_session_id,
                            prior_samples, posterior_samples,
                            elicitation_model, elicitation_run_id, scoring_method,
                            prior_mean, posterior_mean, belief_shift, bayesian_surprise_bits,
                            prior_entropy_bits, posterior_entropy_bits, certainty_gain_bits,
                            action_before, action_after, action_delta,
                            prior_action_samples, posterior_action_samples, action_surprise_bits,
                            reason, author, approved_by, supersedes_id, created_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            item_id,
                            kind,
                            proposition,
                            rationale,
                            json_dumps(scope),
                            json_dumps(aliases),
                            json_dumps(conditions),
                            evidence_quote,
                            source_message_id,
                            hashlib.sha256(source["content"].encode("utf-8")).hexdigest(),
                            source["session_id"],
                            json_dumps(prior_samples),
                            json_dumps(posterior_samples),
                            elicitation_model,
                            elicitation_run_id,
                            metrics["scoring_method"],
                            metrics["prior_mean"],
                            metrics["posterior_mean"],
                            metrics["belief_shift"],
                            metrics["bayesian_surprise_bits"],
                            metrics["prior_entropy_bits"],
                            metrics["posterior_entropy_bits"],
                            metrics["certainty_gain_bits"],
                            json_dumps(action_before) if action_before is not None else None,
                            json_dumps(action_after) if action_after is not None else None,
                            json_dumps(delta),
                            json_dumps(prior_action_samples)
                            if prior_action_samples is not None
                            else None,
                            json_dumps(posterior_action_samples)
                            if posterior_action_samples is not None
                            else None,
                            metrics["action_surprise_bits"],
                            reason,
                            author,
                            approved_by,
                            supersedes_id,
                            created_at,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    if supersedes_id is not None and "supersedes_id" in str(exc):
                        raise ValueError(
                            f"knowledge item {supersedes_id} already has a successor; "
                            "supersede the active head instead"
                        ) from exc
                    raise
            row = connection.execute(
                "SELECT knowledge_items.*, chat_messages.content AS _current_source_content, "
                "0 AS is_superseded FROM knowledge_items JOIN chat_messages "
                "ON chat_messages.id = knowledge_items.source_message_id "
                "WHERE knowledge_items.id = ?",
                (item_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise RuntimeError("knowledge item was not written")
        decoded = self._decode_knowledge(row)
        self._ensure_embeddings([decoded])
        self._sync_knowledge_contributions(decoded)
        return decoded

    def _sync_knowledge_contributions(self, item: dict[str, Any]) -> None:
        self._sync_artifact_contributions(
            artifact_type="knowledge",
            artifact_id=item["id"],
            contributions=[
                (item["author"], "knowledge_author"),
                (item["approved_by"], "knowledge_reviewer"),
            ],
            source_session_id=item["source_session_id"],
            created_at=item["created_at"],
        )

    def _sync_artifact_contributions(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        contributions: list[tuple[str, str]],
        source_session_id: str | None,
        created_at: str,
    ) -> None:
        """Replace one artifact's derived person edges without guessing fuzzy identity merges."""

        now = utc_now()
        people: dict[str, tuple[str, str, str]] = {}
        edges: set[tuple[str, str]] = set()
        for raw_name, role in contributions:
            display_name = clean_person_name(raw_name)
            normalized_name = normalize_person_name(display_name)
            person_id = provisional_person_id(normalized_name)
            people[person_id] = (display_name, normalized_name, person_id)
            edges.add((person_id, role))

        connection = connect(self.path)
        try:
            with connection:
                connection.execute(
                    "DELETE FROM person_contributions "
                    "WHERE artifact_type = ? AND artifact_id = ?",
                    (artifact_type, artifact_id),
                )
                connection.executemany(
                    """
                    INSERT INTO people(
                        id, display_name, normalized_name, aliases, org_unit,
                        identity_status, created_at, updated_at
                    ) VALUES (?, ?, ?, '[]', NULL, 'provisional', ?, ?)
                    ON CONFLICT(normalized_name) DO NOTHING
                    """,
                    [
                        (person_id, display_name, normalized_name, now, now)
                        for display_name, normalized_name, person_id in people.values()
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO person_contributions(
                        person_id, artifact_type, artifact_id, role,
                        source_session_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            person_id,
                            artifact_type,
                            artifact_id,
                            role,
                            source_session_id,
                            created_at,
                        )
                        for person_id, role in sorted(edges)
                    ],
                )
        finally:
            connection.close()

    def _backfill_people(self) -> None:
        connection = connect(self.path)
        try:
            with connection:
                connection.execute(
                    "DELETE FROM person_contributions WHERE artifact_type = 'finding' "
                    "AND artifact_id NOT IN (SELECT id FROM findings)"
                )
                connection.execute(
                    "DELETE FROM person_contributions WHERE artifact_type = 'knowledge' "
                    "AND artifact_id NOT IN (SELECT id FROM knowledge_items)"
                )
            findings = connection.execute(
                "SELECT f.id, f.author, f.source_session_id, f.timestamp FROM findings f "
                "WHERE (SELECT COUNT(*) FROM person_contributions c "
                "WHERE c.artifact_type = 'finding' AND c.artifact_id = f.id) < 1"
            ).fetchall()
            knowledge = connection.execute(
                "SELECT k.id, k.author, k.approved_by, k.source_session_id, k.created_at "
                "FROM knowledge_items k WHERE (SELECT COUNT(*) FROM person_contributions c "
                "WHERE c.artifact_type = 'knowledge' AND c.artifact_id = k.id) < 2"
            ).fetchall()
        finally:
            connection.close()
        for row in findings:
            self._sync_artifact_contributions(
                artifact_type="finding",
                artifact_id=row["id"],
                contributions=[(row["author"], "finding_author")],
                source_session_id=row["source_session_id"],
                created_at=row["timestamp"],
            )
        for row in knowledge:
            self._sync_artifact_contributions(
                artifact_type="knowledge",
                artifact_id=row["id"],
                contributions=[
                    (row["author"], "knowledge_author"),
                    (row["approved_by"], "knowledge_reviewer"),
                ],
                source_session_id=row["source_session_id"],
                created_at=row["created_at"],
            )

    def _ensure_embeddings(self, items: list[dict[str, Any]]) -> None:
        backend = self.embedding_backend
        if backend is None or not items:
            return
        model = backend.model_id
        documents = {item["id"]: knowledge_search_text(item) for item in items}
        hashes = {item_id: content_hash(text) for item_id, text in documents.items()}
        connection = connect(self.path)
        try:
            existing = {
                row["item_id"]: row["content_hash"]
                for row in connection.execute(
                    "SELECT item_id, content_hash FROM knowledge_embeddings WHERE model = ?",
                    (model,),
                )
            }
            pending = [item_id for item_id in documents if existing.get(item_id) != hashes[item_id]]
            if not pending:
                return
            vectors = backend.embed_documents([documents[item_id] for item_id in pending])
            if len(vectors) != len(pending):
                raise ValueError("embedding backend returned the wrong number of document vectors")
            records = []
            for item_id, values in zip(pending, vectors, strict=True):
                blob, dimensions = pack_vector(values)
                records.append(
                    (item_id, model, dimensions, hashes[item_id], blob, utc_now())
                )
            with connection:
                connection.executemany(
                    """
                    INSERT INTO knowledge_embeddings(
                        item_id, model, dimensions, content_hash, vector, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id, model) DO UPDATE SET
                        dimensions = excluded.dimensions,
                        content_hash = excluded.content_hash,
                        vector = excluded.vector,
                        created_at = excluded.created_at
                    """,
                    records,
                )
        finally:
            connection.close()

    def _dense_rankings(
        self,
        query: str,
        items: list[dict[str, Any]],
        *,
        candidate_limit: int,
    ) -> tuple[dict[str, int], dict[str, float]]:
        backend = self.embedding_backend
        if backend is None or not query.strip() or not items:
            return {}, {}
        self._ensure_embeddings(items)
        query_vector = backend.embed_query(query)
        connection = connect(self.path)
        try:
            rows = connection.execute(
                """
                SELECT item_id, dimensions, vector
                FROM knowledge_embeddings
                WHERE model = ?
                """,
                (backend.model_id,),
            ).fetchall()
        finally:
            connection.close()
        scored = [
            (
                row["item_id"],
                cosine_similarity(query_vector, unpack_vector(row["vector"], row["dimensions"])),
            )
            for row in rows
        ]
        scored = [pair for pair in scored if pair[1] >= DENSE_MIN_SIMILARITY]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        scored = scored[:candidate_limit]
        return (
            {item_id: index + 1 for index, (item_id, _) in enumerate(scored)},
            {item_id: round(similarity, 6) for item_id, similarity in scored},
        )

    def recall_knowledge(
        self,
        query: str = "",
        *,
        scope: dict[str, Any] | None = None,
        kinds: Iterable[str] | None = None,
        limit: int = 10,
        include_superseded: bool = False,
        strict_scope: bool = False,
    ) -> list[dict[str, Any]]:
        """Retrieve approved knowledge with local BM25, dense search, and applicability."""

        if not isinstance(query, str):
            raise ValueError("query must be a string")
        requested_scope = json_object({} if scope is None else scope, "scope", allow_empty=True)
        if isinstance(kinds, (str, bytes)):
            raise ValueError("kinds must be an array")
        requested_kinds = set(kinds or [])
        unknown_kinds = requested_kinds - KNOWLEDGE_KINDS
        if unknown_kinds:
            raise ValueError("unknown knowledge kind(s): " + ", ".join(sorted(unknown_kinds)))
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if not isinstance(include_superseded, bool):
            raise ValueError("include_superseded must be a boolean")
        if not isinstance(strict_scope, bool):
            raise ValueError("strict_scope must be a boolean")

        connection = connect(self.path)
        try:
            rows = connection.execute(
                "SELECT k.*, m.content AS _current_source_content, "
                "EXISTS(SELECT 1 FROM knowledge_items newer "
                "WHERE newer.supersedes_id = k.id) AS is_superseded "
                "FROM knowledge_items k JOIN chat_messages m ON m.id = k.source_message_id"
            ).fetchall()
            query_terms = sorted(tokens(query))
            if query_terms:
                fts_query = " OR ".join(f'"{term}"' for term in query_terms)
                fts_rows = connection.execute(
                    """
                    SELECT item_id,
                           bm25(knowledge_fts, 0.0, 3.0, 2.0, 2.0, 2.5, 2.0, 0.5, 1.5, 1.0)
                               AS bm25_raw
                    FROM knowledge_fts
                    WHERE knowledge_fts MATCH ?
                    ORDER BY bm25_raw
                    LIMIT ?
                    """,
                    (fts_query, max(100, limit * 10)),
                ).fetchall()
            else:
                fts_rows = []
        finally:
            connection.close()

        items = [self._decode_knowledge(row) for row in rows]
        fts_rank = {row["item_id"]: index + 1 for index, row in enumerate(fts_rows)}
        fts_raw = {row["item_id"]: row["bm25_raw"] for row in fts_rows}
        dense_rank, dense_similarity = self._dense_rankings(
            query,
            items,
            candidate_limit=max(100, limit * 10),
        )
        by_id = {item["id"]: item for item in items}
        successor_by_id = {
            item["supersedes_id"]: item["id"]
            for item in items
            if item["supersedes_id"] is not None
        }

        def active_head(item: dict[str, Any]) -> dict[str, Any]:
            current = item
            seen = {current["id"]}
            while current["id"] in successor_by_id:
                successor_id = successor_by_id[current["id"]]
                if successor_id in seen:
                    raise RuntimeError("knowledge patch history contains a cycle")
                seen.add(successor_id)
                current = by_id[successor_id]
            return current

        def filters_match(item: dict[str, Any]) -> bool:
            if requested_kinds and item["kind"] not in requested_kinds:
                return False
            if strict_scope and requested_scope:
                return scope_matches(item["scope"], requested_scope)
            return True

        def score_item(
            search_item: dict[str, Any], applicability_item: dict[str, Any]
        ) -> tuple[float, dict[str, Any], dict[str, Any]] | None:
            lexical = lexical_score(query, search_item) if query.strip() else 0.0
            bm25_position = fts_rank.get(search_item["id"])
            dense_position = dense_rank.get(search_item["id"])
            if (
                query.strip()
                and lexical <= 0.0
                and bm25_position is None
                and dense_position is None
            ):
                return None
            applicability = scope_compatibility(
                applicability_item["scope"],
                requested_scope,
                applicability_item.get("conditions", []),
            )
            reciprocal_sum = 0.0
            if bm25_position is not None:
                reciprocal_sum += 1.0 / (RRF_K + bm25_position)
            if dense_position is not None:
                reciprocal_sum += 1.0 / (RRF_K + dense_position)
            signal_count = 2 if self.embedding_backend is not None else 1
            reciprocal_max = signal_count / (RRF_K + 1)
            fusion_score = reciprocal_sum / reciprocal_max if reciprocal_max else 0.0
            combined = 0.45 * lexical + 0.45 * fusion_score
            if requested_scope:
                combined += 0.1 * applicability["score"]
            components = {
                "field_coverage": lexical,
                "bm25_rank": bm25_position,
                "bm25_raw": fts_raw.get(search_item["id"]),
                "dense_rank": dense_position,
                "dense_similarity": dense_similarity.get(search_item["id"]),
                "embedding_model": (
                    self.embedding_backend.model_id
                    if self.embedding_backend is not None
                    else None
                ),
                "dense_min_similarity": DENSE_MIN_SIMILARITY,
                "rrf_k": RRF_K,
                "rank_fusion": round(fusion_score, 6),
                "scope_applicability": applicability["score"],
            }
            return round(combined, 6), components, applicability

        ranked: list[dict[str, Any]] = []
        if include_superseded:
            for item in items:
                if not filters_match(item):
                    continue
                scored = score_item(item, item)
                if scored is None:
                    continue
                score, components, applicability = scored
                item["retrieval_score"] = score
                item["retrieval_components"] = components
                item["scope_compatibility"] = applicability
                item["strict_scope"] = strict_scope
                ranked.append(item)
        else:
            resolved: dict[str, dict[str, Any]] = {}
            for historical_item in items:
                head = active_head(historical_item)
                if not filters_match(head):
                    continue
                scored = score_item(historical_item, head)
                if scored is None:
                    continue
                score, components, applicability = scored
                result = resolved.setdefault(
                    head["id"],
                    {
                        **head,
                        "retrieval_score": float("-inf"),
                        "retrieval_components": {},
                        "scope_compatibility": applicability,
                        "strict_scope": strict_scope,
                        "matched_via_history": [],
                    },
                )
                if score > result["retrieval_score"]:
                    result["retrieval_score"] = score
                    result["retrieval_components"] = components
                    result["scope_compatibility"] = applicability
                if query.strip() and historical_item["id"] != head["id"]:
                    result["matched_via_history"].append(historical_item["id"])
            for result in resolved.values():
                result["matched_via_history"] = sorted(set(result["matched_via_history"]))
                ranked.append(result)

        ranked.sort(
            key=lambda item: (
                item["retrieval_score"],
                item["bayesian_surprise_bits"],
                item["created_at"],
            ),
            reverse=True,
        )
        return ranked[:limit]

    def find_experts(
        self,
        topic: str,
        *,
        scope: dict[str, Any] | None = None,
        limit: int = 5,
        evidence_limit: int = 5,
    ) -> dict[str, Any]:
        """Rank demonstrated topic experience and return the source evidence behind it."""

        topic = nonempty_text(topic, "topic")
        query_terms = tokens(topic)
        if not query_terms:
            raise ValueError("topic must include searchable text")
        requested_scope = json_object({} if scope is None else scope, "scope", allow_empty=True)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("limit must be an integer between 1 and 20")
        if (
            isinstance(evidence_limit, bool)
            or not isinstance(evidence_limit, int)
            or not 1 <= evidence_limit <= 20
        ):
            raise ValueError("evidence_limit must be an integer between 1 and 20")

        knowledge = self.recall_knowledge(
            topic,
            scope=requested_scope,
            limit=100,
            include_superseded=False,
        )
        artifacts: dict[tuple[str, str], dict[str, Any]] = {}
        for item in knowledge:
            components = item["retrieval_components"]
            similarity = components.get("dense_similarity")
            dense_signal = 0.0
            if similarity is not None:
                dense_signal = max(
                    0.0,
                    (similarity - DENSE_MIN_SIMILARITY)
                    / (1.0 - DENSE_MIN_SIMILARITY),
                )
            relevance = min(
                1.0,
                max(
                    float(components.get("field_coverage") or 0.0),
                    float(components.get("rank_fusion") or 0.0),
                    dense_signal,
                ),
            )
            artifacts[("knowledge", item["id"])] = {
                "artifact_type": "knowledge",
                "artifact_id": item["id"],
                "summary": item["proposition"],
                "kind": item["kind"],
                "status": None,
                "reason": item.get("reason"),
                "source_session_id": item["source_session_id"],
                "relevance": round(relevance, 6),
                "retrieval_components": components,
            }

        connection = connect(self.path)
        try:
            finding_rows = connection.execute("SELECT * FROM findings").fetchall()
            contribution_rows = connection.execute(
                """
                SELECT c.*, p.display_name, p.identity_status
                FROM person_contributions c
                JOIN people p ON p.id = c.person_id
                """
            ).fetchall()
        finally:
            connection.close()

        for row in finding_rows:
            item = self._decode(row)
            searchable = {
                "disease": item.get("disease"),
                "hypothesis_text": item.get("hypothesis_text"),
                "signature": item.get("signature"),
                "effect": item.get("effect"),
                "provenance": item.get("provenance"),
                "reason": item.get("reason"),
                "note": item.get("note"),
                "entities": item.get("entities"),
            }
            coverage = len(query_terms & tokens(searchable)) / len(query_terms)
            if coverage <= 0.0:
                continue
            disease = requested_scope.get("disease")
            if (
                disease is not None
                and isinstance(disease, str)
                and isinstance(item.get("disease"), str)
                and disease.casefold() == item["disease"].casefold()
            ):
                coverage = min(1.0, coverage + 0.1)
            artifacts[("finding", item["id"])] = {
                "artifact_type": "finding",
                "artifact_id": item["id"],
                "summary": item["hypothesis_text"],
                "kind": None,
                "status": item["status"],
                "reason": item.get("reason"),
                "source_session_id": item.get("source_session_id"),
                "relevance": round(coverage, 6),
                "retrieval_components": {"field_coverage": round(coverage, 6)},
            }

        people: dict[str, dict[str, Any]] = {}
        for row in contribution_rows:
            artifact_key = (row["artifact_type"], row["artifact_id"])
            artifact = artifacts.get(artifact_key)
            if artifact is None:
                continue
            person = people.setdefault(
                row["person_id"],
                {
                    "person_id": row["person_id"],
                    "display_name": row["display_name"],
                    "identity_status": row["identity_status"],
                    "artifacts": {},
                },
            )
            evidence = person["artifacts"].setdefault(
                artifact_key,
                {
                    **artifact,
                    "roles": [],
                    "role_weight": 0.0,
                    "primary": False,
                },
            )
            role = row["role"]
            evidence["roles"].append(role)
            evidence["role_weight"] = max(evidence["role_weight"], ROLE_WEIGHTS[role])
            evidence["primary"] = evidence["primary"] or role in PRIMARY_ROLES

        ranked: list[dict[str, Any]] = []
        for person in people.values():
            evidence = list(person.pop("artifacts").values())
            primary_evidence = [item for item in evidence if item["primary"]]
            if not primary_evidence:
                continue
            for item in evidence:
                item["roles"] = sorted(set(item["roles"]))
                item["evidence_score"] = round(
                    item["relevance"] * item["role_weight"], 6
                )
            session_best: dict[str, float] = {}
            for item in evidence:
                session_key = item["source_session_id"] or (
                    f"{item['artifact_type']}:{item['artifact_id']}"
                )
                session_best[session_key] = max(
                    session_best.get(session_key, 0.0), item["evidence_score"]
                )
            distinct_sessions = len(session_best)
            primary_count = len(primary_evidence)
            artifact_types = {item["artifact_type"] for item in primary_evidence}
            session_score = sum(session_best.values())
            independent_session_bonus = 0.1 * min(max(distinct_sessions - 1, 0), 3)
            source_diversity_bonus = 0.05 * max(len(artifact_types) - 1, 0)
            score = session_score + independent_session_bonus + source_diversity_bonus
            evidence.sort(
                key=lambda item: (
                    item["evidence_score"],
                    item["primary"],
                    item["artifact_id"],
                ),
                reverse=True,
            )
            ranked.append(
                {
                    **person,
                    "expertise_score": round(score, 6),
                    "confidence": evidence_confidence(
                        distinct_sessions=distinct_sessions,
                        primary_evidence_count=primary_count,
                    ),
                    "distinct_sessions": distinct_sessions,
                    "primary_evidence_count": primary_count,
                    "evidence_count": len(evidence),
                    "score_components": {
                        "session_capped_evidence": round(session_score, 6),
                        "independent_session_bonus": round(
                            independent_session_bonus, 6
                        ),
                        "source_diversity_bonus": round(source_diversity_bonus, 6),
                    },
                    "evidence": evidence[:evidence_limit],
                }
            )

        ranked.sort(
            key=lambda person: (
                person["expertise_score"],
                person["distinct_sessions"],
                person["primary_evidence_count"],
                person["display_name"].casefold(),
            ),
            reverse=True,
        )
        ranked = ranked[:limit]
        searched_sources = ["knowledge_items", "findings"]
        if ranked:
            message = (
                f"Among the sources searched, {ranked[0]['display_name']} has the strongest "
                "demonstrated experience for the requested topic. This is an evidence-backed ranking, "
                "not a definitive organizational title."
            )
        else:
            message = (
                f"No demonstrated expertise evidence for {topic} was found in "
                "knowledge_items or findings. This describes only the sources searched."
            )
        return {
            "topic": topic,
            "scope": requested_scope,
            "searched_sources": searched_sources,
            "ranking_method": {
                "id": EXPERTISE_METHOD,
                "role_weights": ROLE_WEIGHTS,
                "session_cap": "maximum evidence score per person per source session",
                "independent_session_bonus": "0.1 per additional session, capped at 0.3",
                "source_diversity_bonus": "0.05 for both knowledge and finding authorship",
                "score_is_probability": False,
            },
            "message": message,
            "experts": ranked,
        }

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["entities"] = json.loads(item["entities"]) if item.get("entities") else []
        item["resources"] = json.loads(item["resources"]) if item.get("resources") else []
        return item

    @staticmethod
    def _decode_knowledge(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        current_source = item.pop("_current_source_content", None)
        for field in KNOWLEDGE_JSON_FIELDS:
            if field in item and item[field] is not None:
                item[field] = json.loads(item[field])
        for condition in item.get("conditions", []):
            condition.setdefault("field_aliases", [])
        if "is_superseded" in item:
            item["is_superseded"] = bool(item["is_superseded"])
        if current_source is not None:
            current_hash = hashlib.sha256(current_source.encode("utf-8")).hexdigest()
            item["source_drifted"] = current_hash != item["source_message_hash"]
        return item
