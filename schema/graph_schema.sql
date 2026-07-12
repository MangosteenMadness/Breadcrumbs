-- Breadcrumbs graph store: findings as nodes (SQLite, lightest-path per Breadcrumbs.pdf)
-- status: confirmed | in-progress | abandoned

-- A controlled registry prevents topic pages from fragmenting through free-text
-- variants. Add approved categories deliberately before writing findings.
CREATE TABLE IF NOT EXISTS topic_categories (
    id          TEXT PRIMARY KEY,
    description TEXT
);

INSERT OR IGNORE INTO topic_categories(id, description)
VALUES ('LUAD-immune', 'LUAD immune-infiltration and survival research');

CREATE TABLE IF NOT EXISTS findings (
    id              TEXT PRIMARY KEY,       -- e.g. "F-118"
    disease         TEXT NOT NULL,          -- e.g. "LUAD"
    hypothesis_text TEXT NOT NULL,          -- natural-language question
    signature       TEXT,                   -- comma-separated gene/marker list, e.g. "CD8A,GZMB,PRF1,GZMK"
    effect          TEXT,                   -- e.g. "HR 1.8, 95% CI 1.2-2.6"
    n               INTEGER,                -- cohort size
    status          TEXT NOT NULL CHECK (status IN ('confirmed', 'in-progress', 'abandoned')),
    author          TEXT NOT NULL,
    timestamp       TEXT NOT NULL,          -- ISO 8601
    provenance      TEXT,                   -- data source / method, e.g. "TCGA LUAD, cBioPortal, KM+Cox"
    reason          TEXT,                   -- only for status = abandoned
    note            TEXT,                   -- freeform guidance for future researchers
    category        TEXT REFERENCES topic_categories(id),
    entities        TEXT,                   -- JSON array of normalized entity tags
    source_session_id TEXT REFERENCES chat_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_findings_disease ON findings(disease);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(disease, status);

-- Findings form the graph nodes; edges are typed ID-to-ID relationships only.
CREATE TABLE IF NOT EXISTS finding_edges (
    from_id     TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    to_id       TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL CHECK (relationship IN ('extends', 'contradicts', 'related-to')),
    created_at  TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, relationship)
);

-- Raw K Pro chat provenance. These records are the source material for later graph
-- extraction; no chat text leaves the local SQLite database in the ingestion step.
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    title       TEXT,
    scraped_at  TEXT NOT NULL,
    raw_json    TEXT,
    updated_at  TEXT           -- K Pro's own last-update stamp; drives incremental re-ingest
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    created_at  TEXT,
    UNIQUE(session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages(session_id, seq);

-- Visible Markdown sections emitted by K Pro (for example, ## Population
-- Overview) are graph-ready categories derived without sending text externally.
-- Sections nest: a level-3 heading belongs to the level-2 heading above it (a
-- per-indication breakdown under "Indication-Specific Summary"). parent_id
-- records that edge so topics form a tree rather than a flat list, and path
-- carries the readable "Parent > Child" label for topic nodes.
CREATE TABLE IF NOT EXISTS chat_message_sections (
    id          TEXT PRIMARY KEY,
    message_id  TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    heading     TEXT NOT NULL,
    level       INTEGER NOT NULL CHECK (level IN (2, 3)),
    content     TEXT NOT NULL,
    parent_id   TEXT REFERENCES chat_message_sections(id) ON DELETE CASCADE,
    path        TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_message_sections_message
    ON chat_message_sections(message_id, seq);

-- The parent_id index is created by store._migrate_chat_tables, not here: on a pre-existing
-- breadcrumbs.db the CREATE TABLE above is a no-op, so parent_id does not exist yet at this point
-- and indexing it would fail. The migration adds the column first, then the index.

-- A failed page/API shape is recorded locally so unsupported K Pro UI changes are
-- visible without storing fabricated turns.
CREATE TABLE IF NOT EXISTS ingestion_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    url         TEXT,
    error       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
