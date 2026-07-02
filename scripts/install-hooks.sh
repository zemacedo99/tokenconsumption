#!/usr/bin/env bash
# Install TokenConsumption statusLine + Stop/SessionEnd hooks into ~/.claude/settings.json.
# Safe by default: PREVIEW only. Pass --apply to back up and write.
# Requires: python3 (used for JSON merge).
set -euo pipefail

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
LAUNCHER="$ROOT/scripts/tc-launcher.py"
ON_STOP="$ROOT/src/token_consumption/hooks/on_stop.py"
ON_END="$ROOT/src/token_consumption/hooks/on_session_end.py"
SETTINGS="$HOME/.claude/settings.json"

# Build the merged settings JSON with python (no jq dependency).
NEW_JSON="$(APPLY="$APPLY" LAUNCHER="$LAUNCHER" ON_STOP="$ON_STOP" ON_END="$ON_END" SETTINGS="$SETTINGS" python3 - <<'PY'
import json, os
settings_path = os.environ["SETTINGS"]
launcher, on_stop, on_end = os.environ["LAUNCHER"], os.environ["ON_STOP"], os.environ["ON_END"]

data = {}
if os.path.exists(settings_path):
    try:
        with open(settings_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}

data["statusLine"] = {"type": "command", "command": f'python "{launcher}" status --line'}
hooks = data.get("hooks", {})
hooks["Stop"] = [{"hooks": [{"type": "command", "command": f'python "{on_stop}"'}]}]
hooks["SessionEnd"] = [{"hooks": [{"type": "command", "command": f'python "{on_end}"'}]}]
data["hooks"] = hooks
print(json.dumps(data, indent=2))
PY
)"

echo "=== Planned ~/.claude/settings.json ==="
echo "$NEW_JSON"
echo "======================================="

if [[ "$APPLY" -ne 1 ]]; then
    echo
    echo "PREVIEW ONLY. No changes written."
    echo "Re-run with --apply to back up and write:"
    echo "    bash scripts/install-hooks.sh --apply"
    exit 0
fi

mkdir -p "$(dirname "$SETTINGS")"
if [[ -f "$SETTINGS" ]]; then
    STAMP="$(date +%Y%m%d-%H%M%S)"
    cp "$SETTINGS" "$SETTINGS.bak.$STAMP"
    echo "Backup created: $SETTINGS.bak.$STAMP"
fi

printf '%s\n' "$NEW_JSON" > "$SETTINGS"
echo "Wrote $SETTINGS"
echo "Restart Claude Code for the statusLine and hooks to take effect."
