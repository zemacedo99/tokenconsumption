"""SQLite database: schema creation, migrations, and connection helpers."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config as cfg_mod

SCHEMA_VERSION = 3

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

-- ── account_usage_reports ───────────────────────────────────────────────────
-- Usage/cost rows from sources OTHER than local JSONL: official Admin API
-- reports or manually imported billing exports. Kept separate from `turns`
-- (which is exact per-turn local data) so sources are never conflated.
CREATE TABLE IF NOT EXISTS account_usage_reports (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    source                  TEXT NOT NULL,   -- anthropic_admin_api | manual_account_import
    report_start            TEXT,
    report_end              TEXT,
    account_profile         TEXT NOT NULL DEFAULT 'default',
    organization_id         TEXT,
    workspace_id            TEXT,
    user_email_hash         TEXT,            -- sha256 of email, never the raw email
    model                   TEXT,
    service                 TEXT,            -- e.g. tokens | web_search | code_execution
    input_tokens            INTEGER,
    output_tokens           INTEGER,
    cache_read_tokens       INTEGER,
    cache_write_tokens      INTEGER,
    total_tokens            INTEGER,
    cost_value              REAL,
    cost_currency           TEXT NOT NULL DEFAULT 'USD',
    raw_source_reference    TEXT,            -- filename or endpoint, never raw content
    imported_at             TEXT NOT NULL,
    confidence              TEXT NOT NULL DEFAULT 'unknown'  -- exact|estimated|manually_entered|unknown
);

-- Dedup via expression index: SQLite treats NULL != NULL in a plain UNIQUE
-- constraint, which would defeat dedup for rows with no workspace_id/model
-- (the common case). COALESCE to '' makes NULLs compare equal.
CREATE UNIQUE INDEX IF NOT EXISTS ux_acct_usage_dedupe ON account_usage_reports(
    source, COALESCE(report_start,''), COALESCE(report_end,''),
    COALESCE(model,''), COALESCE(service,''), COALESCE(workspace_id,''),
    COALESCE(raw_source_reference,'')
);

CREATE INDEX IF NOT EXISTS idx_acct_usage_period  ON account_usage_reports(report_start, report_end);
CREATE INDEX IF NOT EXISTS idx_acct_usage_source  ON account_usage_reports(source);
CREATE INDEX IF NOT EXISTS idx_acct_usage_model   ON account_usage_reports(model);

-- ── account_balance_snapshots ───────────────────────────────────────────────
-- Point-in-time plan/budget/credits snapshots. Mostly manually entered since
-- Pro/Max usage progress has no documented API.
CREATE TABLE IF NOT EXISTS account_balance_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    source                  TEXT NOT NULL,   -- manual_account_import | anthropic_admin_api
    captured_at             TEXT NOT NULL,
    account_profile         TEXT NOT NULL DEFAULT 'default',
    plan_name               TEXT,
    monthly_budget_value    REAL,
    monthly_budget_currency TEXT,
    usage_credits_total     REAL,
    usage_credits_remaining REAL,
    usage_credits_used      REAL,
    reset_date              TEXT,
    notes                   TEXT,            -- free text the user typed; never file/image content
    confidence              TEXT NOT NULL DEFAULT 'manually_entered'
);

CREATE INDEX IF NOT EXISTS idx_acct_balance_captured ON account_balance_snapshots(captured_at);

-- ── data_sources ─────────────────────────────────────────────────────────────
-- Tracks the health/status of each data source feeding TokenConsumption.
CREATE TABLE IF NOT EXISTS data_sources (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name         TEXT NOT NULL UNIQUE,  -- local_claude_code_jsonl | anthropic_admin_api | manual_account_import
    source_type         TEXT NOT NULL,         -- local | api | manual
    enabled             INTEGER NOT NULL DEFAULT 1,
    last_sync_at        TEXT,
    last_sync_status    TEXT,                  -- ok | error | never_run
    last_error_message  TEXT
);

-- ── providers ────────────────────────────────────────────────────────────────
-- Custom (user-added) AI providers only. Built-in providers (Claude, OpenAI,
-- Copilot, Gemini, Perplexity, Notion AI) are code-defined in providers.py and
-- never stored here.
CREATE TABLE IF NOT EXISTS providers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_key        TEXT NOT NULL UNIQUE,
    display_name        TEXT NOT NULL,
    category            TEXT,
    website             TEXT,
    connection_methods  TEXT,            -- JSON array, e.g. ["manual_entry"]
    env_var_names       TEXT,            -- JSON array, reference only — never a value
    limitations         TEXT,
    is_custom           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL
);

-- ── accounts ─────────────────────────────────────────────────────────────────
-- User-configured AI accounts/subscriptions. Manual entry only in this phase —
-- no login, no password, no API key value is ever stored in this table.
CREATE TABLE IF NOT EXISTS accounts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_key        TEXT NOT NULL,
    label               TEXT,
    plan_name           TEXT,
    monthly_price       REAL,
    price_currency      TEXT NOT NULL DEFAULT 'EUR',
    billing_period      TEXT NOT NULL DEFAULT 'monthly',
    status              TEXT NOT NULL DEFAULT 'manual',  -- connected|manual|unsupported|unknown
    connection_method   TEXT,            -- env_var|manual_import|manual_entry
    last_sync_at        TEXT,
    confidence          TEXT NOT NULL DEFAULT 'manually_entered',
    notes               TEXT,
    created_at          TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_accounts_dedupe ON accounts(
    provider_key, COALESCE(label,'')
);
CREATE INDEX IF NOT EXISTS idx_accounts_provider ON accounts(provider_key);
"""

