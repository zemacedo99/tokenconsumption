# Account & billing data — what's exact, what's not

## Data sources, ranked

1. **Local Claude Code JSONL transcripts** — *primary, exact token counts.*
   Located at `~/.claude/projects/**/**.jsonl`. Every assistant turn records a
   `usage` block with exact input/output/cache tokens. This is what
   `tc import` reads. **Token counts here are exact.**

2. **Local computed cost** — *derived, depends on your pricing table.*
   Cost = tokens × rates in `config/pricing.json`. This is an **estimate**. It
   will differ from official billing if prices change, if discounts/credits
   apply, or if the pricing table is stale.

3. **Official account/billing data** — *optional, manual only.*
   If you can download a usage/billing export from the Anthropic Console, import
   it manually with:
   ```
   tc import-account --file path/to/export.csv
   ```
   Accepts CSV or JSON with period/description/amount/currency columns. Only
   monetary metadata is stored (table `account_billing`).

## What is NOT possible / NOT done

- **No scraping** of the Claude web UI. Ever.
- **No reading browser cookies** or session tokens.
- **No storing** of Claude credentials, API keys, or passwords.
- **Pro/Max plan usage progress** (the "X% of your limit" shown in the app) has
  **no documented local API**. It cannot be reliably read programmatically and
  is out of scope. Use the official app for plan-limit progress.
- **Claude Console usage/cost endpoints** require Console access and the right
  organization permissions. If your account is a Pro/Max subscription (not an
  API/Console org), programmatic billing data is generally **not available** —
  in that case, local computed cost is your best estimate.
- **Enterprise Analytics API** exists but is **Enterprise-plan specific** and not
  applicable to individual accounts.

## Bottom line

For a personal Claude Code budget, **local JSONL token counts (exact) × your
pricing table (configurable)** is the most reliable local signal available.
Treat all cost figures as estimates and reconcile against your official invoice
periodically. The tool labels computed costs as estimates throughout.
