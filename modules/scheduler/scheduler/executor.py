"""
Task execution engine for pwsh, powershell, and standard terminal environments.
Supports admin elevation toggles and captures duration, exit codes, stdout, and stderr.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .config import SchedulerConfig
from .models import ExecutionResult, ShellEnvironment, Task


class TaskExecutor:
    """Executes task code blocks inside designated shell environments."""

    def __init__(self, config: Optional[SchedulerConfig] = None) -> None:
        self.config = config or SchedulerConfig()

    def update_config(self, config: SchedulerConfig) -> None:
        self.config = config

    def resolve_executable(self, env_name: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve executable for the given environment name.
        Returns (executable_path, error_message).
        """
        env_lower = env_name.lower()
        execs = self.config.executables

        if env_lower == ShellEnvironment.PWSH.value:
            exe = execs.pwsh or shutil.which("pwsh") or shutil.which("pwsh.exe")
            if not exe:
                return None, "PowerShell Core ('pwsh') executable not found. Configure it in settings."
            return str(Path(exe).resolve()), None

        elif env_lower == ShellEnvironment.POWERSHELL.value:
            exe = execs.powershell or shutil.which("powershell.exe") or shutil.which("powershell")
            if not exe:
                # If on Linux/WSL/Termux and powershell.exe isn't available, check if pwsh can serve as fallback
                if execs.pwsh or shutil.which("pwsh"):
                    return str(Path(execs.pwsh or shutil.which("pwsh")).resolve()), None
                return None, "Windows PowerShell ('powershell') executable not found. Configure it in settings."
            return str(Path(exe).resolve()), None

        else:  # ShellEnvironment.TERMINAL or any other
            exe = execs.terminal or os.environ.get("SHELL") or shutil.which("bash") or shutil.which("sh")
            if os.name == "nt" and not exe:
                exe = shutil.which("cmd.exe") or os.environ.get("COMSPEC", "cmd.exe")
            if not exe:
                exe = "/bin/sh" if os.name != "nt" else "cmd.exe"
            return str(Path(exe).resolve()), None

    def execute(self, task: Task, timeout_sec: Optional[float] = None) -> ExecutionResult:
        """
        Execute task script and return an ExecutionResult.
        """
        start_time = time.time()
        timestamp = datetime.now().isoformat()

        exe_path, err = self.resolve_executable(task.environment)
        if err or not exe_path:
            duration = time.time() - start_time
            return ExecutionResult(
                task_name=task.name,
                schedule_name=task.schedule_name,
                timestamp=timestamp,
                exit_code=127,
                stdout="",
                stderr=err or "Executable not found",
                duration_sec=duration,
                environment=task.environment,
                admin=task.admin,
                success=False,
                error_message=err,
            )

        env_lower = task.environment.lower()
        suffix = ".ps1" if env_lower in ("pwsh", "powershell") else (".bat" if os.name == "nt" else ".sh")

        temp_dir = Path(tempfile.gettempdir()) / "scheduler_run"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Create temporary script file
        temp_script: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=suffix, dir=temp_dir, delete=False, encoding="utf-8") as f:
                temp_script = Path(f.name)
                # If POSIX shell script, ensure shebang if missing
                if suffix == ".sh" and not task.code.startswith("#!"):
                    f.write("#!/usr/bin/env sh\n")
                f.write(task.code)
                f.flush()

            # Ensure script is executable on POSIX
            if os.name != "nt" and temp_script.exists():
                try:
                    os.chmod(temp_script, 0o700)
                except OSError:
                    pass

            cmd: List[str] = []

            # ── Construct Command Args ──
            if env_lower in ("pwsh", "powershell"):
                cmd = [
                    exe_path,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(temp_script),
                ]
            elif os.name == "nt" and (exe_path.lower().endswith("cmd.exe") or suffix == ".bat"):
                cmd = [exe_path, "/c", str(temp_script)]
            else:
                cmd = [exe_path, str(temp_script)]

            # ── Admin Elevation Handling ──
            if task.admin:
                if os.name != "nt":
                    # POSIX: check if already root
                    is_root = False
                    if hasattr(os, "geteuid"):
                        is_root = (os.geteuid() == 0)
                    if not is_root and shutil.which("sudo"):
                        cmd = ["sudo", "-n"] + cmd
                else:
                    # Windows: elevation wrapper
                    # If already elevated, can run directly, else Start-Process with RunAs
                    ps_launcher = shutil.which("powershell.exe") or "powershell"
                    inner_args = subprocess.list2cmdline(cmd[1:])
                    elevation_script = (
                        f"Start-Process -FilePath '{cmd[0]}' -ArgumentList '{inner_args}' "
                        f"-Verb RunAs -Wait -PassThru | Select-Object -ExpandProperty ExitCode"
                    )
                    cmd = [ps_launcher, "-NoProfile", "-NonInteractive", "-Command", elevation_script]

            # Execute subprocess
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
            )

            duration = time.time() - start_time
            exit_code = proc.returncode
            success = (exit_code == 0)

            return ExecutionResult(
                task_name=task.name,
                schedule_name=task.schedule_name,
                timestamp=timestamp,
                exit_code=exit_code,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                duration_sec=duration,
                environment=task.environment,
                admin=task.admin,
                success=success,
                error_message=proc.stderr if not success else None,
            )

        except subprocess.TimeoutExpired as te:
            duration = time.time() - start_time
            return ExecutionResult(
                task_name=task.name,
                schedule_name=task.schedule_name,
                timestamp=timestamp,
                exit_code=124,
                stdout=te.stdout or "",
                stderr=f"Task timed out after {timeout_sec} seconds",
                duration_sec=duration,
                environment=task.environment,
                admin=task.admin,
                success=False,
                error_message=f"Timeout after {timeout_sec}s",
            )
        except Exception as ex:
            duration = time.time() - start_time
            return ExecutionResult(
                task_name=task.name,
                schedule_name=task.schedule_name,
                timestamp=timestamp,
                exit_code=1,
                stdout="",
                stderr=str(ex),
                duration_sec=duration,
                environment=task.environment,
                admin=task.admin,
                success=False,
                error_message=str(ex),
            )
        finally:
            if temp_script and temp_script.exists():
                try:
                    temp_script.unlink()
                except OSError:
                    pass
