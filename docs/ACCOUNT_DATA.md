# Account & billing data — sources, priority, and honesty

TokenConsumption combines up to three independent data sources. Each row in
the database is labeled with its `source` and `confidence` — nothing is ever
silently blended or presented as more certain than it is.

## Source priority

| # | Source | `source` label | Confidence | Availability |
|---|--------|-----------------|------------|--------------|
| 1 | Local Claude Code JSONL transcripts | `local_claude_code_jsonl` | exact tokens, estimated cost | Always — baseline |
| 2 | Official Anthropic Admin API | `anthropic_admin_api` | exact | **Console org + Admin API key only** — see below |
| 3 | Manual account/billing export | `manual_account_import` | manually_entered | Whenever you can download a CSV/JSON export |

### 1. Local Claude Code JSONL — always available

`~/.claude/projects/**/**.jsonl` records exact `usage` blocks per turn. Token
counts here are **exact**. Cost is **computed** from `config/pricing.json` —
an estimate that depends on your pricing table being current.

### 2. Official Admin API — availability depends on your account type

Researched directly against Anthropic's published docs (July 2026):

- Endpoints: `/v1/organizations/usage_report/messages`, `/v1/organizations/cost_report`,
  and `/v1/organizations/usage_report/claude_code` (Claude Code-specific analytics).
- **Requires an Admin API key** (`sk-ant-admin01-...`), which can only be created
  inside a **Console organization** (Console → Settings → Organization).
- Anthropic's own docs state: **"The Admin API is unavailable for individual accounts."**
- This generally rules out **personal Claude Pro/Max subscriptions** that are not
  also part of a Console org. Claude Enterprise (claude.ai orgs) uses a
  *different* key type (Analytics API key) — also not applicable to personal use.
- Run `tc account test` (or the `/account/connect` UI page) to get a **live,
  authoritative answer** for your specific account rather than relying on this
  general guidance — it reports the exact reason if access fails (missing key,
  403 permission denied, or 404 unavailable).

See [ANTHROPIC_API_SETUP.md](ANTHROPIC_API_SETUP.md) for connection instructions.

### 3. Manual import — the fallback for everyone else

If the Admin API isn't available for your account (the common case for
Pro/Max), download whatever billing/usage export the Console offers and import
it locally:

```
tc import-account --file path/to/export.csv
```

See [MANUAL_IMPORT.md](MANUAL_IMPORT.md) for format details and safety.

## What is NOT possible / NOT done

- **No scraping** of the Claude web UI. Ever.
- **No reading browser cookies** or session tokens.
- **No storing** of Claude credentials, API keys (beyond the env var you set
  yourself), or passwords. See [SECURITY.md](SECURITY.md).
- **Pro/Max plan usage progress** (the "X% of your limit" shown in the app) has
  **no documented local or API access**. It cannot be reliably read
  programmatically. Use `/account`'s manual snapshot form, or check the
  official app for plan-limit progress.
- **Enterprise Analytics API** exists but is **Enterprise-plan specific** —
  different key type, not applicable to individual accounts.

## Reconciling estimate vs official

`/account/reconcile` (or `tc account status`) compares local computed cost
against whichever official/manual data exists for the same period, and
suggests — but never automatically applies — a pricing-table adjustment. See
[RECONCILIATION.md](RECONCILIATION.md).

## Bottom line

For a personal Claude Code budget, **local JSONL token counts (exact) × your
pricing table (configurable)** is the most reliable *always-available* local
signal. Official Admin API data, when available, is exact and should be
preferred (`prefer_official_account_costs: true`). Manual import bridges the
gap when neither local computation nor the API tells the full story.
