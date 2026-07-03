# Security & privacy guarantees

## Hard rules this codebase follows

- **No Claude password is ever requested or stored.** There is no login form
  anywhere in this app for your Claude account.
- **No web scraping** of claude.ai or the Anthropic Console. All data comes
  from local files (`~/.claude/projects/*.jsonl`), the documented Admin API
  (HTTPS + API key you provide), or files you export and import yourself.
- **No browser cookies, localStorage, or session tokens are ever read.**
- **No bypass of Anthropic authentication or terms.** The official API
  connector uses exactly the documented `x-api-key` header with a key you
  create in the Console yourself.
- **The full Admin API key is never printed, logged, or stored on disk** by
  this app. It's read from `ANTHROPIC_ADMIN_API_KEY` at call time and only a
  masked fragment (`sk-ant-admin...ab12`) ever appears in output.
- **Raw API responses are not persisted** unless you explicitly set
  `TC_DEBUG_API=1` — and even then only to local `logs/`, containing
  usage/cost numbers, never prompt or output content.
- **Prompt/output content is never stored**, from any source — local JSONL
  ingest extracts only the `usage` metadata block; manual imports reject any
  column that looks like content (`prompt`, `output`, `content`, `message`,
  `response`, `text`, `diff`).
- **The dashboard binds to `127.0.0.1` by default** and has no login — because
  it's not reachable from outside your machine. `tc run --host` will warn
  loudly if you point it at a non-localhost address.
- **Nothing is uploaded anywhere.** No telemetry, no analytics, no cloud sync.

## What IS stored locally

- Token counts, costs, model names, session IDs, project slugs, timestamps —
  in `data/usage.sqlite` (gitignored).
- Whatever you type into the manual balance-snapshot form (plan name, credit
  numbers, a free-text notes field — e.g. a screenshot **path**, never the
  image itself).
- Whatever numeric/period fields a manual CSV/JSON import contains, minus any
  blocklisted content-like columns.

## Where secrets live (and don't)

| Secret | Where it lives | Stored by this app? |
|---|---|---|
| Claude Code OAuth session | `~/.claude/.credentials.json` (managed by Claude Code itself) | No — never read or touched |
| `ANTHROPIC_ADMIN_API_KEY` | Your OS environment | No — read at call time only, masked in all output |
| Claude account password | Nowhere in this app | Never requested |

## Reporting a concern

If you find a place where this codebase deviates from the rules above, treat
it as a bug: the intent is that every one of these guarantees holds without
exception.
