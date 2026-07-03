"""
Produce the one-line status footer and structured JSON status.
Called by the Claude Code statusLine and by `tc status`.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config as cfg_mod
from . import db as db_mod


def _fmt_cost(value: float | None, currency: str = "USD", target_currency: str = "EUR") -> str:
    """Format a cost value. Returns '?' if None (unpriced)."""
    if value is None:
        return "?"
    cfg = cfg_mod.load()
    if currency == "USD" and target_currency == "EUR":
        value = cfg_mod.fx_to_eur(value, cfg)
        symbol = "€"
    elif target_currency == "USD":
        symbol = "$"
    else:
        symbol = currency
    return f"{symbol}{value:.2f}"


def get_status(session_id: str | None = None, db_path: Path | None = None) -> dict:
    """
    Return a structured status dict. All monetary values in USD internally.
    session_id: current session if known (passed by hook or env var).
    """
    cfg = cfg_mod.load()
    account = cfg.get("account_profile_name", "default")
    monthly_budget = cfg.get("monthly_budget_value", 1000)
    monthly_currency = cfg.get("monthly_budget_currency", "USD")
    threshold = cfg.get("safety_threshold_value", 20)

    now_utc = datetime.now(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    year_month = now_utc.strftime("%Y-%m")

    try:
        db_path = db_path or db_mod._db_path()
        if not db_path.exists():
            return _empty_status(cfg, monthly_budget, threshold)

        with db_mod.connection(db_path) as con:
            month_cost = db_mod.get_monthly_cost(con, year_month, account)
            today_cost = db_mod.get_today_cost(con, today, account)
            session_cost = db_mod.get_session_cost(con, session_id) if session_id else None
            last_turn = db_mod.get_last_turn(con, session_id)
            last_cost = last_turn["cost_total"] if last_turn else None

            month_cost_source = "local_estimate"
            if cfg.get("prefer_official_account_costs"):
                month_start = f"{year_month}-01"
                next_month = (now_utc.replace(day=28) + timedelta(days=4)).strftime("%Y-%m-01")
                official = db_mod.get_official_cost_for_period(con, month_start, next_month)
                if official is not None:
                    month_cost = official
                    month_cost_source = "official_account_api"
                else:
                    manual = db_mod.get_manual_cost_for_period(con, month_start, next_month)
                    if manual is not None:
                        month_cost = manual
                        month_cost_source = "manual_import"

        return {
            "ok": True,
            "account_profile": account,
            "today": today,
            "last_turn_cost_usd": last_cost,
            "session_cost_usd": session_cost,
            "today_cost_usd": today_cost,
            "month_cost_usd": month_cost,
            "month_cost_source": month_cost_source,
            "monthly_budget_usd": monthly_budget if monthly_currency == "USD" else None,
            "monthly_budget_value": monthly_budget,
            "monthly_budget_currency": monthly_currency,
            "safety_threshold_value": threshold,
            "safety_threshold_currency": cfg.get("safety_threshold_currency", "EUR"),
            "has_pricing": month_cost is not None,
            "note": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "note": "tracker error — costs unavailable",
        }


def _empty_status(cfg: dict, monthly_budget: float, threshold: float) -> dict:
    return {
        "ok": True,
        "account_profile": cfg.get("account_profile_name", "default"),
        "today": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "last_turn_cost_usd": None,
        "session_cost_usd": None,
        "today_cost_usd": None,
        "month_cost_usd": None,
        "month_cost_source": "local_estimate",
        "monthly_budget_value": monthly_budget,
        "monthly_budget_currency": cfg.get("monthly_budget_currency", "USD"),
        "safety_threshold_value": threshold,
        "safety_threshold_currency": cfg.get("safety_threshold_currency", "EUR"),
        "has_pricing": False,
        "note": "no data yet — run 'tc import' first",
    }


def status_line(session_id: str | None = None, db_path: Path | None = None) -> str:
    """
    Return the single-line footer for Claude Code statusLine / end-of-reply.

    Important: costs shown here are from the PREVIOUS turn (or session so far).
    The cost of the reply being written is only available after it completes.
    All values labeled 'est' or '~' are estimates; exact values are undecorated.
    """
    # Allow session_id from env (set by hook)
    if session_id is None:
        session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")

    s = get_status(session_id=session_id, db_path=db_path)

    if not s.get("ok"):
        return f"TokenConsumption: tracker unavailable ({s.get('error', '?')})"

    cfg = cfg_mod.load()

    def _eur(usd: float | None) -> str:
        if usd is None:
            return "?"
        return f"€{cfg_mod.fx_to_eur(usd, cfg):.2f}"

    budget_val = s["monthly_budget_value"]
    budget_cur = s["monthly_budget_currency"]
    month_cost = s["month_cost_usd"]

    if budget_cur == "USD" and month_cost is not None:
        budget_eur = cfg_mod.fx_to_eur(budget_val, cfg)
        month_eur = cfg_mod.fx_to_eur(month_cost, cfg)
        month_str = f"€{month_eur:.2f} / €{budget_eur:.0f}"
    elif budget_cur == "USD" and month_cost is None:
        budget_eur = cfg_mod.fx_to_eur(budget_val, cfg)
        month_str = f"? / €{budget_eur:.0f}"
    else:
        month_str = f"? / {budget_val} {budget_cur}"

    note = ""
    if not s.get("has_pricing"):
        note = " [prices not configured — fill config/pricing.json]"

    parts = [
        f"last≈{_eur(s['last_turn_cost_usd'])}",
        f"session≈{_eur(s['session_cost_usd'])}",
        f"today≈{_eur(s['today_cost_usd'])}",
        f"month≈{month_str}",
    ]
    return f"TokenConsumption: {' | '.join(parts)}{note}"
