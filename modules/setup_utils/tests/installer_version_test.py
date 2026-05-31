"""Tests for root setup.py installer metadata helpers."""

import importlib.util
import os
from itertools import count
from pathlib import Path
from unittest.mock import patch

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
    # mock psutil scan to avoid Windows access-violation crash on process_iter + open_files
    with patch.object(setup, "_find_likely_locking_processes", return_value=[]):
        diagnostic = setup._locked_console_script_diagnostic(log_path)
    assert any("locked console script" in line for line in diagnostic)


def test_console_script_lock_check_returns_false_when_not_locked(tmp_path):
    setup = _load_modules_setup()
    module_dir = tmp_path / "mymodule"
    module_dir.mkdir()
    (module_dir / "pyproject.toml").write_text(
        "[project]\nname = 'mymodule'\n[project.scripts]\nmyscript = 'mymodule.cli:main'\n",
        encoding="utf-8",
    )
    # No exe in venv/Scripts for this fake module — should return not-locked
    is_locked, path = setup._check_console_script_lock(module_dir)
    assert not is_locked
    assert path is None


def test_console_script_lock_check_detects_rename_failure(tmp_path, monkeypatch):
    import os

    setup = _load_modules_setup()
    module_dir = tmp_path / "mymodule"
    module_dir.mkdir()
    (module_dir / "pyproject.toml").write_text(
        "[project]\nname = 'mymodule'\n[project.scripts]\nmyscript = 'mymodule.cli:main'\n",
        encoding="utf-8",
    )
    # Fake venv scripts dir with a locked exe
    fake_scripts = tmp_path / "Scripts"
    fake_scripts.mkdir()
    fake_exe = fake_scripts / "myscript.exe"
    fake_exe.write_bytes(b"stub")

    # Make sys.executable point into our fake venv/Scripts
    fake_python = fake_scripts / "python.exe"
    fake_python.write_bytes(b"stub")
    monkeypatch.setattr(setup.sys, "executable", str(fake_python))

    # Simulate WinError 32 on rename by patching Path.rename
    original_rename = Path.rename

    def mock_rename(self, target):
        if self == fake_exe:
            err = OSError("locked")
            err.winerror = 32
            raise err
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", mock_rename)

    is_locked, locked_path = setup._check_console_script_lock(module_dir)
    assert is_locked
    assert locked_path == str(fake_exe)


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


def test_root_setup_stall_heuristic_defaults_are_less_aggressive():
    setup = _load_root_setup()

    assert setup.STALL_NOTICE_AFTER == 30
    assert setup.STALL_AUTO_CONFIRM_AFTER == 45


def test_compact_module_group_tracks_install_skip_and_failure(monkeypatch, capsys):
    setup = _load_root_setup()
    monkeypatch.setattr(setup, "_is_verbose", False)
    monkeypatch.setattr(setup, "_supports_color", lambda: False)

    with setup.CompactGroup("Python Modules", 3, modules=True) as group:
        group.observe_child_line("[OK] alpha: installed - editable")
        group.observe_child_line("[•] beta: already (editable) - skip")
        group.observe_child_line("[X] gamma: install failed - log")

    output = capsys.readouterr().out
    assert "1 installed" in output
    assert "1 skipped" in output
    assert "3 total" in output
    assert "gamma" in output


def test_compact_non_module_group_warn_is_not_terminal_failure(monkeypatch, capsys):
    setup = _load_root_setup()
    monkeypatch.setattr(setup, "_is_verbose", False)
    monkeypatch.setattr(setup, "_supports_color", lambda: False)

    with setup.CompactGroup("Core Modules", 1) as group:
        group.observe_status("cross_platform: MINOR version bump - reinstalling", "warn", None)
        group.observe_status("cross_platform: installed", "ok", "editable")

    output = capsys.readouterr().out
    assert "X 0/1 processed" not in output
    assert "1/1 processed" in output


def test_compact_group_uses_short_elapsed_prefix_and_summary_fields(monkeypatch, capsys):
    setup = _load_root_setup()
    monkeypatch.setattr(setup, "_is_verbose", False)
    monkeypatch.setattr(setup, "_supports_color", lambda: False)

    with setup.CompactGroup("Help Registry Drift Check", 1) as group:
        group.add_summary_field("modules 0/12 help updates")
        group.add_summary_field("scripts 1/34 help updates")

    output = capsys.readouterr().out
    assert "[total:" not in output
    assert "[group:" not in output
    assert "modules 0/12 help updates" in output
    assert "scripts 1/34 help updates" in output


def test_help_update_counts_include_registry_and_actionable_readme_drift():
    setup = _load_root_setup()
    drift = {
        "new": ["pyscripts/new.py"],
        "stale": [{"path": "modules/stale"}],
        "deleted": [],
        "readme": [
            {"path": "modules/readme", "issue": "version_mismatch"},
            {"path": "pyscripts/missing.py", "issue": "missing"},
        ],
    }
    registered = [
        {"path": "modules/stale"},
        {"path": "modules/readme"},
        {"path": "pyscripts/missing.py"},
    ]

    assert setup._help_update_counts(drift, registered) == (2, 2, 1, 2)


def test_root_setup_prunes_stale_editable_metadata(monkeypatch):
    tmp_path = _make_tmp_dir()
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    stale_dist = site_packages / "cross_platform-0.4.0.dist-info"
    current_dist = site_packages / "cross_platform-0.5.0.dist-info"
    stale_dist.mkdir()
    current_dist.mkdir()
    stale_pth = site_packages / "__editable__.cross_platform-0.4.0.pth"
    current_pth = site_packages / "__editable__.cross_platform-0.5.0.pth"
    stale_pth.write_text("", encoding="utf-8")
    current_pth.write_text("", encoding="utf-8")
    stale_finder = site_packages / "__editable___cross_platform_0_4_0_finder.py"
    current_finder = site_packages / "__editable___cross_platform_0_5_0_finder.py"
    stale_finder.write_text("", encoding="utf-8")
    current_finder.write_text("", encoding="utf-8")
    setup = _load_root_setup()
    monkeypatch.setattr(setup.sysconfig, "get_path", lambda key: str(site_packages))
    monkeypatch.setattr(setup, "_venv_site_packages_candidates", lambda: [])

    removed = setup._prune_stale_editable_metadata("cross_platform", "0.5.0", verbose=False)

    assert removed == 3
    assert not stale_dist.exists()
    assert current_dist.exists()
    assert not stale_pth.exists()
    assert current_pth.exists()
    assert not stale_finder.exists()
    assert current_finder.exists()


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
