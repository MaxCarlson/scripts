#!/usr/bin/env python3
"""Repository-root launcher for the scripts-help browser.

This shim makes the help system available from a fresh checkout without first
requiring the scripts_help package to be installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_MODULE_ROOT = _REPO_ROOT / "modules" / "scripts_help"
sys.path.insert(0, str(_MODULE_ROOT))

from scripts_help.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
