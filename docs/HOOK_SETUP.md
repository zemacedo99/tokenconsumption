# Hook & status line setup

TokenConsumption integrates with Claude Code through a **statusLine** (shows a
compact budget line) and **Stop** / **SessionEnd** hooks (log usage metadata
after each turn/session).

## Automatic install

```powershell
# Windows (PowerShell)
powershell -File scripts\install-hooks.ps1          # PREVIEW — shows the diff, writes nothing
powershell -File scripts\install-hooks.ps1 -Apply   # backs up settings.json, then writes
```

```bash
# macOS / Linux / Git Bash
bash scripts/install-hooks.sh            # PREVIEW
bash scripts/install-hooks.sh --apply    # backs up, then writes
```

The installer:
- Previews the merged `~/.claude/settings.json` before writing.
- Backs up to `settings.json.bak.<timestamp>` before any change.
- Preserves existing settings keys.
- Writes UTF-8 **without** a BOM (a BOM breaks strict JSON parsing).

**Restart Claude Code** after applying for the statusLine and hooks to load.

## What gets added

```json
{
  "statusLine": {
    "type": "command",
    "command": "python \"<ROOT>\\scripts\\tc-launcher.py\" status --line"
  },
  "hooks": {
    "Stop": [
      { "hooks": [{ "type": "command", "command": "python \"<ROOT>\\src\\token_consumption\\hooks\\on_stop.py\"" }] }
    ],
    "SessionEnd": [
      { "hooks": [{ "type": "command", "command": "python \"<ROOT>\\src\\token_consumption\\hooks\\on_session_end.py\"" }] }
    ]
  }
}
```

## How it behaves

- **statusLine** runs on Claude Code UI refreshes. It reads only precomputed
  aggregates from SQLite and prints one line. Claude Code pipes the session JSON
  (including `session_id`) to it on stdin, so the session total is accurate.
- **Stop** runs after every assistant turn. It reads `transcript_path` from the
  hook payload and ingests just that file — fast and incremental.
- **SessionEnd** runs once when the session ends, as a final catch-up ingest.

## Fail-safe design

- Every hook wraps its work in `run_safely()` and **always exits 0**. A tracker
  error never blocks or crashes Claude Code.
- Errors are appended to `logs/tc-hook-errors.log` for later inspection.
- If TokenConsumption is missing or broken, Claude Code continues normally; run
  `tc import` later to backfill.

## Timing note

The exact cost of the **current** reply is not known until the turn finishes.
The Stop hook records it *just after* completion, so the statusLine shows the
**previous** turn's actual cost plus running session/day/month totals. The
pre-turn `estimate` (see `tc estimate`) covers the "before work" side.

## Uninstall

Restore a backup:

```powershell
Copy-Item "$env:USERPROFILE\.claude\settings.json.bak.<timestamp>" "$env:USERPROFILE\.claude\settings.json"
```
