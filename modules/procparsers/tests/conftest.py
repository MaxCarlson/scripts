#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ensure the local project root (containing the 'procparsers' package) is on sys.path
so tests can import without requiring an installed/editable package.
"""
from __future__ import annotations

import sys
from pathlib import Path

# tests/ -> project_root/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
