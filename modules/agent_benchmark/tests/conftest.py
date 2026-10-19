"""Keep all filesystem test artifacts inside the owning module."""

import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
for module_name in ("benchmark_core", "agent_benchmark"):
    module_dir = str(REPO_ROOT / "modules" / module_name)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)


def pytest_configure(config):
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(__file__).resolve().parents[1] / ".pytest_tmp_root" / f"run-{os.getpid()}")
    Path(config.option.basetemp).parent.mkdir(parents=True, exist_ok=True)
