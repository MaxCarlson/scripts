"""Independently owned dispatcher and Terminal Launcher integration adapters."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from .errors import ContinuityError, ErrorCode
from .identifiers import generate_id
from .launch_context import (
    VERIFIED_CAPABILITIES,
    is_full_commit_object_id,
    provider_settings_argv,
    resolve_portable_launch_context,
)
from .runtime_discovery import (
    ManagedAssociationState,
    ManagedLaunchAssociation,
    SessionKey,
    TerminalLauncherManagedReceiptSource,
)
from .workspace_checkpoint import (
    ALLOWED_LAUNCH_SETTINGS,
    WorkspaceSlotInput,
    WorkspaceSlotMetadata,
    WorkspaceTopologyRequest,
    WorkspaceWorktreeEvidence,
    sanitize_launch_settings,
)
from .workspace_lifecycle import (
    RestoreLaunchOutcome,
    RestoreLaunchRequest,
    RestorePlanItem,
    SlotGuardLease,
)
from .workspace_ownership import ReservationSlotExecutionGuard, RestorationReservationStore

_PROVIDER_ALLOWED_SETTINGS: dict[str, frozenset[str]] = {
    "codex": frozenset({"model", "sandbox", "approval_policy", "reasoning_effort", "search", "add_dirs", "profile",
                        "no_alt_screen", "no_daemon", "strict_config"}),
    "claude": frozenset({"model", "effort", "permission_mode", "add_dirs"}),
    "agy": frozenset({"model", "effort", "sandbox", "add_dirs"}),
}


def is_managed_terminal_available() -> bool:
    """Return True only when Terminal Launcher 0.2.0 managed APIs are importable."""
    try:
        from terminal_launcher.backends.windows_terminal import WindowsTerminalBackend
        from terminal_launcher.managed import ManagedProcessStore  # noqa: F401
    except ImportError:
        return False
    return callable(getattr(WindowsTerminalBackend, "launch_managed", None))


class MaterializerLike(Protocol):
    """Minimal read-only materializer contract for authoritative environment lookup."""

    def list_environments(self) -> Sequence[Any]: ...


class DispatcherLike(Protocol):
    """Structural subset of DispatcherService used without modifying dispatcher.py."""

    home_dir: Path
    materializer: MaterializerLike

    def list_guis(self, *, active_only: bool = True) -> list[dict[str, Any]]: ...

    def list_slots(self, *, gui: str, active_only: bool = True) -> list[dict[str, Any]]: ...

    def get_slot_by_id(self, slot_id: str) -> dict[str, Any]: ...

    def current_working_directory(self, slot: dict[str, Any]) -> str: ...

    def list_recent_terminal_launches(self, *, limit: int = 20) -> list[dict[str, Any]]: ...

    def latest_terminal_launch_for_identity(
        self, *, slot_id: str, provider: str, environment_id: str, native_session_id: str,
    ) -> dict[str, Any] | None: ...

    def list_terminal_launches_for_session_identity(
        self, *, provider: str, environment_id: str, native_session_id: str,
    ) -> list[dict[str, Any]]: ...

    def get_portable_launch_context(
        self, *, slot_id: str, provider: str, environment_id: str, session_id: str,
    ) -> dict[str, Any] | None: ...


class DispatcherLaunchCommandBuilder(Protocol):
    """Contract for Agent #1 to supply canonical exact-session LLMD-managed pane commands."""

    supports_exact_session: bool

    def build_pane_command(self, request: RestoreLaunchRequest) -> tuple[str, ...]: ...


class DispatcherOwnershipVerifier(Protocol):
    """Optional Agent #1 contract confirming atomic dispatcher ownership of a managed pane."""

    def verify_ownership(
        self,
        request: RestoreLaunchRequest,
        *,
        launch_id: str,
        pane_id: str,
    ) -> tuple[bool, bool]:
        """Return (dispatcher_ownership_acknowledged, exact_association_confirmed)."""
        ...


def validate_provider_launch_settings(
    provider: str,
    raw_settings: Mapping[str, Any] | None,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    """Validate non-secret launch settings against allowlist and provider compatibility."""
    if not raw_settings:
        return {}
    if strict:
        sanitized = sanitize_launch_settings(raw_settings)
    else:
        filtered = {k: v for k, v in raw_settings.items() if k in ALLOWED_LAUNCH_SETTINGS and v is not None}
        sanitized = sanitize_launch_settings(filtered)
    allowed_for_provider = _PROVIDER_ALLOWED_SETTINGS.get(provider)
    if allowed_for_provider is not None:
        disallowed = set(sanitized) - allowed_for_provider
        if disallowed:
            if strict:
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    f"Launch settings {sorted(disallowed)} are not valid for provider {provider!r}.",
                    {"provider": provider, "disallowed": sorted(disallowed)},
                )
            sanitized = {k: v for k, v in sanitized.items() if k in allowed_for_provider}
    return sanitized


def merge_restored_launch_settings(
    provider: str,
    portable_settings: Mapping[str, Any],
    historical_settings: Mapping[str, Any],
    *,
    portable_context_present: bool,
) -> dict[str, Any]:
    """Merge safe launch settings without letting history override current portable constraints."""
    portable = validate_provider_launch_settings(provider, portable_settings, strict=False)
    historical = validate_provider_launch_settings(provider, historical_settings, strict=False)
    protected = {"sandbox", "approval_policy", "permission_mode", "auto_approval"}
    conflicts = sorted(
        key for key in protected
        if key in portable and key in historical and portable[key] != historical[key]
    )
    if conflicts:
        raise ContinuityError(
            ErrorCode.INVALID_INPUT,
            f"Historical launch settings conflict with the portable permission context: {', '.join(conflicts)}.",
            {"provider": provider, "conflicting_settings": conflicts},
        )
    portable_dirs = set(portable.get("add_dirs", ()))
    historical_dirs = set(historical.get("add_dirs", ()))
    if portable_context_present and historical_dirs - portable_dirs:
        raise ContinuityError(
            ErrorCode.INVALID_INPUT,
            "Historical additional directories are not authorized by the current portable context.",
            {"provider": provider, "conflicting_settings": ["add_dirs"]},
        )
    return validate_provider_launch_settings(
        provider,
        {**historical, **portable},
        strict=False,
    )


