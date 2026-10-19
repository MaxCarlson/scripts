import shutil
import uuid
from pathlib import Path

import pytest

MODULE_ROOT = Path(__file__).resolve().parents[1]
PYTEST_TMP_ROOT = MODULE_ROOT / ".pytest_tmp_root"


@pytest.fixture()
def tmp_path():
    PYTEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    unique_dir = PYTEST_TMP_ROOT / f"test_{uuid.uuid4().hex}"
    unique_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield unique_dir
    finally:
        shutil.rmtree(unique_dir, ignore_errors=True)
