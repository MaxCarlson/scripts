from __future__ import annotations

import sys
from pathlib import Path

# Ensure local pscripts module is importable when running from the repo checkout
_repo_root = Path(__file__).resolve().parent
_local_module = _repo_root / "scripts" / "pscripts" / "modules" / "jp_video"
if _local_module.exists():
    sys.path.insert(0, str(_local_module))

from ps_jp_subs.cli import main

if __name__ == "__main__":
    main()
