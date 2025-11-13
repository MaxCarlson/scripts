# tests/test_installer.py
import mypysetup.installer as inst

def test_status_uses_checkers(monkeypatch):
    monkeypatch.setattr(inst, "check_uv", lambda: "/x/uv")
    monkeypatch.setattr(inst, "check_pipx", lambda: "/x/pipx")
    monkeypatch.setattr(inst, "check_micromamba", lambda: None)
    s = inst.status()
    assert s["uv"] == "/x/uv"
    assert s["pipx"] == "/x/pipx"
    assert s["micromamba"] is None
    assert "user_bins" in s and isinstance(s["user_bins"], list)

def test_install_missing_idempotent(monkeypatch):
    monkeypatch.setattr(inst, "install_uv", lambda: (True, "/x/uv", "already"))
    monkeypatch.setattr(inst, "install_pipx", lambda: (True, "/x/pipx", "already"))
    monkeypatch.setattr(inst, "install_micromamba", lambda: (True, "/x/mm", "already"))
    res = inst.install_missing()
    assert res["uv"]["ok"] and res["uv"]["path"] == "/x/uv"
    assert res["pipx"]["ok"] and res["pipx"]["path"] == "/x/pipx"
    assert res["micromamba"]["ok"] and res["micromamba"]["path"] == "/x/mm"

def test_check_py_alignment(monkeypatch):
    # Simulate python and py different executables
    monkeypatch.setattr(inst, "which", lambda exe: "/x/python" if exe in ("python","python3") else ("/x/py" if exe=="py" else None))
    monkeypatch.setattr(inst, "call", lambda cmd: (0, "C:/A/python.exe" if (isinstance(cmd,list) and cmd[0] in ("python","python3")) else (0, "C:/B/python.exe") if (isinstance(cmd,list) and cmd[0]=="py") else (0,"","")) )
    res = inst.check_py_alignment()
    assert res["aligned"] is False
    assert res["python"].endswith("python.exe")
    assert res["py"].endswith("python.exe")

