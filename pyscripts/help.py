#!/usr/bin/env python3
"""Thin shim — delegates to the scripts_help module CLI.

Prefer running via  python help.py  from the repository root or via the
installed  scripts-help  entry point. This file remains as a compatibility
shim for the old pyscripts path.
"""
import sys
from pathlib import Path

# Ensure the module is importable when running directly from pyscripts/
sys.path.insert(0, str(Path(__file__).parent.parent / "modules" / "scripts_help"))

from scripts_help.cli import main

if __name__ == "__main__":
    main()
