"""Read-only DB queries for the dashboard. Returns plain dicts, no content fields."""

from datetime import datetime, timezone

from .. import config as cfg_mod
from .. import db as db_mod
from .. import pricing as pricing_mod


def _eur(usd, cfg):
    if usd is None:
        return None
    return cfg_mod.fx_to_eur(usd, cfg)


def overview() -> dict:
    cfg = cfg_mod.load()
    account = cfg.get("account_profile_name", "default")
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    ym = now.strftime("%Y-%m")

    monthly_budget = float(cfg.get("monthly_budget_value", 1000))
    budget_cur = cfg.get("monthly_budget_currency", "USD")
    budget_eur = _eur(monthly_budget, cfg) if budget_cur == "USD" else monthly_budget

    table = pricing_mod.get_table()

    with db_mod.connection() as con:
        month_usd = db_mod.get_monthly_cost(con, ym, account)
        today_usd = db_mod.get_today_cost(con, today, account)
        last_session = con.execute("""
            SELECT session_id, MAX(ts) mx FROM turns GROUP BY session_id ORDER BY mx DESC LIMIT 1
        """).fetchone()
        session_usd = None
        if last_session:
            session_usd = db_mod.get_session_cost(con, last_session["session_id"])
        models = [r["model"] for r in con.execute(
            "SELECT DISTINCT model FROM turns WHERE model IS NOT NULL").fetchall()]

    unpriced = [m for m in models if not table.is_known(m)]
    month_eur = _eur(month_usd, cfg)
    pct = (month_eur / budget_eur * 100) if (month_eur is not None and budget_eur) else 0.0

    return {
        "account": account,
        "today_eur": _eur(today_usd, cfg),
        "month_eur": month_eur,
        "session_eur": _eur(session_usd, cfg),
        "last_session_id": last_session["session_id"] if last_session else None,
        "budget_eur": budget_eur,
        "remaining_eur": (budget_eur - month_eur) if month_eur is not None else budget_eur,
        "pct": round(pct, 1),
        "unpriced_models": unpriced,
        "pricing_version": table.version,
        "pricing_updated": table._data.get("updated_at", "?"),
    }


def daily_spend(days: int = 30) -> list[dict]:
    cfg = cfg_mod.load()
    with db_mod.connection() as con:
        rows = con.execute("""
            SELECT day, SUM(total_cost) usd FROM agg_daily
            GROUP BY day ORDER BY day DESC LIMIT ?
        """, (days,)).fetchall()
    out = [{"day": r["day"], "eur": _eur(r["usd"], cfg) or 0.0} for r in rows]
    return list(reversed(out))


def spend_by_model() -> list[dict]:
    cfg = cfg_mod.load()
    with db_mod.connection() as con:
        rows = con.execute("""
            SELECT model, COUNT(*) turns, SUM(total_tokens) tokens, SUM(cost_total) usd
            FROM turns WHERE role='assistant' AND model IS NOT NULL
            GROUP BY model ORDER BY usd DESC NULLS LAST
        """).fetchall()
    return [{"model": r["model"], "turns": r["turns"],
             "tokens": r["tokens"] or 0, "eur": _eur(r["usd"], cfg)} for r in rows]


def spend_by_project() -> list[dict]:
    cfg = cfg_mod.load()
    with db_mod.connection() as con:
        rows = con.execute("""
            SELECT project_slug, COUNT(*) turns, SUM(total_tokens) tokens, SUM(cost_total) usd
            FROM turns GROUP BY project_slug ORDER BY usd DESC NULLS LAST
        """).fetchall()
    return [{"project": r["project_slug"] or "(unknown)", "turns": r["turns"],
             "tokens": r["tokens"] or 0, "eur": _eur(r["usd"], cfg)} for r in rows]


def sessions(limit: int = 100) -> list[dict]:
    cfg = cfg_mod.load()
    with db_mod.connection() as con:
        rows = con.execute("""
            SELECT session_id,
                   MAX(project_slug) project,
                   GROUP_CONCAT(DISTINCT model) models,
                   substr(MIN(ts),1,10) day,
                   SUM(total_tokens) tokens,
                   SUM(cost_total) usd,
                   COUNT(*) turns
            FROM turns GROUP BY session_id ORDER BY MAX(ts) DESC LIMIT ?
        """, (limit,)).fetchall()
    return [{"session_id": r["session_id"], "project": r["project"] or "",
             "models": (r["models"] or "").replace("<synthetic>", "").strip(","),
             "day": r["day"], "turns": r["turns"],
             "tokens": r["tokens"] or 0, "eur": _eur(r["usd"], cfg)} for r in rows]


def raw_logs(limit: int = 200) -> list[dict]:
    """Metadata-only rows. NO prompt/output content is stored or returned."""
    cfg = cfg_mod.load()
    with db_mod.connection() as con:
        rows = con.execute("""
            SELECT ts, session_id, project_slug, role, model,
                   input_tokens, output_tokens, cache_read_tokens,
                   cache_write_5m_tokens, cache_write_1h_tokens, cost_total
            FROM turns ORDER BY ts DESC LIMIT ?
        """, (limit,)).fetchall()
    return [{
        "ts": r["ts"], "session": (r["session_id"] or "")[:8],
        "project": r["project_slug"] or "", "role": r["role"], "model": r["model"] or "",
        "in": r["input_tokens"] or 0, "out": r["output_tokens"] or 0,
        "cache_r": r["cache_read_tokens"] or 0,
        "cache_w": (r["cache_write_5m_tokens"] or 0) + (r["cache_write_1h_tokens"] or 0),
        "eur": _eur(r["cost_total"], cfg),
    } for r in rows]
