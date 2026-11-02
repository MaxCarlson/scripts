"""Keep all filesystem test artifacts inside the owning module."""

import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
for module_name in ("benchmark_core", "agent_benchmark", "termdash", "llm_monitor", "web_ui_tools"):
    module_dir = str(REPO_ROOT / "modules" / module_name)
    if module_dir in sys.path:
        sys.path.remove(module_dir)
    sys.path.insert(0, module_dir)


def pytest_configure(config):
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(__file__).resolve().parents[1] / ".pytest_tmp_root" / f"run-{os.getpid()}")
    Path(config.option.basetemp).parent.mkdir(parents=True, exist_ok=True)
