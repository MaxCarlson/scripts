"""Pytest configuration for aebndl tests."""

from __future__ import annotations

import os
import sys
import tempfile
from itertools import count
from pathlib import Path


_MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODULE_ROOT))

_TEMP_ROOT = _MODULE_ROOT / ".pytest_tmp_root" / f"aebndl-temp-{os.getpid()}"
_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
_TMP_COUNTER = count(1)

os.environ["TMP"] = str(_TEMP_ROOT)
os.environ["TEMP"] = str(_TEMP_ROOT)
os.environ["PYTEST_DEBUG_TEMPROOT"] = str(_TEMP_ROOT)
tempfile.tempdir = str(_TEMP_ROOT)


def _make_temp_dir(prefix: str = "tmp") -> Path:
    _TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    clean_prefix = prefix.rstrip("_") or "tmp"
    while True:
        path = _TEMP_ROOT / f"{clean_prefix}_{next(_TMP_COUNTER):04d}"
        try:
            path.mkdir(parents=True, exist_ok=False)
            return path
        except FileExistsError:
            continue


def _module_mkdtemp(suffix: str | None = None, prefix: str | None = None, dir: str | os.PathLike[str] | None = None) -> str:
    root = Path(dir) if dir is not None else _TEMP_ROOT
    root.mkdir(parents=True, exist_ok=True)
    clean_prefix = (prefix or "tmp").rstrip("_") or "tmp"
    clean_suffix = suffix or ""
    while True:
        path = root / f"{clean_prefix}_{next(_TMP_COUNTER):04d}{clean_suffix}"
        try:
            path.mkdir(parents=True, exist_ok=False)
            return str(path)
        except FileExistsError:
            continue


class _ModuleTemporaryDirectory:
    def __init__(self, suffix: str | None = None, prefix: str | None = None, dir: str | os.PathLike[str] | None = None):
        self.name = _module_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)

    def __enter__(self):
        return self.name

    def __exit__(self, exc_type, exc, tb):
        return False

    def cleanup(self):
        return None


tempfile.mkdtemp = _module_mkdtemp
tempfile.TemporaryDirectory = _ModuleTemporaryDirectory
