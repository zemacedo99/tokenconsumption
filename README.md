# TokenConsumption

Local Claude Code token/cost tracker. Reads your Claude Code session transcripts,
stores token usage in a local SQLite database, and shows budget progress.

Data collection, cost pricing, a preventive estimator, Claude Code hook +
status line integration, and a local web dashboard.

---

## Requirements

- Python 3.11+
- Claude Code (the CLI tool)

## Install

```bash
# 1. Clone or copy the TokenConsumption folder
cd TokenConsumption

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
.\.venv\Scripts\Activate.ps1   # Windows PowerShell

# 3. Install
pip install -e ".[dev]"

# 4. Initialise the database and local config
tc init
```

## Configure pricing (required for cost display)

Open `config/pricing.json` and fill in the `rates_per_mtoken` values for the
models you use. Get current rates from <https://www.anthropic.com/pricing>.

Example for Claude Opus 4.7 (check the website — these are placeholders):

```json
"claude-opus-4-7": {
  "rates_per_mtoken": {
    "input": 15.00,
    "output": 75.00,
    "cache_read": 1.50,
    "cache_write_5m": 3.75
  }
}
```

Until prices are filled, token counts are stored correctly but costs show `?`.

## Ingest your history

```bash
# Import all local Claude Code transcripts
tc import

# Import only a specific project
tc import --project MyRepo

# Import turns since a date
tc import --since 2026-07-01
```

## Status footer

```bash
# One-line footer (use this in statusLine or at end of replies)
tc status --line

# Full JSON status
tc status --json
```

Example output:
```
TokenConsumption: last≈€0.38 | session≈€2.10 | today≈€5.44 | month≈€38.20 / €920
```

## Reports

```bash
tc report
tc report --from 2026-07-01 --to 2026-07-31
```

## Edit the safety threshold

The threshold is stored in `config/budget_policy.json`. Edit it directly or use the CLI:

```bash
# View current threshold
tc config get safety_threshold_value

# Change to €10
tc config set safety_threshold_value 10

# Change the monthly budget
tc config set monthly_budget_value 500

# Update the FX rate
tc config set fx_rates '{"USD_to_EUR": 0.91, "updated_at": "2026-07-01"}'
```

The file is gitignored — your settings stay local.

## Estimate before expensive work

```bash
tc estimate --model claude-opus-4-8 --task-type refactor_wide
# -> Budget estimate: likely ≈ €6.09, threshold €20.00, ... recommendation=PROCEED
tc estimate --model claude-opus-4-8 --task-type refactor_wide --turns 60 --save
# -> recommendation=ASK  (over threshold) + cheaper-model suggestion
```

## Local dashboard

```bash
pip install -e ".[ui]"       # first time only (fastapi, uvicorn, jinja2)
tc run                       # http://127.0.0.1:8787  (localhost only)
```
Pages: Overview, Trends, Projects, Sessions, Raw logs (metadata only),
Providers, Accounts, Local sources, Workflows (demo), Settings.

## AI Command Center (providers, accounts, local sources)

A small hub for tracking AI tools/subscriptions beyond just Claude Code —
built-in provider cards (Claude, OpenAI, GitHub Copilot, Gemini, Perplexity,
Notion AI), manual subscription tracking, and a metadata-only local scan for
AI tool data on this machine. No scraping, no passwords, no browser cookies —
see [docs/AI_COMMAND_CENTER.md](docs/AI_COMMAND_CENTER.md).

```bash
tc providers list                 # built-in + custom providers
tc accounts add --provider openai --plan "ChatGPT Plus" --monthly-price 20 --currency USD
tc accounts status                # count + monthly subscription total
tc sources scan                   # metadata-only local data scan
```

See also [docs/PROVIDERS.md](docs/PROVIDERS.md),
[docs/CONNECTED_ACCOUNTS.md](docs/CONNECTED_ACCOUNTS.md),
[docs/LOCAL_SOURCES.md](docs/LOCAL_SOURCES.md), and
[docs/ROADMAP.md](docs/ROADMAP.md) for what's deferred.

## Claude Code integration (global)

```bash
# Preview the settings.json changes, then apply (backs up first):
powershell -File scripts\install-hooks.ps1            # preview
powershell -File scripts\install-hooks.ps1 -Apply     # apply
```
Adds a statusLine + Stop/SessionEnd hooks. See docs/HOOK_SETUP.md.
Paste docs/CLAUDE_MEMORY_SNIPPET.md into `~/.claude/CLAUDE.md` for preventive behavior.

## Claude attribution (no co-author lines)

The repo's `CLAUDE.md` tells Claude Code not to add `Co-Authored-By: Claude` or
"Generated with Claude Code" lines to commits and PRs in this repository.

For tool-level enforcement, run once after cloning:

```powershell
.\scripts\setup-claude.ps1
```

This merges `"attribution": { "commit": "", "pr": "" }` into your own user-level
`~/.claude/settings.json` (backing it up first, keeping all other settings). That
file is yours, not part of the repo, so it is not committed to Git. Use `-DryRun`
to preview without writing.

## Official account data (if your account supports it)

The Anthropic Admin API requires a Console organization — **generally
unavailable for personal Pro/Max accounts.** Check yours directly:

```bash
tc account test                              # live check — never assumes
tc account sync --from 2026-07-01 --to 2026-07-31   # if connected
tc account status                            # all source statuses
```

See [docs/ANTHROPIC_API_SETUP.md](docs/ANTHROPIC_API_SETUP.md).

## Manual account import (fallback for everyone else)

```bash
tc import-account --file export.csv            # preview only, writes nothing
tc import-account --file export.csv --yes      # confirm and import
```

Or use `/account/import` in the dashboard. See [docs/MANUAL_IMPORT.md](docs/MANUAL_IMPORT.md).

## Reconciliation

`/account/reconcile` compares local computed cost against official/manual
account data and suggests (never auto-applies) a pricing adjustment. See
[docs/RECONCILIATION.md](docs/RECONCILIATION.md).

## Diagnose

```bash
tc doctor    # checks config, pricing, DB, Claude Code integration, and account API
```

## Run tests

```bash
python -m unittest discover tests      # 107 tests
```

---

## Limitations

- **Pre-turn cost is estimate-only.** The exact cost of a reply is only known
  *after* it finishes. The status footer shows the cost of the *previous* turn.
- **Prices must be configured manually.** `pricing.json` ships with `null` rates.
  Fill them from the Anthropic pricing page. Costs will show `?` until then.
- **Claude Code integration is opt-in.** `scripts/install-hooks.ps1` modifies
  `~/.claude/settings.json` only when you pass `-Apply` (and backs it up first).
- **Official billing may differ** from local computed cost. Token counts are
  exact; cost depends on your pricing table. See docs/ACCOUNT_DATA.md — Pro/Max
  plan-limit progress has no documented local API.
- **Official Admin API is unavailable for individual accounts** per Anthropic's
  own documentation — expected for personal Pro/Max subscriptions. `tc account
  test` gives you a live, authoritative answer for your specific account.
- **No OS keyring support yet** — the Admin API key is read from the
  `ANTHROPIC_ADMIN_API_KEY` environment variable only, by design (smaller
  attack surface, fully auditable).
- **Local only.** No cloud sync, no external API calls, no web scraping.

## Folder rename

If the folder is currently named `TokenConsumtion` (typo), close Claude Code,
rename it to `TokenConsumption`, and reopen. All paths in the code use relative
references — nothing hard-coded to the old name.

## Privacy

Only token/cost metadata is stored. Message content, file contents, diffs, and
secrets are never written to the database by default. See `docs/PRIVACY.md`.
