from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_repository_modules_path_imports_public_kavita_api() -> None:
    module_root = Path(__file__).resolve().parents[1]
    repository_root = module_root.parent.parent
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository_root / "modules")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import kavita; assert kavita.KavitaClient; assert kavita.__version__ == '0.1.0'",
        ],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
