from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Iterator[Path]:
    """Module-local tmp_path replacement that avoids repo-root pytest temp locks."""

    root = Path(__file__).resolve().parents[1] / ".pytest_tmp_root"
    root.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(char if char.isalnum() else "-" for char in request.node.name)
    path = root / f"{safe_name}-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
