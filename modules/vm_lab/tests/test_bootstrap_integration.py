"""Phase 2 bootstrap, launcher generator, and unmanaged wrapper preservation tests."""

from __future__ import annotations

import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


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
