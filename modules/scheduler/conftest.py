"""
Pytest configuration for modules/scheduler.
Ensures local worktree source takes precedence over installed editable finders.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Remove editable finders for scheduler so the local worktree is loaded
sys.meta_path = [
    f for f in sys.meta_path
    if "scheduler" not in getattr(f, "__name__", "") and "scheduler" not in str(f)
]

worktree_scheduler = Path(__file__).resolve().parent
worktree_notifications = worktree_scheduler.parent / "notifications"

for p in (worktree_notifications, worktree_scheduler):
    p_str = str(p)
    if p_str in sys.path:
        sys.path.remove(p_str)
    sys.path.insert(0, p_str)
