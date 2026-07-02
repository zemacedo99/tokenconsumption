#!/usr/bin/env python3
"""
Claude Code `Stop` hook: ingest the just-finished turn's usage metadata.

Runs after every assistant turn. Reads the transcript_path from the hook
payload and ingests only that session's file (fast, incremental, idempotent).
Fails safely — logs errors to logs/tc-hook-errors.log and always exits 0.

Only token/cost metadata is stored. No prompt or output content is read into
the database.
"""

import os
import sys

# Bootstrap import path before importing the package.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.dirname(os.path.dirname(_HERE))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from token_consumption.hooks._common import read_hook_payload, run_safely  # noqa: E402


def _ingest():
    from token_consumption import ingest as ingest_mod

    payload = read_hook_payload()
    transcript_path = payload.get("transcript_path")
    session_id = payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID")

    if transcript_path:
        ingest_mod.ingest_by_transcript_path(transcript_path)
    elif session_id:
        ingest_mod.ingest_session(session_id)
    # If neither is available, silently do nothing — next `tc import` will catch up.


def main() -> int:
    return run_safely("Stop hook", _ingest)


if __name__ == "__main__":
    sys.exit(main())
