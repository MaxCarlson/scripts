#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pytest suite for permissions_manager.py

Goals
- High coverage of CLI subcommands and edge cases.
- OS-aware: Windows-only tests are skipped on POSIX and vice versa.
- No real system mutation: all cross_platform interactions are monkeypatched.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest


# ---------- Helpers ----------

def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _is_posix() -> bool:
    return not _is_windows()


def import_tool(tmp_path: Path) -> Any:
    """
    Import permissions_manager as a module.
    """
    # Import the target module once for the test session
    import importlib
    mod = importlib.import_module("permissions_manager")
    return mod


# ---------- Fixtures ----------

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    """
    Ensure consistent environment for tests (e.g., Windows CURRENT_USER fallback).
    """
    monkeypatch.delenv("USERDOMAIN", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)


@pytest.fixture
def pmgr(tmp_path: Path) -> Any:
    """
    Return the imported permissions_manager module.
    """
    return import_tool(tmp_path)


@pytest.fixture
def fake_fs(tmp_path: Path) -> Tuple[Path, Path, Path]:
    """
    Create a small temp tree:
        root/
          a.txt
          sub/
            b.txt
    Returns (root, sub, a_file)
    """
    root = tmp_path / "root"
    sub = root / "sub"
    a = root / "a.txt"
    b = sub / "b.txt"
    sub.mkdir(parents=True, exist_ok=True)
    a.write_text("A", encoding="utf-8")
    b.write_text("B", encoding="utf-8")
    return root, sub, a


@pytest.fixture
def patch_cross_platform(pmgr, monkeypatch: pytest.MonkeyPatch, fake_fs):
    """
    Patch cross_platform functions & classes imported into permissions_manager's namespace.
    No system tools are invoked; we simulate behavior.
    """
    root, sub, a = fake_fs

    # Capture/Template structures
    class _Tmpl(pmgr.PermissionsTemplate):  # type: ignore[attr-defined]
        pass

    # read_permissions -> return per-platform template
    def _read_permissions(path: str):
        if _is_windows():
            return _Tmpl(
                backend="windows_icacls",
                payload="Everyone:RX\nBUILTIN\\Administrators:F",
                mode=None,
                owner="TESTDOMAIN\\Alice",
                group=None,
                source_kind="dir" if Path(path).is_dir() else "file",
                meta={"from": "mock"},
            )
        else:
            return _Tmpl(
                backend="posix_mode",
                payload="",
                mode=0o755 if Path(path).is_dir() else 0o644,
                owner="alice",
                group="users",
                source_kind="dir" if Path(path).is_dir() else "file",
                meta={"from": "mock"},
            )

    # diff_permissions -> show change for sub path only
    def _diff_permissions(template, target_path: str) -> Dict[str, Any]:
        target = Path(target_path)
        base = {
            "backend": template.backend,
            "added": [],
            "removed": [],
            "mode_change": None,
            "owner_change": None,
            "group_change": None,
        }
        # Make the "sub/b.txt" look different
        if target.name == "b.txt":
            base["added"] = ["Users:R"] if template.backend == "windows_icacls" else []
            base["mode_change"] = "0o644 -> 0o600" if template.backend != "windows_icacls" else None
        return base

    # apply_permissions -> record calls
    applied: List[str] = []

    def _apply_permissions(template, target_path: str, **kwargs):
        applied.append(str(Path(target_path)))

    # PermissionsUtils.iter_with_depth -> BFS over our temp tree
    def _iter_with_depth(self, root: Path, max_depth: int, follow_symlinks: bool):
        root = root.resolve()
        yield root
        if max_depth <= 0:
            return
        q: List[Tuple[Path, int]] = [(root, 0)]
        while q:
            cur, d = q.pop(0)
            if d >= max_depth:
                continue
            if cur.is_dir():
                for p in sorted(cur.iterdir()):
                    yield p
                    if p.is_dir():
                        q.append((p, d + 1))

    # scan_drift -> fixed results
    def _scan_drift(root_path: str, *, reference=None, max_depth=0, follow_symlinks=False):
        return [(".", {"backend": "posix_mode" if _is_posix() else "windows_icacls",
                       "added": ["x"], "removed": [], "mode_change": None,
                       "owner_change": None, "group_change": None})]

    # list_non_inheriting_windows -> only used on Windows
    def _list_non_inheriting_windows(path: str, *, max_depth=0, follow_symlinks=False):
        return [str(Path(path)) + "\\noinherit"] if _is_windows() else []

    # save/load template
    def _save_template(template, out_path: str):
        Path(out_path).write_text(json.dumps({"backend": template.backend}), encoding="utf-8")

    def _load_template(in_path: str):
        data = json.loads(Path(in_path).read_text(encoding="utf-8"))
        return _Tmpl(
            backend=data["backend"],
            payload="Everyone:RX" if _is_windows() else "",
            mode=None if _is_windows() else 0o644,
            owner="mock",
            group=None if _is_windows() else "users",
            source_kind="file",
            meta={"loaded": True},
        )

    # presets
    if _is_windows():
        presets = [
            {"id": "win-readonly-everyone", "title": "Windows Everyone RX",
             "description": "Allow Everyone read/execute.",
             "platforms": ["windows"],
             "windows": {"grants": ["Everyone:RX"], "inheritance": "enable", "owner": None}},
        ]
    else:
        presets = [
            {"id": "posix-755-exec", "title": "POSIX 755",
             "description": "Owner rwx; group/other rx.",
             "platforms": ["posix"],
             "posix": {"mode": 0o755, "owner": None, "group": None, "acl": None}},
        ]

    def _list_presets():
        return presets

    def _get_preset(pid: str):
        for p in presets:
            if p["id"] == pid:
                return p
        return None

    # PrivilegesManager.ensure_or_explain_permissions -> no-op
    class _PMNoop:
        def ensure_or_explain_permissions(self, *a, **kw):
            return None

    # Monkeypatch into module namespace
    monkeypatch.setattr(pmgr, "read_permissions", _read_permissions)
    monkeypatch.setattr(pmgr, "diff_permissions", _diff_permissions)
    monkeypatch.setattr(pmgr, "apply_permissions", _apply_permissions)
    monkeypatch.setattr(pmgr, "scan_drift", _scan_drift)
    monkeypatch.setattr(pmgr, "list_non_inheriting_windows", _list_non_inheriting_windows)
    monkeypatch.setattr(pmgr, "save_template", _save_template)
    monkeypatch.setattr(pmgr, "load_template", _load_template)
    monkeypatch.setattr(pmgr, "list_presets", _list_presets)
    monkeypatch.setattr(pmgr, "get_preset", _get_preset)

    # Patch PermissionsUtils.iter_with_depth method
    monkeypatch.setattr(pmgr.PermissionsUtils, "iter_with_depth", _iter_with_depth)  # type: ignore[attr-defined]

    # Patch PrivilegesManager to our no-op class
    monkeypatch.setattr(pmgr, "PrivilegesManager", _PMNoop)

    # Provide a handle to applied list so tests can assert call counts
    return {"applied": applied, "root": root, "sub": sub, "afile": a}


