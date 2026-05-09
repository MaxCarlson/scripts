from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture()
def work_tmp() -> Iterator[Path]:
    """Workspace-local temp directory that avoids broken Windows pytest temp roots."""
    root = Path(__file__).resolve().parent / ".work_tmp"
    root.mkdir(exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
