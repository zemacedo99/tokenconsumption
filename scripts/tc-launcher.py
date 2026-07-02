#!/usr/bin/env python3
"""
Standalone launcher for the TokenConsumption CLI.

Lets `tc` run without an activated virtualenv or `pip install` — it simply adds
the project's src/ directory to sys.path and calls the CLI main().

Used by Claude Code hooks and the statusLine so they work from any project dir.

Usage:
    python /path/to/TokenConsumption/scripts/tc-launcher.py status --line
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from token_consumption.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
