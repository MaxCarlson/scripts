"""
Configuration and executable detection for shell environments.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict


@dataclass
class ExecutablePaths:
    pwsh: str = ""
    powershell: str = ""
    terminal: str = ""

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutablePaths:
        return cls(
            pwsh=str(data.get("pwsh", "")),
            powershell=str(data.get("powershell", "")),
            terminal=str(data.get("terminal", "")),
        )


@dataclass
class SchedulerConfig:
    executables: ExecutablePaths = field(default_factory=ExecutablePaths)
    log_retention_runs: int = 10
    notifications_enabled: bool = True
    notify_on_run: bool = True
    notify_on_success: bool = True
    notify_on_failure: bool = True
    system_log_relative_path: str = "logs/system.log"
    tasks_log_relative_path: str = "logs/tasks"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "executables": self.executables.to_dict(),
            "log_retention_runs": self.log_retention_runs,
            "notifications_enabled": self.notifications_enabled,
            "notify_on_run": self.notify_on_run,
            "notify_on_success": self.notify_on_success,
            "notify_on_failure": self.notify_on_failure,
            "system_log_relative_path": self.system_log_relative_path,
            "tasks_log_relative_path": self.tasks_log_relative_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SchedulerConfig:
        exec_data = data.get("executables", {})
        execs = ExecutablePaths.from_dict(exec_data) if isinstance(exec_data, dict) else ExecutablePaths()
        return cls(
            executables=execs,
            log_retention_runs=int(data.get("log_retention_runs", 10)),
            notifications_enabled=bool(data.get("notifications_enabled", True)),
            notify_on_run=bool(data.get("notify_on_run", True)),
            notify_on_success=bool(data.get("notify_on_success", True)),
            notify_on_failure=bool(data.get("notify_on_failure", True)),
            system_log_relative_path=data.get("system_log_relative_path", "logs/system.log"),
            tasks_log_relative_path=data.get("tasks_log_relative_path", "logs/tasks"),
        )


class ConfigManager:
    """Detects and manages executable paths and configuration."""

    @staticmethod
    def detect_executables() -> ExecutablePaths:
        """Auto-detect absolute paths to pwsh, powershell, and the default terminal."""
        is_windows = os.name == "nt"

        # 1. Detect pwsh (PowerShell 7+ / Core)
        pwsh_path = shutil.which("pwsh") or shutil.which("pwsh.exe") or ""
        if not pwsh_path and is_windows:
            possible_pwsh = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PowerShell" / "7" / "pwsh.exe"
            if possible_pwsh.is_file():
                pwsh_path = str(possible_pwsh)

        # 2. Detect Windows PowerShell (powershell.exe)
        powershell_path = ""
        if is_windows:
            powershell_path = shutil.which("powershell.exe") or shutil.which("powershell") or ""
            if not powershell_path:
                windir = os.environ.get("WINDIR", r"C:\Windows")
                candidate = Path(windir) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
                if candidate.is_file():
                    powershell_path = str(candidate)
        else:
            # Under WSL or Linux, check if powershell.exe is accessible via interop
            powershell_exe = shutil.which("powershell.exe")
            if powershell_exe:
                powershell_path = powershell_exe
            elif Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe").is_file():
                powershell_path = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
            elif pwsh_path:
                # If Windows PowerShell is unavailable, fallback gracefully to pwsh
                powershell_path = pwsh_path

        # 3. Detect standard terminal
        terminal_path = ""
        if is_windows:
            terminal_path = shutil.which("cmd.exe") or os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
            if not Path(terminal_path).is_file():
                terminal_path = powershell_path or pwsh_path
        else:
            shell_env = os.environ.get("SHELL")
            if shell_env and shutil.which(shell_env):
                terminal_path = shell_env
            else:
                for candidate in ("bash", "zsh", "sh"):
                    found = shutil.which(candidate)
                    if found:
                        terminal_path = found
                        break
            if not terminal_path:
                terminal_path = "/bin/sh"

        # Resolve to absolute paths if found
        if pwsh_path:
            pwsh_path = str(Path(pwsh_path).resolve())
        if powershell_path:
            powershell_path = str(Path(powershell_path).resolve())
        if terminal_path:
            terminal_path = str(Path(terminal_path).resolve())

        return ExecutablePaths(
            pwsh=pwsh_path,
            powershell=powershell_path,
            terminal=terminal_path,
        )

    @classmethod
    def create_default_config(cls) -> SchedulerConfig:
        paths = cls.detect_executables()
        return SchedulerConfig(executables=paths)
