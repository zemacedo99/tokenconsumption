# Local sources scanner

`/local-sources` (UI) and `tc sources scan` (CLI) run a **metadata-only**
scan of well-known local paths where AI tools commonly store data on this
machine.

## What it checks (best-effort, deep heuristic)

| Tool | Kind | Path checked |
|---|---|---|
| Claude Code | transcripts | `~/.claude/projects` |
| TokenConsumption | database | `data/` (this tool's own DB dir) |
| TokenConsumption | config | `config/` (this tool's own config dir) |
| GitHub Copilot | VS Code extension storage | `%APPDATA%/Code/User/globalStorage/github.copilot*` |
| OpenAI Codex CLI | config | `~/.codex`, `~/.config/openai` |
| Google Gemini CLI | config | `~/.gemini`, `~/.config/gcloud` |
| Cursor | app data | `%APPDATA%/Cursor/User/globalStorage` |
| Continue | config | `~/.continue` |

This list will grow over time and is intentionally best-effort: paths vary
by OS, editor, and tool version. A tool not being found does **not** mean
it isn't installed — only that it wasn't found at the specific paths this
scanner knows about today.

## What it returns

For each checked root: `exists`, `file_count`, `last_modified`,
`approx_bytes` — nothing else. Every result carries:

> "Found on this machine only. May not exist on another computer until a
> sync feature exists."

## What it never does

- **Never opens a file.** Only `Path.exists()`, `os.stat()`, and glob counts
  are used — verified by `tests/test_hub.py::TestLocalSourcesScanner`.
- **Nothing is persisted.** The scan is live/ephemeral on every call; no
  filesystem paths are written to the database, so there is no local
  "sources" table to inspect or leak.
- No file content, prompt, output, or source code is ever read or displayed.

## CLI

```bash
tc sources scan     # full breakdown, one line per checked path
tc sources list      # alias for scan
tc sources status    # one-line found/checked summary
```
