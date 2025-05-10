import sys
import pytest
from pathlib import Path
import psutil
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

def test_pick_log_path_first_two(tmp_path):
    inst = tmp_path / "setup.exe"; inst.write_text("")
    p1 = ri.pick_log_path(inst)
    assert p1.name == "setup.log"
    p1.write_text("")
    p2 = ri.pick_log_path(inst)
    assert p2.name == "setup_2.log"

def test_pick_log_path_third(tmp_path):
    inst = tmp_path / "setup.exe"; inst.write_text("")
    # simulate existing setup.log and setup_2.log
    (tmp_path / "setup.log").write_text("")
    (tmp_path / "setup_2.log").write_text("")
    p3 = ri.pick_log_path(inst)
    assert p3.name == "setup_3.log"

def test_list_options(monkeypatch, capsys):
    # list-options should print flags before installer-exists check
    monkeypatch.setattr(sys, "argv", ["run_installers.py", "-i", "foo", "-l"])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Available Inno Setup Flags" in out
    assert "/VERYSILENT" in out

def test_missing_installer(tmp_path, monkeypatch, capsys):
    inst = tmp_path / "no_such.exe"
    monkeypatch.setattr(sys, "argv", ["run_installers.py", "-i", str(inst), "-t", str(tmp_path/"out")])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    out = capsys.readouterr().out
    assert "Installer not found" in out
    assert exc.value.code == 1

def test_missing_target(tmp_path, monkeypatch, capsys):
    inst = tmp_path / "setup.exe"; inst.write_text("")
    monkeypatch.setattr(sys, "argv", ["run_installers.py", "-i", str(inst)])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    out = capsys.readouterr().out
    assert "--target is required" in out
    assert exc.value.code == 1

def test_quick_run_exits_fast(tmp_path, monkeypatch):
    inst = tmp_path / "setup.exe"; inst.write_text("")
    log = tmp_path / "setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")
    # force pick_log_path to return our pre-populated log
    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)
    # quick intervals so loop exits immediately
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(tmp_path/"out"),
        "-s", "0",
        "-d", "0"
    ])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    assert exc.value.code == 0

def test_popen_fallback_and_cleanup(tmp_path, monkeypatch, capsys):
    # simulate psutil.Popen throwing, and ensure fallback DummyProc used
    inst = tmp_path / "setup.exe"; inst.write_text("")
    log = tmp_path / "setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")
    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)
    # force psutil.Popen to raise
    monkeypatch.setattr(psutil, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(Exception("fail")))
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(tmp_path/"out"),
        "-s", "0",
        "-d", "0"
    ])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    out = capsys.readouterr().out
    assert "could not launch installer" in out
    # DummyProc.wait returns 0, so exit code should be 0
    assert exc.value.code == 0
