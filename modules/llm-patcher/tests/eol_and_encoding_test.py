# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest

import applier


def lep_json(changes, defaults=None):
    return json.dumps(
        {
            "protocol": "LEP/v1",
            "transaction_id": "t",
            "dry_run": False,
            "defaults": defaults or {"eol": "preserve", "encoding": "utf-8"},
            "changes": changes,
        }
    )


def test_preserve_crlf_on_patch(tmp_path):
    p = tmp_path / "crlf.txt"
    # Explicit CRLF content
    p.write_bytes(b"a\r\nb\r\n")
    pre = applier.hashlib.sha256(p.read_bytes()).hexdigest()
    lep = lep_json(
        [
            {
                "path": "crlf.txt",
                "op": "patch",
                "preimage": {"exists": True, "sha256": pre},
                "patch": {
                    "format": "blocks",
                    "hunks": [
                        {
                            "context_before": "a\r\n",
                            "remove": "b\r\n",
                            "insert": "B\r\n",
                            "context_after": "",
                        }
                    ],
                },
            }
        ],
        defaults={"eol": "preserve", "encoding": "utf-8"},
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    # Validate CRLF still present
    data = p.read_bytes()
    assert data == b"a\r\nB\r\n"


def test_dry_run_makes_no_changes(tmp_path):
    p = tmp_path / "dry.txt"
    p.write_text("ORIG\n")
    lep = lep_json(
        [{"path": "dry.txt", "op": "replace", "replace": {"full_text": "NEW\n"}}],
    )
    # dry-run true via parameter
    assert applier.apply_from_text(lep, repo_root=tmp_path, dry_run=True) == 0
    assert p.read_text() == "ORIG\n"


def test_force_eol_crlf_on_replace(tmp_path):
    p = tmp_path / "crlf_force.txt"
    p.write_text("a\nb\nc\n")  # LF
    lep = lep_json(
        [
            {
                "path": "crlf_force.txt",
                "op": "replace",
                "replace": {"full_text": "x\ny\n"},
            }
        ],
        defaults={"eol": "crlf", "encoding": "utf-8"},
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_bytes() == b"x\r\ny\r\n"


def test_utf8_non_ascii_roundtrip(tmp_path):
    p = tmp_path / "utf8.txt"
    p.write_text("μ-law\n", encoding="utf-8")
    pre = applier.hashlib.sha256(p.read_bytes()).hexdigest()
    lep = lep_json(
        [
            {
                "path": "utf8.txt",
                "op": "patch",
                "preimage": {"exists": True, "sha256": pre},
                "patch": {
                    "format": "blocks",
                    "hunks": [
                        {
                            "context_before": "",
                            "remove": "μ-law\n",
                            "insert": "µ-law\n",  # micro sign vs greek mu
                            "context_after": "",
                        }
                    ],
                },
            }
        ]
    )
    assert applier.apply_from_text(lep, repo_root=tmp_path) == 0
    assert p.read_text(encoding="utf-8") == "µ-law\n"
