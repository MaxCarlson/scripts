"""Independently owned shutdown and topology restoration components (LLMD-44, LLMD-45)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import ContinuityError, ErrorCode
from .events import atomic_write_json
from .identifiers import generate_id, now_utc_iso
from .restoration_queue import QueueEntry, QueueEntryStatus, RestorationQueue
from .runtime_discovery import (
    IdentityComparison,
    ManagementState,
    ProcessLiveness,
    ProcessSnapshot,
    RuntimeDiscovery,
    compare_process_identities,
    process_identity_from_windows_filetime,
)
from .workspace_checkpoint import (
    CheckpointStore,
    WorkspaceCheckpoint,
    WorkspaceSlotInput,
    WorkspaceSlotMetadata,
    WorkspaceTopologyRequest,
    observe_slots_batched,
    preview_checkpoint,
    revalidate_checkpoint,
)

RESTORE_RECOVERY_SCHEMA_VERSION = 2


class ManagedShutdownStoreProtocol(Protocol):
    """Structural contract for Terminal Launcher 0.2.0 ManagedProcessStore."""

    def enumerate_processes(self, *, launch_id: str | None = None) -> Sequence[Any]: ...

    def request_interrupt(self, pane_id: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class SlotGuardLease:
    """Opaque lease returned by Agent #1's SlotExecutionGuard."""

    slot_id: str
    lease_token: str
    acquired: bool
    reason: str = "acquired"


class SlotExecutionGuard(Protocol):
    """Cross-checkpoint and dispatcher-wide slot exclusion contract owned by Agent #1."""

    def acquire_slot(
        self,
        slot_id: str,
        *,
        operator_id: str,
        checkpoint_id: str,
        queue_entry_id: str | None,
    ) -> SlotGuardLease: ...

    def release_slot(self, lease: SlotGuardLease) -> None: ...


@dataclass(frozen=True, slots=True)
class ShutdownTargetCandidate:
    """One persisted-checkpoint slot evaluated for bounded owned-session shutdown."""

    slot_id: str
    gui_id: str
    provider: str
    native_session_id: str
    environment_id: str
    eligible: bool
    refusal_reason: str | None = None
    checkpoint_id: str | None = None
    launch_id: str | None = None
    pane_id: str | None = None
    terminal_session_id: str | None = None
    expected_pid: int | None = None
    expected_process_created: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "gui_id": self.gui_id,
            "provider": self.provider,
            "native_session_id": self.native_session_id,
            "environment_id": self.environment_id,
            "eligible": self.eligible,
            "refusal_reason": self.refusal_reason,
            "checkpoint_id": self.checkpoint_id,
            "launch_id": self.launch_id,
            "pane_id": self.pane_id,
            "terminal_session_id": self.terminal_session_id,
            "expected_pid": self.expected_pid,
            "expected_process_created": self.expected_process_created,
        }


@dataclass(frozen=True, slots=True)
class ShutdownPlan:
    """Read-only preview of bounded owned-session shutdown."""

    created_at: str
    targets: tuple[ShutdownTargetCandidate, ...]
    checkpoint_id: str | None = None

    @property
    def eligible_targets(self) -> tuple[ShutdownTargetCandidate, ...]:
        return tuple(item for item in self.targets if item.eligible)

    @property
    def refused_targets(self) -> tuple[ShutdownTargetCandidate, ...]:
        return tuple(item for item in self.targets if not item.eligible)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "checkpoint_id": self.checkpoint_id,
            "targets": [item.to_dict() for item in self.targets],
        }


@dataclass(frozen=True, slots=True)
class ShutdownTargetOutcome:
    """Distinct requested / sent / interrupt / observed exit state for one shutdown target."""

    slot_id: str
    pane_id: str | None
    launch_id: str | None
    requested: bool
    request_reason: str
    sent: bool
    sent_state: str
    observed_state: str
    exit_code: int | None = None
    interrupt_delivered: bool = False
    provider_exit_verified: bool = False
    provider_metadata_finalized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "pane_id": self.pane_id,
            "launch_id": self.launch_id,
            "requested": self.requested,
            "request_reason": self.request_reason,
            "sent": self.sent,
            "sent_state": self.sent_state,
            "observed_state": self.observed_state,
            "exit_code": self.exit_code,
            "interrupt_delivered": self.interrupt_delivered,
            "provider_exit_verified": self.provider_exit_verified,
            "provider_metadata_finalized": self.provider_metadata_finalized,
        }


@dataclass(frozen=True, slots=True)
class ShutdownReport:
    """Aggregate bounded owned-session shutdown report."""

    executed_at: str
    timeout_seconds: float
    outcomes: tuple[ShutdownTargetOutcome, ...]

    @property
    def all_exited(self) -> bool:
        return all(item.observed_state == "exited" for item in self.outcomes)

    @property
    def partial(self) -> bool:
        exited = sum(1 for item in self.outcomes if item.observed_state == "exited")
        return 0 < exited < len(self.outcomes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "executed_at": self.executed_at,
            "timeout_seconds": self.timeout_seconds,
            "all_exited": self.all_exited,
            "partial": self.partial,
            "outcomes": [item.to_dict() for item in self.outcomes],
        }


def _record_attr(record: object, name: str, default: Any = None) -> Any:
    return getattr(record, name, default)


def _enum_text(value: object) -> str:
    return str(getattr(value, "value", value))