class DispatcherWorkspaceAdapter:
    """Read-only adapter translating DispatcherService slots and launches into WorkspaceSlotInput."""

    def __init__(
        self,
        dispatcher: DispatcherLike,
        *,
        environment_lookup: Callable[[str], str | None] | None = None,
        authorization_lookup: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self._environment_lookup = environment_lookup
        self._authorization_lookup = authorization_lookup

    def _resolve_runtime_kind(self, environment_id: str) -> str:
        """Resolve runtime_kind from authoritative materializer metadata; never infer from ID prefixes."""
        if self._environment_lookup is not None:
            resolved = self._environment_lookup(environment_id)
            if resolved:
                return str(resolved)
        materializer = getattr(self.dispatcher, "materializer", None)
        if materializer is not None:
            with contextlib.suppress(Exception):
                for env in materializer.list_environments():
                    if getattr(env, "environment_id", None) == environment_id:
                        return str(getattr(env, "runtime_kind", "unknown"))
        return "unknown"

    def _resolve_portable_context(
        self, *, slot_id: str, provider: str, environment_id: str, session_id: str, runtime_kind: str,
    ) -> tuple[Any | None, dict[str, Any], bool]:
        """Resolve exact-session normalized context for workspace capture and managed restoration."""
        getter = getattr(self.dispatcher, "get_portable_launch_context", None)
        if not callable(getter):
            return None, {}, True
        try:
            snapshot = getter(
                slot_id=slot_id, provider=provider, environment_id=environment_id, session_id=session_id,
            )
        except Exception:
            return None, {}, False
        if snapshot is None:
            return None, {}, True
        if snapshot.get("schema_version") != 1 or snapshot.get("provider") != provider:
            return None, {}, False
        environment = next((item for item in self.dispatcher.materializer.list_environments()
                            if getattr(item, "environment_id", None) == environment_id), None)
        destination_runtime = {
            "environment_id": environment_id,
            "runtime_kind": runtime_kind,
            "distro": getattr(environment, "distro", None),
        }
        context, items = resolve_portable_launch_context(
            snapshot, provider, capabilities=VERIFIED_CAPABILITIES, destination_runtime=destination_runtime,
        )
        blocking = any(item.status == "conflicting" for item in items) or any(
            item.status == "unsupported" and item.key in {"filesystem", "approval", "network"}
            for item in items
        )
        if blocking:
            return context, {}, False
        settings: dict[str, Any] = {}
        preferences = dict(context.destination_preferences.get(provider, {}))
        for key in ("model", "provider_profile"):
            if preferences.get(key) is not None:
                settings["profile" if key == "provider_profile" and provider == "codex" else key] = preferences[key]
        semantic_map = {
            "reasoning_effort": "reasoning_effort" if provider == "codex" else "effort",
            "filesystem": "sandbox",
            "approval": "approval_policy",
            "search": "search",
        }
        supported = VERIFIED_CAPABILITIES.get(provider, frozenset())
        for key, value in context.semantic_settings.items():
            if key in supported and key in semantic_map:
                settings[semantic_map[key]] = value
        if context.authorized_directories:
            settings["add_dirs"] = list(context.authorized_directories)
        if provider == "codex":
            for key in ("no_alt_screen", "no_daemon", "strict_config"):
                if key in context.terminal_settings:
                    settings[key] = context.terminal_settings[key]
        return context, settings, True

    def _recent_by_exact_identity(
        self, slots: Sequence[Mapping[str, Any]],
    ) -> dict[tuple[str, str, str, str], dict[str, Any]]:
        recent_by_identity: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        getter = getattr(self.dispatcher, "latest_terminal_launch_for_identity", None)
        if not callable(getter):
            return recent_by_identity
        for slot in slots:
            current = slot.get("current") if isinstance(slot.get("current"), Mapping) else {}
            slot_id = slot.get("slot_id")
            provider = slot.get("current_provider") or current.get("provider")
            session_id = slot.get("current_session_id") or current.get("native_session_id")
            environment_id = slot.get("current_environment_id") or current.get("environment_id")
            if not all(isinstance(value, str) and value for value in (slot_id, provider, session_id, environment_id)):
                continue
            try:
                launch = getter(
                    slot_id=slot_id,
                    provider=provider,
                    environment_id=environment_id,
                    native_session_id=session_id,
                )
            except Exception:
                continue
            if launch is not None:
                recent_by_identity[(slot_id, provider, session_id, environment_id)] = launch
        return recent_by_identity

    def list_candidate_slots(
        self,
        *,
        gui: str | None = None,
        active_only: bool = True,
    ) -> tuple[WorkspaceSlotInput, ...]:
        guis = self.dispatcher.list_guis(active_only=active_only)
        if gui is not None:
            guis = [
                g
                for g in guis
                if g.get("gui_id") == gui or str(g.get("alias", "")).casefold() == gui.casefold()
            ]

        slots_by_gui = {
            str(g["gui_id"]): self.dispatcher.list_slots(gui=str(g["gui_id"]), active_only=active_only)
            for g in guis
        }
        recent_by_identity = self._recent_by_exact_identity(
            [slot for slots in slots_by_gui.values() for slot in slots]
        )

        inputs: list[WorkspaceSlotInput] = []
        for g in guis:
            gui_id = str(g["gui_id"])
            gui_alias = str(g["alias"]) if g.get("alias") is not None else None
            for slot in slots_by_gui.get(gui_id, ()):
                converted = self._slot_dict_to_input(
                    slot,
                    gui_alias=gui_alias,
                    recent_by_identity=recent_by_identity,
                )
                if converted is not None:
                    inputs.append(converted)
        return tuple(inputs)

    def slot_provider(self, slot_id: str) -> WorkspaceSlotInput | None:
        """Fetch fresh slot state directly from DispatcherService under execution guard."""
        try:
            slot = self.dispatcher.get_slot_by_id(slot_id)
        except Exception:
            return None
        recent_by_identity = self._recent_by_exact_identity([slot])
        return self._slot_dict_to_input(
            slot,
            gui_alias=str(slot["gui_alias"]) if slot.get("gui_alias") is not None else None,
            recent_by_identity=recent_by_identity,
        )

    def associations_for_session(self, key: SessionKey) -> tuple[ManagedLaunchAssociation, ...]:
        """Join DispatcherService terminal-launch history to ManagedLaunchAssociation without inferring pane IDs."""
        associations: list[ManagedLaunchAssociation] = []
        try:
            launches = self.dispatcher.list_terminal_launches_for_session_identity(
                provider=key.provider,
                environment_id=key.environment_id,
                native_session_id=key.native_session_id,
            )
        except Exception:
            return ()
        seen_first = False
        for rec in launches:
            if (
                rec.get("provider") != key.provider
                or rec.get("native_session_id") != key.native_session_id
                or rec.get("environment_id") != key.environment_id
            ):
                continue
            launch_id = rec.get("launch_id")
            term_sid = rec.get("terminal_session_id")
            pane_id = rec.get("pane_id")
            if not launch_id or not term_sid or not pane_id:
                continue
            state = (
                ManagedAssociationState.CURRENT
                if not seen_first and rec.get("launch_exited_at") is None
                else ManagedAssociationState.HISTORICAL
            )
            seen_first = True
            associations.append(
                ManagedLaunchAssociation(
                    launch_id=str(launch_id),
                    terminal_session_id=str(term_sid),
                    pane_id=str(pane_id),
                    session_key=key,
                    association_state=state,
                )
            )
        return tuple(associations)

    def build_receipt_source(self, managed_store: Any | None) -> TerminalLauncherManagedReceiptSource | None:
        if managed_store is None:
            return None
        return TerminalLauncherManagedReceiptSource(managed_store, self.associations_for_session)

    def _slot_dict_to_input(
        self,
        slot: Mapping[str, Any],
        *,
        gui_alias: str | None,
        recent_by_identity: Mapping[tuple[str, str, str, str], Mapping[str, Any]],
    ) -> WorkspaceSlotInput | None:
        current = slot.get("current") if isinstance(slot.get("current"), Mapping) else None
        provider = slot.get("current_provider") or (current.get("provider") if current else None)
        native_session_id = slot.get("current_session_id") or (current.get("native_session_id") if current else None)
        environment_id = slot.get("current_environment_id") or (current.get("environment_id") if current else None)
        if not provider or not native_session_id or not environment_id:
            return None

        slot_id = str(slot["slot_id"])
        recent = recent_by_identity.get((slot_id, str(provider), str(native_session_id), str(environment_id)))

        cwd: str | None = None
        with contextlib.suppress(Exception):
            cwd = self.dispatcher.current_working_directory(dict(slot))

        worktree = WorkspaceWorktreeEvidence(
            requested_cwd=str(recent["requested_cwd"]) if recent and recent.get("requested_cwd") else cwd,
            effective_cwd=str(recent["effective_cwd"]) if recent and recent.get("effective_cwd") else cwd,
            native_cwd=str(recent["native_cwd"]) if recent and recent.get("native_cwd") else None,
            git_repository=str(recent["git_repository"]) if recent and recent.get("git_repository") else None,
            git_worktree=str(recent["git_worktree"]) if recent and recent.get("git_worktree") else None,
            git_branch=str(recent["git_branch"]) if recent and recent.get("git_branch") else None,
            git_commit=(str(recent["git_commit"]) if recent and is_full_commit_object_id(recent.get("git_commit"))
                        else None),
        )
        topology = None
        if recent and (recent.get("launch_id") or recent.get("terminal_session_id")):
            topology = WorkspaceTopologyRequest(
                launch_id=str(recent["launch_id"]) if recent.get("launch_id") else None,
                pane_id=str(recent["pane_id"]) if recent.get("pane_id") else None,
                terminal_session_id=(
                    str(recent["terminal_session_id"]) if recent.get("terminal_session_id") else None
                ),
            )
        metadata = WorkspaceSlotMetadata(
            workflow_type=str(slot["workflow_type"]) if slot.get("workflow_type") is not None else None,
            profile_id=str(slot["profile_id"]) if slot.get("profile_id") is not None else None,
            profile_revision=int(slot["profile_revision"]) if slot.get("profile_revision") is not None else None,
            agent_number=int(slot["agent_number"]) if slot.get("agent_number") is not None else None,
        )
        runtime_kind = self._resolve_runtime_kind(str(environment_id))
        portable_context, portable_settings, portable_authorization = self._resolve_portable_context(
            slot_id=slot_id, provider=str(provider), environment_id=str(environment_id),
            session_id=str(native_session_id), runtime_kind=runtime_kind,
        )
        if portable_context is not None:
            cwd = portable_context.explicit_directory_override or portable_context.working_directory or cwd
            if portable_context.repositories:
                primary_repository = portable_context.repositories[0]
                worktree = WorkspaceWorktreeEvidence(
                    requested_cwd=(portable_context.explicit_directory_override
                                   or (recent.get("requested_cwd") if recent else None)),
                    effective_cwd=portable_context.working_directory or cwd,
                    native_cwd=(recent.get("native_cwd") if recent and recent.get("native_cwd") else None),
                    git_repository=(str(primary_repository["root"]) if primary_repository.get("root") else worktree.git_repository),
                    git_worktree=(str(primary_repository["worktree"]) if primary_repository.get("worktree") else worktree.git_worktree),
                    git_branch=(str(primary_repository["branch"]) if primary_repository.get("branch") else worktree.git_branch),
                    git_commit=(str(primary_repository["commit"]) if primary_repository.get("commit") else worktree.git_commit),
                )
        auth_valid = True
        if self._authorization_lookup is not None:
            auth_valid = bool(self._authorization_lookup(slot))
        auth_valid = auth_valid and portable_authorization

        return WorkspaceSlotInput(
            slot_id=slot_id,
            gui_id=str(slot["gui_id"]),
            provider=str(provider),
            native_session_id=str(native_session_id),
            environment_id=str(environment_id),
            runtime_kind=runtime_kind,
            lifecycle_state=str(slot.get("state", "active")),
            gui_alias=gui_alias or (str(recent["gui_alias"]) if recent and recent.get("gui_alias") else None),
            slot_name=str(slot["name"]) if slot.get("name") is not None else None,
            launch_settings=merge_restored_launch_settings(
                str(provider),
                portable_settings,
                recent.get("settings") if recent else {},
                portable_context_present=portable_context is not None,
            ),
            worktree=worktree,
            requested_topology=topology,
            metadata=metadata,
            pending_launch_id=(
                str(slot["pending_launch_id"]) if slot.get("pending_launch_id") is not None else None
            ),
            pending_provider=str(slot["pending_provider"]) if slot.get("pending_provider") is not None else None,
            authorization_valid=auth_valid,
        )


class DispatcherSlotExecutionGuard:
    """Cooperating cross-process per-slot exclusion lock aligned with canonical slot-<slot_id>.lock."""

    def __init__(self, home_dir: Path, *, blocking: bool = False, timeout_seconds: float = 5.0) -> None:
        self._guard = ReservationSlotExecutionGuard(
            home_dir,
            blocking=blocking,
            timeout_seconds=timeout_seconds,
        )

    def acquire_slot(
        self,
        slot_id: str,
        *,
        operator_id: str,
        checkpoint_id: str,
        queue_entry_id: str | None,
    ) -> SlotGuardLease:
        return self._guard.acquire_slot(
            slot_id,
            operator_id=operator_id,
            checkpoint_id=checkpoint_id,
            queue_entry_id=queue_entry_id,
        )

    def release_slot(self, lease: SlotGuardLease) -> None:
        self._guard.release_slot(lease)


def _installed_llmd_matches_package_version(exe: str) -> bool:
    """Return True only when the installed `llmd` binary matches this package's version."""
    try:
        from . import __version__

        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    output = f"{proc.stdout}\n{proc.stderr}"
    return __version__ in output


def canonical_llmd_dispatcher_entrypoint(*, prefer_installed: bool = True) -> tuple[str, ...]:
    """Return the canonical `llmd` dispatcher entry point (never legacy `python -m agent_continuity`)."""
    if prefer_installed:
        exe = shutil.which("llmd")
        if exe and _installed_llmd_matches_package_version(exe):
            return (exe,)
    return (
        sys.executable,
        "-c",
        "import sys; from agent_continuity.dispatcher_cli import main; sys.exit(main())",
    )


def canonical_llmd_pane_command(
    request: RestoreLaunchRequest,
    *,
    home_dir: Path | None = None,
    prefer_installed: bool = True,
) -> tuple[str, ...]:
    """Build the canonical `llmd pane-run` invocation via dispatcher_cli (never legacy cli.py)."""
    argv = list(canonical_llmd_dispatcher_entrypoint(prefer_installed=prefer_installed))
    argv.append("pane-run")
    if home_dir is not None:
        argv.extend(["-H", str(home_dir)])
    argv.extend(["-s", request.slot_id])
    argv.extend([
        "--expected-provider", request.provider,
        "--expected-environment", request.environment_id,
        "--expected-session-id", request.native_session_id,
    ])
    if request.reservation_id is not None:
        required = (
            request.reservation_token,
            request.checkpoint_id,
            request.reservation_launch_id,
            request.reservation_pane_id,
        )
        if not all(required):
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                "Restoration reservation command is missing required correlation identity.",
                {"slot_id": request.slot_id},
            )
        argv.extend([
            "--reservation-id", request.reservation_id,
            "--reservation-token", request.reservation_token,
            "--checkpoint-id", request.checkpoint_id,
            "--attempt", str(request.attempt),
            "--reservation-launch-id", request.reservation_launch_id,
            "--pane-id", request.reservation_pane_id,
        ])
        if request.queue_entry_id is not None:
            argv.extend(["--queue-entry-id", request.queue_entry_id])
    if request.cwd:
        argv.extend(["--cwd", request.cwd])
    settings = validate_provider_launch_settings(request.provider, request.launch_settings, strict=True)
    provider_args = provider_settings_argv(request.provider, settings)
    if provider_args:
        argv.extend(["--", *provider_args])
    return tuple(argv)


