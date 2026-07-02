"""Shared helpers for Claude Code hook handlers.

Hooks must NEVER block or crash Claude Code. Every handler runs its logic
through `run_safely`, which swallows all errors, logs them, and exits 0.
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _bootstrap_path() -> Path:
    """Add <root>/src to sys.path so the package imports as a plain script. Return root."""
    root = Path(__file__).resolve().parents[3]  # hooks/ -> token_consumption/ -> src/ -> root
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return root


def _log_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    log_dir = root / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return log_dir / "tc-hook-errors.log"


def log_error(context: str, exc: BaseException) -> None:
    """Append an error to logs/tc-hook-errors.log. Never raises."""
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with open(_log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"\n[{ts}] {context}\n")
            fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        pass  # last-resort: never let logging itself break the hook


def read_hook_payload() -> dict:
    """
    Read the JSON payload Claude Code sends on stdin to hooks.
    Contains keys like session_id, transcript_path, cwd, hook_event_name.
    Returns {} if nothing is piped in.
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def run_safely(context: str, fn) -> int:
    """Run fn(); log any error; always return 0 so Claude Code is never blocked."""
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 - deliberately catch everything
        log_error(context, exc)
    return 0
