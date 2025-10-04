from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from cross_platform.system_utils import SystemUtils
except Exception:
    # Fallback: minimal detection without cross_platform
    class SystemUtils:  # type: ignore
        @staticmethod
        def is_wsl2() -> bool:
            try:
                import platform
                rel = platform.uname().release
                return "microsoft" in rel.lower()
            except Exception:
                return False

        @staticmethod
        def is_termux() -> bool:
            return os.environ.get("ANDROID_ROOT", "").startswith("/data/data/") or \
                   "/data/data/com.termux" in (os.environ.get("HOME", ""))

        @staticmethod
        def is_windows() -> bool:
            return os.name == "nt"

        @staticmethod
        def is_linux() -> bool:
            return sys.platform.startswith("linux")


@dataclass
class EnvStatus:
    uv: str | None
    pipx: str | None
    micromamba: str | None


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def detect_status() -> EnvStatus:
    return EnvStatus(
        uv=which("uv"),
        pipx=which("pipx"),
        micromamba=which("micromamba") or which("mamba") or which("conda"),
    )


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, check=check)


def ensure_uv(su: SystemUtils) -> tuple[bool, str]:
    """Try to ensure uv is available. Returns (changed, message)."""
    if which("uv"):
        return False, "uv present"
    # Best-effort installation hints/commands; do not fail hard if unavailable.
    try:
        if su.is_windows():
            # winget path (if available); otherwise print guidance
            if which("winget"):
                run(["winget", "install", "--id", "AstralSoftware.uv", "-e", "--silent"], check=False)
                return True, "attempted winget install for uv"
            return False, "uv missing; install via winget or installer: https://docs.astral.sh/uv"
        elif su.is_termux():
            # Use pip in Termux environment as a fallback
            run([sys.executable, "-m", "pip", "install", "--upgrade", "uv"], check=False)
            return True, "attempted pip install uv (Termux)"
        else:
            # Ubuntu/WSL2: try pip first; user may replace with official installer later
            run([sys.executable, "-m", "pip", "install", "--upgrade", "uv"], check=False)
            return True, "attempted pip install uv"
    except Exception as e:
        return False, f"uv install attempt failed: {e}"


def ensure_pipx(su: SystemUtils) -> tuple[bool, str]:
    if which("pipx"):
        return False, "pipx present"
    try:
        if su.is_windows():
            if which("winget"):
                run(["winget", "install", "--id", "pipxproject.pipx", "-e", "--silent"], check=False)
                return True, "attempted winget install for pipx"
            return False, "pipx missing; install via winget/choco or pip"
        elif su.is_termux():
            # pipx is not always packaged on Termux; fall back to pip install --user pipx
            run([sys.executable, "-m", "pip", "install", "--upgrade", "pipx"], check=False)
            return True, "attempted pip install pipx (Termux)"
        else:
            # Ubuntu/WSL2
            if which("apt"):  # best-practice: apt install pipx
                run(["sudo", "apt", "update"], check=False)
                run(["sudo", "apt", "install", "-y", "pipx"], check=False)
                return True, "attempted apt install pipx"
            # fallback
            run([sys.executable, "-m", "pip", "install", "--upgrade", "pipx"], check=False)
            return True, "attempted pip install pipx"
    except Exception as e:
        return False, f"pipx install attempt failed: {e}"


def ensure_micromamba(su: SystemUtils) -> tuple[bool, str]:
    # Not on Termux per user requirement.
    if su.is_termux():
        return False, "skip micromamba on Termux"
    if which("micromamba") or which("mamba") or which("conda"):
        return False, "conda/mamba already present"
    # Provide guidance, optionally attempt installer if available
    return False, "micromamba not found; install via https://mamba.readthedocs.io/en/latest/ or package manager"


def best_practices_text() -> str:
    return (
        "Best-practices Python on your system:\n\n"
        "- Use `uv` for fast venvs and installs: `uv venv --seed`, `uv pip install -e <module>`\n"
        "- Use `pipx` to globally expose CLIs in isolated envs: `pipx install <package>`\n"
        "- Optionally use micromamba/conda for heavy native stacks (skip on Termux).\n\n"
        "Workflow:\n"
        "  1) Bootstrap tools (uv, pipx, micromamba if applicable).\n"
        "  2) For this repo: run setup.py to create .venv and wire bin wrappers.\n"
        "  3) For reusable modules: `uv pip install -e /path/to/scripts/modules/<name>` in your project venv.\n"
        "  4) For CLIs (like pyscripts), prefer pipx-packaged entry points for system-wide use.\n"
    )


def bootstrap(verbose: bool = False) -> None:
    su = SystemUtils()
    if verbose:
        print("[python_setup] Detecting environment...")
    status = detect_status()
    if verbose:
        print(f"[python_setup] current: uv={status.uv}, pipx={status.pipx}, conda/mamba={status.micromamba}")

    changed = []
    actions = []
    ch, msg = ensure_uv(su)
    changed.append(ch)
    actions.append(msg)
    ch, msg = ensure_pipx(su)
    changed.append(ch)
    actions.append(msg)
    ch, msg = ensure_micromamba(su)
    changed.append(ch)
    actions.append(msg)

    if verbose:
        for a in actions:
            print(f"[python_setup] {a}")

    # No hard failure if tools couldn’t be auto-installed; guidance is enough
    if verbose:
        print("[python_setup] bootstrap complete.")