class OwnedShutdownCoordinator:
    """LLMD-45 bounded owned-session shutdown using exact managed receipts only."""

    def __init__(self, store: ManagedShutdownStoreProtocol | None = None) -> None:
        self.store = store

    def preview_shutdown_for_checkpoint(
        self,
        checkpoint: WorkspaceCheckpoint,
        *,
        observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
        snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
    ) -> ShutdownPlan:
        """Restrict shutdown candidates strictly to a persisted checkpoint's exact identities."""
        slots = [
            WorkspaceSlotInput(
                slot_id=entry.slot_id,
                gui_id=entry.gui_id,
                provider=entry.provider,
                native_session_id=entry.native_session_id,
                environment_id=entry.environment_id,
                runtime_kind=entry.runtime_kind,
                lifecycle_state=entry.lifecycle_state,
                known_process_identity=(
                    entry.observed_topology.managed_pane.to_process_identity()
                    if entry.observed_topology.managed_pane is not None
                    else None
                ),
            )
            for entry in checkpoint.sessions
        ]
        plan = self.preview_shutdown(
            slots,
            observers=observers,
            snapshots=snapshots,
            checkpoint=checkpoint,
        )
        return ShutdownPlan(
            created_at=plan.created_at,
            targets=plan.targets,
            checkpoint_id=checkpoint.checkpoint_id,
        )

    def preview_shutdown(
        self,
        slots: Sequence[WorkspaceSlotInput],
        *,
        observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
        snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
        checkpoint: WorkspaceCheckpoint | None = None,
    ) -> ShutdownPlan:
        """Evaluate which slots have verified managed ownership eligible for shutdown."""
        checkpoint_by_slot = {entry.slot_id: entry for entry in checkpoint.sessions} if checkpoint is not None else None
        observations = observe_slots_batched(slots, observers=observers, snapshots=snapshots)
        records_by_pane: dict[str, Any] = {}
        if self.store is not None:
            for rec in self.store.enumerate_processes():
                records_by_pane[str(_record_attr(rec, "pane_id"))] = rec

        candidates: list[ShutdownTargetCandidate] = []
        for slot in slots:
            chk_entry = checkpoint_by_slot.get(slot.slot_id) if checkpoint_by_slot is not None else None
            if checkpoint_by_slot is not None and chk_entry is None:
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason="not_in_persisted_checkpoint",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                    )
                )
                continue
            if chk_entry is not None and (
                chk_entry.gui_id != slot.gui_id
                or chk_entry.provider != slot.provider
                or chk_entry.native_session_id != slot.native_session_id
                or chk_entry.environment_id != slot.environment_id
            ):
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason="checkpoint_identity_mismatch",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                    )
                )
                continue

            obs = observations[slot.slot_id]
            if obs.identity_conflict:
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason="identity_conflict",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                    )
                )
                continue
            if obs.management is not ManagementState.MANAGED or obs.managed_pane is None:
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason=f"unverified_ownership:{obs.management.value}",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                    )
                )
                continue
            if (
                chk_entry is not None
                and chk_entry.observed_topology.managed_pane is not None
                and (
                    chk_entry.observed_topology.managed_pane.pane_id != obs.managed_pane.pane_id
                    or chk_entry.observed_topology.managed_pane.launch_id != obs.managed_pane.launch_id
                )
            ):
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason="checkpoint_managed_pane_mismatch",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                    )
                )
                continue
            if self.store is None:
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason="managed_store_unavailable",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                        launch_id=obs.managed_pane.launch_id,
                        pane_id=obs.managed_pane.pane_id,
                        terminal_session_id=obs.managed_pane.terminal_session_id,
                    )
                )
                continue

            pane_id = obs.managed_pane.pane_id
            rec = records_by_pane.get(pane_id)
            if rec is None or not bool(_record_attr(rec, "spawn_acknowledged", False)):
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason="missing_acknowledged_receipt",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                        launch_id=obs.managed_pane.launch_id,
                        pane_id=pane_id,
                    )
                )
                continue

            rec_pid = _record_attr(rec, "pid")
            rec_created = _record_attr(rec, "process_created")
            if rec_pid is None or rec_created is None:
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason="missing_process_creation_identity",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                        launch_id=obs.managed_pane.launch_id,
                        pane_id=pane_id,
                    )
                )
                continue

            rec_identity = process_identity_from_windows_filetime(int(rec_pid), int(rec_created))
            cmp_result = compare_process_identities(obs.managed_pane.process_identity, rec_identity)
            if cmp_result is not IdentityComparison.SAME:
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason=f"process_identity_{cmp_result.value}",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                        launch_id=obs.managed_pane.launch_id,
                        pane_id=pane_id,
                    )
                )
                continue

            rec_state = _enum_text(_record_attr(rec, "state", "unknown")).lower()
            rec_liveness = _enum_text(_record_attr(rec, "liveness", "unknown")).lower()
            if rec_state == "stale":
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason="stale_pid_reuse",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                        launch_id=obs.managed_pane.launch_id,
                        pane_id=pane_id,
                    )
                )
                continue
            if rec_state in {"exited", "failed"} or rec_liveness == "exited":
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason="already_exited",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                        launch_id=obs.managed_pane.launch_id,
                        pane_id=pane_id,
                    )
                )
                continue
            if obs.process_liveness is not ProcessLiveness.RUNNING and rec_liveness != "alive":
                candidates.append(
                    ShutdownTargetCandidate(
                        slot_id=slot.slot_id,
                        gui_id=slot.gui_id,
                        provider=slot.provider,
                        native_session_id=slot.native_session_id,
                        environment_id=slot.environment_id,
                        eligible=False,
                        refusal_reason=f"process_not_confirmed_running:{rec_liveness}",
                        checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                        launch_id=obs.managed_pane.launch_id,
                        pane_id=pane_id,
                    )
                )
                continue

            candidates.append(
                ShutdownTargetCandidate(
                    slot_id=slot.slot_id,
                    gui_id=slot.gui_id,
                    provider=slot.provider,
                    native_session_id=slot.native_session_id,
                    environment_id=slot.environment_id,
                    eligible=True,
                    checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
                    launch_id=obs.managed_pane.launch_id,
                    pane_id=pane_id,
                    terminal_session_id=obs.managed_pane.terminal_session_id,
                    expected_pid=int(rec_pid),
                    expected_process_created=int(rec_created),
                )
            )

        return ShutdownPlan(
            created_at=now_utc_iso(),
            targets=tuple(candidates),
            checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
        )

    def execute_shutdown(
        self,
        plan: ShutdownPlan,
        *,
        authorized: bool,
        current_slots: Sequence[WorkspaceSlotInput] | None = None,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.05,
        provider_exit_verifier: Callable[[ShutdownTargetCandidate, int | None], bool] | None = None,
    ) -> ShutdownReport:
        """Request bounded graceful shutdown for verified owned panes only."""
        if not authorized:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                "Owned-session shutdown requires explicit operator authorization.",
            )
        if timeout_seconds <= 0:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                "Shutdown timeout_seconds must be positive.",
                {"timeout_seconds": timeout_seconds},
            )

        current_by_slot = {slot.slot_id: slot for slot in (current_slots or ())}
        outcomes_by_slot: dict[str, ShutdownTargetOutcome] = {}
        active_panes: dict[str, ShutdownTargetCandidate] = {}

        for target in plan.targets:
            if not target.eligible:
                outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                    slot_id=target.slot_id,
                    pane_id=target.pane_id,
                    launch_id=target.launch_id,
                    requested=False,
                    request_reason=target.refusal_reason or "ineligible",
                    sent=False,
                    sent_state="not_sent",
                    observed_state="refused",
                )
                continue

            if current_slots is not None:
                live_slot = current_by_slot.get(target.slot_id)
                if live_slot is None:
                    outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                        slot_id=target.slot_id,
                        pane_id=target.pane_id,
                        launch_id=target.launch_id,
                        requested=False,
                        request_reason="race_slot_removed",
                        sent=False,
                        sent_state="not_sent",
                        observed_state="refused",
                    )
                    continue
                if live_slot.gui_id != target.gui_id or live_slot.native_session_id != target.native_session_id:
                    outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                        slot_id=target.slot_id,
                        pane_id=target.pane_id,
                        launch_id=target.launch_id,
                        requested=False,
                        request_reason="race_session_or_gui_changed",
                        sent=False,
                        sent_state="not_sent",
                        observed_state="refused",
                    )
                    continue

            if self.store is None or target.pane_id is None:
                outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                    slot_id=target.slot_id,
                    pane_id=target.pane_id,
                    launch_id=target.launch_id,
                    requested=False,
                    request_reason="managed_store_unavailable",
                    sent=False,
                    sent_state="not_sent",
                    observed_state="refused",
                )
                continue

            # Revalidate ownership immediately before signaling
            live_records = {
                str(_record_attr(rec, "pane_id")): rec
                for rec in self.store.enumerate_processes(launch_id=target.launch_id)
            }
            rec = live_records.get(target.pane_id)
            if (
                rec is None
                or _record_attr(rec, "pid") != target.expected_pid
                or _record_attr(rec, "process_created") != target.expected_process_created
                or _enum_text(_record_attr(rec, "state", "unknown")).lower() == "stale"
                or _enum_text(_record_attr(rec, "liveness", "unknown")).lower() == "exited"
            ):
                outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                    slot_id=target.slot_id,
                    pane_id=target.pane_id,
                    launch_id=target.launch_id,
                    requested=False,
                    request_reason="race_process_identity_changed",
                    sent=False,
                    sent_state="not_sent",
                    observed_state="refused",
                )
                continue

            req_result = self.store.request_interrupt(target.pane_id)
            accepted = bool(_record_attr(req_result, "accepted", False))
            reason = str(_record_attr(req_result, "reason", "unknown"))
            if not accepted:
                outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                    slot_id=target.slot_id,
                    pane_id=target.pane_id,
                    launch_id=target.launch_id,
                    requested=False,
                    request_reason=reason,
                    sent=False,
                    sent_state="rejected",
                    observed_state="refused",
                )
                continue

            active_panes[target.pane_id] = target
            outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                slot_id=target.slot_id,
                pane_id=target.pane_id,
                launch_id=target.launch_id,
                requested=True,
                request_reason=reason,
                sent=False,
                sent_state="pending",
                observed_state="still_running",
            )

        if active_panes and self.store is not None:
            deadline = time.monotonic() + timeout_seconds
            pending_pane_ids = set(active_panes)
            while pending_pane_ids:
                current_records = {
                    str(_record_attr(rec, "pane_id")): rec for rec in self.store.enumerate_processes()
                }
                for pane_id in list(pending_pane_ids):
                    target = active_panes[pane_id]
                    rec = current_records.get(pane_id)
                    if rec is None:
                        continue
                    sent = bool(_record_attr(rec, "shutdown_delivered", False))
                    interruption_state = _enum_text(_record_attr(rec, "interruption_state", "none")).lower()
                    sent_state = "delivered" if sent else interruption_state
                    rec_state = _enum_text(_record_attr(rec, "state", "unknown")).lower()
                    rec_liveness = _enum_text(_record_attr(rec, "liveness", "unknown")).lower()

                    if (
                        _record_attr(rec, "pid") != target.expected_pid
                        or _record_attr(rec, "process_created") != target.expected_process_created
                        or rec_state == "stale"
                    ):
                        outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                            slot_id=target.slot_id,
                            pane_id=pane_id,
                            launch_id=target.launch_id,
                            requested=True,
                            request_reason=outcomes_by_slot[target.slot_id].request_reason,
                            sent=sent,
                            sent_state=sent_state,
                            observed_state="identity_changed",
                            interrupt_delivered=sent,
                            provider_exit_verified=False,
                            provider_metadata_finalized=False,
                        )
                        pending_pane_ids.remove(pane_id)
                        continue

                    exited_at = _record_attr(rec, "exited_at")
                    exit_code = _record_attr(rec, "exit_code")
                    if exited_at is not None or rec_state == "exited" or rec_liveness == "exited":
                        parsed_code = int(exit_code) if exit_code is not None else None
                        provider_verified = (
                            bool(provider_exit_verifier(target, parsed_code))
                            if provider_exit_verifier is not None
                            else False
                        )
                        outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                            slot_id=target.slot_id,
                            pane_id=pane_id,
                            launch_id=target.launch_id,
                            requested=True,
                            request_reason=outcomes_by_slot[target.slot_id].request_reason,
                            sent=sent,
                            sent_state=sent_state,
                            observed_state="exited",
                            exit_code=parsed_code,
                            interrupt_delivered=sent,
                            provider_exit_verified=provider_verified,
                            provider_metadata_finalized=False,
                        )
                        pending_pane_ids.remove(pane_id)
                    else:
                        outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                            slot_id=target.slot_id,
                            pane_id=pane_id,
                            launch_id=target.launch_id,
                            requested=True,
                            request_reason=outcomes_by_slot[target.slot_id].request_reason,
                            sent=sent,
                            sent_state=sent_state,
                            observed_state="still_running",
                            interrupt_delivered=sent,
                            provider_exit_verified=False,
                            provider_metadata_finalized=False,
                        )
                if not pending_pane_ids or time.monotonic() >= deadline:
                    break
                time.sleep(min(poll_interval_seconds, max(0.001, deadline - time.monotonic())))

            for pane_id in pending_pane_ids:
                target = active_panes[pane_id]
                prev = outcomes_by_slot[target.slot_id]
                outcomes_by_slot[target.slot_id] = ShutdownTargetOutcome(
                    slot_id=target.slot_id,
                    pane_id=pane_id,
                    launch_id=target.launch_id,
                    requested=prev.requested,
                    request_reason=prev.request_reason,
                    sent=prev.sent,
                    sent_state=prev.sent_state,
                    observed_state="timed_out",
                    exit_code=prev.exit_code,
                    interrupt_delivered=prev.interrupt_delivered,
                    provider_exit_verified=False,
                    provider_metadata_finalized=False,
                )

        ordered = tuple(outcomes_by_slot[target.slot_id] for target in plan.targets)
        return ShutdownReport(
            executed_at=now_utc_iso(),
            timeout_seconds=timeout_seconds,
            outcomes=ordered,
        )


