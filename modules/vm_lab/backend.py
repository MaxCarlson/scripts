"""Secure subprocess adapter for the packaged vm_lab PowerShell backend."""

from __future__ import annotations

import importlib.resources
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from vm_lab.exceptions import (
    BackendExecutionError,
    BackendResourceError,
    PowerShellNotFoundError,
    UnsupportedPlatformError,
)
from vm_lab.results import BackendResult, classify_exit_code, redact_sensitive


def resolve_backend_root() -> Path:
    """Resolve the directory containing Invoke-VmLab.ps1 and vm_lab.psd1."""
    candidates: list[Path] = []
    try:
        pkg_root = importlib.resources.files("vm_lab")
        candidates.append(Path(str(pkg_root)))
    except Exception:
        pass
    candidates.append(Path(__file__).resolve().parent)

    for candidate in candidates:
        if (candidate / "Invoke-VmLab.ps1").is_file() and (candidate / "vm_lab.psd1").is_file():
            return candidate

    raise BackendResourceError(
        "Packaged vm_lab PowerShell backend files (Invoke-VmLab.ps1, vm_lab.psd1) could not be found."
    )


def resolve_powershell_exe(*, platform_name: str | None = None) -> str:
    """Resolve PowerShell 7 (pwsh) on Windows; fail clearly on unsupported platforms."""
    current_os = platform_name or os.name
    if current_os != "nt":
        raise UnsupportedPlatformError(
            "Hyper-V and PowerShell Direct backend operations require Windows (os.name == 'nt')."
        )
    pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
    if not pwsh:
        raise PowerShellNotFoundError(
            "PowerShell 7 ('pwsh') was not found on PATH. Install PowerShell 7 to run vm_lab operations."
        )
    return pwsh


def _assert_no_secret_args(args: Sequence[str]) -> None:
    for arg in args:
        low = arg.lower()
        if low in {"-password", "--password", "-plaintextpassword", "--plaintext-password"}:
            raise BackendExecutionError(
                "Refusing plaintext password argument on CLI; use -PromptCredential or PowerShell PSCredential."
            )


class BackendAdapter:
    """Executes packaged vm_lab PowerShell entry points safely without shell=True."""

    def __init__(
        self,
        *,
        backend_root: Path | None = None,
        pwsh_exe: str | None = None,
    ) -> None:
        self._backend_root = backend_root
        self._pwsh_exe = pwsh_exe

    @property
    def backend_root(self) -> Path:
        if self._backend_root is None:
            self._backend_root = resolve_backend_root()
        return self._backend_root

    def get_script_path(self, script_name: str = "Invoke-VmLab.ps1") -> Path:
        script_path = self.backend_root / script_name
        if not script_path.is_file():
            raise BackendResourceError(f"Backend script not found: {script_path}")
        return script_path

    def invoke(
        self,
        args: Sequence[str],
        *,
        script_name: str = "Invoke-VmLab.ps1",
        json_mode: bool = True,
        interactive: bool = False,
        timeout_seconds: int | None = None,
    ) -> BackendResult:
        """Invoke the PowerShell backend with shell=False and explicit argument array."""
        _assert_no_secret_args(args)
        pwsh = self._pwsh_exe or resolve_powershell_exe()
        script_path = self.get_script_path(script_name)

        cmd = [pwsh, "-NoProfile", "-File", str(script_path), *[str(a) for a in args]]
        is_wizard = any(str(a).lower() == "wizard" for a in args)
        if interactive and is_wizard:
            proc = subprocess.run(cmd, shell=False, check=False, timeout=timeout_seconds)
            return BackendResult(
                returncode=proc.returncode,
                exit_code=proc.returncode,
                stdout="",
                stderr="",
                data=None,
                command=tuple(cmd),
            )

        run_kwargs: dict[str, object] = {
            "shell": False,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "check": False,
            "timeout": timeout_seconds,
        }
        if interactive:
            # Inherit stdin/stderr for interactive credential prompting while capturing structured stdout
            run_kwargs["stdout"] = subprocess.PIPE
        else:
            run_kwargs["capture_output"] = True

        proc = subprocess.run(cmd, **run_kwargs)  # type: ignore[call-overload]
        stdout = proc.stdout or ""
        stderr = redact_sensitive(proc.stderr or "")
        parsed = None
        stripped = stdout.strip()
        if json_mode and stripped:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise BackendExecutionError(
                    f"Backend returned invalid JSON (exit={proc.returncode}): {exc}. stderr={stderr.strip()}"
                ) from exc
        elif json_mode and stderr.strip() and not stripped:
            try:
                parsed = json.loads(stderr.strip().splitlines()[-1])
            except Exception:
                parsed = None
        elif not json_mode and (stripped.startswith("{") or stripped.startswith("[")):
            try:
                parsed = json.loads(stdout)
            except Exception:
                parsed = None

        exit_code = classify_exit_code(parsed, proc.returncode)
        return BackendResult(
            returncode=proc.returncode,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            data=parsed,
            command=tuple(cmd),
        )
