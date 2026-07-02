"""
Optional manual import of official account/billing exports.

IMPORTANT — what this does NOT do:
  * It never scrapes the Claude web UI.
  * It never reads browser cookies or session tokens.
  * It never stores Claude credentials or API keys.

Primary usage data comes from local Claude Code JSONL transcripts (exact token
counts). This module is only for reconciling against an official export that
YOU download manually from the Anthropic Console (CSV or JSON), if/when such an
export is available for your account type.

Local computed cost depends on your pricing table and may differ from official
billing. See docs/ACCOUNT_DATA.md.
"""

import csv
import json
from pathlib import Path

from . import db as db_mod


def _ensure_account_table(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS account_billing (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file     TEXT,
            period          TEXT,
            description     TEXT,
            amount          REAL,
            currency        TEXT,
            imported_at     TEXT,
            UNIQUE(source_file, period, description, amount)
        )
    """)


def import_account_export(path: Path, verbose: bool = False) -> dict:
    """
    Import a manually-downloaded billing export.

    Accepts a generic CSV (with columns like period/date, description, amount,
    currency) or a JSON array of similar objects. Only monetary/period metadata
    is stored — never prompts, outputs, or credentials.
    """
    from datetime import datetime, timezone

    rows: list[dict] = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    if path.suffix.lower() == ".json":
        data = json.loads(text)
        rows = data if isinstance(data, list) else data.get("items", [])
    else:  # CSV
        reader = csv.DictReader(text.splitlines())
        rows = list(reader)

    def _get(r: dict, *names):
        for n in names:
            for k in r:
                if k and k.lower().strip() == n:
                    return r[k]
        return None

    imported = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    with db_mod.connection() as con:
        _ensure_account_table(con)
        for r in rows:
            period = _get(r, "period", "date", "month", "invoice_date")
            desc = _get(r, "description", "line_item", "item", "product")
            amount_raw = _get(r, "amount", "cost", "total", "value")
            currency = _get(r, "currency", "cur") or "USD"
            try:
                amount = float(str(amount_raw).replace(",", "").replace("$", "").strip())
            except (TypeError, ValueError):
                skipped += 1
                continue
            try:
                con.execute("""
                    INSERT OR IGNORE INTO account_billing
                        (source_file, period, description, amount, currency, imported_at)
                    VALUES (?,?,?,?,?,?)
                """, (path.name, period, desc, amount, currency, now))
                imported += con.total_changes and 1 or 0
                imported += 0
            except Exception:
                skipped += 1

    return {"imported_rows": imported, "skipped": skipped, "source": path.name}
