# File: scripts/pwsh/tests/pwsh_pathmgr_test.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for pwsh_pathmgr.py (Linux/WSL-safe via mocks).

Covers:
- splitting/normalization
- add/remove/clean behavior
- diff output
- backup/restore roundtrip
- process-scope update + dry-run
- safety rails: no empty write, no shrink on add/clean/set-exact/restore unless --force
"""

from __future__ import annotations
import json
import importlib.util
from pathlib import Path
from uuid import uuid4
import pytest

def _load_pwsh_pathmgr(unique_name: str = None):
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
    mod.IS_WINDOWS = True
    fake_store = {mod.USER: "", mod.MACHINE: ""}

    def _rr(scope: str) -> str: return fake_store.get(scope, "")
    def _wr(scope: str, new_val: str): fake_store[scope] = new_val

    mod._read_reg_path = _rr
    mod._write_reg_path = _wr
    mod._wm_settingchange_broadcast = lambda: None

    mod.BACKUP_DIR = tmp_path / "backups"
    mod.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # predictable exists check: any path ending with "missing" is MISS
    def fake_isdir(p):
        s = str(mod._expand_for_check(str(p)))
        return not s.lower().endswith("missing")

    mod.os.path.isdir = fake_isdir
    mod.os.environ["TESTROOT"] = r"C:\Apps"
    return fake_store

# --- Tests ---

def test_split_and_normalize_basic(tmp_path):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)
    messy = r'  "C:\Tools"  ;;  C:\Windows\System32  ;  %TESTROOT%\Bin  ;  '
    parts = mod._split_path_string(messy)
    assert parts == [r"C:\Tools", r"C:\Windows\System32", r"%TESTROOT%\Bin"]

def test_build_new_string_add_and_dedupe_trailing_slash_preserved(tmp_path):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)

    base = r"C:\A\;c:\a\;C:\B\;"
    out = mod.build_new_string(base, add=["C:\\A\\"], cleanup=True, dedupe=True)
    assert out == "C:\\A\\;C:\\B\\"

    out2 = mod.build_new_string(out, add=["C:\\MyBin\\"], cleanup=True, dedupe=True)
    assert out2 == "C:\\A\\;C:\\B\\;C:\\MyBin\\"

def test_remove_exact_and_contains(tmp_path):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)
    base = r"C:\A;C:\Tools\Bin;C:\Foo;C:\Bar"
    out = mod.build_new_string(base, remove=[r"C:\Foo", "contains:tools"], cleanup=True, dedupe=True)
    assert out == r"C:\A;C:\Bar"

def test_print_diff_marks_added_removed_and_same(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)
    old = r"C:\A;C:\B"; new = r"C:\A;C:\B;C:\C"
    mod.print_diff(mod.USER, old, new)
    out = capsys.readouterr().out
    assert "+ C:\\C" in out and "C:\\A" in out and "C:\\B" in out

def test_backup_and_restore_roundtrip_user(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)
    original = r"C:\Tools;C:\Windows\System32"
    store[mod.USER] = original
    bfile = mod.backup_path(mod.USER)
    assert bfile.is_file()
    store[mod.USER] = r"C:\Different"
    # restore (may shrink or grow); pass --force to allow any delta
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "restore", str(bfile), "--force"])
    args.func(args)
    assert store[mod.USER] == original
    assert "Restored User PATH" in capsys.readouterr().out

def test_backup_file_has_expected_json_content(tmp_path):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)
    store[mod.USER] = r"C:\A;C:\B"
    bfile = mod.backup_path(mod.USER)
    data = json.loads(bfile.read_text(encoding="utf-8"))
    assert data["scope"] == mod.USER
    assert data["path_string"] == r"C:\A;C:\B"
    assert data["segments"] == ["C:\\A", "C:\\B"]

def test_cmd_add_user_writes_registry_and_backup(tmp_path):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)
    store[mod.USER] = r"C:\A;C:\B"
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "add", r"C:\MyBin"])
    args.func(args)
    assert store[mod.USER].endswith(r"C:\MyBin")
    backups = list(mod.BACKUP_DIR.glob("PATH-User-*.json"))
    assert backups, "expected a backup JSON for User scope write"

def test_cmd_remove_contains_dry_run_does_not_write(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)
    store[mod.USER] = r"C:\A;C:\Tools\Bin;C:\Foo"
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "remove", "contains:tools", "--dry-run"])
    args.func(args)
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
    assert store[mod.USER] == r'  "C:\A" ;; C:\A ;; C:\B  '
    out = capsys.readouterr().out
    assert "[dry-run]" in out

def test_add_process_scope_dry_run_no_write(tmp_path):
    mod = _load_pwsh_pathmgr()
    _prepare_windows_like_env(mod, tmp_path)
    mod.os.environ["Path"] = r"C:\A;C:\B"
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "Process", "add-process", r"C:\C", "--dry-run"])
    args.func(args)
    assert mod.os.environ["Path"] == r"C:\A;C:\B"

def test_print_segments_ok_and_miss_with_expansion(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)
    store[mod.USER] = r"%TESTROOT%\Bin;C:\NotThere_missing"
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "validate"])
    args.func(args)
    out = capsys.readouterr().out
    assert "OK" in out and "MISS" in out

def test_non_windows_read_user_raises_systemexit(tmp_path):
    mod = _load_pwsh_pathmgr(unique_name="pwsh_pathmgr_nonwin_" + uuid4().hex)
    if mod.IS_WINDOWS:
        pytest.skip("Host OS is Windows; this check is only meaningful on non-Windows runners.")
    with pytest.raises(SystemExit):
        _ = mod.read_path(mod.USER)

# Safety rails

def test_add_cleanup_that_would_shrink_aborts_without_force(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)
    # duplicate will shrink from 2 -> 1 if cleanup/dedupe allowed
    store[mod.USER] = r"C:\A;C:\A"
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "add", r"C:\A", "--cleanup"])
    args.func(args)
    # No change because shrinking without --force is forbidden
    assert store[mod.USER] == r"C:\A;C:\A"
    assert "[abort]" in capsys.readouterr().out

def test_set_exact_empty_aborts(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)
    store[mod.USER] = r"C:\A;C:\B"
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "set-exact", "--from-file", str(empty_file)])
    args.func(args)
    assert store[mod.USER] == r"C:\A;C:\B"
    assert "Refusing to write EMPTY PATH" in capsys.readouterr().out

def test_set_exact_shrink_requires_force(tmp_path, capsys):
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)
    store[mod.USER] = r"C:\A;C:\B;C:\C"
    target = tmp_path / "newpath.txt"
    target.write_text(r"C:\A;C:\B", encoding="utf-8")

    # Without --force: abort
    parser = mod.build_parser()
    args = parser.parse_args(["--scope", "User", "set-exact", "--from-file", str(target)])
    args.func(args)
    assert store[mod.USER] == r"C:\A;C:\B;C:\C"
    assert "[abort]" in capsys.readouterr().out

    # With --force: write succeeds
    args = parser.parse_args(["--scope", "User", "set-exact", "--from-file", str(target), "--force"])
    args.func(args)
    assert store[mod.USER] == r"C:\A;C:\B"

def test_restore_shrink_requires_force(tmp_path, capsys):
    """Restoring from a JSON that has fewer entries should require --force."""
    mod = _load_pwsh_pathmgr()
    store = _prepare_windows_like_env(mod, tmp_path)
    store[mod.USER] = r"C:\A;C:\B;C:\C"

    # Create a "backup" JSON manually with only two entries
    j = {"scope": mod.USER, "when": "now", "path_string": r"C:\A;C:\B", "segments": ["C:\\A", "C:\\B"]}
    bfile = tmp_path / "bk.json"
    bfile.write_text(json.dumps(j), encoding="utf-8")

    parser = mod.build_parser()

    # Without --force -> abort
    args = parser.parse_args(["--scope", "User", "restore", str(bfile)])
    args.func(args)
    assert store[mod.USER] == r"C:\A;C:\B;C:\C"
    assert "[abort]" in capsys.readouterr().out

    # With --force -> write
    args = parser.parse_args(["--scope", "User", "restore", str(bfile), "--force"])
    args.func(args)
    assert store[mod.USER] == r"C:\A;C:\B"
