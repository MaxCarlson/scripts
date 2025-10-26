# -*- coding: utf-8 -*-
import json
import builtins
import io
import sys
from pathlib import Path

import pytest

import applier


def make_lep(changes, *, tx="tx-1", dry=False, defaults=None, fenced=False):
    obj = {
        "protocol": "LEP/v1",
        "transaction_id": tx,
        "dry_run": dry,
        "defaults": defaults or {"eol": "preserve", "encoding": "utf-8"},
        "changes": changes,
    }
    s = json.dumps(obj, indent=2)
    if fenced:
        return "```json\n" + s + "\n```"
    return s


def test_extract_json_from_fenced_block():
    raw = '{"k": 1}'
    fenced = "```json\n" + raw + "\n```"
    out = applier.extract_json_from_possible_fenced(fenced)
    assert out == raw


def test_extract_json_from_raw_json():
    raw = '{"k": 2}'
    out = applier.extract_json_from_possible_fenced(raw)
    assert out == raw


def test_extract_json_missing_closing_fence_raises():
    bad = '```json\n{"k": 1}\n'
    with pytest.raises(ValueError):
        applier.extract_json_from_possible_fenced(bad)


def test_parse_lep_valid_and_minimum_fields(tmp_path):
    lep = make_lep(
        [
            {
                "path": "a.txt",
                "op": "create",
                "create": {"full_text": "hello\n"},
            }
        ]
    )
    parsed = applier.parse_lep(lep)
    assert parsed.protocol == "LEP/v1"
    assert parsed.transaction_id == "tx-1"
    assert parsed.changes[0].path == "a.txt"
    assert parsed.changes[0].op == "create"
    assert parsed.changes[0].create["full_text"] == "hello\n"


def test_parse_lep_rejects_unsupported_protocol():
    bad = json.dumps(
        {
            "protocol": "X/0",
            "transaction_id": "t",
            "dry_run": False,
            "defaults": {},
            "changes": [],
        }
    )
    with pytest.raises(ValueError):
        applier.parse_lep(bad)


def test_parse_lep_requires_nonempty_changes():
    bad = json.dumps(
        {
            "protocol": "LEP/v1",
            "transaction_id": "t",
            "dry_run": False,
            "defaults": {},
            "changes": [],
        }
    )
    with pytest.raises(ValueError):
        applier.parse_lep(bad)


def test_parse_lep_invalid_json():
    with pytest.raises(ValueError):
        applier.parse_lep("{not-json}")


def test_apply_from_text_invalid_input_code_1(tmp_path):
    # Not JSON and not fenced JSON
    code = applier.apply_from_text("notjson", repo_root=tmp_path)
    assert code == 1


def test_extract_json_from_fenced_block_with_lep_language():
    raw = '{"x": 1}'
    fenced = "```lep\n" + raw + "\n```"
    out = applier.extract_json_from_possible_fenced(fenced)
    assert out == raw


def test_fenced_block_ignores_trailing_text_after_closing_fence():
    raw = '{"k": 3}'
    fenced = "```json\n" + raw + "\n```\nEXTRA TEXT IGNORED"
    out = applier.extract_json_from_possible_fenced(fenced)
    assert out == raw