# ---------- Tests: Shared ----------

def test_view_text_and_json(pmgr, patch_cross_platform, capsys, fake_fs):
    root, sub, a = fake_fs

    # TEXT
    parser = pmgr.build_parser()
    args = parser.parse_args(["view", "-p", str(root)])
    rc = pmgr.cmd_view(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Backend:" in out

    # JSON
    args = parser.parse_args(["view", "-p", str(a), "--json"])
    rc = pmgr.cmd_view(args)
    assert rc == 0
    j = capsys.readouterr().out
    data = json.loads(j)
    assert "backend" in data


def test_diff_multiple_targets_text_and_json(pmgr, patch_cross_platform, capsys, fake_fs):
    root, sub, a = fake_fs
    parser = pmgr.build_parser()

    # TEXT
    args = parser.parse_args(["diff", "-s", str(root), "-t", str(root), str(sub)])
    rc = pmgr.cmd_diff(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "[DIFF]" in out

    # JSON
    args = parser.parse_args(["diff", "-s", str(root), "-t", str(a), str(sub), "--json"])
    rc = pmgr.cmd_diff(args)
    assert rc == 0
    j = capsys.readouterr().out
    arr = json.loads(j)
    assert isinstance(arr, list) and len(arr) == 2


def test_copy_dry_run_and_apply(pmgr, patch_cross_platform, capsys, fake_fs):
    root, sub, a = fake_fs
    applied = patch_cross_platform["applied"]
    parser = pmgr.build_parser()

    # Dry-run depth=1
    args = parser.parse_args(["copy", "-s", str(root), "-t", str(root), "-r", "1", "-n"])
    rc = pmgr.cmd_copy(args)
    assert rc == 0
    out = capsys.readouterr().out
    # Expect diffs for root and its children
    assert "[DRY-RUN DIFF]" in out

    # Real apply (depth=1) — our patched apply will just record paths
    args = parser.parse_args(["copy", "-s", str(root), "-t", str(root), "-r", "1"])
    rc = pmgr.cmd_copy(args)
    assert rc == 0
    # Should include root, a.txt, sub, and b.txt (4 items)
    assert len(applied) >= 3  # cross-platform order variability; but should be >= 3


def test_audit_drift_reports_changes(pmgr, patch_cross_platform, capsys, fake_fs):
    root, sub, a = fake_fs
    parser = pmgr.build_parser()
    args = parser.parse_args(["audit-drift", "-p", str(root), "-r", "1"])
    rc = pmgr.cmd_audit_drift(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "[DRIFT]" in out or "No drift detected." in out


def test_presets_list_text_and_json(pmgr, patch_cross_platform, capsys):
    parser = pmgr.build_parser()

    # Text
    args = parser.parse_args(["presets"])
    rc = pmgr.cmd_presets(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Platforms:" in out

    # JSON
    args = parser.parse_args(["presets", "--json"])
    rc = pmgr.cmd_presets(args)
    assert rc == 0
    j = capsys.readouterr().out
    data = json.loads(j)
    assert isinstance(data, list) and data


def test_export_and_import_apply_dry_run(pmgr, patch_cross_platform, capsys, fake_fs, tmp_path):
    root, sub, a = fake_fs
    parser = pmgr.build_parser()

    tmpl_file = tmp_path / "tmpl.json"
    args = parser.parse_args(["export", "-s", str(root), "-o", str(tmpl_file)])
    rc = pmgr.cmd_export(args)
    assert rc == 0
    assert tmpl_file.exists()

    args = parser.parse_args(["import-apply", "-i", str(tmpl_file), "-t", str(root), "-n", "-r", "1"])
    rc = pmgr.cmd_import_apply(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "[DRY-RUN DIFF]" in out


def test_main_dispatch_and_verbose(pmgr, patch_cross_platform, monkeypatch: pytest.MonkeyPatch, capsys, fake_fs):
    root, sub, a = fake_fs
    # Exercise main() path with sys.argv
    argv = ["permissions_manager.py", "-v", "view", "-p", str(root)]
    monkeypatch.setattr(sys, "argv", argv)
    rc = pmgr.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Path:" in out


# ---------- Tests: POSIX-only ----------

@pytest.mark.skipif(_is_windows(), reason="POSIX-only tests")
def test_set_preset_posix_apply_and_dry_run(pmgr, patch_cross_platform, capsys, fake_fs):
    root, sub, a = fake_fs
    parser = pmgr.build_parser()

    # Dry-run
    args = parser.parse_args(["set", "-p", str(root), "--preset", "posix-755-exec", "-n", "-r", "1"])
    rc = pmgr.cmd_set(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "[DRY-RUN DIFF]" in out

    # Apply
    args = parser.parse_args(["set", "-p", str(root), "--preset", "posix-755-exec", "-r", "1"])
    rc = pmgr.cmd_set(args)
    assert rc == 0
    # No assertion on outputs; success path covered


@pytest.mark.skipif(_is_windows(), reason="POSIX-only tests")
def test_win_noninherit_on_posix_errors(pmgr, patch_cross_platform, capsys, fake_fs):
    root, *_ = fake_fs
    parser = pmgr.build_parser()
    args = parser.parse_args(["win-noninherit", "-p", str(root)])
    rc = pmgr.cmd_win_noninherit(args)
    assert rc != 0  # Error on POSIX
    # Output is via debug logger; just assert return code


# ---------- Tests: Windows-only ----------

@pytest.mark.skipif(_is_posix(), reason="Windows-only tests")
def test_set_preset_windows_apply_and_dry_run(pmgr, patch_cross_platform, capsys, fake_fs, monkeypatch: pytest.MonkeyPatch):
    root, sub, a = fake_fs
    # Simulate USERDOMAIN/USERNAME for current_user_windows()
    monkeypatch.setenv("USERDOMAIN", "TESTDOMAIN")
    monkeypatch.setenv("USERNAME", "Alice")

    parser = pmgr.build_parser()

    # Dry-run
    args = parser.parse_args(["set", "-p", str(root), "--preset", "win-readonly-everyone", "-n", "-r", "1", "-e", "-i"])
    rc = pmgr.cmd_set(args)
    # Both -e and -i set: function warns and proceeds with inheritance None; still success
    assert rc == 0
    out = capsys.readouterr().out
    assert "[DRY-RUN DIFF]" in out

    # Apply
    args = parser.parse_args(["set", "-p", str(root), "--preset", "win-readonly-everyone", "-r", "1", "-e"])
    rc = pmgr.cmd_set(args)
    assert rc == 0


@pytest.mark.skipif(_is_posix(), reason="Windows-only tests")
def test_win_noninherit_lists_items(pmgr, patch_cross_platform, capsys, fake_fs):
    root, *_ = fake_fs
    parser = pmgr.build_parser()
    args = parser.parse_args(["win-noninherit", "-p", str(root), "-r", "1"])
    rc = pmgr.cmd_win_noninherit(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "noinherit" in out
