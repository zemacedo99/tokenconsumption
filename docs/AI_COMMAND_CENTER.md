# AI Command Center (foundational slice)

TokenConsumption started as a Claude Code tracker. This phase adds a small,
local-only hub so you can see, in one place: which AI tools/providers exist,
what's connected, what's manually tracked, and what local data this machine
happens to have — without ever scraping, logging in on your behalf, or
storing prompt/output content.

## What's in this phase

- **Providers** (`/providers`) — built-in cards (Claude, OpenAI/ChatGPT/Codex,
  GitHub Copilot, Google Gemini, Perplexity, Notion AI) plus any custom
  providers you add. Each card lists safe connection methods and known
  limitations — see [PROVIDERS.md](PROVIDERS.md).
- **Accounts** (`/accounts`) — manually tracked subscriptions/accounts (plan,
  monthly price, status). No login, no password, no API key value is ever
  stored here — see [CONNECTED_ACCOUNTS.md](CONNECTED_ACCOUNTS.md).
- **Local sources** (`/local-sources`) — a metadata-only scan of well-known
  local paths for AI tool data on this machine — see
  [LOCAL_SOURCES.md](LOCAL_SOURCES.md).
- **Workflows** (`/workflows`) — a static, rule-based keyword-matching demo.
  It suggests which of your registered providers might fit a stated goal.
  **No workflow is executed and no external model is ever called.**
- **Overview revamp** — the existing `/` dashboard now also shows manual
  subscription totals, configured-account count, and local-sources-found
  count, alongside the existing local/official/manual Claude Code cost cards.

## What this phase deliberately does NOT do

See [ROADMAP.md](ROADMAP.md) for what's deferred, and the safety rules below
for what's permanently out of scope.

## Safety model (unchanged from the rest of the app)

- No website scraping, ever.
- No provider password/email login fields anywhere in the UI.
- No reading of browser cookies, localStorage, session tokens, or profiles.
- No storing of prompts, outputs, diffs, source code, or file contents.
- Connection methods are limited to: environment variables (reference only —
  this app never asks you to paste a key into a form), manual file import,
  and manual subscription entry.
- The dashboard binds to `127.0.0.1` only, same as the rest of the app. No
  cloud sync, no TokenConsumption login/auth.
- The local-sources scanner is metadata-only: it calls `Path.exists()`,
  `os.stat()`, and glob counts — it never opens a file's contents.
