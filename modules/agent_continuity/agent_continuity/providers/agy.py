"""Antigravity CLI (agy) provider adapter (Phase 1 read-only detection & resume command foundation)."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..models import Provider
from .base import ProviderAdapter, ProviderCapabilities, ProviderInstallation, ResumePlan


def _format_cmd_display(argv: list[str], *, runtime_kind: str) -> str:
    if runtime_kind == "windows" or (not runtime_kind and os.name == "nt"):
        parts = []
        for arg in argv:
            if any(ch.isspace() or ch in "\"'`$" for ch in arg):
                parts.append('"' + arg.replace('"', '\\"') + '"')
            else:
                parts.append(arg)
        return " ".join(parts)
    return shlex.join(argv)


class AgyAdapter(ProviderAdapter):
    """Read-only Phase 1 adapter for Antigravity CLI (`agy`)."""

    provider_name = Provider.AGY.value

    def __init__(
        self,
        *,
        which_fn: Callable[[str], str | None] = shutil.which,
        home_dir: Path | None = None,
    ) -> None:
        self._which = which_fn
        self._home_dir = home_dir or Path.home()

    def detect_installation(self) -> ProviderInstallation:
        exe = self._which("agy")
        native_home = self._home_dir / ".gemini" / "antigravity-cli"
        if not native_home.exists():
            alt_home = self._home_dir / ".gemini" / "antigravity"
            native_home_str = str(alt_home) if alt_home.exists() else None
        else:
            native_home_str = str(native_home)
        if not exe:
            return ProviderInstallation(
                provider=self.provider_name,
                installed=False,
                runnable=False,
                executable_path=None,
                version=None,
                native_home=native_home_str,
                detail="agy executable not found on PATH",
            )
        try:
            proc = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if proc.returncode == 0 and out:
                return ProviderInstallation(
                    provider=self.provider_name,
                    installed=True,
                    runnable=True,
                    executable_path=exe,
                    version=out.splitlines()[0].strip(),
                    native_home=native_home_str,
                    detail="Verified via `agy --version`",
                )
            msg = err.splitlines()[0].strip() if err else f"exit code {proc.returncode}"
            return ProviderInstallation(
                provider=self.provider_name,
                installed=True,
                runnable=False,
                executable_path=exe,
                version=None,
                native_home=native_home_str,
                detail=f"agy found at {exe} but failed version check: {msg}",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ProviderInstallation(
                provider=self.provider_name,
                installed=True,
                runnable=False,
                executable_path=exe,
                version=None,
                native_home=native_home_str,
                detail=f"Failed to invoke agy: {exc}",
            )

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.provider_name,
            phase="phase1_foundation",
            install_detection=True,
            resume_command_generation=True,
            hook_event_normalization=False,
            hook_installation=False,
            session_discovery=False,
            history_scan=False,
            notes=[
                "Phase 0 verified agy 1.5.12 (Windows) and 1.2.11 (WSL2) support `agy --conversation <ID>`.",
                "CLI (`antigravity-cli/`) and Desktop/2.0 (`antigravity/`) stores are distinct surfaces.",
                "Hook installation and automatic discovery deferred to Phase 2.",
            ],
        )

    def resolve_resume_command(
        self,
        native_session_id: str,
        *,
        cwd: str | None = None,
        environment_id: str = "",
        runtime_kind: str = "",
    ) -> ResumePlan:
        argv = ["agy", "--conversation", native_session_id]
        notes = "Verified syntax for agy CLI (`agy --conversation <ID>`)."
        if cwd:
            notes += f" Run from working directory: {cwd}"
        return ResumePlan(
            provider=self.provider_name,
            native_session_id=native_session_id,
            environment_id=environment_id,
            argv=argv,
            cwd=cwd,
            display_command=_format_cmd_display(argv, runtime_kind=runtime_kind),
            supported=True,
            notes=notes,
        )