@dataclass(frozen=True, slots=True)
class RestoreLaunchRequest:
    """Validated restoration launch payload passed to an injected SessionLauncher."""

    checkpoint_id: str
    queue_entry_id: str | None
    slot_id: str
    gui_id: str
    provider: str
    native_session_id: str
    environment_id: str
    runtime_kind: str
    cwd: str | None
    launch_settings: dict[str, Any]
    requested_topology: WorkspaceTopologyRequest | None
    metadata: WorkspaceSlotMetadata


@dataclass(frozen=True, slots=True)
class RestoreLaunchOutcome:
    """Outcome returned by an injected SessionLauncher distinguishing acceptance vs spawn."""

    accepted: bool
    launch_id: str | None = None
    pane_id: str | None = None
    terminal_session_id: str | None = None
    failure_reason: str | None = None
    spawn_confirmed: bool | None = None
    association_confirmed: bool = False
    resumability_confirmed: bool = False


class SessionLauncher(Protocol):
    """Pluggable session-restoration launcher owned by dispatcher/CLI integration."""

    def launch_session(self, request: RestoreLaunchRequest) -> RestoreLaunchOutcome: ...


@dataclass(frozen=True, slots=True)
class RestorePlanItem:
    """One checkpointed session evaluated for restoration."""

    slot_id: str
    gui_id: str
    provider: str
    native_session_id: str
    environment_id: str
    runtime_kind: str
    action: str
    reasons: tuple[str, ...]
    cwd: str | None
    launch_settings: dict[str, Any]
    requested_topology: WorkspaceTopologyRequest | None
    metadata: WorkspaceSlotMetadata
    queue_entry_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "gui_id": self.gui_id,
            "provider": self.provider,
            "native_session_id": self.native_session_id,
            "environment_id": self.environment_id,
            "runtime_kind": self.runtime_kind,
            "action": self.action,
            "reasons": list(self.reasons),
            "cwd": self.cwd,
            "launch_settings": dict(self.launch_settings),
            "requested_topology": self.requested_topology.to_dict() if self.requested_topology else None,
            "metadata": self.metadata.to_dict(),
            "queue_entry_id": self.queue_entry_id,
        }


