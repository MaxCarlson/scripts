"""
Pytest configuration for videocompress tests.
Enforces module-local temp directories in accordance with repository standards.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

MODULE_ROOT = Path(__file__).resolve().parent.parent
MODULE_TMP_ROOT = MODULE_ROOT / ".pytest_tmp_root"


@pytest.fixture(scope="session", autouse=True)
def ensure_module_tmp_root():
    """Ensure local .pytest_tmp_root exists and is used."""
    MODULE_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    yield
