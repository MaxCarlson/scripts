# tests/run_installers_test2.py
import sys
import time
import pytest
from pathlib import Path
import psutil
import run_installers as ri


# --- Helpers for fake processes --- #

class FakeChild:
    def __init__(self, pid):
        self.pid = pid
    def is_running(self):
        return True

class FakeSetupProc:
    """
    Cycles through a predefined sequence of child‐sets on each children() call,
    and exposes a fixed pid for itself.
    """
    def __init__(self, seq, pid=999):
        self.seq = seq
        self.idx = 0
        self.pid = pid

    def children(self, recursive=True):
        s = self.seq[min(self.idx, len(self.seq)-1)]
        self.idx += 1
        return [FakeChild(pid) for pid in s]

    def terminate(self): pass
    def wait(self, timeout=None): return 0

class FakePsutilProcess:
    """Fake psutil.Process that returns pid as its cpu_percent."""
    def __init__(self, pid):
        self.pid = pid
    def cpu_percent(self, interval=None):
        return float(self.pid)
    def is_running(self):
        return True

# --- Helpers for fake processes --- #
class FakeExitProc:
    def __init__(self, returncode):
        self.pid = 1
        self._rc = returncode
    def children(self, recursive=True):
        return []
    def wait(self, timeout=None):
        return self._rc

# --- Tests --- #

def test_force_install_block(tmp_path, monkeypatch, capsys):
    inst = tmp_path/"setup.exe"; inst.write_text("")
    target = tmp_path/"out"; target.mkdir()
    monkeypatch.setenv("PYTEST_RUNNING", "1")
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(target),
    ])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    out = capsys.readouterr().out
    assert "already exists" in out
    assert exc.value.code != 0

def test_force_install_allow(tmp_path, monkeypatch, capsys):
    inst = tmp_path/"setup.exe"; inst.write_text("")
    target = tmp_path/"out"; target.mkdir()
    # prepopulate a log so we break out immediately
    log = tmp_path/"setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")

    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)
    monkeypatch.setenv("PYTEST_RUNNING", "1")
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(target),
        "-F",
        "-s", "0",
        "-d", "0",
    ])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    # forced into existing dir → still zero exit
    assert exc.value.code == 0

def test_spawn_exit_and_cpu(monkeypatch, tmp_path, capsys):
    inst = tmp_path/"setup.exe"; inst.write_text("")
    outdir = tmp_path/"out"; outdir.mkdir()
    log = tmp_path/"setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")
    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)

    seq = [
        set(),        # no children
        {101, 202},   # spawn
        set()         # exit
    ]
    fake_proc = FakeSetupProc(seq, pid=999)
    monkeypatch.setattr(psutil, "Popen", lambda *a, **k: fake_proc)
    monkeypatch.setattr(psutil, "Process", lambda pid: FakePsutilProcess(pid))

    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(outdir),
        "-F",                # <-- force into existing dir
        "-s", "0",
        "-d", "0",
    ])
    with pytest.raises(SystemExit):
        ri.main()

    out_lines = capsys.readouterr().out.splitlines()
    # look for spawn lines
    assert any("Spawned:" in l and "PID 101" in l for l in out_lines)
    assert any("Spawned:" in l and "PID 202" in l for l in out_lines)
    # look for exit lines
    assert any("Exited:" in l and "PID 101" in l for l in out_lines)
    assert any("Exited:" in l and "PID 202" in l for l in out_lines)
    # CPU total should be 101 + 202 + 999 = 1302
    cpu_lines = [l for l in out_lines if "CPU Total" in l]
    assert any("1302%" in l for l in cpu_lines)

def test_quick_run_exits_fast(tmp_path, monkeypatch):
    inst = tmp_path/"setup.exe"; inst.write_text("")
    log = tmp_path/"setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")

    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)
    monkeypatch.setenv("PYTEST_RUNNING", "1")
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(tmp_path/"out"),
        "-s", "0",
        "-d", "0",
    ])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    assert exc.value.code == 0

def test_popen_fallback_and_cleanup(tmp_path, monkeypatch, capsys):
    inst = tmp_path/"setup.exe"; inst.write_text("")
    log = tmp_path/"setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")
    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)
    # force psutil.Popen to raise
    monkeypatch.setattr(psutil, "Popen", lambda *a, **k: (_ for _ in ()).throw(Exception("fail")))
    monkeypatch.setenv("PYTEST_RUNNING", "1")
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(tmp_path/"out"),
        "-s", "0",
        "-d", "0",
    ])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    out = capsys.readouterr().out
    assert "could not launch installer" in out
    assert exc.value.code == 0

