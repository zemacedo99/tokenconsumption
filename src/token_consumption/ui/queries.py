"""Read-only DB queries for the dashboard. Returns plain dicts, no content fields."""

from datetime import datetime, timedelta, timezone

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

    month_start = f"{ym}-01"
    next_month = (now.replace(day=28) + timedelta(days=4)).strftime("%Y-%m-01")

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
        official_usd = db_mod.get_official_cost_for_period(con, month_start, next_month)
        manual_usd = db_mod.get_manual_cost_for_period(con, month_start, next_month)

    unpriced = [m for m in models if not table.is_known(m)]
    month_eur = _eur(month_usd, cfg)
    pct = (month_eur / budget_eur * 100) if (month_eur is not None and budget_eur) else 0.0

    from .. import accounts as accounts_mod
    from .. import sources as sources_mod
    from .. import providers as providers_mod

    acct_summary = accounts_mod.account_status_summary()
    src_summary = sources_mod.scan_summary()
    unconfigured_providers = [
        p["display_name"] for p in providers_mod.list_providers()
        if providers_mod.provider_status(p["provider_key"]) == "unconfigured"
    ]

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
        "official_eur": _eur(official_usd, cfg),
        "manual_eur": _eur(manual_usd, cfg),
        "has_official": official_usd is not None,
        "has_manual": manual_usd is not None,
        "subscriptions_eur": acct_summary["monthly_total_eur"],
        "accounts_count": acct_summary["count"],
        "sources_found": src_summary["found"],
        "sources_checked": src_summary["total_checked"],
        "unconfigured_providers": unconfigured_providers,
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


def account_overview() -> dict:
    """Status for the /account page: all three sources + latest manual snapshot."""
    from .. import account as account_mod
    sources = account_mod.get_data_sources_status()
    snapshot = account_mod.get_latest_balance_snapshot()
    return {"sources": sources, "snapshot": snapshot}


def reconciliation(months_back: int = 3) -> dict:
    """
    Compare local computed cost vs official/manual account cost, per month.
    Returns rows the reconcile page can render plus a plain-English explanation.
    """
    from .. import estimate as estimate_mod

    cfg = cfg_mod.load()
    now = datetime.now(timezone.utc)
    rows = []
    cursor = now.replace(day=1)
    for _ in range(months_back):
        start = cursor.strftime("%Y-%m-%d")
        next_cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_cursor.strftime("%Y-%m-%d")
        calib = estimate_mod.calibration_summary(start, end)
        rows.append({
            "period": cursor.strftime("%Y-%m"),
            "local_eur": _eur(calib["local_cost_usd"], cfg) if calib else _eur(
                _local_cost_for_period(start, end), cfg),
            "reference_eur": _eur(calib["reference_cost_usd"], cfg) if calib else None,
            "reference_source": calib["reference_source"] if calib else None,
            "diff_pct": calib["diff_pct"] if calib else None,
            "suggestion": calib["suggestion"] if calib else "No official/manual data for this period yet.",
        })
        cursor = cursor.replace(day=1)
        cursor = (cursor - timedelta(days=1)).replace(day=1)  # step back one month

    return {"rows": rows, "prefer_official": cfg.get("prefer_official_account_costs", False)}


def _local_cost_for_period(start: str, end: str) -> float | None:
    with db_mod.connection() as con:
        row = con.execute("""
            SELECT SUM(cost_total) AS s FROM turns
            WHERE substr(ts,1,10) >= ? AND substr(ts,1,10) < ?
        """, (start, end)).fetchone()
    return row["s"] if row else None


# ── AI Command Center: providers / accounts / local sources ──────────────────

def providers_list() -> list[dict]:
    from .. import providers as providers_mod
    out = []
    for p in providers_mod.list_providers():
        p = dict(p)
        p["status"] = providers_mod.provider_status(p["provider_key"])
        out.append(p)
    return out


def provider_detail(key: str) -> dict | None:
    from .. import providers as providers_mod
    p = providers_mod.get_provider(key)
    if p is None:
        return None
    p = dict(p)
    p["status"] = providers_mod.provider_status(key)
    return p


def accounts_overview() -> dict:
    from .. import accounts as accounts_mod
    return {
        "accounts": accounts_mod.list_accounts(),
        "monthly_total_eur": accounts_mod.monthly_subscription_total_eur(),
    }


def sources_scan() -> dict:
    from .. import sources as sources_mod
    return sources_mod.scan_summary()


# Static rule-based demo only — keyword match against provider categories.
# No external model call is ever made here.
_WORKFLOW_RULES = [
    (("code", "refactor", "bug", "programming", "pull request", "pr "),
     ["anthropic", "github_copilot", "openai"]),
    (("write", "email", "draft", "essay", "blog", "post"), ["anthropic", "openai"]),
    (("search", "research", "find sources", "cite", "fact"), ["perplexity"]),
    (("notes", "docs", "wiki", "meeting"), ["notion_ai"]),
    (("chat", "assistant", "question", "ask"), ["anthropic", "openai", "google_gemini"]),
]


def workflow_suggestions(goal: str) -> list[dict]:
    from .. import providers as providers_mod
    goal_lower = goal.lower()
    matched_keys: list[str] = []
    for keywords, keys in _WORKFLOW_RULES:
        if any(kw in goal_lower for kw in keywords):
            for k in keys:
                if k not in matched_keys:
                    matched_keys.append(k)
    all_providers = {p["provider_key"]: p for p in providers_mod.list_providers()}
    return [all_providers[k] for k in matched_keys if k in all_providers]
