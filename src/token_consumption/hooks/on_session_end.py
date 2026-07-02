#!/usr/bin/env python3
"""
Claude Code `SessionEnd` hook: final ingest of the session's usage metadata.

Runs once when a session ends. Ensures the last turns are captured even if a
Stop hook was missed. Fails safely and always exits 0.
"""

import os
import sys

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


def main() -> int:
    return run_safely("SessionEnd hook", _ingest)


if __name__ == "__main__":
    sys.exit(main())
