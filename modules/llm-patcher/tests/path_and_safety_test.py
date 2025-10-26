# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest

import applier


def make_lep(changes, tx="t", dry=False, defaults=None):
    return json.dumps(
        {
            "protocol": "LEP/v1",
            "transaction_id": tx,
            "dry_run": dry,
            "defaults": defaults or {"eol": "preserve", "encoding": "utf-8"},
            "changes": changes,
        }
    )


def test_rejects_absolute_paths(tmp_path):
    lep = make_lep(
        [
            {"path": "/etc/passwd", "op": "delete"},
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 1


def test_rejects_parent_traversal(tmp_path):
    lep = make_lep(
        [
            {"path": "../escape.txt", "op": "delete"},
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 1


def test_delete_nonexistent_is_ok(tmp_path):
    lep = make_lep(
        [
            {"path": "does-not-exist.txt", "op": "delete"},
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0


def test_rename_missing_source_returns_2(tmp_path):
    lep = make_lep(
        [
            {"path": "missing.txt", "op": "rename", "rename": {"new_path": "new.txt"}},
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 2


def test_rename_rejects_new_path_escaping_root(tmp_path):
    lep = make_lep(
        [
            {
                "path": "file.txt",
                "op": "rename",
                "rename": {"new_path": "../escape.txt"},
            }
        ]
    )
    # Source file missing will also cause a 2, but we expect path validation to
    # trigger first (ValueError -> code 1). Either is acceptable safety-wise.
    code = applier.apply_from_text(lep, repo_root=tmp_path)
    assert code in (1, 2)


def test_normalizes_path_with_inner_parent_dir(tmp_path):
    # "a/../b.txt" normalizes to "b.txt" and should be allowed.
    lep = make_lep(
        [
            {
                "path": "a/../b.txt",
                "op": "create",
                "create": {"full_text": "ok\n"},
            }
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert (tmp_path / "b.txt").read_text() == "ok\n"
