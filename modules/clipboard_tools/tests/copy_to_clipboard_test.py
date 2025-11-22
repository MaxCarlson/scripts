from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pyscripts import copy_to_clipboard as c2c


def _call(files, *args) -> int:
    argv = list(args) + [str(Path(f)) for f in files]
    parsed = c2c.parser.parse_args(argv)
    return c2c.copy_files_to_clipboard(
        parsed.files,
        raw_copy=parsed.raw_copy,
        wrap=parsed.wrap,
        whole_wrap=parsed.whole_wrap,
        show_full_path=parsed.show_full_path,
        append=parsed.append,
        override_append_wrapping=parsed.override_append_wrapping,
        no_stats=True,
        buffer_id=parsed.buffer,
    )


def test_copy_single_file_raw(tmp_path):
    p = tmp_path / "one.txt"
    p.write_text("hello\n", encoding="utf-8")
    rc = _call([p])
    assert rc == 0


def test_copy_wrap_multi(tmp_path):
    p1 = tmp_path / "a.txt"
    p2 = tmp_path / "b.txt"
    p1.write_text("A", encoding="utf-8")
    p2.write_text("B", encoding="utf-8")
    rc = _call([p1, p2], "-w")
    assert rc == 0


def test_copy_whole_wrap(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("C", encoding="utf-8")
    rc = _call([p], "-W")
    assert rc == 0


def test_append_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(c2c, "get_clipboard", lambda: "existing")
    p = tmp_path / "d.txt"
    p.write_text("D", encoding="utf-8")
    rc = _call([p], "-a")
    assert rc == 0
