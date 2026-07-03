"""
Official Anthropic Admin API connector (Usage & Cost Report endpoints).

Uses ONLY documented REST endpoints over HTTPS with an Admin API key:
  https://api.anthropic.com/v1/organizations/usage_report/messages
  https://api.anthropic.com/v1/organizations/cost_report

IMPORTANT — per Anthropic's own docs, "The Admin API is unavailable for
individual accounts." It requires a Console organization with an Admin API
key. Personal Claude Pro/Max subscriptions generally do NOT have this. This
module reports that clearly via test_connection() rather than assuming access.

What this module does NOT do:
  * No web scraping, no browser automation, no cookie/session-token reading.
  * No password prompts. Auth is exactly one env var: ANTHROPIC_ADMIN_API_KEY.
  * Never logs or prints the full API key (mask_key() only).
  * Never persists raw API responses unless TC_DEBUG_API=1 is explicitly set,
    and even then only under logs/ (metadata/numbers, not prompt content).
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT_SECONDS = 15


class AnthropicAdminAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def mask_key(key: str | None) -> str:
    """Never expose a full key. Show a short, unambiguous fragment only."""
    if not key:
        return "(not set)"
    if len(key) <= 12:
        return "*" * len(key)
    return f"{key[:12]}...{key[-4:]}"


def get_api_key() -> str | None:
    """
    Read the Admin API key from the environment ONLY.
    Local storage (e.g. OS keyring) is intentionally not implemented in this
    version to keep the attack surface minimal — see docs/ANTHROPIC_API_SETUP.md.
    """
    return os.environ.get("ANTHROPIC_ADMIN_API_KEY")


def get_org_id() -> str | None:
    return os.environ.get("ANTHROPIC_ORG_ID")


def get_workspace_id() -> str | None:
    return os.environ.get("ANTHROPIC_WORKSPACE_ID")


def _debug_enabled() -> bool:
    return os.environ.get("TC_DEBUG_API") == "1"


def _debug_dump(name: str, payload: dict) -> None:
    if not _debug_enabled():
        return
    try:
        root = Path(__file__).resolve().parents[3]
        log_dir = root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (log_dir / f"account-api-debug-{name}-{ts}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _request(path: str, params: dict) -> dict:
    """
    GET a documented Admin API endpoint. Raises AnthropicAdminAPIError with a
    clear, non-sensitive message on failure. Never includes the API key value
    in any exception message.
    """
    api_key = get_api_key()
    if not api_key:
        raise AnthropicAdminAPIError(
            "ANTHROPIC_ADMIN_API_KEY is not set. Admin API access requires an "
            "Admin API key from a Console organization. See docs/ANTHROPIC_API_SETUP.md.",
            status_code=None,
        )

    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{API_BASE}{path}?{query}"
    req = urllib.request.Request(url, headers={
        "anthropic-version": ANTHROPIC_VERSION,
        "x-api-key": api_key,
        "User-Agent": "TokenConsumption/0.1.0 (local budget tracker)",
    })

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            _debug_dump(path.strip("/").replace("/", "_"), body)
            return body
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        if status == 401:
            msg = "API key missing or invalid (HTTP 401)."
        elif status == 403:
            msg = ("Permission denied (HTTP 403). Admin/Billing permissions are "
                   "required for this API key/organization.")
        elif status == 404:
            msg = ("Endpoint unavailable for this account (HTTP 404). This usually means "
                   "there is no Console organization associated with this key, or the "
                   "Admin API is not enabled — expected for personal Pro/Max accounts.")
        else:
            msg = f"Unexpected error (HTTP {status})."
        if detail:
            msg += f" Detail: {detail}"
        raise AnthropicAdminAPIError(msg, status_code=status) from None
    except urllib.error.URLError as e:
        raise AnthropicAdminAPIError(f"Network error reaching Anthropic API: {e.reason}") from None


def test_connection() -> dict:
    """
    Lightweight, safe connectivity check. Makes ONE minimal cost_report request.
    Returns a dict — never raises. Never includes the full API key.
    """
    api_key = get_api_key()
    if not api_key:
        return {
            "ok": False,
            "status_code": None,
            "message": ("ANTHROPIC_ADMIN_API_KEY not set. Admin API is unavailable for "
                       "individual accounts per Anthropic's docs — this is expected for "
                       "most personal Pro/Max users. See docs/ANTHROPIC_API_SETUP.md."),
            "masked_key": mask_key(None),
        }
    try:
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        _request("/v1/organizations/cost_report", {
            "starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 1,
        })
        return {
            "ok": True,
            "status_code": 200,
            "message": "Connected. Admin API access confirmed for this organization.",
            "masked_key": mask_key(api_key),
        }
    except AnthropicAdminAPIError as e:
        return {
            "ok": False,
            "status_code": e.status_code,
            "message": e.message,
            "masked_key": mask_key(api_key),
        }


def _iter_pages(path: str, params: dict):
    """Yield successive response pages, following has_more/next_page."""
    page_params = dict(params)
    while True:
        body = _request(path, page_params)
        yield body
        if not body.get("has_more"):
            break
        page_params["page"] = body["next_page"]


def fetch_usage_rows(start_iso: str, end_iso: str) -> list[dict]:
    """
    Fetch token usage grouped by model, daily buckets.
    Returns normalized rows ready for db.insert_account_usage_row (service='tokens_usage').
    """
    rows: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    for page in _iter_pages("/v1/organizations/usage_report/messages", {
        "starting_at": start_iso, "ending_at": end_iso,
        "bucket_width": "1d", "group_by[]": "model",
    }):
        for bucket in page.get("data", []):
            for item in bucket.get("results", []):
                rows.append({
                    "source": "anthropic_admin_api",
                    "report_start": bucket.get("starting_at"),
                    "report_end": bucket.get("ending_at"),
                    "account_profile": "default",
                    "organization_id": get_org_id(),
                    "workspace_id": item.get("workspace_id"),
                    "user_email_hash": None,
                    "model": item.get("model"),
                    "service": "tokens_usage",
                    "input_tokens": item.get("uncached_input_tokens"),
                    "output_tokens": item.get("output_tokens"),
                    "cache_read_tokens": item.get("cache_read_input_tokens"),
                    "cache_write_tokens": (
                        (item.get("cache_creation", {}) or {}).get("ephemeral_5m_input_tokens", 0)
                        + (item.get("cache_creation", {}) or {}).get("ephemeral_1h_input_tokens", 0)
                    ) or None,
                    "total_tokens": None,
                    "cost_value": None,
                    "cost_currency": "USD",
                    "raw_source_reference": "/v1/organizations/usage_report/messages",
                    "imported_at": now,
                    "confidence": "exact",
                })
    return rows


def fetch_cost_rows(start_iso: str, end_iso: str) -> list[dict]:
    """
    Fetch cost breakdown grouped by description (yields model + cost_type).
    Returns normalized rows ready for db.insert_account_usage_row (service=cost_type).
    """
    rows: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    for page in _iter_pages("/v1/organizations/cost_report", {
        "starting_at": start_iso, "ending_at": end_iso,
        "group_by[]": "description",
    }):
        for bucket in page.get("data", []):
            for item in bucket.get("results", []):
                amount_str = item.get("amount")
                try:
                    amount = float(amount_str) / 100.0 if amount_str is not None else None
                except (TypeError, ValueError):
                    amount = None
                rows.append({
                    "source": "anthropic_admin_api",
                    "report_start": bucket.get("starting_at"),
                    "report_end": bucket.get("ending_at"),
                    "account_profile": "default",
                    "organization_id": get_org_id(),
                    "workspace_id": item.get("workspace_id"),
                    "user_email_hash": None,
                    "model": item.get("model"),
                    "service": item.get("cost_type") or "tokens",
                    "input_tokens": None,
                    "output_tokens": None,
                    "cache_read_tokens": None,
                    "cache_write_tokens": None,
                    "total_tokens": None,
                    "cost_value": amount,
                    "cost_currency": item.get("currency", "USD"),
                    "raw_source_reference": "/v1/organizations/cost_report",
                    "imported_at": now,
                    "confidence": "exact",
                })
    return rows


def sync(start_iso: str, end_iso: str) -> dict:
    """
    Fetch usage + cost reports and insert into account_usage_reports.
    Updates the data_sources sync status regardless of outcome. Never raises —
    returns a result dict with ok/error for the CLI/UI to display.
    """
    from .. import db as db_mod

    try:
        usage_rows = fetch_usage_rows(start_iso, end_iso)
        cost_rows = fetch_cost_rows(start_iso, end_iso)
    except AnthropicAdminAPIError as e:
        with db_mod.connection() as con:
            db_mod.record_source_sync(con, "anthropic_admin_api", "api", "error", e.message)
        return {"ok": False, "error": e.message, "usage_rows": 0, "cost_rows": 0}

    inserted = 0
    with db_mod.connection() as con:
        for row in usage_rows + cost_rows:
            if db_mod.insert_account_usage_row(con, row):
                inserted += 1
        db_mod.record_source_sync(con, "anthropic_admin_api", "api", "ok")

    return {"ok": True, "error": None, "usage_rows": len(usage_rows),
            "cost_rows": len(cost_rows), "inserted": inserted}
