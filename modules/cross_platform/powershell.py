"""PowerShell execution helpers for cross-platform callers."""

from __future__ import annotations

import base64
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PowerShellResult:
    """Result from a PowerShell invocation."""

    command: str
    stdout: str
    stderr: str
    returncode: int


def run_powershell(
    script: str,
    *,
    timeout: int = 30,
    prefer_pwsh: bool = True,
    check: bool = False,
) -> PowerShellResult:
    """Run a PowerShell script through pwsh 7 when available.

    The script is passed via -EncodedCommand so callers do not need to quote
    nested PowerShell syntax for the active shell.
    """
    if prefer_pwsh:
        executable = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    else:
        executable = shutil.which("powershell") or shutil.which("pwsh") or "powershell"

    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    cmd = [
        executable,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    result = PowerShellResult(
        command=" ".join(cmd[:5] + ["<encoded>"]),
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
        returncode=proc.returncode,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"PowerShell failed with exit code {result.returncode}: {result.stderr}")
    return result


def run_powershell_text(script: str, *, timeout: int = 30, prefer_pwsh: bool = True) -> str:
    """Run PowerShell and return stdout text for legacy call sites."""
    return run_powershell(script, timeout=timeout, prefer_pwsh=prefer_pwsh).stdout
