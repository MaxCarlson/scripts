#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ensure the src directory (containing the 'procparsers' package) is on sys.path
so tests can import without requiring an installed/editable package.
"""
from __future__ import annotations

import sys
from pathlib import Path

# tests/ -> project_root/src/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
