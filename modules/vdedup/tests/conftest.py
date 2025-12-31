from __future__ import annotations

import os
import tempfile
from pathlib import Path


_PYTEST_TMP_ROOT = Path(__file__).resolve().parent / ".pytest_tmp"
_PYTEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _configure_temp_environment() -> None:
    """
    Ensure pytest writes all temporary files inside the repository so Windows ACLs
    never block tmp_path/tmp_path_factory.
    """
    temp_dir = str(_PYTEST_TMP_ROOT)
    os.environ["TMP"] = temp_dir
    os.environ["TEMP"] = temp_dir
    os.environ["TMPDIR"] = temp_dir
    tempfile.tempdir = temp_dir


_configure_temp_environment()
