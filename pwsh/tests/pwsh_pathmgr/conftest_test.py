import os, sys, textwrap, subprocess, shutil, stat, platform, json
from pathlib import Path
import pytest

# >>>>> CHANGE ME if your module path differs (module or console_script)
# Supports "module:callable" or a console entrypoint name.
ENTRYPOINT = os.environ.get("PATHCTL_ENTRYPOINT", "python_module:scripts.pyscripts.pathctl:main")

@pytest.fixture
def repo_root(tmp_path):
    """Simulate repo with scripts/bin."""
    root = tmp_path / "repo"
    (root / "scripts" / "bin").mkdir(parents=True)
    # add a dummy executable to simulate bin content
    exe = root / "scripts" / "bin" / "demo-tool"
    exe.write_text("#!/usr/bin/env bash\necho demo\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return root

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Isolate $HOME/$USERPROFILE and common profile locations."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    # common shells
    (home / ".bashrc").write_text("# bashrc\n")
    (home / ".zshrc").write_text("# zshrc\n")
    (home / ".config" / "fish").mkdir(parents=True)
    (home / ".config" / "fish" / "config.fish").write_text("# fish config\n")
    # PowerShell profiles
    psdir = home / "Documents" / "PowerShell"
    psdir.mkdir(parents=True)
    (psdir / "Microsoft.PowerShell_profile.ps1").write_text("# ps profile\n")
    return home

@pytest.fixture
def clean_env(monkeypatch):
    """Start with a minimal env so PATH and SHELL are controlled."""
    keep = {"SYSTEMROOT", "WINDIR", "ProgramFiles", "ProgramFiles(x86)", "NUMBER_OF_PROCESSORS"}
    for k in list(os.environ):
        if k not in keep:
            monkeypatch.delenv(k, raising=False)

@pytest.fixture
def set_shell(monkeypatch):
    def _set(shell_name):
        # typical env hints used by tools
        if platform.system() == "Windows":
            monkeypatch.setenv("ComSpec", r"C:\Windows\System32\cmd.exe")
            if shell_name.lower() == "powershell":
                monkeypatch.setenv("PSModulePath", "1")  # hint
        else:
            monkeypatch.setenv("SHELL", f"/bin/{shell_name}")
    return _set

def _split_entrypoint():
    if ":" not in ENTRYPOINT:
        return ("console", ENTRYPOINT, None)
    kind, rest = ENTRYPOINT.split("_", 1)[0], ENTRYPOINT
    _, module, func = rest.split(":")
    return ("module", module, func)

def run_cli(args, cwd=None, extra_env=None, input=None):
    kind, module, func = _split_entrypoint()
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    if kind == "console":
        cmd = [module] + args  # console_script
    else:
        cmd = [sys.executable, "-c",
               textwrap.dedent(f"""
               import runpy, sys
               mod = __import__("{module}", fromlist=["*"])
               sys.exit(mod.{func}())
               """)]
        cmd += args
    proc = subprocess.run(cmd, cwd=cwd, env=env, input=input, text=True,
                          capture_output=True)
    return proc

@pytest.fixture
def cli():
    return run_cli