@dataclass(frozen=True, slots=True)
class RestorePlan:
    """Read-only preview of a checkpoint/topology restoration."""

    checkpoint_id: str
    created_at: str
    items: tuple[RestorePlanItem, ...]
    stale: bool
    stale_reasons: tuple[str, ...]

    @property
    def ready_items(self) -> tuple[RestorePlanItem, ...]:
        return tuple(item for item in self.items if item.action == "restore")

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at,
            "stale": self.stale,
            "stale_reasons": list(self.stale_reasons),
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class ObservedLaunchReceipt:
    """Observed LLMD-40 managed receipt recorded separately from requested layout."""

    launch_id: str
    pane_id: str
    state: str
    requested_layout: str | None = None
    requested_tab_index: int | None = None
    requested_pane_index: int | None = None
    pid: int | None = None
    process_created: int | None = None
    spawn_acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "pane_id": self.pane_id,
            "state": self.state,
            "requested_layout": self.requested_layout,
            "requested_tab_index": self.requested_tab_index,
            "requested_pane_index": self.requested_pane_index,
            "pid": self.pid,
            "process_created": self.process_created,
            "spawn_acknowledged": self.spawn_acknowledged,
        }


@dataclass(frozen=True, slots=True)
class RestoreItemOutcome:
    """Execution outcome for one restoration item."""

    slot_id: str
    queue_entry_id: str | None
    status: str
    reason: str | None = None
    launch_accepted: bool = False
    spawn_confirmed: bool = False
    association_confirmed: bool = False
    resumability_confirmed: bool = False
    requested_topology: WorkspaceTopologyRequest | None = None
    observed_receipt: ObservedLaunchReceipt | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "queue_entry_id": self.queue_entry_id,
            "status": self.status,
            "reason": self.reason,
            "launch_accepted": self.launch_accepted,
            "spawn_confirmed": self.spawn_confirmed,
            "association_confirmed": self.association_confirmed,
            "resumability_confirmed": self.resumability_confirmed,
            "requested_topology": self.requested_topology.to_dict() if self.requested_topology else None,
            "observed_receipt": self.observed_receipt.to_dict() if self.observed_receipt else None,
        }


