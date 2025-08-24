import os, sys, platform
from pathlib import Path
import pytest

@pytest.mark.skipif(platform.system() == "Windows", reason="POSIX only")
def test_shell_detection_defaults_to_env_shell(repo_root, fake_home, cli, set_shell):
    set_shell("zsh")
    p = cli(["-i","-t",str(repo_root / "scripts" / "bin")])
    assert p.returncode == 0
    assert (fake_home / ".zshrc").read_text().count("pathctl") >= 1

@pytest.mark.skipif(platform.system() == "Windows", reason="POSIX only")
def test_fish_profile_is_used_when_forced(repo_root, fake_home, cli, set_shell):
    set_shell("bash")  # force mismatch on purpose
    p = cli([
        "-i",
        "-s","fish",
        "-t", str(repo_root / "scripts" / "bin"),
        "-f", str(fake_home / ".config" / "fish" / "config.fish")
    ])
    assert p.returncode == 0
    fish = (fake_home / ".config" / "fish" / "config.fish").read_text()
    assert "set -gx PATH" in fish

@pytest.mark.skipif(platform.system() == "Windows", reason="POSIX only")
def test_profile_override_with_dash_f(repo_root, fake_home, cli, set_shell, tmp_path):
    set_shell("bash")
    custom = tmp_path / "my_profile"
    custom.write_text("# custom profile\n")
    p = cli(["-i","-t",str(repo_root/"scripts"/"bin"), "-f", str(custom)])
    assert p.returncode == 0
    assert "export PATH=" in custom.read_text()
