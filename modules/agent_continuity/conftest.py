"""Root pytest configuration ensuring local worktree source takes precedence."""

from __future__ import annotations

import os
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
TMP_ROOT = MODULE_ROOT / ".pytest_tmp_root"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))
os.environ.setdefault("TEMP", str(TMP_ROOT))
os.environ.setdefault("TMP", str(TMP_ROOT))

root_str = str(MODULE_ROOT)
if root_str in sys.path:
    sys.path.remove(root_str)
sys.path.insert(0, root_str)
