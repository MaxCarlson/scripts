"""Claude Code provider adapter using its supported exact-session CLI flags."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from ..errors import ContinuityError, ErrorCode
from ..models import Provider
from .base import ProviderAdapter, ProviderCapabilities, ProviderInstallation, ResumePlan


class ClaudeAdapter(ProviderAdapter):
    """Claude Code executable discovery, session evidence and command construction."""

    provider_name = Provider.CLAUDE.value

    def __init__(self, *, which_fn: Callable[[str], str | None] = shutil.which,
                 home_dir: Path | None = None) -> None:
        self._which = which_fn
        self._home_dir = home_dir or Path.home()

    def find_executable(self) -> str | None:
        return self._which("claude")

    def _config_dir(self) -> Path:
        configured = os.environ.get("CLAUDE_CONFIG_DIR")
        return Path(configured).expanduser() if configured else self._home_dir / ".claude"

    def detect_installation(self) -> ProviderInstallation:
        executable = self.find_executable()
        native_home = self._config_dir()
        if not executable:
            return ProviderInstallation(
                provider=self.provider_name, installed=False, runnable=False, executable_path=None,
                version=None, native_home=str(native_home) if native_home.exists() else None,
                detail="claude executable not found on PATH",
            )
        try:
            result = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=5, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return ProviderInstallation(
                provider=self.provider_name, installed=True, runnable=False, executable_path=executable,
                version=None, native_home=str(native_home) if native_home.exists() else None,
                detail=f"claude found but its version probe failed: {type(exc).__name__}",
            )
        version = next((line.strip() for line in (result.stdout or "").splitlines() if line.strip()), None)
        return ProviderInstallation(
            provider=self.provider_name,
            installed=True,
            runnable=result.returncode == 0 and bool(version),
            executable_path=executable,
            version=version if result.returncode == 0 else None,
            native_home=str(native_home) if native_home.exists() else None,
            detail="Verified via `claude --version`" if result.returncode == 0 and version
            else f"claude version probe returned exit code {result.returncode}",
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.provider_name,
            phase="phase1_cli",
            install_detection=True,
            resume_command_generation=True,
            hook_event_normalization=False,
            hook_installation=False,
            session_discovery=False,
            history_scan=False,
            notes=[
                "Claude Code supports --session-id <UUID> for new interactive sessions and --resume <ID> for exact resumption.",
                "Transcript presence is local evidence only; no provider invocation verifies resumability.",
                "Hook installation and normalization are deferred.",
            ],
        )

    def discover_sessions(self, *, limit: int = 50) -> list[dict[str, str]]:
        """Return no broad history records until Claude's transcript schema is qualified.

        Exact session verification is supported by :meth:`get_session_metadata`.
        Claude's transcript format is documented as internal and may change, so
        listing every local transcript as a native session would overstate what
        LLMD can safely infer.
        """
        del limit
        return []

    def get_session_metadata(self, native_session_id: str) -> dict[str, str] | None:
        """Return exact transcript evidence, None only when absence is observable.

        Transcript records are an internal Claude format. LLMD therefore uses
        only the filename as the candidate identity and treats any unreadable,
        malformed, contradictory, or duplicate evidence as unavailable rather
        than guessing that a session is absent or resumable.
        """
        try:
            session_uuid = str(uuid.UUID(native_session_id))
        except (ValueError, AttributeError) as exc:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Claude transcript lookup requires a valid session UUID.") from exc
        projects = self._config_dir() / "projects"
        try:
            projects.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _evidence_unavailable(f"Claude transcript store is inaccessible ({type(exc).__name__}).") from exc
        if not projects.is_dir():
            raise _evidence_unavailable("Claude transcript store path is not a directory.")

        matches: list[Path] = []

        def fail_walk(error: OSError) -> None:
            raise error

        try:
            for root, _directories, filenames in os.walk(projects, onerror=fail_walk):
                if f"{session_uuid}.jsonl" in filenames:
                    matches.append(Path(root) / f"{session_uuid}.jsonl")
        except OSError as exc:
            raise _evidence_unavailable(f"Claude transcript evidence could not be fully scanned ({type(exc).__name__}).") from exc

        if not matches:
            return None
        if len(matches) != 1:
                raise _evidence_unavailable("multiple Claude transcripts match this session UUID; evidence is ambiguous.")

        transcript = matches[0]
        try:
            if not transcript.is_file() or transcript.stat().st_size == 0:
                raise _evidence_unavailable("The matching Claude transcript is empty; evidence is unavailable.")
            records = []
            with transcript.open("r", encoding="utf-8", errors="strict") as stream:
                for line_number, line in enumerate(stream, start=1):
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, UnicodeError) as exc:
                        raise _evidence_unavailable(
                            f"Claude transcript JSONL is malformed at line {line_number}; evidence is unavailable."
                        ) from exc
                    if not isinstance(record, dict):
                        raise _evidence_unavailable(
                            f"Claude transcript record at line {line_number} is not an object; evidence is unavailable."
                        )
                    for key in ("sessionId", "session_id", "nativeSessionId", "native_session_id"):
                        value = record.get(key)
                        if value is not None and str(value) != session_uuid:
                            raise _evidence_unavailable(
                                f"Claude transcript contains contradictory session identity at line {line_number}."
                            )
                    records.append(record)
            if not records:
                raise _evidence_unavailable("The matching Claude transcript contains no records; evidence is unavailable.")
        except ContinuityError:
            raise
        except (OSError, UnicodeError) as exc:
            raise _evidence_unavailable(f"Claude transcript evidence is inaccessible ({type(exc).__name__}).") from exc
        return {
            "provider": self.provider_name,
            "native_session_id": session_uuid,
            "transcript_reference": str(transcript),
            "metadata_source": "claude_transcript_presence",
        }

    def resolve_new_session_command(
        self, native_session_id: str, *, cwd: str | None = None, environment_id: str = "",
        runtime_kind: str = "", native_args: Sequence[str] = (),
    ) -> ResumePlan:
        try:
            session_id = str(uuid.UUID(native_session_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError("Claude --session-id requires a valid UUID") from exc
        if self.get_session_metadata(session_id):
            raise ValueError(f"Claude session ID {session_id} already exists locally")
        argv = ["claude", "--session-id", session_id, *native_args]
        display = shlex.join(argv) if runtime_kind != "windows" else subprocess_display(argv)
        return ResumePlan(
            provider=self.provider_name,
            native_session_id=session_id,
            environment_id=environment_id,
            argv=argv,
            cwd=cwd,
            display_command=display,
            supported=True,
            notes="Starts one interactive Claude session with the reserved UUID; transcript evidence is checked after exit.",
        )

    def resolve_resume_command(
        self, native_session_id: str, *, cwd: str | None = None, environment_id: str = "",
        runtime_kind: str = "", native_args: Sequence[str] = (),
    ) -> ResumePlan:
        try:
            session_id = str(uuid.UUID(native_session_id.strip()))
        except (ValueError, AttributeError) as exc:
            raise ValueError("Claude exact resume requires a valid session UUID") from exc
        argv = ["claude", "--resume", session_id, *native_args]
        display = shlex.join(argv) if runtime_kind != "windows" else subprocess_display(argv)
        return ResumePlan(
            provider=self.provider_name,
            native_session_id=session_id,
            environment_id=environment_id,
            argv=argv,
            cwd=cwd,
            display_command=display,
            supported=True,
            notes="Verified Claude CLI syntax: claude --resume <session-id>.",
        )


def subprocess_display(argv: list[str]) -> str:
    """Quote argv for a Windows command preview without shell execution."""
    return " ".join('"' + value.replace('"', '\\"') + '"' if any(ch.isspace() for ch in value) else value
                    for value in argv)


def _evidence_unavailable(message: str) -> ContinuityError:
    return ContinuityError(ErrorCode.METADATA_INACCESSIBLE, message)