def build_manual_restore_command(
    item: RestorePlanItem | RestoreLaunchRequest,
    *,
    home_dir: Path | None = None,
    prefer_llmd: bool = True,
    exact_llmd_supported: bool = False,
    allow_direct_native_fallback: bool = False,
) -> list[str]:
    """Build a manual exact-session restoration command.

    Unless `exact_llmd_supported=True`, `llmd continue` cannot assert exact
    provider/session/environment identity, so callers must either opt into
    `allow_direct_native_fallback=True` (`--direct-native`) or fail closed.
    """
    if prefer_llmd and exact_llmd_supported:
        argv = ["llmd", "continue"]
        if home_dir is not None:
            argv.extend(["-H", str(home_dir)])
        argv.extend(
            [
                "-S",
                item.slot_id,
                "--provider",
                item.provider,
                "--session-id",
                item.native_session_id,
                "--environment",
                item.environment_id,
            ]
        )
        if item.cwd:
            argv.extend(["-C", item.cwd])
        settings = validate_provider_launch_settings(item.provider, item.launch_settings, strict=False)
        provider_args = provider_settings_argv(item.provider, settings)
        if provider_args:
            argv.extend(["--", *provider_args])
        return argv
    if prefer_llmd and not allow_direct_native_fallback:
        raise ContinuityError(
            ErrorCode.RESUME_UNSUPPORTED,
            "Exact-session `llmd continue` restoration is not yet supported by the installed dispatcher; "
            "pass allow_direct_native_fallback=True (--direct-native) to emit an unmanaged native resume command.",
            {"slot_id": item.slot_id, "provider": item.provider},
        )

    settings = validate_provider_launch_settings(item.provider, item.launch_settings, strict=False)
    if item.provider == "codex":
        argv = ["codex", "resume", item.native_session_id]
        if settings.get("model"):
            argv.extend(["-m", str(settings["model"])])
        if settings.get("sandbox"):
            argv.extend(["-s", str(settings["sandbox"])])
        if settings.get("approval_policy"):
            argv.extend(["-a", str(settings["approval_policy"])])
        if settings.get("search"):
            argv.append("--search")
        return argv
    if item.provider == "claude":
        argv = ["claude", "--resume", item.native_session_id]
        if settings.get("model"):
            argv.extend(["--model", str(settings["model"])])
        if settings.get("effort"):
            argv.extend(["--effort", str(settings["effort"])])
        if settings.get("permission_mode"):
            argv.extend(["--permission-mode", str(settings["permission_mode"])])
        return argv
    if item.provider == "agy":
        argv = ["agy", "--conversation", item.native_session_id]
        if settings.get("model"):
            argv.extend(["--model", str(settings["model"])])
        if settings.get("effort"):
            argv.extend(["--effort", str(settings["effort"])])
        if settings.get("sandbox"):
            argv.append("--sandbox")
        return argv
    return [item.provider, item.native_session_id]


