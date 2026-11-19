"""Codex CLI provider adapter (Phase 1 read-only detection & resume command foundation)."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..errors import ContinuityError, ErrorCode
from ..hooks import NormalizedHookEvent, NormalizedHookType
from ..identifiers import generate_id, now_utc_iso
from ..markers import parse_workflow_markers
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
            phase="phase2_hooks",
            install_detection=True,
            resume_command_generation=True,
            hook_event_normalization=True,
            hook_installation=True,
            session_discovery=True,
            history_scan=False,
            notes=[
                "Phase 0/2 verified codex-cli 0.170.0 supports `codex resume <SESSION_ID>` and `hooks` feature.",
                "Supports SessionStart, UserPromptSubmit, Stop, and SessionEnd hook normalization.",
                "Bounded historical rollout scan deferred to Phase 3.",
            ],
        )

    def normalize_hook_event(
        self,
        raw_event: dict[str, Any],
        *,
        environment_id: str,
        observed_timestamp: str | None = None,
        event_name_hint: str | None = None,
    ) -> NormalizedHookEvent:
        session_id = str(raw_event.get("session_id") or "").strip()
        if not session_id:
            raise ContinuityError(
                ErrorCode.HOOK_SCHEMA_MISMATCH,
                "Codex hook payload missing required 'session_id'.",
            )
        native_event = str(raw_event.get("hook_event_name") or event_name_hint or "").strip()
        if not native_event:
            raise ContinuityError(
                ErrorCode.HOOK_SCHEMA_MISMATCH,
                "Codex hook payload missing 'hook_event_name'.",
            )

        source = raw_event.get("source")
        source_str = str(source).strip() if isinstance(source, str) and source.strip() else None
        cwd = raw_event.get("cwd")
        cwd_str = str(cwd).strip() if isinstance(cwd, str) and cwd.strip() else None
        transcript_path = raw_event.get("transcript_path")
        transcript_str = str(transcript_path).strip() if isinstance(transcript_path, str) and transcript_path.strip() else None
        parent_id = raw_event.get("parent_thread_id") or raw_event.get("parent_session_id")
        parent_str = str(parent_id).strip() if isinstance(parent_id, str) and parent_id.strip() else None

        marker: str | None = None
        conflict_markers: list[str] = []
        turn_id: str | None = None
        metadata: dict[str, Any] = {}

        if native_event == "SessionStart":
            if source_str in {"startup", "clear"} or source_str is None:
                norm_type = NormalizedHookType.SESSION_CREATED.value
            else:
                norm_type = NormalizedHookType.SESSION_OBSERVED.value
        elif native_event == "UserPromptSubmit":
            norm_type = NormalizedHookType.TURN_SUBMITTED.value
            turn_id = str(raw_event.get("turn_id") or generate_id("turn"))
            prompt_text = raw_event.get("prompt")
            if isinstance(prompt_text, str):
                parsed = parse_workflow_markers(prompt_text)
                marker = parsed.marker
                if parsed.conflict:
                    conflict_markers = parsed.markers_found
                if parsed.ignored_malformed:
                    metadata["ignored_malformed_markers"] = parsed.ignored_malformed
        elif native_event == "Stop":
            norm_type = NormalizedHookType.TURN_COMPLETED.value
            if raw_event.get("turn_id"):
                turn_id = str(raw_event["turn_id"])
        elif native_event == "SessionEnd":
            norm_type = NormalizedHookType.SESSION_ENDED.value
        else:
            norm_type = NormalizedHookType.SESSION_OBSERVED.value
            metadata["unmapped_native_event"] = native_event

        obs_ts = observed_timestamp or now_utc_iso()
        src_ts = raw_event.get("timestamp")
        src_ts_str = str(src_ts).strip() if isinstance(src_ts, str) and src_ts.strip() else None

        return NormalizedHookEvent(
            provider=self.provider_name,
            environment_id=environment_id,
            native_session_id=session_id,
            native_event_type=native_event,
            normalized_event_type=norm_type,
            event_id=generate_id("evt"),
            event_schema_version=1,
            source_timestamp=src_ts_str,
            observed_timestamp=obs_ts,
            source_adapter_version="0.2.0",
            workflow_marker=marker,
            workflow_markers_conflict=conflict_markers,
            turn_id=turn_id,
            cwd=cwd_str,
            transcript_path=transcript_str,
            source=source_str,
            parent_session_id=parent_str,
            surface="codex-cli",
            metadata=metadata,
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
