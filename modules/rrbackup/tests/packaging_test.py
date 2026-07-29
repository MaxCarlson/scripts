from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_modules_path_import_resolves_regular_package_and_cli(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    modules_root = repo_root / "modules"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(modules_root)

    script = (
        "import rrbackup; "
        "from rrbackup import __version__; "
        "from rrbackup.cli import build_parser; "
        "assert rrbackup.__file__; "
        "assert __version__ == '0.3.0'; "
        "assert build_parser().prog == 'rrb'; "
        "print(rrbackup.__file__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "modules" in result.stdout.lower()
    assert "rrbackup" in result.stdout.lower()
