"""Optional PowerShell helpers isolated from core logic."""

from __future__ import annotations

import subprocess


def run_powershell(command: str, *, timeout_seconds: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Run a PowerShell command and capture text output."""
    return subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )

