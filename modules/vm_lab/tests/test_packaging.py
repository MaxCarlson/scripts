"""Phase 1 packaging, resource discovery, and console-script tests for vm_lab."""

from __future__ import annotations

import subprocess
import sys
import tomllib
import venv
import zipfile
from pathlib import Path

import pytest

MODULE_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_defines_both_console_scripts() -> None:
    pyproject = MODULE_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["vm"] == "vm_lab.cli:main"
    assert scripts["vm-lab"] == "vm_lab.cli:main"


def test_backend_resource_resolution_from_source() -> None:
    from vm_lab.backend import resolve_backend_root

    root = resolve_backend_root()
    assert (root / "Invoke-VmLab.ps1").is_file()
    assert (root / "vm_lab.psd1").is_file()
    assert (root / "templates" / "windows11-dev.json").is_file()


def test_wheel_build_and_isolated_install_with_spaces(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist out"
    dist_dir.mkdir(parents=True)

    build_res = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(MODULE_ROOT), "--no-deps", "-w", str(dist_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if build_res.returncode != 0:
        pytest.skip(f"pip wheel unavailable in current environment: {build_res.stderr}")

    wheels = list(dist_dir.glob("vm_lab-*.whl"))
    assert len(wheels) == 1
    wheel_path = wheels[0]

    with zipfile.ZipFile(wheel_path) as zf:
        names = set(zf.namelist())
    assert "vm_lab/Invoke-VmLab.ps1" in names
    assert "vm_lab/Invoke-VmLabApprovedPlan.ps1" in names
    assert "vm_lab/vm_lab.psd1" in names
    assert "vm_lab/vm_lab.psm1" in names
    assert "vm_lab/src/Contracts.ps1" in names
    assert "vm_lab/templates/windows11-dev.json" in names
    assert "vm_lab/examples/h4-like-acceptance.workflow.json" in names

    venv_dir = tmp_path / "venv with spaces"
    venv.create(venv_dir, with_pip=True)
    venv_py = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    inst_res = subprocess.run(
        [str(venv_py), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert inst_res.returncode == 0, f"wheel install failed: {inst_res.stderr}"

    scripts_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
    vm_exe = scripts_dir / ("vm.exe" if sys.platform == "win32" else "vm")
    vm_lab_exe = scripts_dir / ("vm-lab.exe" if sys.platform == "win32" else "vm-lab")
    assert vm_exe.is_file()
    assert vm_lab_exe.is_file()

    unrelated_cwd = tmp_path / "unrelated cwd"
    unrelated_cwd.mkdir()

    for exe in (vm_exe, vm_lab_exe):
        r_help = subprocess.run([str(exe), "--help"], cwd=str(unrelated_cwd), capture_output=True, text=True, check=False)
        assert r_help.returncode == 0
        assert "vm" in r_help.stdout

        r_h = subprocess.run([str(exe), "-h"], cwd=str(unrelated_cwd), capture_output=True, text=True, check=False)
        assert r_h.returncode == 0

        r_ver = subprocess.run([str(exe), "version", "--json"], cwd=str(unrelated_cwd), capture_output=True, text=True, check=False)
        assert r_ver.returncode == 0
        assert '"package": "vm_lab"' in r_ver.stdout
        assert str(MODULE_ROOT) not in r_ver.stdout
