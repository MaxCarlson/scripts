# conftest.py — shared pytest fixtures for pwsh_pathmgr tests
from __future__ import annotations
import os
import sys
import shutil
import platform
from pathlib import Path
import subprocess
import textwrap
import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """
    Path to the scripts repo root (where setup.py lives).
    Test files live under: pwsh/tests/pwsh_pathmgr/
    """
    # conftest.py: pwsh/tests/pwsh_pathmgr/conftest.py
    # repo_root is two levels up from pwsh/tests/pwsh_pathmgr
    return Path(__file__).resolve().parents[3]  # -> <repo>/scripts


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """
    Isolated HOME/USERPROFILE so nothing touches the real machine/user PATH.
    """
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    # Windows-style locations used by some tools
    (home / "AppData" / "Roaming").mkdir(parents=True, exist_ok=True)
    (home / "AppData" / "Local").mkdir(parents=True, exist_ok=True)

    # POSIX
    monkeypatch.setenv("HOME", str(home))
    # Windows-style envs (so code that checks them stays sandboxed)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOMEPATH", str(home))
    monkeypatch.setenv("HOMEDRIVE", "")
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))

    # Give each test its own temp PATH that won’t affect the runner
    monkeypatch.setenv("PATH", os.defpath or "/usr/bin:/bin")
    return home


@pytest.fixture
def set_shell(monkeypatch):
    """
    Helper to simulate the current shell for POSIX-profile tests.
    Default to the runner’s shell, but make it overrideable.
    Usage inside tests:
        set_shell("/bin/zsh")  or  set_shell("/bin/bash")
    """
    def _apply(shell_path: str | None = None):
        if not shell_path:
            shell_path = os.environ.get("SHELL", "/bin/sh")
        monkeypatch.setenv("SHELL", shell_path)
        # also hint some tools
        if shell_path.endswith("zsh"):
            monkeypatch.setenv("ZDOTDIR", str(Path.home()))
        if shell_path.endswith("fish"):
            monkeypatch.setenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return _apply


@pytest.fixture
def cli(repo_root, fake_home, monkeypatch):
    """
    Returns a callable to run the pwsh_pathmgr CLI with args and isolated env.

    Usage:
        result = cli("-h")
        assert result.returncode == 0
        print(result.stdout)
    """
    # Where the CLI lives
    candidate_paths = [
        repo_root / "pyscripts" / "pwsh_pathmgr.py",
        repo_root / "pyscripts" / "pwsh-pathmgr.py",
        repo_root / "pyscripts" / "pwsh_pathmgr",
    ]
    script = next((p for p in candidate_paths if p.exists()), None)
    if script is None:
        pytest.skip("pwsh_pathmgr script not found in <repo>/pyscripts/")

    def _run(*args: str, input_data: str | None = None, extra_env: dict[str, str] | None = None):
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("NO_COLOR", "1")

        if extra_env:
            env.update(extra_env)

        # Ensure our repo modules are importable if the CLI does local imports
        pythonpath = [str(repo_root), str(repo_root / "modules")]
        if env.get("PYTHONPATH"):
            pythonpath.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(pythonpath)

        cmd = [sys.executable, str(script)]
        cmd.extend(args)

        return subprocess.run(
            cmd,
            input=input_data,
            text=True,
            capture_output=True,
            env=env,
        )

    return _run


# --- Optional convenience fixtures some tests may reference elsewhere ---

@pytest.fixture
def user_path(monkeypatch, tmp_path):
    """
    A mutable, fake 'User PATH' for tests that want to simulate persistence
    without touching the real registry or OS.
    Provided as a simple semicolon-string in env USER_PATH_FAKE.
    """
    initial = "C:\\Tools;C:\\MyApp\\bin" if platform.system() == "Windows" else "/usr/local/bin:/usr/bin"
    monkeypatch.setenv("USER_PATH_FAKE", initial)
    return initial


@pytest.fixture
def zshrc(fake_home) -> Path:
    """
    A fake ~/.zshrc path in the isolated HOME for profile-writing tests.
    """
    z = fake_home / ".zshrc"
    if not z.exists():
        z.write_text("# test zshrc\n", encoding="utf-8")
    return z
