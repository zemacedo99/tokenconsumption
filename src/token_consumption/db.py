"""SQLite database: schema creation, migrations, and connection helpers."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config as cfg_mod

SCHEMA_VERSION = 1

DDL = """
-- ── turns ────────────────────────────────────────────────────────────────────
-- One row per JSONL line ingested (assistant and user turns).
-- Idempotent on turn_uuid.
CREATE TABLE IF NOT EXISTS turns (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_uuid               TEXT NOT NULL UNIQUE,
    session_id              TEXT NOT NULL,
    parent_uuid             TEXT,
    ts                      TEXT NOT NULL,
    account_profile         TEXT NOT NULL DEFAULT 'default',
    cwd                     TEXT,
    project_slug            TEXT,
    role                    TEXT NOT NULL,
    model                   TEXT,
    task_type               TEXT,
    input_tokens            INTEGER,
    output_tokens           INTEGER,
    cache_read_tokens       INTEGER,
    cache_write_5m_tokens   INTEGER,
    cache_write_1h_tokens   INTEGER,
    total_tokens            INTEGER,
    cost_input              REAL,
    cost_output             REAL,
    cost_cache_read         REAL,
    cost_cache_write        REAL,
    cost_total              REAL,
    cost_currency           TEXT NOT NULL DEFAULT 'USD',
    cost_source             TEXT NOT NULL DEFAULT 'jsonl_local_pricing',
    pricing_version         TEXT
);

CREATE INDEX IF NOT EXISTS idx_turns_ts        ON turns(ts);
CREATE INDEX IF NOT EXISTS idx_turns_session   ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_project   ON turns(project_slug);
CREATE INDEX IF NOT EXISTS idx_turns_model     ON turns(model);
CREATE INDEX IF NOT EXISTS idx_turns_date      ON turns(substr(ts, 1, 10));

-- ── estimates ────────────────────────────────────────────────────────────────
-- Pre-turn estimates (phase 2). Written before the turn; backfilled after.
CREATE TABLE IF NOT EXISTS estimates (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    estimate_uuid           TEXT NOT NULL UNIQUE,
    ts                      TEXT NOT NULL,
    session_id              TEXT NOT NULL,
    linked_turn_uuid        TEXT,
    model                   TEXT NOT NULL,
    task_type               TEXT,
    project_slug            TEXT,
    est_input_tokens        INTEGER,
    est_output_tokens       INTEGER,
    est_cache_read_tokens   INTEGER,
    est_cost                REAL,
    est_currency            TEXT NOT NULL DEFAULT 'USD',
    confidence              TEXT NOT NULL DEFAULT 'low',
    threshold_at_time       REAL NOT NULL,
    threshold_currency      TEXT NOT NULL DEFAULT 'EUR',
    confirmation_required   INTEGER NOT NULL DEFAULT 0,
    cheaper_model_recommended TEXT,
    actual_cost             REAL,
    error_pct               REAL
);

CREATE INDEX IF NOT EXISTS idx_est_session    ON estimates(session_id);
CREATE INDEX IF NOT EXISTS idx_est_task_model ON estimates(task_type, model);

-- ── agg_daily ────────────────────────────────────────────────────────────────
-- Precomputed daily aggregates for fast statusLine reads.
CREATE TABLE IF NOT EXISTS agg_daily (
    day             TEXT NOT NULL,
    account_profile TEXT NOT NULL,
    model           TEXT NOT NULL DEFAULT '',
    project_slug    TEXT NOT NULL DEFAULT '',
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    total_cost      REAL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    PRIMARY KEY (day, account_profile, model, project_slug)
);

-- ── meta ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
"""

MIGRATIONS = [
    # v1 → baseline (DDL above covers this)
]


def _db_path() -> Path:
    cfg = cfg_mod.load()
    return Path(cfg_mod._data_dir(cfg)) / "usage.sqlite"


@contextmanager
def connection(db_path: Path | None = None):
    """Context manager yielding a WAL-mode sqlite3 connection."""
    path = db_path or _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db(db_path: Path | None = None) -> Path:
    """Create schema and apply any pending migrations. Idempotent."""
    path = db_path or _db_path()
    with connection(path) as con:
        con.executescript(DDL)

        current = _schema_version(con)
        for i, migration_sql in enumerate(MIGRATIONS, start=current + 1):
            con.executescript(migration_sql)
            con.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(i),)
            )

        if current == 0:
            con.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),)
            )
    return path


def _schema_version(con: sqlite3.Connection) -> int:
    try:
        row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 0
    except sqlite3.OperationalError:
        return 0


# ── Aggregate helpers ─────────────────────────────────────────────────────────

def recompute_agg_daily(con: sqlite3.Connection, day: str, account_profile: str) -> None:
    """Recompute agg_daily rows for a specific day and profile. Call after ingest."""
    con.execute("DELETE FROM agg_daily WHERE day=? AND account_profile=?", (day, account_profile))
    con.execute("""
        INSERT INTO agg_daily(day, account_profile, model, project_slug, total_tokens, total_cost, currency)
        SELECT
            substr(ts, 1, 10)               AS day,
            account_profile,
            COALESCE(model, '')             AS model,
            COALESCE(project_slug, '')      AS project_slug,
            SUM(COALESCE(total_tokens, 0))  AS total_tokens,
            SUM(cost_total)                 AS total_cost,
            MAX(cost_currency)              AS currency
        FROM turns
        WHERE substr(ts, 1, 10) = ? AND account_profile = ?
        GROUP BY substr(ts, 1, 10), account_profile, model, project_slug
    """, (day, account_profile))


def get_monthly_cost(con: sqlite3.Connection, year_month: str, account_profile: str) -> float | None:
    """Sum of cost for YYYY-MM, or None if no priced data."""
    row = con.execute("""
        SELECT SUM(total_cost) AS s FROM agg_daily
        WHERE day LIKE ? AND account_profile=?
    """, (f"{year_month}%", account_profile)).fetchone()
    return row["s"] if row else None


def get_today_cost(con: sqlite3.Connection, day: str, account_profile: str) -> float | None:
    row = con.execute("""
        SELECT SUM(total_cost) AS s FROM agg_daily
        WHERE day=? AND account_profile=?
    """, (day, account_profile)).fetchone()
    return row["s"] if row else None


def get_session_cost(con: sqlite3.Connection, session_id: str) -> float | None:
    row = con.execute("""
        SELECT SUM(cost_total) AS s FROM turns WHERE session_id=?
    """, (session_id,)).fetchone()
    return row["s"] if row else None


def get_last_turn(con: sqlite3.Connection, session_id: str | None = None) -> sqlite3.Row | None:
    if session_id:
        return con.execute("""
            SELECT * FROM turns WHERE session_id=? AND role='assistant'
            ORDER BY ts DESC LIMIT 1
        """, (session_id,)).fetchone()
    return con.execute("""
        SELECT * FROM turns WHERE role='assistant' ORDER BY ts DESC LIMIT 1
    """).fetchone()
