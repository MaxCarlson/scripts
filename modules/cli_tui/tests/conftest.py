from __future__ import annotations

import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

_MODULE_ROOT = Path(__file__).resolve().parents[1]
_BASE_TEMP_ROOT = _MODULE_ROOT / ".pytest_tmp_root"

if str(_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODULE_ROOT))


def _unique_base_temp() -> Path:
    """Return a process-unique pytest base directory inside the module."""
    return _BASE_TEMP_ROOT / f"clitui-tests-{os.getpid()}-{uuid4().hex[:8]}"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Keep pytest temporary files and saved layouts isolated inside the module."""
    os.environ["CLI_TUI_LAYOUT_DIR"] = str(_BASE_TEMP_ROOT / "layouts")
    configured_base_temp = config.option.basetemp
    if configured_base_temp is None:
        configured_path = _unique_base_temp()
        config.option.basetemp = str(configured_path)
    else:
        configured_path = Path(configured_base_temp).expanduser()

    configured_path.parent.mkdir(parents=True, exist_ok=True)
