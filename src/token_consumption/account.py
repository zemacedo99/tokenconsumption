"""
Account data orchestration layer used by the CLI and UI.

Delegates to connectors/anthropic_account.py (official Admin API) and
connectors/manual_import.py (CSV/JSON exports). This module never talks to
the network or filesystem directly beyond what those connectors expose —
its job is normalizing results for callers and updating data_sources status.
"""

from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg_mod
from . import db as db_mod
from .connectors import anthropic_account, manual_import


# ── Official API ──────────────────────────────────────────────────────────────

def test_official_connection() -> dict:
    return anthropic_account.test_connection()


def sync_official(start_date: str, end_date: str) -> dict:
    """start_date/end_date: YYYY-MM-DD."""
    start_iso = f"{start_date}T00:00:00Z"
    end_iso = f"{end_date}T00:00:00Z"
    return anthropic_account.sync(start_iso, end_iso)


# ── Manual import ─────────────────────────────────────────────────────────────

def preview_manual_import(path: Path) -> dict:
    return manual_import.preview(path)


def import_manual(path: Path, dry_run: bool = True) -> dict:
    cfg = cfg_mod.load()
    account_profile = cfg.get("account_profile_name", "default")
    return manual_import.import_file(path, account_profile=account_profile, dry_run=dry_run)


def import_account_export(path: Path, dry_run: bool = False, verbose: bool = False) -> dict:
    """Back-compat wrapper used by earlier CLI wiring."""
    return import_manual(path, dry_run=dry_run)


# ── Manual balance snapshot (Pro/Max usage — no documented API) ──────────────

def record_balance_snapshot(
    plan_name: str | None = None,
    monthly_budget_value: float | None = None,
    monthly_budget_currency: str | None = None,
    usage_credits_total: float | None = None,
    usage_credits_remaining: float | None = None,
    usage_credits_used: float | None = None,
    reset_date: str | None = None,
    notes: str | None = None,
) -> None:
    """
    Record a manually-entered snapshot of your plan/usage progress, since
    Pro/Max Settings > Usage has no documented API. `notes` may reference a
    screenshot file path as plain text — the image itself is never stored.
    """
    cfg = cfg_mod.load()
    row = {
        "source": "manual_account_import",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "account_profile": cfg.get("account_profile_name", "default"),
        "plan_name": plan_name,
        "monthly_budget_value": monthly_budget_value,
        "monthly_budget_currency": monthly_budget_currency,
        "usage_credits_total": usage_credits_total,
        "usage_credits_remaining": usage_credits_remaining,
        "usage_credits_used": usage_credits_used,
        "reset_date": reset_date,
        "notes": notes,
        "confidence": "manually_entered",
    }
    with db_mod.connection() as con:
        db_mod.insert_balance_snapshot(con, row)


def get_latest_balance_snapshot() -> dict | None:
    with db_mod.connection() as con:
        row = db_mod.get_latest_balance_snapshot(con)
    return dict(row) if row else None


# ── Status ─────────────────────────────────────────────────────────────────────

def get_data_sources_status() -> list[dict]:
    """
    Return status for all three source types, seeding local_claude_code_jsonl
    as always-enabled since it requires no external connection.
    """
    with db_mod.connection() as con:
        rows = {r["source_name"]: dict(r) for r in db_mod.get_data_sources(con)}

    if "local_claude_code_jsonl" not in rows:
        rows["local_claude_code_jsonl"] = {
            "source_name": "local_claude_code_jsonl",
            "source_type": "local",
            "enabled": 1,
            "last_sync_at": None,
            "last_sync_status": "never_run",
            "last_error_message": None,
        }
    for name, source_type in (
        ("anthropic_admin_api", "api"),
        ("manual_account_import", "manual"),
    ):
        if name not in rows:
            rows[name] = {
                "source_name": name, "source_type": source_type, "enabled": 1,
                "last_sync_at": None, "last_sync_status": "never_run", "last_error_message": None,
            }
    return list(rows.values())