MIGRATIONS = {
    # Keyed by the schema_version each migration produces (NOT list position) —
    # applying by fixed target version, rather than by relative list index, is
    # what makes running init_db() repeatedly idempotent.
    # v1 → v2: account_usage_reports, account_balance_snapshots, data_sources.
    # CREATE TABLE IF NOT EXISTS in the DDL above already applies these to
    # existing databases idempotently, so this migration is a no-op marker.
    2: "SELECT 1;",
    # v2 → v3: providers, accounts (AI Command Center hub). Also CREATE TABLE
    # IF NOT EXISTS in the DDL above — no-op marker.
    3: "SELECT 1;",
}


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
    """
    Create schema and apply any pending migrations. Idempotent — safe to call
    on every startup. Migrations are keyed by the fixed schema_version they
    produce, so re-running never re-bumps the version past SCHEMA_VERSION.
    """
    path = db_path or _db_path()
    with connection(path) as con:
        con.executescript(DDL)

        current = _schema_version(con)
        for version in sorted(MIGRATIONS):
            if version > current:
                con.executescript(MIGRATIONS[version])
                con.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                    (str(version),)
                )
                current = version

        if current < SCHEMA_VERSION:
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


# ── data_sources helpers ──────────────────────────────────────────────────────

def record_source_sync(con: sqlite3.Connection, source_name: str, source_type: str,
                       status: str, error_message: str | None = None,
                       synced_at: str | None = None) -> None:
    """Upsert a data_sources row after a sync attempt (success or failure)."""
    from datetime import datetime, timezone
    ts = synced_at or datetime.now(timezone.utc).isoformat()
    con.execute("""
        INSERT INTO data_sources (source_name, source_type, enabled, last_sync_at, last_sync_status, last_error_message)
        VALUES (?, ?, 1, ?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
            last_sync_at=excluded.last_sync_at,
            last_sync_status=excluded.last_sync_status,
            last_error_message=excluded.last_error_message
    """, (source_name, source_type, ts, status, error_message))


def get_data_sources(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM data_sources ORDER BY source_name").fetchall()


# ── account_usage_reports helpers ─────────────────────────────────────────────

def insert_account_usage_row(con: sqlite3.Connection, row: dict) -> bool:
    """Insert one normalized account usage row. Returns True if a new row was added."""
    before = con.total_changes
    con.execute("""
        INSERT OR IGNORE INTO account_usage_reports (
            source, report_start, report_end, account_profile, organization_id,
            workspace_id, user_email_hash, model, service,
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, total_tokens,
            cost_value, cost_currency, raw_source_reference, imported_at, confidence
        ) VALUES (:source, :report_start, :report_end, :account_profile, :organization_id,
            :workspace_id, :user_email_hash, :model, :service,
            :input_tokens, :output_tokens, :cache_read_tokens, :cache_write_tokens, :total_tokens,
            :cost_value, :cost_currency, :raw_source_reference, :imported_at, :confidence)
    """, row)
    return con.total_changes > before


def get_official_cost_for_period(con: sqlite3.Connection, start: str, end: str,
                                 source: str = "anthropic_admin_api") -> float | None:
    row = con.execute("""
        SELECT SUM(cost_value) AS s FROM account_usage_reports
        WHERE source=? AND report_start >= ? AND report_start < ?
    """, (source, start, end)).fetchone()
    return row["s"] if row else None


def get_manual_cost_for_period(con: sqlite3.Connection, start: str, end: str) -> float | None:
    return get_official_cost_for_period(con, start, end, source="manual_account_import")


# ── account_balance_snapshots helpers ─────────────────────────────────────────

def insert_balance_snapshot(con: sqlite3.Connection, row: dict) -> None:
    con.execute("""
        INSERT INTO account_balance_snapshots (
            source, captured_at, account_profile, plan_name,
            monthly_budget_value, monthly_budget_currency,
            usage_credits_total, usage_credits_remaining, usage_credits_used,
            reset_date, notes, confidence
        ) VALUES (:source, :captured_at, :account_profile, :plan_name,
            :monthly_budget_value, :monthly_budget_currency,
            :usage_credits_total, :usage_credits_remaining, :usage_credits_used,
            :reset_date, :notes, :confidence)
    """, row)


def get_latest_balance_snapshot(con: sqlite3.Connection) -> sqlite3.Row | None:
    return con.execute("""
        SELECT * FROM account_balance_snapshots ORDER BY captured_at DESC LIMIT 1
    """).fetchone()


# ── providers helpers (custom providers only; built-ins are code-defined) ────

def insert_provider(con: sqlite3.Connection, row: dict) -> bool:
    """Insert one custom provider. Returns True if a new row was added."""
    before = con.total_changes
    con.execute("""
        INSERT OR IGNORE INTO providers (
            provider_key, display_name, category, website,
            connection_methods, env_var_names, limitations, is_custom, created_at
        ) VALUES (:provider_key, :display_name, :category, :website,
            :connection_methods, :env_var_names, :limitations, :is_custom, :created_at)
    """, row)
    return con.total_changes > before


def get_custom_providers(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM providers ORDER BY provider_key").fetchall()


# ── accounts helpers ──────────────────────────────────────────────────────────

def insert_account(con: sqlite3.Connection, row: dict) -> bool:
    """Insert one configured account. Returns True if a new row was added."""
    before = con.total_changes
    con.execute("""
        INSERT OR IGNORE INTO accounts (
            provider_key, label, plan_name, monthly_price, price_currency,
            billing_period, status, connection_method, last_sync_at,
            confidence, notes, created_at
        ) VALUES (:provider_key, :label, :plan_name, :monthly_price, :price_currency,
            :billing_period, :status, :connection_method, :last_sync_at,
            :confidence, :notes, :created_at)
    """, row)
    return con.total_changes > before


def get_accounts(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM accounts ORDER BY provider_key, label").fetchall()


def get_account_by_id(con: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
