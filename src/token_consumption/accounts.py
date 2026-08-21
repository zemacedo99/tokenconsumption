"""
Configured AI accounts/subscriptions. Manual entry only in this phase — no
login, no password, no API key value is ever read or stored here (API keys,
where they matter, stay in provider env vars — see providers.py).
"""

from datetime import datetime, timezone

from . import config as cfg_mod
from . import db as db_mod


def list_accounts() -> list[dict]:
    with db_mod.connection() as con:
        return [dict(r) for r in db_mod.get_accounts(con)]


def add_account(
    provider_key: str,
    label: str | None = None,
    plan_name: str | None = None,
    monthly_price: float | None = None,
    price_currency: str = "EUR",
    billing_period: str = "monthly",
    status: str = "manual",
    connection_method: str = "manual_entry",
    notes: str | None = None,
) -> bool:
    """Add a manually-entered account/subscription. Returns True if a new row was added."""
    row = {
        "provider_key": provider_key,
        "label": label,
        "plan_name": plan_name,
        "monthly_price": monthly_price,
        "price_currency": price_currency or "EUR",
        "billing_period": billing_period or "monthly",
        "status": status or "manual",
        "connection_method": connection_method,
        "last_sync_at": None,
        "confidence": "manually_entered",
        "notes": notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with db_mod.connection() as con:
        return db_mod.insert_account(con, row)


def monthly_subscription_total_eur() -> float:
    """
    Sum of monthly_price across all accounts, FX-converted to EUR. USD is
    converted via the configured rate; any other currency is added at face
    value (documented simplification — see docs/CONNECTED_ACCOUNTS.md).
    """
    cfg = cfg_mod.load()
    total = 0.0
    for a in list_accounts():
        price = a.get("monthly_price")
        if price is None:
            continue
        currency = a.get("price_currency") or "EUR"
        total += cfg_mod.fx_to_eur(price, cfg) if currency == "USD" else price
    return total


def account_status_summary() -> dict:
    accts = list_accounts()
    return {
        "count": len(accts),
        "monthly_total_eur": monthly_subscription_total_eur(),
    }
