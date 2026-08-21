# Provider registry

Providers are defined two ways:

- **Built-in** — code-defined in `src/token_consumption/providers.py`
  (`BUILTIN_PROVIDERS`). MVP set: `anthropic`, `openai`, `github_copilot`,
  `google_gemini`, `perplexity`, `notion_ai`.
- **Custom** — anything you add yourself, stored in the `providers` table
  (schema v3). Custom provider keys cannot shadow a built-in key.

Both are merged and returned by `providers.list_providers()` — built-ins win
on key collision.

## Fields per provider

| Field | Meaning |
|---|---|
| `provider_key` | Unique identifier, e.g. `openai` |
| `display_name` | Shown in the UI |
| `category` | Free-text grouping, e.g. `assistant`, `coding_assistant` |
| `website` | Reference link only |
| `connection_methods` | Subset of `env_var`, `manual_import`, `manual_entry` |
| `env_var_names` | Documented env var names for that provider's API, if any — **reference only, never a stored value** |
| `limitations` | Plain-English note on what data isn't available and why |

## Connection status

`providers.provider_status(key)` returns one of:

- `connected` — a listed env var is set in this process's environment.
- `manual` — no env var, but you've added at least one account for this
  provider under `/accounts`.
- `unconfigured` — a safe connection method exists but nothing is set up.
- `unsupported` — no safe connection method is available at all.
- `unknown` — provider key not found.

## CLI

```bash
tc providers list                 # built-in + custom
tc providers status               # per-provider connection status
tc providers add --key my_tool --name "My Tool" \
    --category custom --env-var MY_TOOL_API_KEY --limitations "..."
```

## Adding a custom provider via the UI

There's no dedicated "add provider" UI page in this MVP — use the CLI command
above, then it appears in `/providers` immediately. A UI form is a documented
follow-up in [ROADMAP.md](ROADMAP.md).

## Known limitations for the MVP provider set

Only Claude/Anthropic has a wired-up cost-data integration (Admin API +
manual import + reconciliation — see [ACCOUNT_DATA.md](ACCOUNT_DATA.md)).
The other five built-in providers are registered for visibility and manual
subscription tracking only; none of them expose a per-token cost API for
individual consumer accounts today.
