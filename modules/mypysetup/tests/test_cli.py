# tests/test_cli.py
import io
import os
import sys
from pathlib import Path
import types
import mypysetup.cli as cli
import mypysetup.installer as inst
import mypysetup.projects as projects

def run_cli(args, monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    rc = cli.main(args)
    out = buf.getvalue()
    return rc, out

def test_print_cmds_linux(monkeypatch):
    monkeypatch.setattr(inst.sysu, "os_name", "linux", raising=False)
    rc, out = run_cli(["-p"], monkeypatch)
    assert rc == 0
    assert "Basic commands for linux" in out
    assert "uv add requests" in out

def test_print_cmds_windows(monkeypatch):
    monkeypatch.setattr(inst.sysu, "os_name", "windows", raising=False)
    rc, out = run_cli(["-p"], monkeypatch)
    assert rc == 0
    assert "Basic commands for windows" in out
    assert "py -m pipx install ruff" in out

def test_status_aggregates(monkeypatch):
    monkeypatch.setattr(inst, "check_uv", lambda: "C:/User/bin/uv.exe")
    monkeypatch.setattr(inst, "check_pipx", lambda: "C:/User/bin/pipx.exe")
    monkeypatch.setattr(inst, "check_micromamba", lambda: None)
    rc, out = run_cli(["-S"], monkeypatch)
    assert rc == 0
    assert "uv: C:/User/bin/uv.exe" in out
    assert "pipx: C:/User/bin/pipx.exe" in out

def test_install_reports(monkeypatch, tmp_path):
    # Pretend python exists
    monkeypatch.setattr(inst, "which", lambda exe: "C:/py.exe" if exe in ("python","python3","pwsh") else None)
    monkeypatch.setattr(inst, "ensure_global_python", lambda: "C:/py.exe")
    monkeypatch.setattr(inst, "install_uv", lambda: (True, "C:/uv.exe", "already"))
    monkeypatch.setattr(inst, "install_pipx", lambda: (True, "C:/pipx.exe", "already"))
    monkeypatch.setattr(inst, "install_micromamba", lambda: (True, "C:/mm.exe", "installed"))
    monkeypatch.setattr(inst.sysu, "os_name", "windows", raising=False)
    rc, out = run_cli(["-I"], monkeypatch)
    assert rc == 0
    assert "uv:" in out and "pipx:" in out and "micromamba:" in out

def test_cli_create_uv_fallback_to_venv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # uv missing
    monkeypatch.setattr(projects, "which", lambda exe: None if exe=="uv" else sys.executable)
    # venv succeeds
    def fake_call(cmd):
        return 0, "", ""
    monkeypatch.setattr(projects, "call", fake_call)
    rc, out = run_cli(["-C","demo","-k","uv","-V",".venv"], monkeypatch)
    assert rc == 0
    assert "uv not found; falling back to stdlib venv." in out
    assert (tmp_path/"demo"/".venv").exists() is False  # venv creation is simulated only

def test_cli_create_uv_ok(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    seq = []
    monkeypatch.setattr(projects, "which", lambda exe: "/usr/bin/uv" if exe=="uv" else sys.executable)
    def fake_call(cmd):
        seq.append(cmd if isinstance(cmd,str) else " ".join(cmd))
        return 0, "", ""
    monkeypatch.setattr(projects, "call", fake_call)
    rc, out = run_cli(["-C","demo","-k","uv"], monkeypatch)
    assert rc == 0
    assert "uv project initialized and synced." in out
    assert any("uv init" in s for s in seq)
    assert any("uv sync" in s for s in seq)

def test_patch_profile_skip_when_present(monkeypatch, tmp_path):
    # Make a temp profile file containing markers
    profile = tmp_path/"profile.ps1"
    profile.write_text('export PATH="$HOME/.local/bin:$PATH"\n(& uv generate-shell-completion powershell) | Out-String | Invoke-Expression\n', encoding="utf-8")
    # Force windows path selection
    monkeypatch.setattr(inst.sysu, "os_name", "windows", raising=False)
    monkeypatch.setattr(inst, "profile_paths", lambda: (profile, None))
    # Auto-input "n" to avoid appending
    monkeypatch.setattr(cli, "input", lambda *a, **k: "n")
    rc, out = run_cli(["-P"], monkeypatch)
    assert rc == 0
    assert "[SKIP] Detected similar lines already in profile." in out
