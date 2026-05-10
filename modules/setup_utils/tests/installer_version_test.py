"""Tests for root setup.py installer metadata helpers."""

import importlib.util
import os
from itertools import count
from pathlib import Path

_TMP_COUNTER = count(1)


def _load_root_setup():
    setup_path = Path(__file__).resolve().parents[3] / "setup.py"
    spec = importlib.util.spec_from_file_location("root_setup_for_tests", setup_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_modules_setup():
    setup_path = Path(__file__).resolve().parents[3] / "modules" / "setup.py"
    spec = importlib.util.spec_from_file_location("modules_setup_for_tests", setup_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_pscripts_modules_setup():
    setup_path = Path(__file__).resolve().parents[3] / "pscripts" / "modules" / "setup.py"
    spec = importlib.util.spec_from_file_location("pscripts_modules_setup_for_tests", setup_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_tmp_dir() -> Path:
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp_root" / f"setup-utils-{os.getpid()}"
    root.mkdir(parents=True, exist_ok=True)
    while True:
        path = root / f"tmp_{next(_TMP_COUNTER):04d}"
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue


def test_source_metadata_falls_back_to_setup_py():
    tmp_path = _make_tmp_dir()
    module_dir = tmp_path / "legacy_module"
    module_dir.mkdir()
    (module_dir / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='legacy-module', version='1.2.3')\n",
        encoding="utf-8",
    )
    setup = _load_root_setup()

    assert setup._get_pkg_name_from_source(module_dir, verbose=False) == "legacy-module"
    assert setup._get_source_version(module_dir, verbose=False) == (1, 2, 3)


def test_source_version_prefers_pyproject_over_setup_py():
    tmp_path = _make_tmp_dir()
    module_dir = tmp_path / "mixed_module"
    module_dir.mkdir()
    (module_dir / "pyproject.toml").write_text(
        "[project]\nname = 'mixed-module'\nversion = '2.4.6+local'\n",
        encoding="utf-8",
    )
    (module_dir / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='old-name', version='1.0.0')\n",
        encoding="utf-8",
    )
    setup = _load_root_setup()

    assert setup._get_pkg_name_from_source(module_dir, verbose=False) == "mixed-module"
    assert setup._get_source_version(module_dir, verbose=False) == (2, 4, 6)


def test_modules_setup_version_falls_back_to_setup_py():
    tmp_path = _make_tmp_dir()
    module_dir = tmp_path / "legacy_module"
    module_dir.mkdir()
    (module_dir / "setup.py").write_text(
        "from setuptools import setup\nsetup(name='legacy-module', version='3.4.5')\n",
        encoding="utf-8",
    )
    setup = _load_modules_setup()

    assert setup._project_version_from_source(module_dir, verbose=False) == "3.4.5"


def test_locked_console_script_failure_is_classified():
    tmp_path = _make_tmp_dir()
    log_path = tmp_path / "aebndl_module-pip.log"
    locked = tmp_path / ".venv" / "Scripts" / "aebndl.exe"
    log_path.write_text(
        f"ERROR: [WinError 32] The process cannot access the file because it is being used by another process: '{locked}'\n",
        encoding="utf-8",
    )
    setup = _load_modules_setup()

    assert setup._extract_locked_console_script(log_path) == locked
    diagnostic = setup._locked_console_script_diagnostic(log_path)
    assert any("locked console script" in line for line in diagnostic)


def test_invalid_aebndl_leftovers_detected_but_not_deleted_by_default():
    tmp_path = _make_tmp_dir()
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    leftover = site_packages / "~ebndl.dist-info"
    leftover.mkdir()
    unrelated = site_packages / "normal.dist-info"
    unrelated.mkdir()
    setup = _load_root_setup()

    assert setup.find_invalid_aebndl_dist_leftovers(site_packages) == [leftover]
    assert leftover.exists()


def test_pscripts_duplicate_aebndl_skips_when_canonical_module_exists():
    tmp_path = _make_tmp_dir()
    scripts_dir = tmp_path / "scripts"
    old_project = scripts_dir / "pscripts" / "modules" / "aebn-vod-downloader-custom"
    canonical = scripts_dir / "modules" / "aebndl_module"
    old_project.mkdir(parents=True)
    canonical.mkdir(parents=True)
    (old_project / "setup.py").write_text("from setuptools import setup\nsetup(name='aebndl')\n", encoding="utf-8")
    (canonical / "setup.py").write_text("from setuptools import setup\nsetup(name='aebndl')\n", encoding="utf-8")
    setup = _load_pscripts_modules_setup()

    should_skip, reason = setup._should_skip_duplicate_project(old_project, scripts_dir)

    assert should_skip is True
    assert "canonical" in reason
