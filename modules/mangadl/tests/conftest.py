from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest


_MODULE_ROOT = Path(__file__).resolve().parents[1]
_BASE_TEMP_ROOT = _MODULE_ROOT / ".pytest_tmp_root"


def _unique_base_temp() -> Path:
    """Return a process-unique pytest base directory inside the module."""
    return _BASE_TEMP_ROOT / f"mangadl-tests-{os.getpid()}-{uuid4().hex[:8]}"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Keep pytest temporary files isolated inside the mangadl module."""
    configured_base_temp = config.option.basetemp
    if configured_base_temp is None:
        configured_path = _unique_base_temp()
        config.option.basetemp = str(configured_path)
    else:
        configured_path = Path(configured_base_temp).expanduser()

    configured_path.parent.mkdir(parents=True, exist_ok=True)
