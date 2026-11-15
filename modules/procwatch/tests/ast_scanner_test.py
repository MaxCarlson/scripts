"""Unit and safety tests for Phase 3 Python/PowerShell static scanner (`ast_scanner`)."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from unittest import mock

from procwatch.analyzers.ast_scanner import (
    FindingCategory,
    apply_proposed_fixes,
    parse_git_worktree_porcelain,
    scan_directory,
    scan_powershell_files,
    scan_python_source,
)
from procwatch.cli import main


def test_python_scanner_aliases_guards_interactive_and_dynamic() -> None:
    src = """
import os
import sys
import subprocess as sp
from subprocess import run as sp_run

def hidden_already():
    sp.run(["cmd", "/c", "echo"], creationflags=sp.CREATE_NO_WINDOW)

def interactive_shell():
    sp.run(["cmd.exe"], stdin=None)

def dynamic_call(cmd_var):
    sp.Popen(cmd_var)

def background_pipe():
    # preserve this comment
    sp_run(["python", "--version"], stdout=sp.PIPE, stderr=sp.PIPE)

def win_guarded():
    if sys.platform == "win32":
        sp.Popen(["ping", "127.0.0.1"], stdout=sp.DEVNULL)

def legacy_os():
    os.system("dir")
"""
    findings, err = scan_python_source(src, file_path="sample.py")
    assert err is None
    mechanisms = [f.mechanism for f in findings]
    assert len(findings) == 5  # hidden_already skipped
    assert "subprocess.run" in mechanisms
    assert "os.system" in mechanisms

    by_sym = {f.enclosing_symbol: f for f in findings}
    assert by_sym["interactive_shell"].category == FindingCategory.INTENTIONAL_INTERACTIVE
    assert by_sym["dynamic_call"].category == FindingCategory.UNKNOWN_DYNAMIC
    assert by_sym["background_pipe"].category == FindingCategory.LIKELY_UNINTENDED
    assert by_sym["win_guarded"].category == FindingCategory.LIKELY_UNINTENDED
    assert by_sym["legacy_os"].category == FindingCategory.LIKELY_UNINTENDED


def test_python_scanner_handles_syntax_error() -> None:
    findings, err = scan_python_source("def broken(:\n    pass\n", file_path="bad.py")
    assert findings == []
    assert err is not None and "SyntaxError" in err


def test_powershell_scanner_variants_and_spaces(tmp_path: Path) -> None:
    ps_dir = tmp_path / "dir with spaces"
    ps_dir.mkdir()
    ps_file = ps_dir / "test script.ps1"
    ps_file.write_text(
        "\n".join(
            [
                "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c echo ok' -WindowStyle Hidden",
                "Start-Process -FilePath 'cmd.exe' -NoNewWindow -Wait",
                "Start-Process -FilePath 'python.exe' -ArgumentList 'bg.py' -Wait",
            ]
        ),
        encoding="utf-8",
    )
    bad_ps = ps_dir / "broken.ps1"
    bad_ps.write_text("function oops { if ($true) { ", encoding="utf-8")

    findings, errors = scan_powershell_files([ps_file, bad_ps])
    assert any("ParseError" in e["error"] for e in errors)
    # Hidden call should be skipped; -NoNewWindow should carry warning; -Wait should be likely_unintended
    assert len(findings) == 2
    assert any("cannot be combined" in w for f in findings for w in f.warnings)
    assert any(f.category == FindingCategory.LIKELY_UNINTENDED for f in findings)


def test_worktree_porcelain_parser_with_spaces_and_missing(tmp_path: Path) -> None:
    wt1 = tmp_path / "repo main"
    wt2 = tmp_path / "repo wt"
    wt1.mkdir()
    wt2.mkdir()
    missing = tmp_path / "does not exist"
    porcelain = (
        f"worktree {wt1}\nHEAD aaa\nbranch refs/heads/main\n\n"
        f"worktree {wt2}\nHEAD bbb\ndetached\n\n"
        f"worktree {missing}\nHEAD ccc\n\n"
        f"worktree {wt1}\nHEAD aaa\n"
    )
    roots = parse_git_worktree_porcelain(porcelain)
    assert roots == [wt1, wt2]


def test_default_scan_is_non_mutating_and_dirty_guard_blocks_apply(tmp_path: Path, capsys) -> None:
    target = tmp_path / "worker.py"
    orig = (
        "import subprocess\n\n"
        "def run_bg():\n"
        "    # Important comment\n"
        "    return subprocess.run(['cmd', '/c', 'echo'], stdout=subprocess.PIPE)\n"
    )
    target.write_text(orig, encoding="utf-8")
    before_hash = hashlib.sha256(target.read_bytes()).hexdigest()

    # Default scan + CLI JSON output must not modify the file.
    rc = main(["scan", "-d", str(tmp_path), "-u", "-j"])
    assert rc == 0
    captured = capsys.readouterr().out
    parsed = json.loads(captured)
    assert parsed["files_scanned"] == 1
    assert parsed["finding_count"] == 1
    assert str(target) in parsed["diffs"]
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before_hash

    report = scan_directory(tmp_path, generate_diffs=True)
    # Dirty file in git must be skipped when force=False.
    with mock.patch("procwatch.analyzers.ast_scanner._is_file_dirty_in_git", return_value=True):
        res = apply_proposed_fixes(report, apply_fixes=True, force=False, backup_dir=tmp_path / "bak")
    assert len(res["skipped"]) == 1
    assert res["applied"] == []
    assert target.read_text(encoding="utf-8") == orig

    # Clean file with explicit apply_fixes=True writes valid AST and creates backup.
    with mock.patch("procwatch.analyzers.ast_scanner._is_file_dirty_in_git", return_value=False):
        res2 = apply_proposed_fixes(report, apply_fixes=True, force=False, backup_dir=tmp_path / "bak")
    assert len(res2["applied"]) == 1
    patched = target.read_text(encoding="utf-8")
    assert "# Important comment" in patched
    assert "CREATE_NO_WINDOW" in patched
    ast.parse(patched)
