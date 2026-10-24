from __future__ import annotations

import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

# Ensure worktree's runmux and resource_metrics take precedence over any editable install in virtualenv
WORKTREE_ROOT = Path(__file__).resolve().parents[3]
RUNMUX_SRC = WORKTREE_ROOT / "modules" / "runmux" / "src"
RESOURCE_METRICS_ROOT = WORKTREE_ROOT / "modules" / "resource_metrics"

sys.meta_path = [
    finder
    for finder in sys.meta_path
    if "resource_metrics" not in str(finder)
    and "resource_metrics" not in getattr(finder, "__module__", "")
    and "runmux" not in str(finder)
    and "runmux" not in getattr(finder, "__module__", "")
]
for target_dir in (str(RUNMUX_SRC), str(RESOURCE_METRICS_ROOT)):
    if target_dir not in sys.path:
        sys.path.insert(0, target_dir)

for mod_name in list(sys.modules):
    if mod_name in {"runmux", "resource_metrics"} or mod_name.startswith(("runmux.", "resource_metrics.")):
        del sys.modules[mod_name]


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
