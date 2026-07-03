# Manual account/billing import

The fallback path when the official Admin API isn't available for your
account (the common case for personal Pro/Max subscriptions — see
[ANTHROPIC_API_SETUP.md](ANTHROPIC_API_SETUP.md)).

You download the export yourself from the Anthropic Console. This app never
automates that download, never logs into Claude on your behalf, and never
reads browser state.

## Supported formats

CSV or JSON, with columns/fields resembling:

| Logical field | Accepted column name variants |
|---|---|
| period | `period`, `date`, `start_date`, `starting_at`, `month` |
| model | `model`, `model_name` |
| service/description | `service`, `cost_type`, `description`, `line_item`, `item` |
| cost amount | `cost_value`, `amount`, `cost`, `total`, `value` |
| currency | `cost_currency`, `currency` |
| input tokens | `input_tokens`, `uncached_input_tokens` |
| output tokens | `output_tokens` |

Column names are matched case-insensitively; unrecognized columns are simply
ignored (except a small blocklist — see Safety below).

## Usage

```bash
# 1. Preview only — nothing is written. Always safe to run.
tc import-account --file export.csv

# 2. Explicit dry run (same effect, more obvious intent)
tc import-account --file export.csv --dry-run

# 3. Actually import (requires explicit confirmation)
tc import-account --file export.csv --yes

# Force a format instead of auto-detecting by extension:
tc import-account --file export.txt --type csv
```

Without `--yes`, the command **always** stops after showing a preview — it
never writes silently.

## UI

Visit `/account/import`:
1. Choose a local CSV/JSON file (upload stays on `127.0.0.1` — nothing leaves
   your machine).
2. Review the parsed preview and detected column mapping.
3. Click **Confirm import**.

## Safety

- **Content columns are never imported.** Any column named `prompt`,
  `output`, `content`, `message`, `response`, `text`, or `diff` is flagged in
  the preview and its values are dropped — even if you click confirm.
- **Idempotent.** Re-importing the same file inserts zero duplicate rows
  (deduped by source + period + model + service + reference file).
- Rows are stored with `source=manual_account_import`,
  `confidence=manually_entered` — always visually distinct from local
  estimates or official API data in the UI and reports.

## Recording Pro/Max plan usage (no file needed)

If you don't have a file export at all — e.g. you just want to note what
Claude's Settings→Usage page showed you — use the manual snapshot form on
`/account` instead of a file import. It records plan name, credits
total/remaining/used, and a reset date. A screenshot **path** can go in the
notes field as plain text; the image itself is never uploaded or stored.