class TerminalLauncherRestoreAdapter:
    """Canonical LLMD-managed and grouped-topology restoration adapter using Terminal Launcher 0.2.0."""

    def __init__(
        self,
        *,
        backend: Any,
        managed_store: Any,
        home_dir: Path | None = None,
        command_builder: DispatcherLaunchCommandBuilder | None = None,
        ownership_verifier: DispatcherOwnershipVerifier | None = None,
        require_exact_session_support: bool = True,
        require_dispatcher_ownership: bool = True,
        reservation_store: RestorationReservationStore | None = None,
        default_window: str = "llmd-restore",
        startup_timeout: float = 2.0,
        submission_timeout: float = 10.0,
    ) -> None:
        self.backend = backend
        self.managed_store = managed_store
        self.home_dir = home_dir
        self.command_builder = command_builder
        self.ownership_verifier = ownership_verifier
        self.require_exact_session_support = require_exact_session_support
        self.require_dispatcher_ownership = require_dispatcher_ownership
        self.reservation_store = reservation_store or (
            RestorationReservationStore(home_dir) if home_dir is not None else None
        )
        self.default_window = default_window
        self.startup_timeout = startup_timeout
        self.submission_timeout = submission_timeout

    def _pane_argv(self, request: RestoreLaunchRequest) -> tuple[str, ...]:
        validate_provider_launch_settings(request.provider, request.launch_settings, strict=True)
        if self.command_builder is not None:
            if self.require_exact_session_support and not getattr(
                self.command_builder, "supports_exact_session", False
            ):
                raise ContinuityError(
                    ErrorCode.RESUME_UNSUPPORTED,
                    "Dispatcher launch command builder does not assert exact provider/session/environment identity.",
                )
            return tuple(self.command_builder.build_pane_command(request))
        if self.require_exact_session_support:
            raise ContinuityError(
                ErrorCode.RESUME_UNSUPPORTED,
                "Canonical `llmd pane-run` does not yet expose exact-session CLI assertions; "
                "supply an exact-session DispatcherLaunchCommandBuilder.",
            )
        return canonical_llmd_pane_command(request, home_dir=self.home_dir)

    def launch_session(self, request: RestoreLaunchRequest) -> RestoreLaunchOutcome:
        return self.launch_grouped([request])[request.slot_id]

    def _evaluate_pane_outcome(
        self,
        req: RestoreLaunchRequest,
        *,
        launch_id: str,
        pane_id: str,
        rec: Any | None,
        used_fallback: bool,
        startup_timed_out: bool,
    ) -> RestoreLaunchOutcome:
        relay_spawn_ok = bool(rec is not None and getattr(rec, "spawn_acknowledged", False))
        latest_rec = rec
        raw_state = getattr(latest_rec, "state", None)
        current_liveness = str(getattr(raw_state, "value", raw_state) or "unknown")
        exit_code = getattr(latest_rec, "exit_code", None)
        ownership_ok = False
        startup_ok = False
        association_ok = False
        reservation_state: str | None = None
        verifier_reason: str | None = None

        if relay_spawn_ok and self.ownership_verifier is not None:
            deadline = time.monotonic() + min(max(self.startup_timeout, 0.1), 2.0)
            while True:
                try:
                    if hasattr(self.ownership_verifier, "verify_ownership_details"):
                        details = self.ownership_verifier.verify_ownership_details(
                            req, launch_id=launch_id, pane_id=pane_id
                        )
                        ownership_ok = bool(details.get("dispatcher_ownership_acknowledged", False))
                        startup_ok = bool(details.get("provider_startup_confirmed", False))
                        association_ok = bool(details.get("exact_association_confirmed", False))
                        reservation_state = details.get("reservation_state")
                        verifier_reason = details.get("reason")
                    else:
                        ownership_ok, association_ok = self.ownership_verifier.verify_ownership(
                            req, launch_id=launch_id, pane_id=pane_id
                        )
                        startup_ok = bool(ownership_ok and association_ok)
                except Exception as exc:
                    if self.reservation_store is not None and req.reservation_id:
                        with contextlib.suppress(Exception):
                            self.reservation_store.mark_ambiguous(
                                req.reservation_id,
                                reason=f"ownership_verification_error:{type(exc).__name__}:{exc}",
                                launch_id=launch_id,
                                pane_id=pane_id,
                            )
                    return RestoreLaunchOutcome(
                        accepted=True,
                        launch_id=launch_id,
                        pane_id=pane_id,
                        failure_reason=f"ownership_verification_error:{type(exc).__name__}:{exc}",
                        spawn_confirmed=relay_spawn_ok,
                        relay_spawn_acknowledged=relay_spawn_ok,
                        dispatcher_ownership_acknowledged=False,
                        provider_startup_confirmed=False,
                        association_confirmed=False,
                        current_liveness=current_liveness,
                        resumability_confirmed=False,
                        submission_ambiguous=True,
                        geometry_fallback_used=used_fallback,
                    )
                if self.managed_store is not None:
                    with contextlib.suppress(Exception):
                        for cand in self.managed_store.enumerate_processes(launch_id=launch_id):
                            if getattr(cand, "pane_id", None) == pane_id:
                                latest_rec = cand
                                raw_state = getattr(latest_rec, "state", None)
                                current_liveness = str(getattr(raw_state, "value", raw_state) or "unknown")
                                exit_code = getattr(latest_rec, "exit_code", None)
                                break
                if reservation_state in {"ambiguous", "aborted"}:
                    break
                if current_liveness in {"exited", "failed"} and exit_code not in {None, 0}:
                    break
                if ownership_ok and startup_ok and association_ok:
                    if self.managed_store is not None:
                        time.sleep(0.05)
                        with contextlib.suppress(Exception):
                            for cand in self.managed_store.enumerate_processes(launch_id=launch_id):
                                if getattr(cand, "pane_id", None) == pane_id:
                                    latest_rec = cand
                                    raw_state = getattr(latest_rec, "state", None)
                                    current_liveness = str(getattr(raw_state, "value", raw_state) or "unknown")
                                    exit_code = getattr(latest_rec, "exit_code", None)
                                    break
                    break
                if (
                    not self.require_dispatcher_ownership or not getattr(req, "reservation_id", None)
                ) and (ownership_ok or time.monotonic() >= deadline):
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.025)

        if not relay_spawn_ok:
            if self.reservation_store is not None and req.reservation_id:
                with contextlib.suppress(Exception):
                    self.reservation_store.mark_ambiguous(
                        req.reservation_id,
                        reason="relay_startup_timed_out" if startup_timed_out else "relay_spawn_unconfirmed",
                        launch_id=launch_id,
                        pane_id=pane_id,
                    )
            return RestoreLaunchOutcome(
                accepted=True,
                launch_id=launch_id,
                pane_id=pane_id,
                failure_reason="relay_startup_timed_out" if startup_timed_out else "relay_spawn_unconfirmed",
                spawn_confirmed=False,
                relay_spawn_acknowledged=False,
                dispatcher_ownership_acknowledged=False,
                provider_startup_confirmed=False,
                association_confirmed=False,
                current_liveness=current_liveness,
                resumability_confirmed=False,
                submission_ambiguous=False,
                geometry_fallback_used=used_fallback,
            )

        if reservation_state == "ambiguous":
            return RestoreLaunchOutcome(
                accepted=True,
                launch_id=launch_id,
                pane_id=pane_id,
                failure_reason=verifier_reason or "post_consumption_uncertainty",
                spawn_confirmed=True,
                relay_spawn_acknowledged=True,
                dispatcher_ownership_acknowledged=ownership_ok,
                provider_startup_confirmed=False,
                association_confirmed=False,
                current_liveness=current_liveness,
                resumability_confirmed=False,
                submission_ambiguous=True,
                geometry_fallback_used=used_fallback,
            )

        if exit_code not in {None, 0} or (current_liveness in {"exited", "failed"} and not (startup_ok and association_ok)):
            fail_reason = (
                f"provider_nonzero_exit:{exit_code}"
                if exit_code not in {None, 0}
                else (verifier_reason or "provider_exited_before_association")
            )
            if self.reservation_store is not None and req.reservation_id:
                with contextlib.suppress(Exception):
                    self.reservation_store.mark_ambiguous(
                        req.reservation_id,
                        reason=fail_reason,
                        launch_id=launch_id,
                        pane_id=pane_id,
                    )
            return RestoreLaunchOutcome(
                accepted=True,
                launch_id=launch_id,
                pane_id=pane_id,
                failure_reason=fail_reason,
                spawn_confirmed=True,
                relay_spawn_acknowledged=True,
                dispatcher_ownership_acknowledged=ownership_ok,
                provider_startup_confirmed=startup_ok,
                association_confirmed=association_ok,
                current_liveness=current_liveness,
                resumability_confirmed=False,
                submission_ambiguous=False,
                geometry_fallback_used=used_fallback,
            )

        if self.require_dispatcher_ownership and not ownership_ok:
            if self.reservation_store is not None and req.reservation_id:
                with contextlib.suppress(Exception):
                    self.reservation_store.mark_ambiguous(
                        req.reservation_id,
                        reason=verifier_reason or "dispatcher_ownership_unconfirmed",
                        launch_id=launch_id,
                        pane_id=pane_id,
                    )
            return RestoreLaunchOutcome(
                accepted=True,
                launch_id=launch_id,
                pane_id=pane_id,
                failure_reason=verifier_reason or "dispatcher_ownership_unconfirmed",
                spawn_confirmed=True,
                relay_spawn_acknowledged=True,
                dispatcher_ownership_acknowledged=False,
                provider_startup_confirmed=startup_ok,
                association_confirmed=association_ok,
                current_liveness=current_liveness,
                resumability_confirmed=False,
                submission_ambiguous=False,
                geometry_fallback_used=used_fallback,
            )

        return RestoreLaunchOutcome(
            accepted=True,
            launch_id=launch_id,
            pane_id=pane_id,
            failure_reason=verifier_reason,
            spawn_confirmed=True,
            relay_spawn_acknowledged=True,
            dispatcher_ownership_acknowledged=ownership_ok,
            provider_startup_confirmed=startup_ok,
            association_confirmed=association_ok,
            current_liveness=current_liveness,
            resumability_confirmed=False,
            submission_ambiguous=False,
            geometry_fallback_used=used_fallback,
        )

    def launch_grouped(self, requests: Sequence[RestoreLaunchRequest]) -> dict[str, RestoreLaunchOutcome]:
        """Group restoration requests into window/tab/pane plans and launch via managed relay."""
        from terminal_launcher.backend import LaunchStatus
        from terminal_launcher.layouts import _layout_for_pane_count
        from terminal_launcher.models import PaneSpec, TabSpec, TerminalLaunchPlan

        if not requests:
            return {}

        by_window: dict[str, list[RestoreLaunchRequest]] = {}
        for req in requests:
            topo = req.requested_topology
            win = (topo.target_window if topo and topo.target_window else None) or self.default_window
            by_window.setdefault(win, []).append(req)

        outcomes: dict[str, RestoreLaunchOutcome] = {}
        for target_window, win_reqs in by_window.items():
            launch_id = generate_id("tlaunch")
            tab_buckets: dict[tuple[int, int], list[RestoreLaunchRequest]] = {}
            fallback_list: list[RestoreLaunchRequest] = []
            for req in win_reqs:
                topo = req.requested_topology
                if topo and topo.requested_tab_index is not None:
                    tab_buckets.setdefault((0, topo.requested_tab_index), []).append(req)
                else:
                    fallback_list.append(req)

            ordered_groups: list[tuple[list[RestoreLaunchRequest], bool]] = []
            for key in sorted(tab_buckets):
                bucket = sorted(
                    tab_buckets[key],
                    key=lambda r: (
                        r.requested_topology.requested_pane_index
                        if r.requested_topology and r.requested_topology.requested_pane_index is not None
                        else 999,
                        r.slot_id,
                    ),
                )
                for i in range(0, len(bucket), 4):
                    chunk = bucket[i : i + 4]
                    ordered_groups.append((chunk, len(bucket) > 4))

            for i in range(0, len(fallback_list), 2):
                chunk = fallback_list[i : i + 2]
                ordered_groups.append((chunk, True))

            tabs: list[TabSpec] = []
            slot_order: list[tuple[int, int, RestoreLaunchRequest, bool]] = []
            prep_failed = False
            for _group_idx, (group_reqs, group_fallback) in enumerate(ordered_groups):
                # Failed preparation creates no submitted tab; number identities
                # from the compact final topology, not the requested topology.
                tab_idx = len(tabs)
                panes: list[PaneSpec] = []
                requested_layout = (
                    group_reqs[0].requested_topology.requested_layout
                    if group_reqs[0].requested_topology
                    else None
                )
                canonical_layout = _layout_for_pane_count(len(group_reqs))
                layout_fallback = bool(requested_layout and requested_layout != canonical_layout)
                used_fallback = group_fallback or layout_fallback
                for req in group_reqs:
                    # A failed preceding pane is excluded from this submitted tab,
                    # so later pane identities use their final compact index.
                    pane_idx = len(panes)
                    pane_id = f"{launch_id}:{tab_idx}:{pane_idx}"
                    req = replace(req, reservation_launch_id=launch_id, reservation_pane_id=pane_id)
                    try:
                        argv = self._pane_argv(req)
                    except Exception as exc:
                        outcomes[req.slot_id] = RestoreLaunchOutcome(
                            accepted=False,
                            failure_reason=f"command_preparation_failed:{type(exc).__name__}:{exc}",
                            spawn_confirmed=False,
                            submission_ambiguous=False,
                            geometry_fallback_used=used_fallback,
                        )
                        prep_failed = True
                        continue
                    panes.append(
                        PaneSpec(
                            title=f"{req.provider}:{req.slot_id}",
                            argv=argv,
                            cwd=req.cwd,
                        )
                    )
                    slot_order.append((tab_idx, pane_idx, req, used_fallback))
                if not panes:
                    continue
                chosen_layout = _layout_for_pane_count(len(panes))
                tabs.append(
                    TabSpec(
                        title=" | ".join(p.title for p in panes),
                        panes=tuple(panes),
                        layout=chosen_layout,  # type: ignore[arg-type]
                    )
                )

            if prep_failed and not tabs:
                continue
            if not tabs:
                continue

            plan = TerminalLaunchPlan(tabs=tuple(tabs), target_window=target_window)
            if self.reservation_store is not None:
                for tab_idx, pane_idx, req, _used_fallback in slot_order:
                    if req.reservation_id:
                        self.reservation_store.bind_launch(
                            req.reservation_id,
                            launch_id=launch_id,
                            pane_id=f"{launch_id}:{tab_idx}:{pane_idx}",
                        )

            if callable(getattr(self.backend, "launch_managed", None)):
                managed_res = self.backend.launch_managed(
                    plan,
                    launch_id=launch_id,
                    store=self.managed_store,
                    startup_timeout=self.startup_timeout,
                    submission_timeout=self.submission_timeout,
                )
                pane_by_id = {rec.pane_id: rec for rec in managed_res.panes}
                sub = managed_res.submission
                for tab_idx, pane_idx, req, used_fallback in slot_order:
                    pane_id = f"{launch_id}:{tab_idx}:{pane_idx}"
                    rec = pane_by_id.get(pane_id)
                    if sub.status is LaunchStatus.FAILED:
                        if self.reservation_store is not None and req.reservation_id:
                            with contextlib.suppress(Exception):
                                self.reservation_store.abort_reservation(
                                    req.reservation_id,
                                    reason=sub.diagnostic or "managed_launch_rejected",
                                )
                        outcomes[req.slot_id] = RestoreLaunchOutcome(
                            accepted=False,
                            launch_id=launch_id,
                            pane_id=pane_id,
                            failure_reason=sub.diagnostic or "managed_launch_rejected",
                            spawn_confirmed=False,
                            submission_ambiguous=False,
                            geometry_fallback_used=used_fallback,
                        )
                    elif sub.status is LaunchStatus.AMBIGUOUS:
                        if self.reservation_store is not None and req.reservation_id:
                            with contextlib.suppress(Exception):
                                self.reservation_store.mark_ambiguous(
                                    req.reservation_id,
                                    reason=sub.diagnostic or "managed_submission_ambiguous",
                                    launch_id=launch_id,
                                    pane_id=pane_id,
                                )
                        outcomes[req.slot_id] = RestoreLaunchOutcome(
                            accepted=False,
                            launch_id=launch_id,
                            pane_id=pane_id,
                            failure_reason=sub.diagnostic or "managed_submission_ambiguous",
                            spawn_confirmed=False,
                            submission_ambiguous=True,
                            geometry_fallback_used=used_fallback,
                        )
                    else:
                        outcomes[req.slot_id] = self._evaluate_pane_outcome(
                            req,
                            launch_id=launch_id,
                            pane_id=pane_id,
                            rec=rec,
                            used_fallback=used_fallback,
                            startup_timed_out=managed_res.startup_timed_out,
                        )
            else:
                from terminal_launcher.managed import LaunchSubmissionState, ManagedPaneReservation

                reservations = [
                    ManagedPaneReservation(
                        pane_id=f"{launch_id}:{tab_idx}:{pane_idx}",
                        tab_index=tab_idx,
                        pane_index=pane_idx,
                        requested_layout=tabs[tab_idx].layout,
                    )
                    for tab_idx, pane_idx, _req, _fb in slot_order
                ]
                self.managed_store.reserve_launch(launch_id, target_window, reservations)
                self.managed_store.mark_submission_started(launch_id)
                try:
                    sub = self.backend.launch(plan)
                except Exception as exc:
                    self.managed_store.mark_submission_outcome(
                        launch_id, LaunchSubmissionState.AMBIGUOUS, failure_code=type(exc).__name__
                    )
                    for tab_idx, pane_idx, req, used_fallback in slot_order:
                        outcomes[req.slot_id] = RestoreLaunchOutcome(
                            accepted=False,
                            launch_id=launch_id,
                            pane_id=f"{launch_id}:{tab_idx}:{pane_idx}",
                            failure_reason=f"backend_exception:{type(exc).__name__}:{exc}",
                            spawn_confirmed=False,
                            submission_ambiguous=True,
                            geometry_fallback_used=used_fallback,
                        )
                    continue

                if sub.status is LaunchStatus.FAILED:
                    self.managed_store.mark_submission_outcome(
                        launch_id, LaunchSubmissionState.REJECTED, failure_code=sub.diagnostic or "launch_failed"
                    )
                    for tab_idx, pane_idx, req, used_fallback in slot_order:
                        if self.reservation_store is not None and req.reservation_id:
                            with contextlib.suppress(Exception):
                                self.reservation_store.abort_reservation(
                                    req.reservation_id,
                                    reason=sub.diagnostic or "backend_rejected",
                                )
                        outcomes[req.slot_id] = RestoreLaunchOutcome(
                            accepted=False,
                            launch_id=launch_id,
                            pane_id=f"{launch_id}:{tab_idx}:{pane_idx}",
                            failure_reason=sub.diagnostic or "backend_rejected",
                            spawn_confirmed=False,
                            submission_ambiguous=False,
                            geometry_fallback_used=used_fallback,
                        )
                elif sub.status is LaunchStatus.AMBIGUOUS:
                    self.managed_store.mark_submission_outcome(
                        launch_id, LaunchSubmissionState.AMBIGUOUS, failure_code=sub.diagnostic or "launch_ambiguous"
                    )
                    for tab_idx, pane_idx, req, used_fallback in slot_order:
                        pane_id = f"{launch_id}:{tab_idx}:{pane_idx}"
                        if self.reservation_store is not None and req.reservation_id:
                            with contextlib.suppress(Exception):
                                self.reservation_store.mark_ambiguous(
                                    req.reservation_id,
                                    reason=sub.diagnostic or "submission_ambiguous",
                                    launch_id=launch_id,
                                    pane_id=pane_id,
                                )
                        outcomes[req.slot_id] = RestoreLaunchOutcome(
                            accepted=False,
                            launch_id=launch_id,
                            pane_id=pane_id,
                            failure_reason=sub.diagnostic or "submission_ambiguous",
                            spawn_confirmed=False,
                            submission_ambiguous=True,
                            geometry_fallback_used=used_fallback,
                        )
                else:
                    self.managed_store.mark_submission_outcome(launch_id, LaunchSubmissionState.ACCEPTED)
                    recs = {r.pane_id: r for r in self.managed_store.enumerate_processes(launch_id=launch_id)}
                    for tab_idx, pane_idx, req, used_fallback in slot_order:
                        pane_id = f"{launch_id}:{tab_idx}:{pane_idx}"
                        outcomes[req.slot_id] = self._evaluate_pane_outcome(
                            req,
                            launch_id=launch_id,
                            pane_id=pane_id,
                            rec=recs.get(pane_id),
                            used_fallback=used_fallback,
                            startup_timed_out=False,
                        )
        return outcomes
