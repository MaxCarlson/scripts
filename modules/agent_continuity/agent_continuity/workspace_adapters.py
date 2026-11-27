"""Independently owned dispatcher and Terminal Launcher integration adapters."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from terminal_launcher.backend import LaunchStatus, TerminalBackend
from terminal_launcher.managed import (
    LaunchSubmissionState,
    ManagedPaneReservation,
    ManagedProcessStore,
)
from terminal_launcher.models import PaneSpec, TabSpec, TerminalLaunchPlan

from .identifiers import generate_id
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


class DispatcherLike(Protocol):
    """Structural subset of DispatcherService used without modifying dispatcher.py."""

    home_dir: Path

    def list_guis(self, *, active_only: bool = True) -> list[dict[str, Any]]: ...

    def list_slots(self, *, gui: str, active_only: bool = True) -> list[dict[str, Any]]: ...

    def get_slot_by_id(self, slot_id: str) -> dict[str, Any]: ...

    def current_working_directory(self, slot: dict[str, Any]) -> str: ...

    def list_recent_terminal_launches(self, *, limit: int = 20) -> list[dict[str, Any]]: ...


def _extract_safe_settings(raw_settings: Mapping[str, Any] | None) -> dict[str, Any]:
    if not raw_settings:
        return {}
    filtered = {k: v for k, v in raw_settings.items() if k in ALLOWED_LAUNCH_SETTINGS and v is not None}
    try:
        return sanitize_launch_settings(filtered)
    except Exception:
        return {}


class DispatcherWorkspaceAdapter:
    """Read-only adapter translating DispatcherService slots and launches into WorkspaceSlotInput."""

    def __init__(self, dispatcher: DispatcherLike) -> None:
        self.dispatcher = dispatcher

    def list_candidate_slots(
        self,
        *,
        gui: str | None = None,
        active_only: bool = True,
    ) -> tuple[WorkspaceSlotInput, ...]:
        recent_by_slot: dict[str, dict[str, Any]] = {}
        with contextlib.suppress(Exception):
            for rec in self.dispatcher.list_recent_terminal_launches(limit=500):
                sid = rec.get("slot_id")
                if isinstance(sid, str) and sid and sid not in recent_by_slot:
                    recent_by_slot[sid] = rec

        guis = self.dispatcher.list_guis(active_only=active_only)
        if gui is not None:
            guis = [
                g
                for g in guis
                if g.get("gui_id") == gui or str(g.get("alias", "")).casefold() == gui.casefold()
            ]

        inputs: list[WorkspaceSlotInput] = []
        for g in guis:
            gui_id = str(g["gui_id"])
            gui_alias = str(g["alias"]) if g.get("alias") is not None else None
            for slot in self.dispatcher.list_slots(gui=gui_id, active_only=active_only):
                converted = self._slot_dict_to_input(slot, gui_alias=gui_alias, recent=recent_by_slot.get(str(slot["slot_id"])))
                if converted is not None:
                    inputs.append(converted)
        return tuple(inputs)

    def slot_provider(self, slot_id: str) -> WorkspaceSlotInput | None:
        """Fetch fresh slot state directly from DispatcherService under execution guard."""
        try:
            slot = self.dispatcher.get_slot_by_id(slot_id)
        except Exception:
            return None
        recent_match: dict[str, Any] | None = None
        with contextlib.suppress(Exception):
            for rec in self.dispatcher.list_recent_terminal_launches(limit=200):
                if rec.get("slot_id") == slot_id:
                    recent_match = rec
                    break
        return self._slot_dict_to_input(slot, gui_alias=None, recent=recent_match)

    def associations_for_session(self, key: SessionKey) -> tuple[ManagedLaunchAssociation, ...]:
        """Join DispatcherService terminal-launch history to ManagedLaunchAssociation."""
        associations: list[ManagedLaunchAssociation] = []
        try:
            launches = self.dispatcher.list_recent_terminal_launches(limit=500)
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
            pane_id = rec.get("pane_id") or launch_id
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

    def build_receipt_source(
        self, managed_store: ManagedProcessStore | None
    ) -> TerminalLauncherManagedReceiptSource | None:
        if managed_store is None:
            return None
        return TerminalLauncherManagedReceiptSource(managed_store, self.associations_for_session)

    def _slot_dict_to_input(
        self,
        slot: Mapping[str, Any],
        *,
        gui_alias: str | None,
        recent: Mapping[str, Any] | None,
    ) -> WorkspaceSlotInput | None:
        current = slot.get("current") if isinstance(slot.get("current"), Mapping) else None
        provider = slot.get("current_provider") or (current.get("provider") if current else None)
        native_session_id = slot.get("current_session_id") or (current.get("native_session_id") if current else None)
        environment_id = slot.get("current_environment_id") or (current.get("environment_id") if current else None)
        if not provider or not native_session_id or not environment_id:
            return None

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
            git_commit=str(recent["git_commit"]) if recent and recent.get("git_commit") else None,
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
        runtime_kind = "wsl" if str(environment_id).startswith("env_wsl_") else "local"
        return WorkspaceSlotInput(
            slot_id=str(slot["slot_id"]),
            gui_id=str(slot["gui_id"]),
            provider=str(provider),
            native_session_id=str(native_session_id),
            environment_id=str(environment_id),
            runtime_kind=runtime_kind,
            lifecycle_state=str(slot.get("state", "active")),
            gui_alias=gui_alias or (str(recent["gui_alias"]) if recent and recent.get("gui_alias") else None),
            slot_name=str(slot["name"]) if slot.get("name") is not None else None,
            launch_settings=_extract_safe_settings(recent.get("settings") if recent else None),
            worktree=worktree,
            requested_topology=topology,
            metadata=metadata,
        )


class DispatcherSlotExecutionGuard:
    """Cooperating cross-process per-slot exclusion lock under <home_dir>/locks/."""

    def __init__(self, home_dir: Path) -> None:
        self.locks_dir = Path(home_dir) / "locks"
        self._handles: dict[str, Any] = {}

    def acquire_slot(
        self,
        slot_id: str,
        *,
        operator_id: str,
        checkpoint_id: str,
        queue_entry_id: str | None,
    ) -> SlotGuardLease:
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.locks_dir / f"slot_{slot_id}.lock"
        stream = lock_path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return SlotGuardLease(
                slot_id=slot_id,
                lease_token="",
                acquired=False,
                reason="slot_lock_held",
            )
        token = generate_id("sgl")
        self._handles[token] = stream
        return SlotGuardLease(
            slot_id=slot_id,
            lease_token=token,
            acquired=True,
            reason="acquired",
        )

    def release_slot(self, lease: SlotGuardLease) -> None:
        stream = self._handles.pop(lease.lease_token, None)
        if stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                with contextlib.suppress(OSError):
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                with contextlib.suppress(OSError):
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def build_manual_restore_command(item: RestorePlanItem | RestoreLaunchRequest) -> list[str]:
    """Build an exact non-managed provider resume command for manual restoration."""
    settings = item.launch_settings or {}
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
    """Concrete SessionLauncher using Terminal Launcher 0.2.0 plans and managed receipts."""

    def __init__(
        self,
        *,
        backend: TerminalBackend,
        managed_store: ManagedProcessStore,
        default_window: str = "llmd-restore",
    ) -> None:
        self.backend = backend
        self.managed_store = managed_store
        self.default_window = default_window

    def launch_session(self, request: RestoreLaunchRequest) -> RestoreLaunchOutcome:
        launch_id = generate_id("tlaunch")
        pane_id = generate_id("pane")
        topo = request.requested_topology
        target_window = (topo.target_window if topo and topo.target_window else None) or self.default_window
        tab_index = topo.requested_tab_index if topo and topo.requested_tab_index is not None else 0
        pane_index = topo.requested_pane_index if topo and topo.requested_pane_index is not None else 0
        layout = (topo.requested_layout if topo and topo.requested_layout else None) or "single"

        argv = tuple(build_manual_restore_command(request))
        pane_title = f"{request.provider}:{request.slot_id}"
        plan = TerminalLaunchPlan(
            tabs=(
                TabSpec(
                    title=f"Restore {request.slot_id}",
                    panes=(PaneSpec(title=pane_title, argv=argv, cwd=request.cwd),),
                    layout="single",
                ),
            ),
            target_window=target_window,
        )

        self.managed_store.reserve_launch(
            launch_id,
            target_window,
            [ManagedPaneReservation(pane_id=pane_id, tab_index=tab_index, pane_index=pane_index, requested_layout=layout)],
        )
        self.managed_store.mark_submission_started(launch_id)

        try:
            result = self.backend.launch(plan)
        except Exception as exc:
            self.managed_store.mark_submission_outcome(
                launch_id, LaunchSubmissionState.AMBIGUOUS, failure_code=type(exc).__name__
            )
            return RestoreLaunchOutcome(
                accepted=False,
                launch_id=launch_id,
                pane_id=pane_id,
                failure_reason=f"backend_exception:{type(exc).__name__}:{exc}",
                spawn_confirmed=False,
            )

        if result.status is LaunchStatus.FAILED:
            self.managed_store.mark_submission_outcome(
                launch_id, LaunchSubmissionState.REJECTED, failure_code=result.diagnostic or "launch_failed"
            )
            return RestoreLaunchOutcome(
                accepted=False,
                launch_id=launch_id,
                pane_id=pane_id,
                failure_reason=result.diagnostic or "backend_rejected",
                spawn_confirmed=False,
            )

        if result.status is LaunchStatus.AMBIGUOUS:
            self.managed_store.mark_submission_outcome(
                launch_id, LaunchSubmissionState.AMBIGUOUS, failure_code=result.diagnostic or "launch_ambiguous"
            )
            return RestoreLaunchOutcome(
                accepted=True,
                launch_id=launch_id,
                pane_id=pane_id,
                failure_reason=result.diagnostic or "submission_ambiguous",
                spawn_confirmed=False,
            )

        self.managed_store.mark_submission_outcome(launch_id, LaunchSubmissionState.ACCEPTED)
        records = self.managed_store.enumerate_processes(launch_id=launch_id)
        pane_rec = next((r for r in records if r.pane_id == pane_id), None)
        spawn_confirmed = bool(pane_rec is not None and pane_rec.spawn_acknowledged)
        return RestoreLaunchOutcome(
            accepted=True,
            launch_id=launch_id,
            pane_id=pane_id,
            spawn_confirmed=spawn_confirmed,
            association_confirmed=spawn_confirmed,
            resumability_confirmed=False,
        )
