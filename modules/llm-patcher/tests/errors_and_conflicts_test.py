# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest

import applier


def lep_json(obj):
    return json.dumps(obj)


def base_obj():
    return {
        "protocol": "LEP/v1",
        "transaction_id": "t",
        "dry_run": False,
        "defaults": {"eol": "preserve", "encoding": "utf-8"},
        "changes": [],
    }


def test_missing_hunks_in_patch_is_invalid(tmp_path):
    o = base_obj()
    o["changes"] = [{"path": "x.txt", "op": "patch", "patch": {"format": "blocks"}}]
    code = applier.apply_from_text(lep_json(o), repo_root=tmp_path)
    assert code == 1


def test_patch_conflict_bad_anchors(tmp_path):
    p = tmp_path / "y.txt"
    p.write_text("A\nB\nC\n")
    o = base_obj()
    o["changes"] = [
        {
            "path": "y.txt",
            "op": "patch",
            "patch": {
                "format": "blocks",
                "hunks": [
                    {
                        "context_before": "nope\n",
                        "remove": "missing\n",
                        "insert": "X\n",
                        "context_after": "still-nope\n",
                    }
                ],
            },
        }
    ]
    code = applier.apply_from_text(lep_json(o), repo_root=tmp_path)
    # Anchors not found -> PatchConflict => 2
    assert code == 2


def test_transaction_id_and_dry_run_echo(tmp_path, capsys):
    o = base_obj()
    o["transaction_id"] = "txn-123"
    o["dry_run"] = True
    o["changes"] = [{"path": "z.txt", "op": "create", "create": {"full_text": "Z\n"}}]
    code = applier.apply_from_text(lep_json(o), repo_root=tmp_path)
    assert code == 0
    out = capsys.readouterr().out
    assert "Transaction: txn-123" in out
    assert "dry-run" in out
    assert not (tmp_path / "z.txt").exists()


def test_unsupported_op_is_code_1(tmp_path):
    bad = {
        "protocol": "LEP/v1",
        "transaction_id": "t",
        "dry_run": False,
        "defaults": {"eol": "preserve", "encoding": "utf-8"},
        "changes": [{"path": "x.txt", "op": "move", "rename": {"new_path": "y.txt"}}],
    }
    code = applier.apply_from_text(json.dumps(bad), repo_root=tmp_path)
    assert code == 1
