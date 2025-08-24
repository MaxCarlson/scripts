import os, platform, stat
from pathlib import Path
import pytest

def test_install_is_idempotent(repo_root, fake_home, cli, set_shell):
    set_shell("bash")
    t = str(repo_root / "scripts" / "bin")
    first = cli(["-i","-t",t]); assert first.returncode == 0
    second = cli(["-i","-t",t]); assert second.returncode == 0
    content = (fake_home / ".bashrc").read_text()
    assert content.count("BEGIN pathctl") == 1
    assert content.count(t) == 1

def test_uninstall_without_install_is_safe(repo_root, fake_home, cli, set_shell):
    set_shell("bash")
    p = cli(["-u","-t", str(repo_root/"scripts"/"bin")])
    assert p.returncode == 0  # noop, but OK

def test_write_failure_rolls_back(repo_root, fake_home, cli, set_shell, monkeypatch):
    set_shell("bash")
    prof = fake_home / ".bashrc"
    # Make profile read-only to simulate permission error
    prof.chmod(stat.S_IREAD)
    p = cli(["-i","-t", str(repo_root/"scripts"/"bin")])
    assert p.returncode != 0
    # content must be unchanged
    assert "pathctl" not in prof.read_text()
