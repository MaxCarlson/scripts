from __future__ import annotations

from typing import List, Tuple
from cross_platform.system_utils import SystemUtils
import shutil


def detect_env(sysu: SystemUtils) -> str:
    """Return 'wsl' when running inside WSL Linux kernel, 'windows' for Windows host, 'unsupported' otherwise."""
    if sysu.is_windows():
        return "windows"
    if sysu.is_linux() and sysu.is_wsl2():
        return "wsl"
    return "unsupported"


def compact(
    sysu: SystemUtils,
    *,
    guard_gb: int = 15,
    dry_run: bool = True,
    show_host_instructions: bool = False,
) -> List[str]:
    """Perform or stage WSL compaction steps appropriate to the current environment.

    - In WSL: run fstrim -av (sudo) and print PowerShell guidance for host compaction.
    - On Windows: check free space guard; shutdown WSL; compact the largest ext4.vhdx found using NTFS LZX.
    - Unsupported: return informative message and no action.
    """
    env = detect_env(sysu)
    actions: List[str] = []

    def _run(label: str, cmd: str, *, sudo: bool = False) -> None:
        if dry_run:
            actions.append(f"DRY-RUN: {label}: {cmd}")
            return
        out = sysu.run_command(cmd, sudo=sudo)
        actions.append(f"{label}: {cmd}\n{out}")

    if env == "wsl":
        _run("WSL fstrim", "fstrim -av", sudo=True)
        actions.append("Tip: To reduce host 'size on disk', run 'fsu wsl compact' on Windows, or re-run here with -H to print the script.")
        if show_host_instructions:
            actions.append(
                "On Windows host, run PowerShell to compact the VHDX (guarded):\n"
                f"  $minGB={guard_gb}; $freeGB=([math]::Round((Get-PSDrive C).Free/1GB,2));\n"
                "  if ($freeGB -ge $minGB) { wsl --shutdown;\n"
                "    $vhd=(Get-ChildItem \"$env:LOCALAPPDATA\\wsl\\*\\ext4.vhdx\", \"$env:LOCALAPPDATA\\Packages\\*\\LocalState\\ext4.vhdx\" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName;\n"
                "    if ($vhd) { compact /c /a /f /i /exe:lzx \"$vhd\"; compact /q \"$vhd\" } }\n"
            )
        return actions

    if env == "windows":
        # Guard: ensure enough free space before compaction; use -EncodedCommand to avoid quoting issues.
        ps_exe = shutil.which("pwsh") or shutil.which("powershell") or "pwsh"
        script = (
            f"$min={guard_gb}; $free=[math]::Round((Get-PSDrive C).Free/1GB,2); "
            "if ($free -lt $min) { Write-Output \"Skipping compact: only $free GB free (< $min GB).\" } else { "
            "wsl --shutdown; "
            "$v=(Get-ChildItem \"$env:LOCALAPPDATA\\wsl\\*\\ext4.vhdx\", \"$env:LOCALAPPDATA\\Packages\\*\\LocalState\\ext4.vhdx\", \"$env:LOCALAPPDATA\\Docker\\wsl\\data\\ext4.vhdx\" -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 1).FullName; "
            "if ($v) { compact /c /a /f /i /exe:lzx \"$v\"; compact /q \"$v\" } }"
        )
        import base64 as _b64
        encoded = _b64.b64encode(script.encode("utf-16le")).decode("ascii")
        cmd = f"{ps_exe} -NoProfile -EncodedCommand {encoded}"
        _run("Windows VHDX LZX compact", cmd)
        return actions

    actions.append("Unsupported environment for WSL compaction (not Windows host nor WSL).")
    return actions


def docker_desktop_fixups(sysu: SystemUtils, *, dry_run: bool = True) -> List[str]:
    """Provide actions to switch Docker context to Desktop Linux engine and recover from pipe errors.

    On Windows, this includes terminating WSL backends and restarting Docker Desktop, then using the desktop-linux context.
    """
    actions: List[str] = []

    def _run(label: str, cmd: str) -> None:
        if dry_run:
            actions.append(f"DRY-RUN: {label}: {cmd}")
            return
        out = sysu.run_command(cmd)
        actions.append(f"{label}: {cmd}\n{out}")

    if sysu.is_windows():
        ps = shutil.which("pwsh") or shutil.which("powershell") or "pwsh"
        def PS(cmd: str) -> str:
            return f"{ps} -NoProfile -Command \"{cmd}\""

        _run("Docker contexts", "docker context ls")
        _run("Use desktop-linux", "docker context use desktop-linux")
        # Recovery steps for 500 errors on named pipe — run via PowerShell
        _run(
            "Terminate WSL docker backends",
            PS("wsl --terminate docker-desktop; wsl --terminate docker-desktop-data; wsl --shutdown"),
        )
        _run(
            "Stop Docker Desktop processes",
            PS("Stop-Process -Name 'Docker Desktop','com.docker.*' -Force -ErrorAction SilentlyContinue"),
        )
        _run(
            "Start Docker Desktop",
            PS(r"Start-Process \"$env:ProgramFiles\Docker\Docker\Docker Desktop.exe\""),
        )
        _run("Use desktop-linux", "docker context use desktop-linux")
        _run("Docker df", "docker system df -v")
        return actions

    actions.append("Docker Desktop fixups are only applicable on Windows hosts.")
    return actions