@dataclass(frozen=True, slots=True)
class RestoreReport:
    """Aggregate restoration execution report and durable recovery record."""

    restore_id: str
    checkpoint_id: str
    executed_at: str
    operator_id: str
    outcomes: tuple[RestoreItemOutcome, ...]
    partial_failure: bool
    recovery_record_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESTORE_RECOVERY_SCHEMA_VERSION,
            "restore_id": self.restore_id,
            "checkpoint_id": self.checkpoint_id,
            "executed_at": self.executed_at,
            "operator_id": self.operator_id,
            "partial_failure": self.partial_failure,
            "recovery_record_path": self.recovery_record_path,
            "outcomes": [item.to_dict() for item in self.outcomes],
        }


class TopologyRestorer:
    """LLMD-44 operator-authorized topology and session restoration component."""

    def preview_restore(
        self,
        checkpoint: WorkspaceCheckpoint,
        *,
        queue: RestorationQueue | None = None,
        current_slots: Sequence[WorkspaceSlotInput] | None = None,
        observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
        snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
        path_exists: Callable[[str], bool] | None = None,
        allow_reserved_claude: bool = False,
        allow_unknown_runtime: bool = False,
    ) -> RestorePlan:
        """Revalidate a checkpoint and produce a read-only restoration plan."""
        reval = revalidate_checkpoint(
            checkpoint,
            current_slots=current_slots,
            observers=observers,
            snapshots=snapshots,
            path_exists=path_exists,
            allow_unknown_runtime=allow_unknown_runtime,
        )
        reval_by_slot = {entry.slot_id: entry for entry in reval.entries}
        queue_by_slot: dict[str, QueueEntry] = {}
        if queue is not None:
            for q_entry in queue.list_entries(checkpoint_id=checkpoint.checkpoint_id):
                queue_by_slot[q_entry.slot_id] = q_entry

        items: list[RestorePlanItem] = []
        for entry in checkpoint.sessions:
            rev = reval_by_slot[entry.slot_id]
            q_entry = queue_by_slot.get(entry.slot_id)
            reasons = list(rev.reasons)

            if q_entry is not None and q_entry.status in {QueueEntryStatus.COMPLETED, QueueEntryStatus.CANCELLED}:
                action = f"skip_{q_entry.status.value}"
                reasons.append(f"queue_{q_entry.status.value}")
            elif q_entry is not None and q_entry.status in {QueueEntryStatus.CLAIMED, QueueEntryStatus.LAUNCHING}:
                action = "skip_claimed"
                reasons.append("queue_claimed_by_operator")
            elif q_entry is not None and q_entry.status is QueueEntryStatus.AMBIGUOUS:
                action = "blocked_ambiguous_launch"
                reasons.append("ambiguous_launch_requires_resolution")
            elif rev.already_running:
                action = "skip_already_running"
            elif "unknown_runtime_evidence" in rev.reasons and not allow_unknown_runtime:
                action = "blocked_unknown_runtime"
            elif "reserved_unconfirmed" in rev.reasons and not allow_reserved_claude:
                action = "blocked_reserved_unconfirmed"
            elif not rev.can_restore and not (
                allow_reserved_claude and set(rev.reasons) == {"reserved_unconfirmed"}
            ):
                action = "blocked_stale_or_conflict"
            else:
                action = "restore"

            items.append(
                RestorePlanItem(
                    slot_id=entry.slot_id,
                    gui_id=rev.current_gui_id or entry.gui_id,
                    provider=entry.provider,
                    native_session_id=entry.native_session_id,
                    environment_id=entry.environment_id,
                    runtime_kind=entry.runtime_kind,
                    action=action,
                    reasons=tuple(dict.fromkeys(reasons)),
                    cwd=entry.worktree.primary_cwd(),
                    launch_settings=dict(entry.launch_settings),
                    requested_topology=entry.requested_topology,
                    metadata=entry.metadata,
                    queue_entry_id=q_entry.queue_entry_id if q_entry else None,
                )
            )

        return RestorePlan(
            checkpoint_id=checkpoint.checkpoint_id,
            created_at=now_utc_iso(),
            items=tuple(items),
            stale=reval.stale,
            stale_reasons=reval.stale_reasons,
        )

    def execute_restore(
        self,
        plan: RestorePlan,
        *,
        authorized: bool,
        operator_id: str,
        launcher: SessionLauncher,
        checkpoint: WorkspaceCheckpoint | None = None,
        queue: RestorationQueue | None = None,
        receipt_store: ManagedShutdownStoreProtocol | None = None,
        slot_guard: SlotExecutionGuard | None = None,
        authorization_check: Callable[[RestorePlanItem], tuple[bool, str | None]] | None = None,
        recovery_dir: Path | None = None,
        current_slots: Sequence[WorkspaceSlotInput] | None = None,
        observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
        snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
        path_exists: Callable[[str], bool] | None = None,
        allow_unknown_runtime: bool = False,
        allow_reserved_claude: bool = False,
    ) -> RestoreReport:
        """Execute an authorized restore plan with execution-boundary revalidation and durable recovery."""
        if not authorized:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                "Topology restoration requires explicit operator authorization.",
            )
        if not operator_id or not operator_id.strip():
            raise ContinuityError(ErrorCode.INVALID_INPUT, "operator_id cannot be empty.")

        if queue is not None and checkpoint is not None:
            queue.enqueue_checkpoint(checkpoint)

        queue_by_slot: dict[str, QueueEntry] = {}
        if queue is not None:
            for q_entry in queue.list_entries(checkpoint_id=plan.checkpoint_id):
                queue_by_slot[q_entry.slot_id] = q_entry

        outcomes: list[RestoreItemOutcome] = []
        any_uncertain_or_failed = False
        any_succeeded = False

        for item in plan.items:
            q_entry = queue_by_slot.get(item.slot_id)
            q_id = q_entry.queue_entry_id if q_entry else item.queue_entry_id

            if item.action != "restore":
                outcomes.append(
                    RestoreItemOutcome(
                        slot_id=item.slot_id,
                        queue_entry_id=q_id,
                        status="skipped",
                        reason=item.action,
                        requested_topology=item.requested_topology,
                    )
                )
                continue

            claim_token: str | None = None
            if queue is not None and q_id is not None:
                claim_res = queue.claim(q_id, operator_id=operator_id)
                if not claim_res.acquired or claim_res.claim_token is None:
                    outcomes.append(
                        RestoreItemOutcome(
                            slot_id=item.slot_id,
                            queue_entry_id=q_id,
                            status="skipped",
                            reason=f"concurrent_claim:{claim_res.reason}",
                            requested_topology=item.requested_topology,
                        )
                    )
                    continue
                claim_token = claim_res.claim_token

            lease: SlotGuardLease | None = None
            try:
                if slot_guard is not None:
                    lease = slot_guard.acquire_slot(
                        item.slot_id,
                        operator_id=operator_id,
                        checkpoint_id=plan.checkpoint_id,
                        queue_entry_id=q_id,
                    )
                    if not lease.acquired:
                        fail_reason = f"slot_guard_busy:{lease.reason}"
                        if queue is not None and q_id is not None and claim_token is not None:
                            queue.release(q_id, claim_token=claim_token, reason=fail_reason)
                        outcomes.append(
                            RestoreItemOutcome(
                                slot_id=item.slot_id,
                                queue_entry_id=q_id,
                                status="skipped",
                                reason=fail_reason,
                                requested_topology=item.requested_topology,
                            )
                        )
                        continue

                # Fresh execution-boundary revalidation AFTER acquiring claim & slot guard
                if authorization_check is not None:
                    auth_ok, auth_reason = authorization_check(item)
                    if not auth_ok:
                        fail_reason = f"authorization_revoked:{auth_reason or 'denied'}"
                        if queue is not None and q_id is not None and claim_token is not None:
                            queue.record_failure(q_id, claim_token=claim_token, reason=fail_reason, partial=False)
                        any_uncertain_or_failed = True
                        outcomes.append(
                            RestoreItemOutcome(
                                slot_id=item.slot_id,
                                queue_entry_id=q_id,
                                status="failed",
                                reason=fail_reason,
                                requested_topology=item.requested_topology,
                            )
                        )
                        continue

                if checkpoint is not None:
                    fresh_reval = revalidate_checkpoint(
                        checkpoint,
                        current_slots=current_slots,
                        observers=observers,
                        snapshots=snapshots,
                        path_exists=path_exists,
                        allow_unknown_runtime=allow_unknown_runtime,
                    )
                    fresh_entry = next((e for e in fresh_reval.entries if e.slot_id == item.slot_id), None)
                    if fresh_entry is not None:
                        allowed_reserved_only = (
                            allow_reserved_claude and set(fresh_entry.reasons) == {"reserved_unconfirmed"}
                        )
                        if not fresh_entry.can_restore and not allowed_reserved_only:
                            fail_reason = f"execution_revalidation_failed:{','.join(fresh_entry.reasons)}"
                            if queue is not None and q_id is not None and claim_token is not None:
                                queue.record_failure(
                                    q_id, claim_token=claim_token, reason=fail_reason, partial=False
                                )
                            any_uncertain_or_failed = True
                            outcomes.append(
                                RestoreItemOutcome(
                                    slot_id=item.slot_id,
                                    queue_entry_id=q_id,
                                    status="failed",
                                    reason=fail_reason,
                                    requested_topology=item.requested_topology,
                                )
                            )
                            continue

                if queue is not None and q_id is not None and claim_token is not None:
                    queue.mark_launching(q_id, claim_token=claim_token)

                launch_req = RestoreLaunchRequest(
                    checkpoint_id=plan.checkpoint_id,
                    queue_entry_id=q_id,
                    slot_id=item.slot_id,
                    gui_id=item.gui_id,
                    provider=item.provider,
                    native_session_id=item.native_session_id,
                    environment_id=item.environment_id,
                    runtime_kind=item.runtime_kind,
                    cwd=item.cwd,
                    launch_settings=dict(item.launch_settings),
                    requested_topology=item.requested_topology,
                    metadata=item.metadata,
                )

                try:
                    launch_res = launcher.launch_session(launch_req)
                except Exception as exc:
                    fail_reason = f"launcher_exception:{type(exc).__name__}:{exc}"
                    if queue is not None and q_id is not None and claim_token is not None:
                        queue.mark_ambiguous(
                            q_id,
                            claim_token=claim_token,
                            reason=fail_reason,
                            launch_submission_state="ambiguous",
                        )
                    any_uncertain_or_failed = True
                    outcomes.append(
                        RestoreItemOutcome(
                            slot_id=item.slot_id,
                            queue_entry_id=q_id,
                            status="ambiguous",
                            reason=fail_reason,
                            requested_topology=item.requested_topology,
                        )
                    )
                    continue

                if not launch_res.accepted:
                    fail_reason = launch_res.failure_reason or "launch_rejected"
                    if queue is not None and q_id is not None and claim_token is not None:
                        queue.record_failure(q_id, claim_token=claim_token, reason=fail_reason, partial=True)
                    any_uncertain_or_failed = True
                    outcomes.append(
                        RestoreItemOutcome(
                            slot_id=item.slot_id,
                            queue_entry_id=q_id,
                            status="failed",
                            reason=fail_reason,
                            launch_accepted=False,
                            spawn_confirmed=False,
                            requested_topology=item.requested_topology,
                        )
                    )
                    continue

                observed_receipt = self._lookup_receipt(
                    receipt_store,
                    launch_id=launch_res.launch_id,
                    pane_id=launch_res.pane_id,
                )
                spawn_confirmed = bool(
                    launch_res.spawn_confirmed is True
                    or (observed_receipt is not None and observed_receipt.spawn_acknowledged)
                )
                if not spawn_confirmed:
                    uncertain_reason = "launch_accepted_spawn_unconfirmed"
                    if queue is not None and q_id is not None and claim_token is not None:
                        queue.mark_ambiguous(
                            q_id,
                            claim_token=claim_token,
                            reason=uncertain_reason,
                            launch_id=launch_res.launch_id,
                            launch_submission_state="accepted",
                        )
                    any_uncertain_or_failed = True
                    outcomes.append(
                        RestoreItemOutcome(
                            slot_id=item.slot_id,
                            queue_entry_id=q_id,
                            status="accepted_unconfirmed",
                            reason=uncertain_reason,
                            launch_accepted=True,
                            spawn_confirmed=False,
                            association_confirmed=launch_res.association_confirmed,
                            resumability_confirmed=launch_res.resumability_confirmed,
                            requested_topology=item.requested_topology,
                            observed_receipt=observed_receipt,
                        )
                    )
                    continue

                if queue is not None and q_id is not None and claim_token is not None:
                    queue.complete(
                        q_id,
                        claim_token=claim_token,
                        launch_id=launch_res.launch_id,
                        spawn_confirmed=True,
                    )
                any_succeeded = True
                outcomes.append(
                    RestoreItemOutcome(
                        slot_id=item.slot_id,
                        queue_entry_id=q_id,
                        status="restored",
                        launch_accepted=True,
                        spawn_confirmed=True,
                        association_confirmed=launch_res.association_confirmed,
                        resumability_confirmed=launch_res.resumability_confirmed,
                        requested_topology=item.requested_topology,
                        observed_receipt=observed_receipt,
                    )
                )
            finally:
                if lease is not None and slot_guard is not None and lease.acquired:
                    slot_guard.release_slot(lease)

        restore_id = generate_id("rst")
        partial_failure = any_uncertain_or_failed and any_succeeded
        recovery_path_str: str | None = None
        if any_uncertain_or_failed and recovery_dir is not None:
            recovery_path = Path(recovery_dir) / f"{restore_id}.json"
            recovery_path_str = str(recovery_path)
            report_payload = RestoreReport(
                restore_id=restore_id,
                checkpoint_id=plan.checkpoint_id,
                executed_at=now_utc_iso(),
                operator_id=operator_id,
                outcomes=tuple(outcomes),
                partial_failure=partial_failure,
                recovery_record_path=recovery_path_str,
            )
            atomic_write_json(recovery_path, report_payload.to_dict())
            return report_payload

        return RestoreReport(
            restore_id=restore_id,
            checkpoint_id=plan.checkpoint_id,
            executed_at=now_utc_iso(),
            operator_id=operator_id,
            outcomes=tuple(outcomes),
            partial_failure=partial_failure,
            recovery_record_path=recovery_path_str,
        )

    @staticmethod
    def _lookup_receipt(
        receipt_store: ManagedShutdownStoreProtocol | None,
        *,
        launch_id: str | None,
        pane_id: str | None,
    ) -> ObservedLaunchReceipt | None:
        if receipt_store is None or launch_id is None:
            return None
        for rec in receipt_store.enumerate_processes(launch_id=launch_id):
            rec_pane = str(_record_attr(rec, "pane_id"))
            if pane_id is not None and rec_pane != pane_id:
                continue
            return ObservedLaunchReceipt(
                launch_id=str(_record_attr(rec, "launch_id")),
                pane_id=rec_pane,
                state=_enum_text(_record_attr(rec, "state", "unknown")),
                requested_layout=(
                    str(_record_attr(rec, "requested_layout"))
                    if _record_attr(rec, "requested_layout") is not None
                    else None
                ),
                requested_tab_index=_record_attr(rec, "requested_tab_index"),
                requested_pane_index=_record_attr(rec, "requested_pane_index"),
                pid=_record_attr(rec, "pid"),
                process_created=_record_attr(rec, "process_created"),
                spawn_acknowledged=bool(_record_attr(rec, "spawn_acknowledged", False)),
            )
        return None


