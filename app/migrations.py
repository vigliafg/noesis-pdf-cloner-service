"""Schema del database (SQLite) e migrazioni versionate.

Include fin da subito le tabelle ``stub`` per le espansioni commerciali
(piani, abbonamenti, entitlement, API key, team, audit, email, eventi Stripe):
restano vuote, ma evitano migrazioni dolorose quando auth e pagamenti verranno
attivati.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

_TABLES = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    page_count  INTEGER NOT NULL,
    path        TEXT NOT NULL,
    page_labels TEXT NOT NULL DEFAULT '[]',
    toc         TEXT NOT NULL DEFAULT '[]',
    owner_id    TEXT,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    created     TEXT NOT NULL,
    updated     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id         TEXT PRIMARY KEY,
    doc_id         TEXT NOT NULL,
    pages          TEXT NOT NULL DEFAULT '[]',
    src_lang       TEXT NOT NULL DEFAULT 'auto',
    dst_lang       TEXT NOT NULL DEFAULT 'it',
    engine         TEXT NOT NULL DEFAULT 'google',
    output_name    TEXT NOT NULL DEFAULT '',
    range_mode     TEXT NOT NULL DEFAULT 'merged',
    state          TEXT NOT NULL DEFAULT 'queued',
    priority       INTEGER NOT NULL DEFAULT 0,
    pages_total    INTEGER NOT NULL DEFAULT 0,
    pages_done     INTEGER NOT NULL DEFAULT 0,
    pages_failed   INTEGER NOT NULL DEFAULT 0,
    queue_position INTEGER,
    error          TEXT,
    artifact_path  TEXT,
    owner_id       TEXT,
    created        TEXT NOT NULL,
    scheduled_at   TEXT,
    started        TEXT,
    finished       TEXT,
    duration_ms    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_jobs_state   ON jobs(state, priority DESC, created);
CREATE INDEX IF NOT EXISTS idx_jobs_doc     ON jobs(doc_id);
CREATE INDEX IF NOT EXISTS idx_jobs_owner   ON jobs(owner_id);
CREATE INDEX IF NOT EXISTS idx_docs_owner   ON documents(owner_id);

CREATE TABLE IF NOT EXISTS usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    job_id      TEXT,
    doc_id      TEXT,
    actor_id    TEXT,
    engine      TEXT,
    pages       INTEGER NOT NULL DEFAULT 0,
    chars       INTEGER NOT NULL DEFAULT 0,
    tokens      INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_usage_actor ON usage(actor_id, ts);

CREATE TABLE IF NOT EXISTS audit (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    actor_id TEXT,
    action   TEXT NOT NULL,
    resource TEXT,
    meta     TEXT
);

CREATE TABLE IF NOT EXISTS emails (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    recipient TEXT,
    subject   TEXT,
    body      TEXT,
    status    TEXT NOT NULL DEFAULT 'logged'
);

-- ── stub commerciali (vuote finché non si attivano auth/pagamenti) ──────
CREATE TABLE IF NOT EXISTS plans (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    price_cents     INTEGER NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'EUR',
    pages_included  INTEGER NOT NULL DEFAULT 0,
    stripe_price_id TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                    TEXT PRIMARY KEY,
    actor_id              TEXT NOT NULL,
    plan_id               TEXT,
    stripe_customer_id    TEXT,
    stripe_subscription_id TEXT,
    status                TEXT NOT NULL DEFAULT 'inactive',
    current_period_end    TEXT
);

CREATE TABLE IF NOT EXISTS entitlements (
    actor_id        TEXT PRIMARY KEY,
    plan_id         TEXT,
    pages_remaining INTEGER NOT NULL DEFAULT 0,
    updated         TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash  TEXT PRIMARY KEY,
    actor_id  TEXT NOT NULL,
    name      TEXT,
    active    INTEGER NOT NULL DEFAULT 1,
    created   TEXT,
    last_used TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    owner_id   TEXT,
    created    TEXT
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id  TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    role     TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY (team_id, actor_id)
);

CREATE TABLE IF NOT EXISTS stripe_events (
    id      TEXT PRIMARY KEY,
    type    TEXT,
    payload TEXT,
    created TEXT
);
"""


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, ddl: str
) -> None:
    """Aggiunge una colonna se manca (migrazione idempotente per DB esistenti)."""
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Crea/aggiorna lo schema e registra la versione corrente."""
    conn.executescript(_TABLES)
    _ensure_column(conn, "jobs", "scheduled_at", "TEXT")
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
