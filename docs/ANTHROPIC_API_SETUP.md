# Connecting the official Anthropic Admin API

This is entirely optional. If your account doesn't support it (common for
personal Pro/Max subscriptions), skip straight to
[MANUAL_IMPORT.md](MANUAL_IMPORT.md).

## What this does NOT do

- **No password field, anywhere.** Authentication is one environment variable.
- **No Claude email/password login form** — this app never asks for your
  Claude account credentials.
- **No browser automation, no cookies, no session tokens.**

## Prerequisites

1. A **Console organization**. Personal API/Console access alone is not
   enough — go to **Console → Settings → Organization** and confirm one
   exists (or create one).
2. **Admin or Billing permission** within that organization.
3. Per Anthropic's docs: *"The Admin API is unavailable for individual
   accounts."* If you're on a personal Pro/Max subscription with no Console
   organization, this path is not available to you — `tc account test` will
   confirm this with a clear error rather than a guess.

## Step 1 — Create an Admin API key

In the Console, create an **Admin API key** (format `sk-ant-admin01-...`).
This is different from a normal API key — it grants read access to
organization-wide usage/cost reports.

## Step 2 — Set environment variables

Only environment variables are read — nothing is stored to disk by this app.

**Windows (PowerShell), persistent:**
```powershell
setx ANTHROPIC_ADMIN_API_KEY "sk-ant-admin01-..."
# optional:
setx ANTHROPIC_ORG_ID "org_..."
setx ANTHROPIC_WORKSPACE_ID "wrkspc_..."
```
Restart your terminal (and Claude Code) for `setx` to take effect.

**Windows (current session only):**
```powershell
$env:ANTHROPIC_ADMIN_API_KEY = "sk-ant-admin01-..."
```

**macOS/Linux:**
```bash
export ANTHROPIC_ADMIN_API_KEY="sk-ant-admin01-..."
```

> Local storage via OS keyring is intentionally **not implemented** in this
> version, to keep the code auditable and the attack surface minimal.
> Environment variables are the only supported mechanism. If you need
> persistence, use your OS's standard env-var mechanism (`setx`, shell
> profile, etc.) — not this tool.

## Step 3 — Test the connection

```bash
tc account test
```

or visit `/account/connect` in the dashboard and click **Test connection**.

Possible results:

| Result | Meaning |
|---|---|
| `Connected` | Admin API access confirmed. Proceed to `tc account sync`. |
| `API key missing or invalid (401)` | Key not set, mistyped, or revoked. |
| `Permission denied (403)` | Key exists but lacks Admin/Billing permission. |
| `Endpoint unavailable for this account (404)` | No Console org, or Admin API not enabled — **expected for personal Pro/Max accounts.** |

The full key is **never printed** — only a masked fragment like
`sk-ant-admin...ab12`.

## Step 4 — Sync usage/cost data

```bash
tc account sync --from 2026-07-01 --to 2026-07-31
```

This fetches:
- `/v1/organizations/usage_report/messages` (token counts by model, daily buckets)
- `/v1/organizations/cost_report` (USD cost by model/service, daily buckets)

and stores normalized rows in `account_usage_reports` with
`source=anthropic_admin_api`, `confidence=exact`. Raw API responses are
**never persisted** unless you explicitly set `TC_DEBUG_API=1` (writes to
`logs/` for troubleshooting only — still metadata/numbers, never prompt content).

## Troubleshooting

- **"Admin API unavailable for individual accounts"** — this is the expected,
  documented outcome for most personal subscriptions. Use manual import instead.
- **404 on sync but 200 on test** — the org may have zero usage in the
  requested date range; not an error.
- **Rate limiting** — the API supports polling once per minute for sustained
  use; `tc account sync` makes a small, bounded number of paginated requests.
