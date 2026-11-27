"""Independently owned dispatcher and Terminal Launcher integration adapters."""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from .errors import ContinuityError, ErrorCode
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

_PROVIDER_ALLOWED_SETTINGS: dict[str, frozenset[str]] = {
    "codex": frozenset({"model", "sandbox", "approval_policy", "reasoning_effort", "search", "add_dirs", "profile"}),
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


class DispatcherLaunchCommandBuilder(Protocol):
    """Contract for Agent #1 to supply canonical LLMD-managed pane commands."""

    def build_pane_command(self, request: RestoreLaunchRequest) -> tuple[str, ...]: ...


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

    def _recent_by_exact_identity(self) -> dict[tuple[str, str, str, str], dict[str, Any]]:
        recent_by_identity: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        with contextlib.suppress(Exception):
            for rec in self.dispatcher.list_recent_terminal_launches(limit=500):
                sid = rec.get("slot_id")
                prov = rec.get("provider")
                nsid = rec.get("native_session_id")
                env_id = rec.get("environment_id")
                if all(isinstance(v, str) and v for v in (sid, prov, nsid, env_id)):
                    key = (str(sid), str(prov), str(nsid), str(env_id))
                    if key not in recent_by_identity:
                        recent_by_identity[key] = rec
        return recent_by_identity

    def list_candidate_slots(
        self,
        *,
        gui: str | None = None,
        active_only: bool = True,
    ) -> tuple[WorkspaceSlotInput, ...]:
        recent_by_identity = self._recent_by_exact_identity()
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
        recent_by_identity = self._recent_by_exact_identity()
        return self._slot_dict_to_input(
            slot,
            gui_alias=str(slot["gui_alias"]) if slot.get("gui_alias") is not None else None,
            recent_by_identity=recent_by_identity,
        )

    def associations_for_session(self, key: SessionKey) -> tuple[ManagedLaunchAssociation, ...]:
        """Join DispatcherService terminal-launch history to ManagedLaunchAssociation without inferring pane IDs."""
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
            pane_id = rec.get("pane_id")
            # Never infer pane_id from launch_id
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
        runtime_kind = self._resolve_runtime_kind(str(environment_id))
        auth_valid = True
        if self._authorization_lookup is not None:
            auth_valid = bool(self._authorization_lookup(slot))

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
            launch_settings=validate_provider_launch_settings(
                str(provider),
                recent.get("settings") if recent else None,
                strict=False,
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


def canonical_llmd_pane_command(
    request: RestoreLaunchRequest,
    *,
    home_dir: Path | None = None,
) -> tuple[str, ...]:
    """Build the canonical `llmd pane-run` command preserving slot/lifecycle/history safeguards."""
    argv = [sys.executable, "-m", "agent_continuity", "pane-run"]
    if home_dir is not None:
        argv.extend(["-H", str(home_dir)])
    argv.extend(["-s", request.slot_id])
    return tuple(argv)


def build_manual_restore_command(
    item: RestorePlanItem | RestoreLaunchRequest,
    *,
    home_dir: Path | None = None,
    prefer_llmd: bool = True,
) -> list[str]:
    """Prefer canonical exact-session LLMD continuation; fall back to direct native resume only if requested."""
    if prefer_llmd:
        argv = ["llmd", "continue"]
        if home_dir is not None:
            argv.extend(["-H", str(home_dir)])
        gui_selector = getattr(item, "gui_alias", None) or item.gui_id
        argv.extend(["-g", gui_selector, item.slot_id])
        return argv

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
        default_window: str = "llmd-restore",
        startup_timeout: float = 2.0,
        submission_timeout: float = 10.0,
    ) -> None:
        self.backend = backend
        self.managed_store = managed_store
        self.home_dir = home_dir
        self.command_builder = command_builder
        self.default_window = default_window
        self.startup_timeout = startup_timeout
        self.submission_timeout = submission_timeout

    def _pane_argv(self, request: RestoreLaunchRequest) -> tuple[str, ...]:
        validate_provider_launch_settings(request.provider, request.launch_settings, strict=True)
        if self.command_builder is not None:
            return tuple(self.command_builder.build_pane_command(request))
        return canonical_llmd_pane_command(request, home_dir=self.home_dir)

    def launch_session(self, request: RestoreLaunchRequest) -> RestoreLaunchOutcome:
        return self.launch_grouped([request])[request.slot_id]

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
            # Group by explicit requested_tab_index when present; otherwise chunk into <=4 panes per tab
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
            for tab_idx, (group_reqs, used_fallback) in enumerate(ordered_groups):
                panes: list[PaneSpec] = []
                for pane_idx, req in enumerate(group_reqs):
                    panes.append(
                        PaneSpec(
                            title=f"{req.provider}:{req.slot_id}",
                            argv=self._pane_argv(req),
                            cwd=req.cwd,
                        )
                    )
                    slot_order.append((tab_idx, pane_idx, req, used_fallback))
                requested_layout = (
                    group_reqs[0].requested_topology.requested_layout
                    if group_reqs[0].requested_topology
                    else None
                )
                canonical_layout = _layout_for_pane_count(len(panes))
                if requested_layout and requested_layout == canonical_layout:
                    chosen_layout = requested_layout
                else:
                    chosen_layout = canonical_layout
                tabs.append(
                    TabSpec(
                        title=" | ".join(p.title for p in panes),
                        panes=tuple(panes),
                        layout=chosen_layout,  # type: ignore[arg-type]
                    )
                )

            plan = TerminalLaunchPlan(tabs=tuple(tabs), target_window=target_window)
            launch_id = generate_id("tlaunch")

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
                        spawn_ok = bool(rec is not None and rec.spawn_acknowledged)
                        outcomes[req.slot_id] = RestoreLaunchOutcome(
                            accepted=True,
                            launch_id=launch_id,
                            pane_id=pane_id,
                            failure_reason=(
                                "relay_startup_timed_out" if not spawn_ok and managed_res.startup_timed_out else None
                            ),
                            spawn_confirmed=spawn_ok,
                            association_confirmed=spawn_ok,
                            resumability_confirmed=False,
                            submission_ambiguous=False,
                            geometry_fallback_used=used_fallback,
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
                        outcomes[req.slot_id] = RestoreLaunchOutcome(
                            accepted=False,
                            launch_id=launch_id,
                            pane_id=f"{launch_id}:{tab_idx}:{pane_idx}",
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
                        rec = recs.get(pane_id)
                        spawn_ok = bool(rec is not None and rec.spawn_acknowledged)
                        outcomes[req.slot_id] = RestoreLaunchOutcome(
                            accepted=True,
                            launch_id=launch_id,
                            pane_id=pane_id,
                            spawn_confirmed=spawn_ok,
                            association_confirmed=spawn_ok,
                            resumability_confirmed=False,
                            submission_ambiguous=False,
                            geometry_fallback_used=used_fallback,
                        )
        return outcomes
