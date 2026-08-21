"""
Metadata-only local AI data source scanner.

Never opens or reads file contents — only Path.exists()/os.stat()/glob
counts. Nothing scanned here is persisted to the database; results are
live/ephemeral each call, by design (no filesystem paths are stored).

Every result is machine-local only: it reflects what exists on THIS
computer and may not exist on another machine until a sync feature exists.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg_mod

MACHINE_LOCAL_NOTE = (
    "Found on this machine only. May not exist on another computer until a "
    "sync feature exists."
)


def _stat_info(path: Path) -> dict:
    try:
        st = path.stat()
        return {
            "last_modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "approx_bytes": st.st_size,
        }
    except OSError:
        return {"last_modified": None, "approx_bytes": None}


def _probe_dir(root: Path) -> dict:
    """Stat/glob only — never opens a file's contents."""
    if not root.exists():
        return {"exists": False, "file_count": 0, "last_modified": None, "approx_bytes": None}
    total_bytes = 0
    latest = None
    file_count = 0
    try:
        for p in root.glob("**/*"):
            if not p.is_file():
                continue
            file_count += 1
            info = _stat_info(p)
            if info["approx_bytes"]:
                total_bytes += info["approx_bytes"]
            if info["last_modified"] and (latest is None or info["last_modified"] > latest):
                latest = info["last_modified"]
    except OSError:
        pass
    return {"exists": True, "file_count": file_count, "last_modified": latest, "approx_bytes": total_bytes}


def _known_roots() -> list[dict]:
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))

    cfg = cfg_mod.load()
    tc_data_dir = cfg_mod._data_dir(cfg)

    return [
        {"tool": "Claude Code", "kind": "transcripts", "root": home / ".claude" / "projects"},
        {"tool": "TokenConsumption", "kind": "database", "root": tc_data_dir},
        {"tool": "TokenConsumption", "kind": "config", "root": cfg_mod._config_dir()},
        {"tool": "GitHub Copilot", "kind": "vscode_extension_storage",
         "root": appdata / "Code" / "User" / "globalStorage" / "github.copilot"},
        {"tool": "GitHub Copilot", "kind": "vscode_chat_extension_storage",
         "root": appdata / "Code" / "User" / "globalStorage" / "github.copilot-chat"},
        {"tool": "OpenAI Codex CLI", "kind": "config", "root": home / ".codex"},
        {"tool": "OpenAI", "kind": "config", "root": home / ".config" / "openai"},
        {"tool": "Google Gemini CLI", "kind": "config", "root": home / ".gemini"},
        {"tool": "Google Cloud (gcloud)", "kind": "config", "root": home / ".config" / "gcloud"},
        {"tool": "Cursor", "kind": "app_data", "root": appdata / "Cursor" / "User" / "globalStorage"},
        {"tool": "Continue", "kind": "config", "root": home / ".continue"},
    ]


def scan() -> list[dict]:
    """Live, ephemeral scan. Metadata only — never opens a file."""
    results = []
    for entry in _known_roots():
        root = entry["root"]
        info = _probe_dir(root)
        results.append({
            "tool": entry["tool"],
            "kind": entry["kind"],
            "root_display": str(root),
            **info,
            "machine_local": True,
            "note": MACHINE_LOCAL_NOTE,
        })
    return results


def scan_summary() -> dict:
    results = scan()
    found = sum(1 for r in results if r["exists"])
    return {"total_checked": len(results), "found": found, "results": results}
