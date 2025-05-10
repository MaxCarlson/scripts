import sys
import time
import argparse
from pathlib import Path
import pytest
import psutil

import run_installers as ri


def test_pick_log_path(tmp_path):
    inst = tmp_path / "setup.exe"
    inst.write_text("")
    (tmp_path / "setup.log").write_text("")
    (tmp_path / "setup_2.log").write_text("")
    out = ri.pick_log_path(inst)
    assert out.name == "setup_3.log"


def test_total_size_gb(tmp_path):
    # create a directory tree with 1 KiB + 1 MiB
    d = tmp_path / "data"
    d.mkdir()
    (d / "a.bin").write_bytes(b"x" * 1024)              # 1 KiB
    sub = d / "sub"; sub.mkdir()
    (sub / "b.bin").write_bytes(b"x" * 1024 * 1024)     # 1 MiB
    size = ri.total_size_gb(d)
    # Expect (1 MiB + 1 KiB) / (1024**3)
    expected = (1 * 1024 + 1024) / (1024 ** 3)
    assert pytest.approx(size, rel=1e-3) == expected


def test_format_line_returns_text():
    txt = "2025-05-10 12:34:56.789   Hello world"
    out = ri.format_line(txt)
    assert hasattr(out, "plain")
    assert "Hello world" in out.plain


# -- Argument-parsing & exit branches --

def run_main_with_args(monkeypatch, args):
    monkeypatch.setenv("PYTHONUNBUFFERED", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(sys, "argv", ["run_installers.py"] + args)
    with pytest.raises(SystemExit) as exc:
        ri.main()
    return exc.value.code


def test_missing_installer(tmp_path, monkeypatch):
    code = run_main_with_args(monkeypatch, ["-i", "nope.exe", "-t", str(tmp_path / "out")])
    assert code == 1


def test_list_options(tmp_path, monkeypatch, capsys):
    inst = tmp_path / "setup.exe"
    inst.write_text("")
    code = run_main_with_args(monkeypatch, ["-i", str(inst), "-l"])
    captured = capsys.readouterr().out
    assert code == 0
    assert "Available Inno Setup Flags" in captured


def test_missing_target(tmp_path, monkeypatch):
    inst = tmp_path / "setup.exe"
    inst.write_text("")
    code = run_main_with_args(monkeypatch, ["-i", str(inst)])
    assert code == 1


# -- Integration-style with fake log --

def test_quick_run_exits_fast(tmp_path, monkeypatch, capsys):
    # Prepare a tiny fake installer and log
    inst = tmp_path / "setup.exe"; inst.write_text("")
    log = tmp_path / "setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")

    # Monkey-patch pick_log_path and argv
    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(tmp_path / "out"),
        "-s", "0",    # status interval
        "-d", "0"     # exit delay
    ])

    # Run main() and capture exit code
    with pytest.raises(SystemExit) as exc:
        ri.main()
    out = capsys.readouterr().out

    assert ri.FINAL_LOG_MARKER in out
    assert "✔ Done" in out
    assert exc.value.code == 0
