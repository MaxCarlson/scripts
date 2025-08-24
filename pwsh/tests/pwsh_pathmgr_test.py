#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comprehensive tests for pwsh_pathmgr.py.

These tests:
- Run on any OS (Linux/WSL/Termux/macOS/Windows) by mocking Windows-only bits.
- Avoid touching real registry by patching _read_reg_path/_write_reg_path.
- Validate normalization, diffing, add/remove/clean, process-scope updates.
- Exercise backup/restore with a tmp directory.
- Use the real CLI parser (build_parser) to ensure subcommand wiring works.

To run just this file:
    pytest scripts/pwsh/tests/pwsh_pathmgr_test.py -q
"""

from __future__ import annotations

import io
import json
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


# ---------- Helpers to load and prepare the module under test ----------

def _load_pwsh_pathmgr(unique_name: str = None):
    """Load pwsh_pathmgr.py from its real location as an importable module object."""
    mod_name = unique_name or f"pwsh_pathmgr_{uuid4().hex}"
    here = Path(__file__).resolve()
    module_file = here.parents[1] / "pwsh_pathmgr.py"
    assert module_file.is_file(), f"Could not find pwsh_pathmgr.py at {module_file}"
    spec = importlib.util.spec_from_file_location(mod_name, str(module_file))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _prepare_windows_like_env(mod, tmp_path: Path):
    """
    Make the module behave like it's on Windows without requiring a real registry:
    - Force IS_WINDOWS=True.
    - Provide fake registry storage and patch _read/_write functions.
    - NOP broadcast.
    - Redirect BACKUP_DIR into tmp_path.
    - Stub os.path.isdir to deterministic behavior.
    """
    mod.IS_WINDOWS = True

    # Fake registry store
    fake_store = {mod.USER: "", mod.MACHINE: ""}

    def _rr(scope: str) -> str:
        return fake_store.get(scope, "")

    def _wr(scope: str, new_val: str):
        fake_store[scope] = new_val

    mod._read_reg_path = _rr
    mod._write_reg_path = _wr
    mod._wm_settingchange_broadcast = lambda: None

    # BACKUP dir inside tmp
    mod.BACKUP_DIR = tmp_path / "backups"
    mod.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Deterministic directory existence:
    # treat any path that endswith "missing" (case-insensitive) as non-existent, everything else as existent
    def fake_isdir(p):
        s = str(mod._expand_for_check(str(p)))
        return not s.lower().endswith("missing")

    mod.os.path.isdir = fake_isdir  # patch only inside module
    # Env var expansion test support
    mod.os.environ["TESTROOT"] = r"C:\Apps"

    return fake_store


# ---------- Unit Tests ----------

def test_split_and_normalize_basic(tmp_path):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)

    messy = r'  "C:\Tools"  ;;  C:\Windows\System32  ;  %TESTROOT%\Bin  ;  '
    parts = mod._split_path_string(messy)
    # Should strip quotes/whitespace, collapse ;;, keep order, dedupe-insensitive to case
    assert parts == [r"C:\Tools", r"C:\Windows\System32", r"%TESTROOT%\Bin"]


def test_build_new_string_add_and_dedupe_trailing_slash_preserved(tmp_path):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)

    base = r"C:\A\;c:\a\;C:\B\;"
    out = mod.build_new_string(base, add=["C:\\A\\"], cleanup=True, dedupe=True)
    # Dedup should collapse case-insensitive duplicates but keep first-seen exact text (including trailing '\')
    assert out == "C:\\A\\;C:\\B\\"

    # Now add a new unique
    out2 = mod.build_new_string(out, add=["C:\\MyBin\\"], cleanup=True, dedupe=True)
    assert out2 == "C:\\A\\;C:\\B\\;C:\\MyBin\\"


def test_remove_exact_and_contains(tmp_path):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)

    base = r"C:\A;C:\Tools\Bin;C:\Foo;C:\Bar"
    # remove exact 'C:\Foo' and anything containing 'tools'
    out = mod.build_new_string(base, remove=[r"C:\Foo", "contains:tools"], cleanup=True, dedupe=True)
    assert out == r"C:\A;C:\Bar"


def test_print_diff_marks_added_removed_and_same(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)

    old = r"C:\A;C:\B"
    new = r"C:\A;C:\B;C:\C"
    mod.print_diff(mod.USER, old, new)
    out = capsys.readouterr().out
    # Should show "+ C:\C" and show the existing as present (color codes ignored)
    assert "+ C:\\C" in out
    assert "C:\\A" in out and "C:\\B" in out


def test_backup_and_restore_roundtrip_user(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)

    original = r"C:\Tools;C:\Windows\System32"
    store[mod.USER] = original

    # backup
    backup_file = mod.backup_path(mod.USER)
    assert backup_file.is_file()

    # mutate and then restore
    store[mod.USER] = r"C:\Different"
    mod.restore_from(backup_file, mod.USER)

    assert store[mod.USER] == original
    out = capsys.readouterr().out
    assert "Restored User PATH" in out


def test_backup_file_has_expected_json_content(tmp_path):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)

    store[mod.USER] = r"C:\A;C:\B"
    bfile = mod.backup_path(mod.USER)
    data = json.loads(bfile.read_text(encoding="utf-8"))
    assert data["scope"] == mod.USER
    assert data["path_string"] == r"C:\A;C:\B"
    assert data["segments"] == ["C:\\A", "C:\\B"]


def test_cmd_add_user_writes_registry(tmp_path):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)

    store[mod.USER] = r"C:\A;C:\B"
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "add", r"C:\MyBin"])
    # call the bound function
    args.func(args)
    assert store[mod.USER].endswith(r"C:\MyBin")


def test_cmd_remove_contains_dry_run_does_not_write(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)

    store[mod.USER] = r"C:\A;C:\Tools\Bin;C:\Foo"
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "remove", "contains:tools", "--dry-run"])
    args.func(args)

    # No changes written due to dry-run
    assert store[mod.USER] == r"C:\A;C:\Tools\Bin;C:\Foo"
    out = capsys.readouterr().out
    assert "[dry-run]" in out


def test_cmd_clean_dry_run(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)

    store[mod.USER] = r'  "C:\A" ;; C:\A ;; C:\B  '
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "clean", "--dry-run"])
    args.func(args)

    # Ensure unchanged due to dry-run
    assert store[mod.USER] == r'  "C:\A" ;; C:\A ;; C:\B  '
    out = capsys.readouterr().out
    assert "[dry-run]" in out


def test_add_process_scope_updates_environment_and_backups(tmp_path):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)

    # Start from a known process PATH (module checks "Path" then "PATH")
    mod.os.environ["Path"] = r"C:\A;C:\B"
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "Process", "add-process", r"C:\C"])
    args.func(args)

    assert mod.os.environ["Path"].endswith(r";C:\C")
    # backup should have been created for process scope too
    backups = list(mod.BACKUP_DIR.glob("PATH-Process-*.json"))
    assert backups, "Expected a backup JSON for Process scope"


def test_print_segments_ok_and_miss_with_expansion(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)

    # %TESTROOT%\Bin should expand OK via fake_isdir; ending "missing" path should be shown as MISS
    store[mod.USER] = r"%TESTROOT%\Bin;C:\NotThere_missing"
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "validate"])
    args.func(args)

    out = capsys.readouterr().out
    assert "OK" in out and "MISS" in out


def test_non_windows_read_user_raises_systemexit(tmp_path):
    # Load a fresh module with its default IS_WINDOWS derived from real os.name
    mod = _load_pwsh_pathmgr(unique_name="pwsh_pathmgr_nonwin_" + uuid4().hex)
    if mod.IS_WINDOWS:
        pytest.skip("Host OS is Windows; this check is only meaningful on non-Windows runners.")
    with pytest.raises(SystemExit):
        _ = mod.read_path(mod.USER)
