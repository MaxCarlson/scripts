"""Canonical imports must work even when repository modules/ precedes editable installs."""

from pathlib import Path
import subprocess
import sys


def test_modules_first_uses_same_canonical_classes():
    repo = Path(__file__).resolve().parents[3]
    script = "import sys; sys.path.insert(0, 'modules'); from benchmark_core import RunInfo; from benchmark_core.models import RunInfo as Direct; assert RunInfo is Direct; assert RunInfo.__module__ == 'benchmark_core.models'"
    result = subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
