# -*- coding: utf-8 -*-
import json
import sys
from io import StringIO
from pathlib import Path

import pytest

import cli


def lep(changes):
    return json.dumps(
        {
            "protocol": "LEP/v1",
            "transaction_id": "t",
            "dry_run": False,
            "defaults": {"eol": "preserve", "encoding": "utf-8"},
            "changes": changes,
        }
    )


def test_cli_reads_from_file(tmp_path, capsys):
    content = lep([{"path": "foo.txt", "op": "create", "create": {"full_text": "A\n"}}])
    f = tmp_path / "in.json"
    f.write_text(content, encoding="utf-8")
    code = cli.main(["--file", str(f), "--repo-root", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "foo.txt").read_text() == "A\n"


def test_cli_reads_from_stdin(tmp_path, monkeypatch):
    content = lep([{"path": "bar.txt", "op": "create", "create": {"full_text": "B\n"}}])
    monkeypatch.setattr(sys, "stdin", StringIO(content))
    code = cli.main(["--repo-root", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "bar.txt").read_text() == "B\n"


def test_cli_reads_from_clipboard_via_cross_platform(tmp_path, monkeypatch):
    # Monkeypatch cli._get_clipboard_text to simulate cross_platform module behavior.
    def fake_clip():
        return lep([{"path": "cb.txt", "op": "create", "create": {"full_text": "C\n"}}])

    monkeypatch.setattr(cli, "_get_clipboard_text", lambda: fake_clip())
    code = cli.main(["--clipboard", "--repo-root", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "cb.txt").read_text() == "C\n"


def test_cli_clipboard_missing_exits_1(monkeypatch):
    monkeypatch.setattr(cli, "_get_clipboard_text", lambda: None)
    with pytest.raises(SystemExit) as e:
        cli.main(["--clipboard"])
    assert e.value.code == 1


def test_cli_force_overrides_preimage(tmp_path, monkeypatch):
    f = tmp_path / "t.txt"
    f.write_text("OLD\n")
    payload = lep(  # renamed from `lep = ...` to avoid shadowing the helper
        [
            {
                "path": "t.txt",
                "op": "replace",
                "preimage": {"exists": True, "sha256": "deadbeef"},
                "replace": {"full_text": "NEW\n"},
            }
        ]
    )
    monkeypatch.setattr(sys, "stdin", StringIO(payload))
    code = cli.main(["--repo-root", str(tmp_path), "--force"])
    assert code == 0
    assert f.read_text() == "NEW\n"


def test_cli_quiet_suppresses_done(tmp_path, capsys, monkeypatch):
    content = lep([{"path": "qq.txt", "op": "create", "create": {"full_text": "Q\n"}}])
    monkeypatch.setattr(sys, "stdin", StringIO(content))
    code = cli.main(["--repo-root", str(tmp_path), "--quiet"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Done." not in out
