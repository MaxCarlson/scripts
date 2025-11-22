from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure():
    repo_root = Path(__file__).resolve().parents[3]
    modules_dir = repo_root / "modules"
    for p in (repo_root, modules_dir):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
