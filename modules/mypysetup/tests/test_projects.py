# tests/test_projects.py
from pathlib import Path
import sys
import mypysetup.projects as projects

def test_create_project_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = projects.create_project("p1", kind="none")
    assert (tmp_path/"p1"/"README.md").exists()
    assert (tmp_path/"p1"/"pyproject.toml").exists()

def test_create_project_venv_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(projects, "which", lambda exe: sys.executable if exe in ("python","python3") else None)
    monkeypatch.setattr(projects, "call", lambda cmd: (0,"",""))
    r = projects.create_project("p2", kind="venv", venv_dir=".venv")
    assert any("Created venv at" in m for m in r["messages"])

def test_create_project_uv_sync_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(projects, "which", lambda exe: "/usr/bin/uv" if exe=="uv" else sys.executable)
    calls = []
    def fake_call(cmd):
        calls.append(cmd)
        # uv init ok, uv sync fails
        if isinstance(cmd, list) and cmd[:2]==["uv","init"]:
            return 0,"",""
        if isinstance(cmd, list) and cmd[:2]==["uv","sync"]:
            return 1,"","boom"
        return 0,"",""
    monkeypatch.setattr(projects, "call", fake_call)
    r = projects.create_project("p3", kind="uv")
    assert any("uv sync failed" in m for m in r["messages"])

