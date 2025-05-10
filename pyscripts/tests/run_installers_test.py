import sys
import pytest
from pathlib import Path
import run_installers as ri

def test_total_size_gb(tmp_path):
    # create a directory tree with 1 KiB + 1 MiB
    d = tmp_path / "data"
    d.mkdir()
    (d / "a.bin").write_bytes(b"x" * 1024)              # 1 KiB
    sub = d / "sub"; sub.mkdir()
    (sub / "b.bin").write_bytes(b"x" * 1024 * 1024)     # 1 MiB
    size = ri.total_size_gb(d)
    # Expect (1 MiB + 1 KiB) / (1024**3)
    expected = (1024 * 1024 + 1024) / (1024 ** 3)
    assert pytest.approx(size, rel=1e-3) == expected

def test_format_line():
    txt = "2025-05-10 12:34:56.789   Hello world"
    out = ri.format_line(txt)
    assert "Hello world" in out.plain
    # ensure coloring info present
    assert any(span.style == "grey50" for span in out._spans)
    assert any(span.style == "bright_blue" for span in out._spans)

def test_file_count(tmp_path):
    d = tmp_path / "data"; d.mkdir()
    (d/"a.txt").write_text("x")
    sub = d/"sub"; sub.mkdir()
    (sub/"b.txt").write_text("y")
    assert ri.file_count(d) == 2

def test_pick_log_path(tmp_path):
    inst = tmp_path / "setup.exe"; inst.write_text("")
    p1 = ri.pick_log_path(inst)
    assert p1.name == "setup.log"
    p1.write_text("")
    p2 = ri.pick_log_path(inst)
    assert p2.name == "setup_2.log"

def test_list_options(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run_installers.py", "-i", "foo", "-l"])
    with pytest.raises(SystemExit):
        ri.main()
    out = capsys.readouterr().out
    assert "/VERYSILENT" in out
    assert "Available Inno Setup Flags" in out

def test_quick_run_exits_fast(tmp_path, monkeypatch):
    inst = tmp_path / "setup.exe"; inst.write_text("")
    log = tmp_path / "setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")

    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(tmp_path / "out"),
        "-s", "0",    # status interval
        "-d", "0"     # exit delay
    ])

    with pytest.raises(SystemExit) as exc:
        ri.main()
    assert exc.value.code == 0
