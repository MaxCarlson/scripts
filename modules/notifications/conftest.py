"""
Pytest configuration for modules/notifications.
Ensures local worktree source takes precedence over installed editable finders.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Remove editable finders for scheduler, notifications, and remote_control so local worktree is loaded
sys.meta_path = [
    f for f in sys.meta_path
    if not any(
        mod in getattr(f, "__name__", "") or mod in str(f)
        for mod in ("scheduler", "notifications", "remote_control")
    )
]

modules_dir = Path(__file__).resolve().parent.parent
for mod_name in ("notifications", "scheduler", "remote_control"):
    mod_path = str(modules_dir / mod_name)
    if mod_path in sys.path:
        sys.path.remove(mod_path)
    sys.path.insert(0, mod_path)
