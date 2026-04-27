from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional


def _is_writable_temp_root(path: Path) -> bool:
    probe_dir = path / f".write-probe-{uuid.uuid4().hex}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_dir.mkdir()
        probe_file = probe_dir / "probe.txt"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
        probe_dir.rmdir()
        return True
    except OSError:
        return False


def _select_pytest_tmp_root() -> Path:
    repo_root = Path(__file__).resolve().parent / ".pytest_tmp"
    fallback_root = Path(__file__).resolve().parent / ".pytest_tmp_runtime"
    if os.name != "nt" and _is_writable_temp_root(repo_root):
        return repo_root
    if _is_writable_temp_root(fallback_root):
        return fallback_root
    raise RuntimeError("No writable pytest temp root available")


_PYTEST_TMP_ROOT = _select_pytest_tmp_root()
os.environ["VDEDUP_PYTEST_TMP_ROOT"] = str(_PYTEST_TMP_ROOT)


def _make_temp_dir(prefix: str = "tmp", suffix: str = "", parent: Optional[Path] = None) -> Path:
    parent = parent or _PYTEST_TMP_ROOT
    parent.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        candidate = parent / f"{prefix}{uuid.uuid4().hex}{suffix}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not create unique temp directory under {parent}")


def _safe_mkdtemp(
    suffix: Optional[str] = None,
    prefix: Optional[str] = None,
    dir: Optional[os.PathLike[str]] = None,
) -> str:
    parent = Path(dir) if dir is not None else _PYTEST_TMP_ROOT
    return str(_make_temp_dir(prefix or "tmp", suffix or "", parent))


class _SafeTemporaryDirectory:
    def __init__(
        self,
        suffix: Optional[str] = None,
        prefix: Optional[str] = None,
        dir: Optional[os.PathLike[str]] = None,
        ignore_cleanup_errors: bool = False,
        *,
        delete: bool = True,
    ) -> None:
        self.name = _safe_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        self._ignore_cleanup_errors = ignore_cleanup_errors
        self._delete = delete

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if self._delete:
            shutil.rmtree(self.name, ignore_errors=self._ignore_cleanup_errors)


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
    tempfile.mkdtemp = _safe_mkdtemp
    tempfile.TemporaryDirectory = _SafeTemporaryDirectory


_configure_temp_environment()


def pytest_configure(config) -> None:  # pragma: no cover - exercised implicitly
    """
    Force pytest to place tmp_path/tmp_path_factory assets inside the repository.
    Some CI sandboxes block access to %LOCALAPPDATA%, so we override basetemp early.
    """
    base = _PYTEST_TMP_ROOT / "basetemp"
    base.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(base)
    # Ensure pytest rebuilds the factory with the new basetemp.
    if hasattr(config, "_tmp_path_factory"):
        delattr(config, "_tmp_path_factory")
