#!/usr/bin/env python3
from __future__ import annotations

from termdash.cli import build_parser, main


def test_cli_parses_and_runs_plain_progress(capsys):
    parser = build_parser()
    ns = parser.parse_args(["progress", "--plain", "--total", "5", "--interval", "0", "--width", "10"])
    assert ns.cmd == "progress"
    # run via main entry with argv to exercise top-level path
    rc = main(["progress", "--plain", "--total", "5", "--interval", "0", "--width", "10"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "100%" in out or "100" in out  # loose check


def test_cli_plain_seemake(capsys):
    rc = main(["seemake", "--plain", "--steps", "3", "--interval", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[100%]" in out
