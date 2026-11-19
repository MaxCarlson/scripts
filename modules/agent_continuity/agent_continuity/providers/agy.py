"""Antigravity CLI (agy) provider adapter (Phase 1 read-only detection & resume command foundation)."""

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
            phase="phase2_hooks",
            install_detection=True,
            resume_command_generation=True,
            hook_event_normalization=True,
            hook_installation=True,
            session_discovery=True,
            history_scan=False,
            notes=[
                "Phase 0/2 verified agy 1.5.12 (Windows) and 1.2.11 (WSL2) support `agy --conversation <ID>`.",
                "PreInvocation is the primary cross-version hook (SessionStart is absent in 1.2.11).",
                "CLI (`antigravity-cli/`) and Desktop/2.0 (`antigravity/`) stores are distinct surfaces.",
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
        conv_id = str(raw_event.get("conversationId") or "").strip()
        if not conv_id:
            raise ContinuityError(
                ErrorCode.HOOK_SCHEMA_MISMATCH,
                "AGY hook payload missing required 'conversationId'.",
            )

        native_event = str(raw_event.get("hookEventName") or event_name_hint or "").strip()
        if not native_event:
            if "terminationReason" in raw_event or "executionNum" in raw_event:
                native_event = "Stop"
            elif "invocationNum" in raw_event or "lastUserInput" in raw_event:
                native_event = "PreInvocation"
            else:
                raise ContinuityError(
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    "AGY hook payload missing 'hookEventName' and could not infer event type.",
                )

        cwd_val = raw_event.get("cwd")
        if not isinstance(cwd_val, str) or not cwd_val.strip():
            ws_paths = raw_event.get("workspacePaths")
            if isinstance(ws_paths, list) and ws_paths and isinstance(ws_paths[0], str):
                cwd_val = ws_paths[0]
            else:
                cwd_val = None
        cwd_str = cwd_val.strip() if isinstance(cwd_val, str) and cwd_val.strip() else None

        transcript = raw_event.get("transcriptPath")
        transcript_str = str(transcript).strip() if isinstance(transcript, str) and transcript.strip() else None
        surface = "antigravity-cli"
        if transcript_str:
            lower_t = transcript_str.replace("\\", "/").lower()
            if "/antigravity-ide/" in lower_t:
                surface = "antigravity-ide"
            elif "/antigravity/" in lower_t and "/antigravity-cli/" not in lower_t:
                surface = "antigravity"

        marker: str | None = None
        conflict_markers: list[str] = []
        turn_id: str | None = None
        metadata: dict[str, Any] = {}

        if "invocationNum" in raw_event and raw_event["invocationNum"] is not None:
            turn_id = f"inv_{raw_event['invocationNum']}"
            metadata["invocation_num"] = raw_event["invocationNum"]
        if "initialNumSteps" in raw_event and raw_event["initialNumSteps"] is not None:
            metadata["initial_num_steps"] = raw_event["initialNumSteps"]

        prompt_text = raw_event.get("lastUserInput")
        if native_event == "SessionStart":
            norm_type = NormalizedHookType.SESSION_CREATED.value
        elif native_event == "PreInvocation":
            norm_type = NormalizedHookType.TURN_SUBMITTED.value
            if isinstance(prompt_text, str):
                parsed = parse_workflow_markers(prompt_text)
                marker = parsed.marker
                if parsed.conflict:
                    conflict_markers = parsed.markers_found
                if parsed.ignored_malformed:
                    metadata["ignored_malformed_markers"] = parsed.ignored_malformed
        elif native_event == "PostInvocation":
            norm_type = NormalizedHookType.SESSION_OBSERVED.value
        elif native_event == "Stop":
            norm_type = NormalizedHookType.TURN_COMPLETED.value
            if raw_event.get("terminationReason"):
                metadata["termination_reason"] = str(raw_event["terminationReason"])
            if raw_event.get("executionNum") is not None:
                metadata["execution_num"] = raw_event["executionNum"]
            if raw_event.get("continuationActive") is not None:
                metadata["continuation_active"] = bool(raw_event["continuationActive"])
        else:
            norm_type = NormalizedHookType.SESSION_OBSERVED.value
            metadata["unmapped_native_event"] = native_event

        obs_ts = observed_timestamp or now_utc_iso()
        return NormalizedHookEvent(
            provider=self.provider_name,
            environment_id=environment_id,
            native_session_id=conv_id,
            native_event_type=native_event,
            normalized_event_type=norm_type,
            event_id=generate_id("evt"),
            event_schema_version=1,
            source_timestamp=None,
            observed_timestamp=obs_ts,
            source_adapter_version="0.2.0",
            workflow_marker=marker,
            workflow_markers_conflict=conflict_markers,
            turn_id=turn_id,
            cwd=cwd_str,
            transcript_path=transcript_str,
            surface=surface,
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
