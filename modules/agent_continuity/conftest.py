"""Root pytest configuration ensuring local worktree source takes precedence."""

from __future__ import annotations

import os
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
configured_tmp_root = os.environ.get("LLMD_TEST_TMP_ROOT")
base_tmp_root = Path(configured_tmp_root) if configured_tmp_root else MODULE_ROOT / ".pytest_tmp_root"
worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
TMP_ROOT = base_tmp_root / worker_id if worker_id != "master" else base_tmp_root
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["LLMD_TEST_TMP_ROOT"] = str(TMP_ROOT)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))
os.environ.setdefault("TEMP", str(TMP_ROOT))
os.environ.setdefault("TMP", str(TMP_ROOT))

root_str = str(MODULE_ROOT)
for source_root in (MODULE_ROOT.parent, MODULE_ROOT):
    source_str = str(source_root)
    if source_root.is_dir():
        if source_str in sys.path:
            sys.path.remove(source_str)
        sys.path.insert(0, source_str)
