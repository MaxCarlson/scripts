import os, platform
from pathlib import Path

def test_install_dry_run_shows_changes_only(repo_root, fake_home, cli, set_shell):
    set_shell("bash")
    p = cli(["-i","-n","-t", str(repo_root / "scripts" / "bin")])
    assert p.returncode == 0
    assert "export PATH=" in (p.stdout + p.stderr)

def test_install_persists_in_bashrc(repo_root, fake_home, cli, set_shell):
    set_shell("bash")
    target = repo_root / "scripts" / "bin"
    prof = fake_home / ".bashrc"
    before = prof.read_text()
    p = cli(["-i", "-t", str(target)])
    assert p.returncode == 0, p.stderr
    after = prof.read_text()
    assert after != before
    assert str(target) in after
    assert "# BEGIN pathctl" in after and "# END pathctl" in after

def test_install_then_check_returns_zero(repo_root, fake_home, cli, set_shell):
    set_shell("zsh")
    target = repo_root / "scripts" / "bin"
    cli(["-i","-t",str(target)])
    p = cli(["-c","-t",str(target)])
    assert p.returncode == 0

def test_uninstall_removes_block(repo_root, fake_home, cli, set_shell):
    set_shell("bash")
    target = repo_root / "scripts" / "bin"
    cli(["-i","-t",str(target)])
    p = cli(["-u","-t",str(target)])
    assert p.returncode == 0
    content = (fake_home / ".bashrc").read_text()
    assert "BEGIN pathctl" not in content
    assert str(target) not in content
