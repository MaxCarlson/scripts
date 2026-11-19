"""Codex CLI provider adapter (Phase 1 read-only detection & resume command foundation)."""

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


class CodexAdapter(ProviderAdapter):
    """Read-only Phase 1 adapter for OpenAI Codex CLI."""

    provider_name = Provider.CODEX.value

    def __init__(
        self,
        *,
        which_fn: Callable[[str], str | None] = shutil.which,
        home_dir: Path | None = None,
    ) -> None:
        self._which = which_fn
        self._home_dir = home_dir or Path.home()

    def detect_installation(self) -> ProviderInstallation:
        exe = self._which("codex")
        native_home = self._home_dir / ".codex"
        native_home_str = str(native_home) if native_home.exists() else None
        if not exe:
            return ProviderInstallation(
                provider=self.provider_name,
                installed=False,
                runnable=False,
                executable_path=None,
                version=None,
                native_home=native_home_str,
                detail="codex executable not found on PATH",
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
                    detail="Verified via `codex --version`",
                )
            msg = err.splitlines()[0].strip() if err else f"exit code {proc.returncode}"
            return ProviderInstallation(
                provider=self.provider_name,
                installed=True,
                runnable=False,
                executable_path=exe,
                version=None,
                native_home=native_home_str,
                detail=f"codex found at {exe} but failed version check: {msg}",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ProviderInstallation(
                provider=self.provider_name,
                installed=True,
                runnable=False,
                executable_path=exe,
                version=None,
                native_home=native_home_str,
                detail=f"Failed to invoke codex: {exc}",
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
                "Phase 0 verified codex-cli 0.170.0 supports `codex resume <SESSION_ID>` and `hooks` feature.",
                "Hook installation and automatic discovery deferred to Phase 2.",
                "Bounded historical scan deferred to Phase 3.",
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
        argv = ["codex", "resume"]
        if cwd:
            argv.extend(["-C", cwd])
        argv.append(native_session_id)
        return ResumePlan(
            provider=self.provider_name,
            native_session_id=native_session_id,
            environment_id=environment_id,
            argv=argv,
            cwd=cwd,
            display_command=_format_cmd_display(argv, runtime_kind=runtime_kind),
            supported=True,
            notes="Verified syntax for codex-cli (`codex resume [-C <DIR>] <SESSION_ID>`).",
        )
