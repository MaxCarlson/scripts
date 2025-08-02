# tests/test_additional_run_installers.py

import sys
import pytest
import psutil
from pathlib import Path
from datetime import datetime
import run_installers as ri

# --- Helpers for fake processes --- #
class FakeExitProc:
    def __init__(self, returncode):
        self.pid = 1
        self._rc = returncode
    def children(self, recursive=True):
        return []
    def wait(self, timeout=None):
        return self._rc

# --- New tests --- #

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