@dataclass(frozen=True, slots=True)
class SavePreview:
    """Operator preview equivalent to `llmd save -d`."""

    checkpoint_preview: Any
    shutdown_plan: ShutdownPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint": self.checkpoint_preview.to_dict(),
            "shutdown": self.shutdown_plan.to_dict() if self.shutdown_plan else None,
        }


@dataclass(frozen=True, slots=True)
class SaveResult:
    """Operator result equivalent to `llmd save`."""

    checkpoint: WorkspaceCheckpoint
    enqueue_result: Any
    shutdown_report: ShutdownReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint": self.checkpoint.to_dict(),
            "enqueued_count": len(self.enqueue_result.enqueued),
            "deduplicated_count": len(self.enqueue_result.deduplicated),
            "shutdown": self.shutdown_report.to_dict() if self.shutdown_report else None,
        }


class WorkspaceCheckpointCoordinator:
    """High-level coordinator exposing `save` and `restore` workflows for CLI integration."""

    def __init__(
        self,
        root_dir: Path,
        *,
        managed_store: ManagedShutdownStoreProtocol | None = None,
        slot_guard: SlotExecutionGuard | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.checkpoints = CheckpointStore(self.root_dir)
        self.queue = RestorationQueue(self.root_dir)
        self.shutdown = OwnedShutdownCoordinator(managed_store)
        self.restorer = TopologyRestorer()
        self.managed_store = managed_store
        self.slot_guard = slot_guard

    def preview_save(
        self,
        slots: Sequence[WorkspaceSlotInput],
        *,
        label: str | None = None,
        with_shutdown: bool = False,
        observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
        snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
    ) -> SavePreview:
        chk_preview = preview_checkpoint(slots, label=label, observers=observers, snapshots=snapshots)
        shutdown_plan = (
            self.shutdown.preview_shutdown(slots, observers=observers, snapshots=snapshots)
            if with_shutdown
            else None
        )
        return SavePreview(checkpoint_preview=chk_preview, shutdown_plan=shutdown_plan)

    def save(
        self,
        slots: Sequence[WorkspaceSlotInput],
        *,
        label: str | None = None,
        enqueue: bool = True,
        authorized_shutdown: bool = False,
        shutdown_timeout_seconds: float = 5.0,
        observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
        snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
    ) -> SaveResult:
        checkpoint = self.checkpoints.create_checkpoint(
            slots,
            label=label,
            observers=observers,
            snapshots=snapshots,
        )
        enqueue_result = (
            self.queue.enqueue_checkpoint(checkpoint)
            if enqueue
            else type("_EmptyEnqueue", (), {"enqueued": (), "deduplicated": ()})()
        )
        shutdown_report = None
        if authorized_shutdown:
            # Restrict shutdown strictly to the successfully persisted checkpoint's exact identities
            plan = self.shutdown.preview_shutdown_for_checkpoint(
                checkpoint,
                observers=observers,
                snapshots=snapshots,
            )
            shutdown_report = self.shutdown.execute_shutdown(
                plan,
                authorized=True,
                current_slots=slots,
                timeout_seconds=shutdown_timeout_seconds,
            )
        return SaveResult(
            checkpoint=checkpoint,
            enqueue_result=enqueue_result,
            shutdown_report=shutdown_report,
        )

    def preview_restore(
        self,
        checkpoint_id: str,
        *,
        current_slots: Sequence[WorkspaceSlotInput] | None = None,
        observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
        snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
        path_exists: Callable[[str], bool] | None = None,
        allow_reserved_claude: bool = False,
        allow_unknown_runtime: bool = False,
    ) -> RestorePlan:
        checkpoint = self.checkpoints.get_checkpoint(checkpoint_id)
        return self.restorer.preview_restore(
            checkpoint,
            queue=self.queue,
            current_slots=current_slots,
            observers=observers,
            snapshots=snapshots,
            path_exists=path_exists,
            allow_reserved_claude=allow_reserved_claude,
            allow_unknown_runtime=allow_unknown_runtime,
        )

    def restore(
        self,
        checkpoint_id: str,
        *,
        authorized: bool,
        operator_id: str,
        launcher: SessionLauncher,
        current_slots: Sequence[WorkspaceSlotInput] | None = None,
        observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
        snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
        path_exists: Callable[[str], bool] | None = None,
        allow_reserved_claude: bool = False,
        allow_unknown_runtime: bool = False,
        authorization_check: Callable[[RestorePlanItem], tuple[bool, str | None]] | None = None,
    ) -> RestoreReport:
        checkpoint = self.checkpoints.get_checkpoint(checkpoint_id)
        plan = self.restorer.preview_restore(
            checkpoint,
            queue=self.queue,
            current_slots=current_slots,
            observers=observers,
            snapshots=snapshots,
            path_exists=path_exists,
            allow_reserved_claude=allow_reserved_claude,
            allow_unknown_runtime=allow_unknown_runtime,
        )
        return self.restorer.execute_restore(
            plan,
            authorized=authorized,
            operator_id=operator_id,
            launcher=launcher,
            checkpoint=checkpoint,
            queue=self.queue,
            receipt_store=self.managed_store,
            slot_guard=self.slot_guard,
            authorization_check=authorization_check,
            recovery_dir=self.root_dir / "restores",
            current_slots=current_slots,
            observers=observers,
            snapshots=snapshots,
            path_exists=path_exists,
            allow_unknown_runtime=allow_unknown_runtime,
            allow_reserved_claude=allow_reserved_claude,
        )