def test_total_size_gb(tmp_path):
    d = tmp_path/"data"; d.mkdir()
    (d/"a.bin").write_bytes(b"x"*1024)               # 1 KiB
    sub = d/"sub"; sub.mkdir()
    (sub/"b.bin").write_bytes(b"x"*1024*1024)        # 1 MiB
    size = ri.total_size_gb(d)
    expected = (1024 + 1024*1024)/(1024**3)
    assert pytest.approx(size, rel=1e-3) == expected

def test_format_line():
    txt = "2025-05-10 12:34:56.789   Hello world"
    out = ri.format_line(txt)
    assert "Hello world" in out.plain
    assert any(span.style=="grey50" for span in out._spans)
    assert any(span.style=="bright_blue" for span in out._spans)

def test_file_count(tmp_path):
    d = tmp_path/"data"; d.mkdir()
    (d/"a.txt").write_text("x")
    sub = d/"sub"; sub.mkdir()
    (sub/"b.txt").write_text("y")
    assert ri.file_count(d) == 2

def test_pick_log_path(tmp_path):
    inst = tmp_path/"setup.exe"; inst.write_text("")
    p1 = ri.pick_log_path(inst)
    assert p1.name=="setup.log"
    p1.write_text("x")
    p2 = ri.pick_log_path(inst)
    assert p2.name=="setup_2.log"
    (tmp_path/"setup_2.log").write_text("x")
    p3 = ri.pick_log_path(inst)
    assert p3.name=="setup_3.log"

def test_list_options(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run_installers.py","-i","foo","-l"])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    assert exc.value.code==0
    out = capsys.readouterr().out
    assert "Available Inno Setup Flags" in out
    assert "/VERYSILENT" in out

def test_missing_installer(tmp_path, monkeypatch, capsys):
    inst = tmp_path/"no_such.exe"
    monkeypatch.setattr(sys, "argv", ["run_installers.py","-i",str(inst),"-t",str(tmp_path/"out")])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    out = capsys.readouterr().out
    assert "Installer not found" in out
    assert exc.value.code==1

def test_missing_target(tmp_path, monkeypatch, capsys):
    inst = tmp_path/"setup.exe"; inst.write_text("")
    monkeypatch.setattr(sys, "argv", ["run_installers.py","-i",str(inst)])
    with pytest.raises(SystemExit) as exc:
        ri.main()
    out = capsys.readouterr().out
    assert "--target is required" in out
    assert exc.value.code==1

def test_format_line_no_timestamp():
    """Lines without a timestamp should be styled entirely white."""
    line = "This is just a plain message"
    out = ri.format_line(line)
    assert out.plain == line
    # All spans should carry the 'white' style
    assert all(span.style == "white" for span in out._spans)

def test_exit_code_propagation(monkeypatch, tmp_path, capsys):
    """
    If the installer process returns a non-zero exit code via .wait(),
    main() should sys.exit() with that exact code.
    """
    inst = tmp_path / "setup.exe"
    inst.write_text("")
    target = tmp_path / "out"
    target.mkdir()
    log = tmp_path / "setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")

    # Force pick_log_path to our pre-made log
    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)

    # Monkey-patch Popen to return a process with returncode=42
    monkeypatch.setattr(psutil, "Popen", lambda *args, **kwargs: FakeExitProc(42))

    # Run with force so existing target doesn't abort
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(target),
        "-F",            # force-install
        "-s", "0",       # status-interval
        "-d", "0"        # exit-delay
    ])

    with pytest.raises(SystemExit) as exc:
        ri.main()
    assert exc.value.code == 42

def test_unattended_flag_inclusion(monkeypatch, tmp_path, capsys):
    """
    -u should inject /VERYSILENT into the Running: command,
    and omitting -u should not.
    """
    inst = tmp_path / "setup.exe"
    inst.write_text("")
    target = tmp_path / "out"
    target.mkdir()
    log = tmp_path / "setup.log"
    log.write_text(f"2025-05-10 00:00:00.000   {ri.FINAL_LOG_MARKER}\n")
    monkeypatch.setattr(ri, "pick_log_path", lambda _: log)

    # Dummy process that immediately exits
    class DummyProc:
        def __init__(self): self.pid = 1
        def children(self, recursive=True): return []
        def wait(self, timeout=None): return 0
    monkeypatch.setattr(psutil, "Popen", lambda *a, **k: DummyProc())

    # with -u
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(target),
        "-F",
        "-u",
        "-s", "0",
        "-d", "0"
    ])
    with pytest.raises(SystemExit):
        ri.main()
    out = capsys.readouterr().out
    assert "/VERYSILENT" in out

    # without -u
    monkeypatch.setattr(sys, "argv", [
        "run_installers.py",
        "-i", str(inst),
        "-t", str(target),
        "-F",
        "-s", "0",
        "-d", "0"
    ])
    with pytest.raises(SystemExit):
        ri.main()
    out2 = capsys.readouterr().out
    assert "/VERYSILENT" not in out2
