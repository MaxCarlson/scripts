"""Phase 2 & Final Validation bootstrap, legacy launcher migration, and Windows resolution tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]
MODULE_ROOT = WORKTREE_ROOT / "modules" / "vm_lab"


def test_launcher_generator_discovers_vm_and_vm_lab_via_pyproject() -> None:
    if str(WORKTREE_ROOT) not in sys.path:
        sys.path.insert(0, str(WORKTREE_ROOT))
    from scripts_setup.launcher_generator import scan_repository_programs

    commands = scan_repository_programs(WORKTREE_ROOT)
    assert "vm" in commands
    assert "vm-lab" in commands
    assert commands["vm"].kind == "console_script"
    assert commands["vm-lab"].kind == "console_script"
    assert commands["vm"].entry_point == "vm_lab.cli:main"
    assert commands["vm-lab"].entry_point == "vm_lab.cli:main"


def test_classify_vm_launcher_covers_all_four_classes(tmp_path: Path) -> None:
    if str(WORKTREE_ROOT) not in sys.path:
        sys.path.insert(0, str(WORKTREE_ROOT))
    from scripts_setup.launcher_generator import (
        MANAGED_SIGNATURE_WINDOWS,
        classify_vm_launcher,
    )

    missing = tmp_path / "missing.cmd"
    assert classify_vm_launcher(missing) == "missing"

    managed = tmp_path / "managed.cmd"
    managed.write_text(f"{MANAGED_SIGNATURE_WINDOWS}\r\n@echo off\r\n", encoding="utf-8")
    assert classify_vm_launcher(managed) == "managed_current"

    legacy = tmp_path / "legacy.cmd"
    legacy.write_text(
        '@echo off\npwsh -NoProfile -File "C:\\src\\scripts\\modules\\vm_lab\\Invoke-VmLab.ps1" %*\nexit /b %ERRORLEVEL%\n',
        encoding="utf-8",
    )
    assert classify_vm_launcher(legacy) == "legacy_vm_lab_powershell"

    unmanaged = tmp_path / "unmanaged.cmd"
    unmanaged.write_text("@echo off\necho custom user vm tool\n", encoding="utf-8")
    assert classify_vm_launcher(unmanaged) == "unmanaged"

    ambiguous = tmp_path / "ambiguous.cmd"
    ambiguous.write_text(
        '@echo off\necho custom\npwsh -File "Invoke-VmLab.ps1" %*\n',
        encoding="utf-8",
    )
    assert classify_vm_launcher(ambiguous) == "ambiguous"


def test_unmanaged_wrapper_is_preserved(tmp_path: Path) -> None:
    if str(WORKTREE_ROOT) not in sys.path:
        sys.path.insert(0, str(WORKTREE_ROOT))
    from scripts_setup.launcher_generator import is_managed_wrapper, write_wrapper

    custom_cmd = tmp_path / "vm.cmd"
    custom_cmd.write_text("@echo off\necho custom user wrapper\n", encoding="utf-8")
    assert is_managed_wrapper(custom_cmd) is False
    changed = write_wrapper(custom_cmd, "vm", is_windows=True, overwrite_unmanaged=False)
    assert changed is False
    assert "custom user wrapper" in custom_cmd.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows .cmd and pwsh launcher resolution test")
def test_disposable_bootstrap_migration_and_real_windows_cli_resolution(tmp_path: Path) -> None:
    if str(WORKTREE_ROOT) not in sys.path:
        sys.path.insert(0, str(WORKTREE_ROOT))
    import bootstrap_latest
    from scripts_setup.launcher_generator import (
        MANAGED_SIGNATURE_WINDOWS,
        classify_vm_launcher,
        generate_manifest,
    )

    # 1. Create disposable repo-like root with isolated venv + bin + scripts_setup + script_logging + vm_lab
    disp_root = tmp_path / "disp_repo"
    (disp_root / "modules").mkdir(parents=True)
    shutil.copytree(WORKTREE_ROOT / "scripts_setup", disp_root / "scripts_setup")
    shutil.copytree(WORKTREE_ROOT / "modules" / "script_logging", disp_root / "modules" / "script_logging")
    shutil.copytree(
        MODULE_ROOT,
        disp_root / "modules" / "vm_lab",
        ignore=shutil.ignore_patterns(".pytest_tmp_root", "__pycache__", "*.pyc"),
    )

    venv_dir = disp_root / ".venv"
    venv.create(venv_dir, with_pip=True)
    venv_py = venv_dir / "Scripts" / "python.exe"

    # Build vm_lab wheel using host toolchain (no network) and install into disposable venv
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    wb = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(disp_root / "modules" / "vm_lab"), "--no-deps", "-w", str(wheel_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert wb.returncode == 0, f"Wheel build failed for vm_lab: {wb.stderr}"

    wheels = [str(w) for w in sorted(wheel_dir.glob("*.whl"))]
    inst = subprocess.run(
        [str(venv_py), "-m", "pip", "install", "--no-deps", "--no-index", *wheels],
        capture_output=True,
        text=True,
        check=False,
    )
    assert inst.returncode == 0, f"Disposable venv wheel install failed: {inst.stderr}"
    (venv_dir / "Lib" / "site-packages" / "disp_script_logging.pth").write_text(
        "\n".join(
            [
                str(disp_root / "modules" / "script_logging" / "src"),
                str(disp_root / "modules" / "script_logging"),
                str(WORKTREE_ROOT / "modules" / "cross_platform" / "src"),
                str(WORKTREE_ROOT / "modules" / "cross_platform"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    bin_dir = disp_root / "bin"
    bin_dir.mkdir()

    # 2. Seed legacy vm.cmd & vm-lab.cmd PowerShell wrappers and verify migration
    legacy_vm = bin_dir / "vm.cmd"
    legacy_vmlab = bin_dir / "vm-lab.cmd"
    for p in (legacy_vm, legacy_vmlab):
        p.write_text(
            f'@echo off\npwsh -NoProfile -File "{disp_root}\\modules\\vm_lab\\Invoke-VmLab.ps1" %*\nexit /b %ERRORLEVEL%\n',
            encoding="utf-8",
        )
        assert classify_vm_launcher(p) == "legacy_vm_lab_powershell"

    for name, target_path in (("vm", legacy_vm), ("vm-lab", legacy_vmlab)):
        assert classify_vm_launcher(target_path) == "legacy_vm_lab_powershell"
        bootstrap_latest.write_console_proxy(target_path, name, True, venv_dir, overwrite_legacy=True)
        assert classify_vm_launcher(target_path) == "managed_current"
        assert MANAGED_SIGNATURE_WINDOWS in target_path.read_text(encoding="utf-8")

    # 3. Generate scripts_manifest.json and verify both entries
    generate_manifest(disp_root)
    manifest = json.loads((disp_root / "scripts_manifest.json").read_text(encoding="utf-8"))
    assert "vm" in manifest["commands"]
    assert "vm-lab" in manifest["commands"]

    # 4. Verify unmanaged wrapper is NOT migrated
    custom_vm = tmp_path / "custom_bin" / "vm.cmd"
    custom_vm.parent.mkdir()
    custom_vm.write_text("@echo off\necho do not touch\n", encoding="utf-8")
    assert classify_vm_launcher(custom_vm) == "unmanaged"

    # 5. Verify pwsh Get-Command precedence and actual CLI execution via bin\vm.cmd & bin\vm-lab.cmd
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PATH"] = f"{bin_dir};{env.get('PATH', '')}"
    pwsh = shutil.which("pwsh")
    assert pwsh is not None

    cmd_check = subprocess.run(
        [pwsh, "-NoProfile", "-Command", "(Get-Command vm -All | Select-Object -First 1).Source; (Get-Command vm-lab -All | Select-Object -First 1).Source"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert cmd_check.returncode == 0
    resolved_lines = [ln.strip() for ln in cmd_check.stdout.splitlines() if ln.strip()]
    assert str(legacy_vm).lower() == resolved_lines[0].lower()
    assert str(legacy_vmlab).lower() == resolved_lines[1].lower()

    example_wf = disp_root / "modules" / "vm_lab" / "examples" / "h4-like-acceptance.workflow.json"
    for cli_cmd in (
        ["vm", "-h"],
        ["vm-lab", "-h"],
        ["vm", "version", "--json"],
        ["vm-lab", "version", "--json"],
        ["vm", "templates", "-j"],
        ["vm", "workflow", "validate", str(example_wf), "-j"],
    ):
        res = subprocess.run(
            [pwsh, "-NoProfile", "-Command", subprocess.list2cmdline(cli_cmd)],
            env=env,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"Command {cli_cmd} failed ({res.returncode}): {res.stderr}\n{res.stdout}"
