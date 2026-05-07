"""pytest configuration for grid_search tests."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")


@pytest.fixture()
def tmp_path() -> Path:
    """Use a module-local temp root to avoid stale global pytest temp ACLs."""
    base = Path(__file__).resolve().parents[1] / ".pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="test-", dir=base))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
