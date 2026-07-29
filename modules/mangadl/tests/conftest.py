from __future__ import annotations

from pathlib import Path

import pytest


_MODULE_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BASE_TEMP = _MODULE_ROOT / ".pytest_tmp_root" / "mangadl-tests"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Keep pytest temporary files inside the mangadl module on every platform."""
    configured_base_temp = config.option.basetemp
    if configured_base_temp is None:
        configured_path = _DEFAULT_BASE_TEMP
        config.option.basetemp = str(configured_path)
    else:
        configured_path = Path(configured_base_temp).expanduser()

    configured_path.parent.mkdir(parents=True, exist_ok=True)
