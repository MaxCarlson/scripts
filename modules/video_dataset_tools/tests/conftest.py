import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True, scope="session")
def _override_tmpdir(tmp_path_factory):
    base = Path(__file__).parent / "_tmp"
    base.mkdir(parents=True, exist_ok=True)
    # Point Python and pytest temp dirs to a writable project-local path
    os.environ["TMPDIR"] = str(base)
    os.environ["TEMP"] = str(base)
    os.environ["TMP"] = str(base)
    tempfile.tempdir = str(base)
    return base
