"""
Manual import of official account/billing exports (CSV or JSON) that you
download yourself from the Anthropic Console. No scraping, no automation of
any login — you export the file, this module parses it.

Only token/cost metadata is imported. Prompt text, outputs, and file content
columns (if a CSV happens to have one) are never read into the database.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

# Column name variants we try to detect, per logical field.
_COLUMN_ALIASES = {
    "period_start": ["period_start", "period", "date", "start_date", "starting_at", "month"],
    "period_end": ["period_end", "end_date", "ending_at"],
    "model": ["model", "model_name"],
    "service": ["service", "cost_type", "line_item", "description", "item", "product"],
    "input_tokens": ["input_tokens", "uncached_input_tokens", "prompt_tokens"],
    "output_tokens": ["output_tokens", "completion_tokens"],
    "cache_read_tokens": ["cache_read_tokens", "cache_read_input_tokens"],
    "cache_write_tokens": ["cache_write_tokens", "cache_creation_input_tokens"],
    "cost_value": ["cost_value", "amount", "cost", "total", "value", "total_cost"],
    "cost_currency": ["cost_currency", "currency", "cur"],
    "workspace_id": ["workspace_id", "workspace"],
    "organization_id": ["organization_id", "org_id", "organization"],
}

# Columns we deliberately refuse to import even if present, to avoid ever
# storing prompt/output content from an unexpected export format.
_FORBIDDEN_COLUMNS = {"prompt", "output", "content", "message", "response", "text", "diff"}


def sniff_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    # Fallback: peek at content
    head = path.read_text(encoding="utf-8-sig", errors="replace")[:200].strip()
    return "json" if head.startswith(("[", "{")) else "csv"


def _read_rows(path: Path, fmt: str) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if fmt == "json":
        data = json.loads(text)
        return data if isinstance(data, list) else data.get("items", data.get("data", []))
    reader = csv.DictReader(text.splitlines())
    return list(reader)


def _normalize_key(k: str) -> str:
    return (k or "").strip().lower().replace(" ", "_").replace("-", "_")


def detect_columns(rows: list[dict]) -> dict:
    """Return {logical_field: actual_column_name_or_None} best-effort mapping."""
    if not rows:
        return {}
    available = {_normalize_key(k): k for k in rows[0].keys()}
    mapping: dict[str, str | None] = {}
    for field, aliases in _COLUMN_ALIASES.items():
        found = None
        for alias in aliases:
            if alias in available:
                found = available[alias]
                break
        mapping[field] = found
    return mapping


def flagged_forbidden_columns(rows: list[dict]) -> list[str]:
    """Columns present in the file that we refuse to import (content-like)."""
    if not rows:
        return []
    return [k for k in rows[0].keys() if _normalize_key(k) in _FORBIDDEN_COLUMNS]


def preview(path: Path, limit: int = 20) -> dict:
    """
    Parse the file and return a preview WITHOUT importing anything.
    {format, total_rows, sample_rows, column_mapping, forbidden_columns, warnings}
    """
    fmt = sniff_format(path)
    rows = _read_rows(path, fmt)
    mapping = detect_columns(rows)
    forbidden = flagged_forbidden_columns(rows)

    warnings = []
    missing_required = [f for f in ("cost_value",) if not mapping.get(f)]
    if missing_required:
        warnings.append(f"Could not detect a cost/amount column ({missing_required}). "
                        "Rows without a parseable cost will be skipped on import.")
    if forbidden:
        warnings.append(f"Columns {forbidden} look like content fields and will NEVER "
                        "be imported, regardless of confirmation.")

    return {
        "format": fmt,
        "total_rows": len(rows),
        "sample_rows": rows[:limit],
        "column_mapping": mapping,
        "forbidden_columns": forbidden,
        "warnings": warnings,
    }


def _parse_amount(raw) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", "").replace("$", "").replace("€", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_int(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def validate_rows(rows: list[dict], mapping: dict) -> list[str]:
    """Return a list of validation error strings (empty = ok to proceed)."""
    errors = []
    if not rows:
        errors.append("File contains no rows.")
    if not mapping.get("cost_value") and not (mapping.get("input_tokens") or mapping.get("output_tokens")):
        errors.append("Neither a cost column nor token columns were detected — nothing to import.")
    return errors


def to_account_usage_rows(path: Path, rows: list[dict], mapping: dict,
                          account_profile: str = "default") -> list[dict]:
    """Convert raw parsed rows into normalized account_usage_reports dicts."""
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for r in rows:
        def get(field):
            col = mapping.get(field)
            return r.get(col) if col else None

        cost_value = _parse_amount(get("cost_value"))
        in_tok = _parse_int(get("input_tokens"))
        out_tok = _parse_int(get("output_tokens"))
        if cost_value is None and in_tok is None and out_tok is None:
            continue  # nothing usable on this row

        cache_r = _parse_int(get("cache_read_tokens"))
        cache_w = _parse_int(get("cache_write_tokens"))
        total = None
        if any(v is not None for v in (in_tok, out_tok, cache_r, cache_w)):
            total = sum(v or 0 for v in (in_tok, out_tok, cache_r, cache_w))

        out.append({
            "source": "manual_account_import",
            "report_start": get("period_start"),
            "report_end": get("period_end") or get("period_start"),
            "account_profile": account_profile,
            "organization_id": get("organization_id"),
            "workspace_id": get("workspace_id"),
            "user_email_hash": None,
            "model": get("model"),
            "service": get("service") or "tokens",
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cache_read_tokens": cache_r,
            "cache_write_tokens": cache_w,
            "total_tokens": total,
            "cost_value": cost_value,
            "cost_currency": get("cost_currency") or "USD",
            "raw_source_reference": path.name,
            "imported_at": now,
            "confidence": "manually_entered",
        })
    return out


def import_file(path: Path, account_profile: str = "default", dry_run: bool = True) -> dict:
    """
    Preview + optionally commit a manual import.
    dry_run=True (default): parses and validates but writes nothing.
    dry_run=False: writes normalized rows into account_usage_reports.
    """
    from .. import db as db_mod

    fmt = sniff_format(path)
    rows = _read_rows(path, fmt)
    mapping = detect_columns(rows)
    errors = validate_rows(rows, mapping)
    if errors:
        return {"ok": False, "errors": errors, "imported": 0, "total_rows": len(rows)}

    normalized = to_account_usage_rows(path, rows, mapping, account_profile)

    if dry_run:
        return {"ok": True, "errors": [], "imported": 0, "would_import": len(normalized),
                "total_rows": len(rows), "dry_run": True}

    imported = 0
    with db_mod.connection() as con:
        for row in normalized:
            if db_mod.insert_account_usage_row(con, row):
                imported += 1
        db_mod.record_source_sync(con, "manual_account_import", "manual", "ok")

    return {"ok": True, "errors": [], "imported": imported, "total_rows": len(rows), "dry_run": False}
