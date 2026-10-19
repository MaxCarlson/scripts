"""Keep all filesystem test artifacts inside the owning module."""

import os
from pathlib import Path


def pytest_configure(config):
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(__file__).resolve().parents[1] / ".pytest_tmp_root" / f"run-{os.getpid()}")
    Path(config.option.basetemp).parent.mkdir(parents=True, exist_ok=True)
