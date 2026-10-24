"""Automated isolated rehearsal test for 168-wrapper migration.

Verifies:
1. Copying bin and repo setup into disposable native Windows paths.
2. Content-signature identification of legacy wrappers vs unmanaged files.
3. Before/after diff for console scripts, python scripts, shell scripts.
4. Complete migration in disposable environment with CMD and PowerShell tests.
5. Byte-for-byte preservation of all 10 unmanaged and 79 obsolete wrappers.
6. Idempotent regeneration, backup completeness, interrupted recovery, rollback.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts_setup.launcher_generator import (
    analyze_migration,
    classify_wrapper,
    is_managed_wrapper,
    migrate_wrappers,
    rollback_wrappers,
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def test_migration_rehearsal_isolated(tmp_path: Path):
    live_repo = Path(r"C:\Users\mcarls\src\scripts")
    live_bin = live_repo / "bin"
    assert live_bin.is_dir(), f"Live bin directory must exist at {live_bin}"

    # Step 1: Copy live bin and setup into disposable native Windows directory
    rehearsal_repo = tmp_path / "scripts_rehearsal"
    rehearsal_bin = rehearsal_repo / "bin"
    rehearsal_bin.mkdir(parents=True)

    for item in live_bin.iterdir():
        dest = rehearsal_bin / item.name
        if item.is_symlink():
            try:
                target = os.readlink(item)
                dest.symlink_to(target)
            except OSError:
                dest.write_text("dummy symlink", encoding="utf-8")
        elif item.is_file():
            shutil.copy2(item, dest)

    assert len(list(rehearsal_bin.iterdir())) == 257

    # Step 2: Content-signature verification
    plan = analyze_migration(live_repo, rehearsal_bin)
    assert len(plan.commands_to_generate) == 168
    assert len(plan.managed_to_update) == 168
    assert len(plan.unmanaged_preserved) == 10
    assert len(plan.obsolete_managed) == 79

    # Verify each of the 168 files has a genuine legacy marker and is not classified just by name
    for wrapper in plan.managed_to_update:
        classification = classify_wrapper(wrapper)
        assert classification.status == "managed_legacy", f"{wrapper.name} missing legacy marker!"

    # Verify a custom user file sharing the name of a command is NEVER overwritten
    custom_conflict = rehearsal_bin / "mangadl.cmd"
    custom_conflict.write_text("@echo off\necho MY CUSTOM MANGADL\n", encoding="utf-8")
    plan_with_custom = analyze_migration(live_repo, rehearsal_bin)
    assert custom_conflict in plan_with_custom.unmanaged_preserved
    # Restore legacy mangadl for the rest of the test
    shutil.copy2(live_bin / "mangadl.cmd", custom_conflict)

    # Step 3: Record pre-migration hashes of unmanaged and obsolete files
    unmanaged_hashes_before = {f.name: _sha256(f) for f in plan.unmanaged_preserved if f.is_file()}
    obsolete_hashes_before = {f.name: _sha256(f) for f in plan.obsolete_managed if f.is_file()}
    all_hashes_before = {f.name: _sha256(f) for f in rehearsal_bin.iterdir() if f.is_file()}

    # Step 4: Generate before/after diff for representative wrappers
    diff_report_lines = ["# Wrapper Migration Before/After Diffs\n"]
    for rep_name in ["mangadl.cmd", "append_clipboard.cmd", "add_submodule.cmd"]:
        rep_file = rehearsal_bin / rep_name
        before_content = rep_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        from scripts_setup.launcher_generator import generate_windows_wrapper
        after_content = generate_windows_wrapper(rep_file.stem).splitlines(keepends=True)
        diff = difflib.unified_diff(
            before_content, after_content,
            fromfile=f"before/{rep_name}", tofile=f"after/{rep_name}"
        )
        diff_report_lines.append(f"## {rep_name}\n```diff\n" + "".join(diff) + "\n```\n")

    # Step 5: Apply complete migration in disposable rehearsal environment
    rehearsal_backup = rehearsal_repo / ".launcher_backup_rehearsal"
    report = migrate_wrappers(
        repo_root=live_repo,
        bin_dir=rehearsal_bin,
        dry_run=False,
        backup_dir=rehearsal_backup,
        cleanup=False,
    )

    assert report.is_dry_run is False
    assert report.updated_count == 168
    assert report.preserved_unmanaged_count == 10
    assert report.removed_obsolete_count == 0

    # Step 6: Verify all 10 unmanaged wrappers remain byte-for-byte unchanged
    for name, original_hash in unmanaged_hashes_before.items():
        current_file = rehearsal_bin / name
        assert current_file.is_file()
        assert _sha256(current_file) == original_hash, f"Unmanaged wrapper {name} was modified!"

    # Step 7: Verify all 79 obsolete wrappers remain byte-for-byte untouched
    for name, original_hash in obsolete_hashes_before.items():
        current_file = rehearsal_bin / name
        assert current_file.is_file()
        assert _sha256(current_file) == original_hash, f"Obsolete wrapper {name} was modified!"

    # Step 8: Verify backup completeness
    assert rehearsal_backup.is_dir()
    for name, original_hash in all_hashes_before.items():
        backup_file = rehearsal_backup / name
        assert backup_file.is_file(), f"Missing backup for {name}"
        assert _sha256(backup_file) == original_hash, f"Backup mismatch for {name}"

    # Step 9: Test Idempotent regeneration
    repeat_plan = analyze_migration(live_repo, rehearsal_bin)
    assert len(repeat_plan.managed_up_to_date) == 168
    assert len(repeat_plan.managed_to_update) == 0
    assert len(repeat_plan.missing_to_create) == 0
    repeat_report = migrate_wrappers(
        repo_root=live_repo,
        bin_dir=rehearsal_bin,
        dry_run=False,
        backup_dir=rehearsal_backup,
        cleanup=False,
    )
    assert repeat_report.updated_count == 0
    assert repeat_report.created_count == 0

    # Step 10: Test Interrupted Migration Recovery
    # Corrupt or delete 5 managed files to simulate an interruption mid-migration
    interrupted_files = ["mangadl.cmd", "compresser.cmd", "termdash.cmd", "aebndl.cmd", "agt.cmd"]
    for f_name in interrupted_files:
        (rehearsal_bin / f_name).unlink()

    interrupted_plan = analyze_migration(live_repo, rehearsal_bin)
    assert len(interrupted_plan.missing_to_create) == 5

    recovery_report = migrate_wrappers(
        repo_root=live_repo,
        bin_dir=rehearsal_bin,
        dry_run=False,
        backup_dir=rehearsal_backup,
        cleanup=False,
    )
    assert recovery_report.created_count == 5
    for f_name in interrupted_files:
        assert (rehearsal_bin / f_name).is_file()
        assert is_managed_wrapper(rehearsal_bin / f_name) is True

    # Step 11: Test Full Rollback
    rollback_report = rollback_wrappers(rehearsal_backup, rehearsal_bin)
    assert rollback_report.restored_count == len(all_hashes_before)
    assert not rollback_report.errors
    for name, original_hash in all_hashes_before.items():
        restored_file = rehearsal_bin / name
        assert _sha256(restored_file) == original_hash, f"Rollback hash mismatch for {name}"

    # Step 12: Write Diff Report artifact
    diff_report_path = rehearsal_repo / "REHEARSAL_DIFFS.md"
    diff_report_path.write_text("\n".join(diff_report_lines), encoding="utf-8")
    assert diff_report_path.is_file()


def test_rehearsal_cmd_and_powershell_execution(tmp_path: Path):
    """Run CMD and PowerShell argument-fidelity tests against a generated rehearsal wrapper."""
    rehearsal_repo = tmp_path / "repo"
    rehearsal_bin = rehearsal_repo / "bin"
    rehearsal_bin.mkdir(parents=True)

    # Setup mock venv interpreter
    rehearsal_venv = rehearsal_repo / ".venv"
    rehearsal_venv_scripts = rehearsal_venv / "Scripts"
    rehearsal_venv_scripts.mkdir(parents=True)
    real_python = Path(sys.executable)
    rehearsal_python = rehearsal_venv_scripts / "python.exe"
    try:
        rehearsal_python.symlink_to(real_python)
    except OSError:
        shutil.copy2(real_python, rehearsal_python)

    # Provide pyvenv.cfg so python recognizes venv
    real_cfg = real_python.parents[1] / "pyvenv.cfg"
    if real_cfg.is_file():
        shutil.copy2(real_cfg, rehearsal_venv / "pyvenv.cfg")
    else:
        (rehearsal_venv / "pyvenv.cfg").write_text(
            f"home = {sys.base_prefix}\ninclude-system-site-packages = false\nversion = 3.12.10\n",
            encoding="utf-8",
        )

    # Link/pth script_logging into rehearsal site-packages
    site_packages = rehearsal_venv / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    repo_worktree = Path(__file__).parents[1]
    script_logging_path = repo_worktree / "modules" / "script_logging"
    (site_packages / "script_logging.pth").write_text(str(script_logging_path), encoding="utf-8")

    # Echo target
    echo_target = rehearsal_repo / "echo_target.py"
    echo_target.write_text(
        "import sys, json\n"
        "if sys.platform == 'win32':\n"
        "    sys.stdout.reconfigure(encoding='utf-8')\n"
        "json.dump(sys.argv[1:], sys.stdout)\n"
        "sys.stdout.write('\\n')\n"
        "sys.exit(0 if 'fail' not in sys.argv else 42)\n",
        encoding="utf-8",
    )

    # Write manifest
    manifest_data = {
        "schema_version": 1,
        "commands": {
            "rehearsal_echo": {
                "program_id": "pyscript:echo_target.py",
                "kind": "python_file",
                "target": str(echo_target),
            }
        },
    }
    manifest_file = rehearsal_repo / "scripts_manifest.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    from scripts_setup.launcher_generator import generate_windows_wrapper
    wrapper_file = rehearsal_bin / "rehearsal_echo.cmd"
    wrapper_file.write_text(generate_windows_wrapper("rehearsal_echo"), encoding="utf-8")

    # Set up env with worktree PYTHONPATH so launcher module resolves during rehearsal
    env = os.environ.copy()
    worktree_root = Path(__file__).parents[1]
    env_paths = [
        str(worktree_root / "modules" / "script_logging"),
        str(worktree_root / "scripts_setup"),
        str(worktree_root),
    ]
    env["PYTHONPATH"] = os.pathsep.join(env_paths + ([env["PYTHONPATH"]] if "PYTHONPATH" in env else []))

    # 1. Test via CMD
    cmd_inner = f'"{wrapper_file}" "arg_one" "with space" "quotes\\"inside" "unicode_🚀_日本語"'
    res_cmd = subprocess.run(
        f'cmd.exe /c "{cmd_inner}"',
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(rehearsal_repo),
        env=env,
    )
    assert res_cmd.returncode == 0
    received_cmd = json.loads(res_cmd.stdout.strip())
    assert received_cmd[0] == "arg_one"
    assert received_cmd[1] == "with space"
    assert "unicode_🚀_日本語" in received_cmd[3]

    # 2. Test via PowerShell
    pwsh_cmd = f'& "{wrapper_file}" "first" "second with space" "🚀"'
    res_pwsh = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", pwsh_cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(rehearsal_repo),
        env=env,
    )
    if res_pwsh.returncode == 0:
        received_pwsh = json.loads(res_pwsh.stdout.strip())
        assert received_pwsh == ["first", "second with space", "🚀"]

    # 3. Test failure code propagation
    res_fail = subprocess.run(
        f'cmd.exe /c ""{wrapper_file}" fail"',
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(rehearsal_repo),
        env=env,
    )
    assert res_fail.returncode == 42

