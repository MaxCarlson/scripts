from __future__ import annotations

import types
from pathlib import Path
from types import SimpleNamespace

from file_utils import lister as lmod


class Args(SimpleNamespace):
    pass


def test_lister_plain_output_when_no_curses(monkeypatch, capsys, tmp_path):
    # Simulate missing curses on Windows
    monkeypatch.setattr(lmod, "curses", None)

    # Build minimal args
    args = Args(
        directory=str(tmp_path), depth=0, glob=None, sort="name", order="desc",
        json=False, no_dirs_first=False, calc_sizes=False,
    )
    # Create sample files
    (tmp_path / "a.txt").write_text("hi")
    (tmp_path / "b.txt").write_text("world")

    rc = lmod.run_lister(args)
    out = capsys.readouterr()
    assert rc == 0
    assert "Curses UI not available" in out.err
    assert "a.txt" in out.out or "b.txt" in out.out

