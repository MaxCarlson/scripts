# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest

import applier


def lep_obj(changes, tx="tx", dry=False, defaults=None):
    return {
        "protocol": "LEP/v1",
        "transaction_id": tx,
        "dry_run": dry,
        "defaults": defaults or {"eol": "preserve", "encoding": "utf-8"},
        "changes": changes,
    }


def lep_json(changes, tx="tx", dry=False, defaults=None, fenced=False):
    s = json.dumps(lep_obj(changes, tx, dry, defaults))
    return "```json\n" + s + "\n```" if fenced else s


def test_create_then_replace_then_delete(tmp_path):
    # create
    lep = lep_json(
        [
            {"path": "f.txt", "op": "create", "create": {"full_text": "A\n"}},
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert (tmp_path / "f.txt").read_text() == "A\n"

    # replace with preimage
    new = "B\n"
    pre_sha = applier.hashlib.sha256(b"A\n").hexdigest()
    lep2 = lep_json(
        [
            {
                "path": "f.txt",
                "op": "replace",
                "preimage": {"exists": True, "sha256": pre_sha},
                "replace": {"full_text": new},
            }
        ]
    )
    assert applier.apply_from_text(lep2, repo_root=tmp_path) == 0
    assert (tmp_path / "f.txt").read_text() == "B\n"

    # delete
    lep3 = lep_json([{"path": "f.txt", "op": "delete"}])
    assert applier.apply_from_text(lep3, repo_root=tmp_path) == 0
    assert not (tmp_path / "f.txt").exists()


def test_replace_preimage_mismatch_conflict_and_force(tmp_path):
    (tmp_path / "g.txt").write_text("OLD\n")
    lep = lep_json(
        [
            {
                "path": "g.txt",
                "op": "replace",
                "preimage": {"exists": True, "sha256": "deadbeef"},
                "replace": {"full_text": "NEW\n"},
            }
        ]
    )
    # conflict -> code 2
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 2
    # force overrides preimage mismatch
    assert applier.apply_from_text(lep, repo_root=tmp_path, force=True) == 0
    assert (tmp_path / "g.txt").read_text() == "NEW\n"


def test_patch_with_context_and_idempotent(tmp_path):
    p = tmp_path / "h.py"
    p.write_text("line1\nold\nline3\n")
    pre_sha = applier.hashlib.sha256(p.read_bytes()).hexdigest()

    lep = lep_json(
        [
            {
                "path": "h.py",
                "op": "patch",
                "preimage": {"exists": True, "sha256": pre_sha},
                "patch": {
                    "format": "blocks",
                    "hunks": [
                        {
                            "context_before": "line1\n",
                            "remove": "old\n",
                            "insert": "new\n",
                            "context_after": "line3\n",
                        }
                    ],
                },
            }
        ]
    )
    # first apply
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text() == "line1\nnew\nline3\n"
    # applying same patch again should be idempotent success
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text() == "line1\nnew\nline3\n"


def test_patch_nonexistent_file_is_code_2(tmp_path):
    lep = lep_json(
        [
            {
                "path": "missing.py",
                "op": "patch",
                "patch": {"format": "blocks", "hunks": [{"remove": "", "insert": ""}]},
            }
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 2


def test_rename_success(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("X\n")
    lep = lep_json(
        [
            {"path": "src.txt", "op": "rename", "rename": {"new_path": "dst/d.txt"}},
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert not src.exists()
    assert (tmp_path / "dst" / "d.txt").read_text() == "X\n"


def test_multi_hunk_patch_order_and_idempotency(tmp_path):
    p = tmp_path / "multi.txt"
    p.write_text("H1\nOLD-A\nMID\nOLD-B\nTAIL\n")

    lep = lep_json(
        [
            {
                "path": "multi.txt",
                "op": "patch",
                "patch": {
                    "format": "blocks",
                    "hunks": [
                        {
                            "context_before": "H1\n",
                            "remove": "OLD-A\n",
                            "insert": "NEW-A\n",
                            "context_after": "MID\n",
                        },
                        {
                            "context_before": "MID\n",
                            "remove": "OLD-B\n",
                            "insert": "NEW-B\n",
                            "context_after": "TAIL\n",
                        },
                    ],
                },
            }
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text() == "H1\nNEW-A\nMID\nNEW-B\nTAIL\n"
    # Reapplying must stay unchanged
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text() == "H1\nNEW-A\nMID\nNEW-B\nTAIL\n"


def test_pure_insertion_with_empty_remove(tmp_path):
    p = tmp_path / "ins.txt"
    p.write_text("A\nC\n")
    lep = lep_json(
        [
            {
                "path": "ins.txt",
                "op": "patch",
                "patch": {
                    "format": "blocks",
                    "hunks": [
                        {
                            "context_before": "A\n",
                            "remove": "",
                            "insert": "B\n",
                            "context_after": "C\n",
                        }
                    ],
                },
            }
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text() == "A\nB\nC\n"


def test_pure_deletion_with_empty_insert(tmp_path):
    p = tmp_path / "del.txt"
    p.write_text("A\nX\nB\n")
    lep = lep_json(
        [
            {
                "path": "del.txt",
                "op": "patch",
                "patch": {
                    "format": "blocks",
                    "hunks": [
                        {
                            "context_before": "A\n",
                            "remove": "X\n",
                            "insert": "",
                            "context_after": "B\n",
                        }
                    ],
                },
            }
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text() == "A\nB\n"


def test_create_nested_directories(tmp_path):
    lep = lep_json(
        [
            {
                "path": "nested/dir/file.txt",
                "op": "create",
                "create": {"full_text": "nested\n"},
            }
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert (tmp_path / "nested" / "dir" / "file.txt").read_text() == "nested\n"


def test_patch_with_only_before_anchor(tmp_path):
    p = tmp_path / "only_before.txt"
    p.write_text("START\nOLD\nEND\n")
    lep = lep_json(
        [
            {
                "path": "only_before.txt",
                "op": "patch",
                "patch": {
                    "format": "blocks",
                    "hunks": [
                        {
                            "context_before": "START\n",
                            "remove": "OLD\n",
                            "insert": "NEW\n",
                        }
                    ],
                },
            }
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text() == "START\nNEW\nEND\n"


def test_patch_with_only_after_anchor(tmp_path):
    p = tmp_path / "only_after.txt"
    p.write_text("A\nOLD\nB\n")
    lep = lep_json(
        [
            {
                "path": "only_after.txt",
                "op": "patch",
                "patch": {
                    "format": "blocks",
                    "hunks": [
                        {"remove": "OLD\n", "insert": "NEW\n", "context_after": "B\n"}
                    ],
                },
            }
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text() == "A\nNEW\nB\n"


def test_idempotency_when_remove_equals_insert(tmp_path):
    p = tmp_path / "idem.txt"
    p.write_text("K\nSAME\nZ\n")
    lep = lep_json(
        [
            {
                "path": "idem.txt",
                "op": "patch",
                "patch": {
                    "format": "blocks",
                    "hunks": [
                        {
                            "context_before": "K\n",
                            "remove": "SAME\n",
                            "insert": "SAME\n",
                        }
                    ],
                },
            }
        ]
    )
    # no change expected and should succeed
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text() == "K\nSAME\nZ\n"
