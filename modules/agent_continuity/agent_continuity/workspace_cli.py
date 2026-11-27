"""Operator-facing workspace save/restore/checkpoint/queue command handlers.

Agent #1 owns final parser registration in dispatcher_cli.py and may call
`register_workspace_subcommands` or dispatch directly to these handlers.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from .errors import ContinuityError, ErrorCode
from .restoration_queue import ClaimRecoveryEvidence, RestorationQueue
from .runtime_discovery import ProcessSnapshot, RuntimeDiscovery
from .workspace_adapters import (
    DispatcherLike,
    DispatcherSlotExecutionGuard,
    DispatcherWorkspaceAdapter,
    build_manual_restore_command,
)
from .workspace_checkpoint import CheckpointStore, WorkspaceSlotInput
from .workspace_lifecycle import (
    ManagedShutdownStoreProtocol,
    SessionLauncher,
    SlotExecutionGuard,
    WorkspaceCheckpointCoordinator,
)


def _emit(payload: dict[str, Any], text: str, *, json_output: bool, stream: TextIO) -> int:
    if json_output:
        stream.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    else:
        stream.write(text.rstrip() + "\n")
    return 0


def _build_coordinator(
    *,
    state_root: Path,
    managed_store: ManagedShutdownStoreProtocol | None = None,
    slot_guard: SlotExecutionGuard | None = None,
) -> WorkspaceCheckpointCoordinator:
    return WorkspaceCheckpointCoordinator(
        state_root,
        managed_store=managed_store,
        slot_guard=slot_guard,
    )


def handle_save(
    args: argparse.Namespace,
    *,
    dispatcher: DispatcherLike,
    state_root: Path | None = None,
    managed_store: ManagedShutdownStoreProtocol | None = None,
    observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
    snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
    stream: TextIO | None = None,
) -> int:
    """Handle `llmd save`: preview or persist a workspace checkpoint (and optional authorized shutdown)."""
    out = stream or sys.stdout
    adapter = DispatcherWorkspaceAdapter(dispatcher)
    slots = adapter.list_candidate_slots(gui=getattr(args, "gui", None), active_only=True)
    root = state_root or (Path(dispatcher.home_dir) / "workspace_state")
    coordinator = _build_coordinator(state_root=root, managed_store=managed_store)

    dry_run = bool(getattr(args, "dry_run", False))
    apply = bool(getattr(args, "apply", False))
    with_shutdown = bool(getattr(args, "shutdown", False))
    json_output = bool(getattr(args, "json_output", False))
    label = getattr(args, "label", None)
    timeout = float(getattr(args, "timeout", 5.0))

    if dry_run or not apply:
        preview = coordinator.preview_save(
            slots,
            label=label,
            with_shutdown=with_shutdown,
            observers=observers,
            snapshots=snapshots,
        )
        payload = {"action": "save", "mode": "preview", **preview.to_dict()}
        lines = [
            f"Workspace save preview ({len(preview.checkpoint_preview.sessions)} observed, "
            f"{len(preview.checkpoint_preview.skipped_slots)} skipped):"
        ]
        for entry in preview.checkpoint_preview.sessions:
            lines.append(
                f"  + {entry.slot_id} ({entry.provider}:{entry.native_session_id}) "
                f"[{entry.process_liveness}/{entry.resumability_state}]"
            )
        for skip in preview.checkpoint_preview.skipped_slots:
            lines.append(f"  - {skip.slot_id} ({skip.provider}) skipped: {skip.reason}")
        if preview.shutdown_plan is not None:
            lines.append(
                f"Shutdown plan: {len(preview.shutdown_plan.eligible_targets)} eligible, "
                f"{len(preview.shutdown_plan.refused_targets)} refused"
            )
        return _emit(payload, "\n".join(lines), json_output=json_output, stream=out)

    result = coordinator.save(
        slots,
        label=label,
        enqueue=True,
        authorized_shutdown=with_shutdown,
        shutdown_timeout_seconds=timeout,
        observers=observers,
        snapshots=snapshots,
    )
    payload = {"action": "save", "mode": "applied", **result.to_dict()}
    lines = [
        f"Saved checkpoint {result.checkpoint.checkpoint_id} "
        f"({len(result.checkpoint.sessions)} sessions, {len(result.enqueue_result.enqueued)} queued)."
    ]
    if result.shutdown_report is not None:
        for outcome in result.shutdown_report.outcomes:
            lines.append(
                f"  shutdown {outcome.slot_id}: requested={outcome.requested} "
                f"sent={outcome.sent} observed={outcome.observed_state}"
            )
    return _emit(payload, "\n".join(lines), json_output=json_output, stream=out)


def handle_restore(
    args: argparse.Namespace,
    *,
    dispatcher: DispatcherLike,
    launcher: SessionLauncher | None = None,
    state_root: Path | None = None,
    managed_store: ManagedShutdownStoreProtocol | None = None,
    slot_guard: SlotExecutionGuard | None = None,
    observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
    snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
    path_exists: Callable[[str], bool] | None = None,
    authorization_check: Callable[[Any], tuple[bool, str | None]] | None = None,
    stream: TextIO | None = None,
) -> int:
    """Handle `llmd restore`: preview, execute managed restore, or emit manual commands."""
    out = stream or sys.stdout
    adapter = DispatcherWorkspaceAdapter(dispatcher)
    root = state_root or (Path(dispatcher.home_dir) / "workspace_state")
    guard = slot_guard or DispatcherSlotExecutionGuard(Path(dispatcher.home_dir))
    coordinator = _build_coordinator(state_root=root, managed_store=managed_store, slot_guard=guard)

    checkpoint_id = getattr(args, "checkpoint", None)
    if not checkpoint_id:
        checkpoints, _corrupt = coordinator.checkpoints.list_checkpoints()
        if not checkpoints:
            raise ContinuityError(ErrorCode.SESSION_NOT_FOUND, "No workspace checkpoints found.")
        checkpoint_id = checkpoints[0].checkpoint_id

    current_slots: Sequence[WorkspaceSlotInput] = adapter.list_candidate_slots(
        gui=getattr(args, "gui", None),
        active_only=False,
    )
    allow_reserved = bool(getattr(args, "allow_reserved_claude", False))
    allow_unknown = bool(getattr(args, "allow_unmanaged_unknown", False))
    dry_run = bool(getattr(args, "dry_run", False))
    apply = bool(getattr(args, "apply", False))
    manual = bool(getattr(args, "manual", False))
    json_output = bool(getattr(args, "json_output", False))
    operator_id = getattr(args, "operator", None) or "operator"

    plan = coordinator.preview_restore(
        checkpoint_id,
        current_slots=current_slots,
        observers=observers,
        snapshots=snapshots,
        path_exists=path_exists,
        allow_reserved_claude=allow_reserved,
        allow_unknown_runtime=allow_unknown,
    )

    if manual or dry_run or not apply:
        manual_commands = {
            item.slot_id: build_manual_restore_command(item)
            for item in plan.items
            if item.action in {"restore", "conditional_restore"}
        }
        payload = {
            "action": "restore",
            "mode": "manual" if manual else "preview",
            "plan": plan.to_dict(),
            "manual_commands": manual_commands,
        }
        lines = [f"Restore preview for {plan.checkpoint_id} ({len(plan.items)} entries):"]
        for item in plan.items:
            cmd = " ".join(manual_commands[item.slot_id]) if item.slot_id in manual_commands else ""
            suffix = f" -> `{cmd}`" if manual and cmd else ""
            lines.append(
                f"  {item.slot_id} [{item.provider}:{item.native_session_id}] action={item.action} "
                f"reasons={','.join(item.reasons) or 'none'}{suffix}"
            )
        return _emit(payload, "\n".join(lines), json_output=json_output, stream=out)

    if launcher is None:
        raise ContinuityError(
            ErrorCode.INVALID_INPUT,
            "Authorized restore execution requires a SessionLauncher; use -m/--manual for manual commands.",
        )

    report = coordinator.restore(
        checkpoint_id,
        authorized=True,
        operator_id=operator_id,
        launcher=launcher,
        current_slots=current_slots,
        slot_provider=adapter.slot_provider,
        require_slot_guard=True,
        observers=observers,
        snapshots=snapshots,
        path_exists=path_exists,
        allow_reserved_claude=allow_reserved,
        allow_unknown_runtime=allow_unknown,
        authorization_check=authorization_check,
    )
    payload = {"action": "restore", "mode": "applied", "report": report.to_dict()}
    lines = [f"Restore {report.restore_id} for {report.checkpoint_id} (partial_failure={report.partial_failure}):"]
    for outcome in report.outcomes:
        lines.append(
            f"  {outcome.slot_id}: status={outcome.status} "
            f"accepted={outcome.launch_accepted} spawn_confirmed={outcome.spawn_confirmed} "
            f"reason={outcome.reason or 'ok'}"
        )
    if report.recovery_record_path:
        lines.append(f"Recovery record: {report.recovery_record_path}")
    return _emit(payload, "\n".join(lines), json_output=json_output, stream=out)


def handle_checkpoints(
    args: argparse.Namespace,
    *,
    dispatcher: DispatcherLike,
    state_root: Path | None = None,
    stream: TextIO | None = None,
) -> int:
    """Handle `llmd checkpoints list|show`."""
    out = stream or sys.stdout
    root = state_root or (Path(dispatcher.home_dir) / "workspace_state")
    store = CheckpointStore(root)
    json_output = bool(getattr(args, "json_output", False))
    sub = getattr(args, "checkpoint_action", "list")

    if sub == "show":
        cid = getattr(args, "checkpoint", None)
        if not cid:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Checkpoint ID (-c/--checkpoint) is required for show.")
        chk = store.get_checkpoint(cid)
        return _emit(
            {"action": "checkpoints.show", "checkpoint": chk.to_dict()},
            f"Checkpoint {chk.checkpoint_id} ({chk.created_at}, {len(chk.sessions)} sessions, stale={chk.stale})",
            json_output=json_output,
            stream=out,
        )

    checkpoints, corrupt = store.list_checkpoints()
    payload = {
        "action": "checkpoints.list",
        "checkpoints": [c.to_dict() for c in checkpoints],
        "corrupt": [{"path": item.path, "error": item.error} for item in corrupt],
    }
    lines = [f"Workspace checkpoints ({len(checkpoints)} valid, {len(corrupt)} corrupt):"]
    for chk in checkpoints:
        lines.append(
            f"  {chk.checkpoint_id}  {chk.created_at}  sessions={len(chk.sessions)}  "
            f"label={chk.label or '-'}  stale={chk.stale}"
        )
    return _emit(payload, "\n".join(lines), json_output=json_output, stream=out)


def handle_queue(
    args: argparse.Namespace,
    *,
    dispatcher: DispatcherLike,
    state_root: Path | None = None,
    stream: TextIO | None = None,
) -> int:
    """Handle `llmd queue list|recover|resolve|cancel|reconcile`."""
    out = stream or sys.stdout
    root = state_root or (Path(dispatcher.home_dir) / "workspace_state")
    queue = RestorationQueue(root)
    json_output = bool(getattr(args, "json_output", False))
    sub = getattr(args, "queue_action", "list")
    operator_id = getattr(args, "operator", None) or "operator"

    if sub == "list":
        entries = queue.list_entries(
            checkpoint_id=getattr(args, "checkpoint", None),
            unresolved_only=bool(getattr(args, "unresolved", False)),
        )
        payload = {"action": "queue.list", "entries": [e.to_dict() for e in entries]}
        lines = [f"Restoration queue ({len(entries)} entries):"]
        for entry in entries:
            lines.append(
                f"  {entry.queue_entry_id}  {entry.checkpoint_id}  {entry.slot_id}  "
                f"status={entry.status.value}  attempts={entry.attempts}"
            )
        return _emit(payload, "\n".join(lines), json_output=json_output, stream=out)

    if sub == "reconcile":
        replayed = queue.reconcile()
        return _emit(
            {"action": "queue.reconcile", "replayed_events": replayed},
            f"Reconciled restoration queue ({replayed} events replayed).",
            json_output=json_output,
            stream=out,
        )

    entry_id = getattr(args, "entry", None)
    if not entry_id:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Queue entry ID (-e/--entry) is required.")
    reason = getattr(args, "reason", None) or "operator_action"

    if sub == "recover":
        updated = queue.recover_abandoned_claim(
            entry_id,
            operator_id=operator_id,
            reason=reason,
            recovery_evidence=ClaimRecoveryEvidence(verified_abandoned=True, reason=reason),
        )
    elif sub == "resolve":
        outcome = getattr(args, "outcome", None) or "failed"
        updated = queue.resolve_ambiguous(
            entry_id,
            operator_id=operator_id,
            outcome=outcome,
            reason=reason,
        )
    elif sub == "cancel":
        updated = queue.cancel(entry_id, operator_id=operator_id, reason=reason)
    else:
        raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported queue action {sub!r}.")

    return _emit(
        {"action": f"queue.{sub}", "entry": updated.to_dict()},
        f"Queue entry {updated.queue_entry_id} -> {updated.status.value}",
        json_output=json_output,
        stream=out,
    )


def register_workspace_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register save/restore/checkpoints/queue subcommands following LLMD short+long CLI conventions."""
    save_p = subparsers.add_parser("save", help="Preview or save a durable workspace checkpoint.")
    save_p.add_argument("-H", "--home", default=argparse.SUPPRESS, help="Override registry directory.")
    save_p.add_argument("-g", "--gui", default=None, help="Scope checkpoint to one GUI alias or ID.")
    save_p.add_argument("-l", "--label", default=None, help="Optional checkpoint label.")
    save_p.add_argument("-s", "--shutdown", action="store_true", help="Request bounded shutdown of owned panes.")
    save_p.add_argument("-t", "--timeout", type=float, default=5.0, help="Shutdown timeout in seconds.")
    save_p.add_argument("-d", "--dry-run", action="store_true", help="Preview without persisting.")
    save_p.add_argument("-a", "--apply", action="store_true", help="Persist checkpoint (and authorize shutdown if -s).")
    save_p.add_argument("-j", "--json", dest="json_output", action="store_true", help="Emit JSON output.")

    restore_p = subparsers.add_parser("restore", help="Preview or restore a saved workspace checkpoint.")
    restore_p.add_argument("-H", "--home", default=argparse.SUPPRESS, help="Override registry directory.")
    restore_p.add_argument("-g", "--gui", default=None, help="Scope restoration check to one GUI alias or ID.")
    restore_p.add_argument("-c", "--checkpoint", default=None, help="Checkpoint ID (defaults to latest).")
    restore_p.add_argument("-o", "--operator", default="operator", help="Operator ID for queue claims.")
    restore_p.add_argument("-m", "--manual", action="store_true", help="Emit manual resume commands.")
    restore_p.add_argument("-d", "--dry-run", action="store_true", help="Preview without launching.")
    restore_p.add_argument("-a", "--apply", action="store_true", help="Authorize and execute restoration.")
    restore_p.add_argument("--allow-unmanaged-unknown", action="store_true", help="Allow unmanaged partial-enum recovery.")
    restore_p.add_argument("--allow-reserved-claude", action="store_true", help="Allow reserved Claude UUID recovery.")
    restore_p.add_argument("-j", "--json", dest="json_output", action="store_true", help="Emit JSON output.")

    chk_p = subparsers.add_parser("checkpoints", help="Inspect persisted workspace checkpoints.")
    chk_p.add_argument("checkpoint_action", nargs="?", default="list", choices=["list", "show"])
    chk_p.add_argument("-H", "--home", default=argparse.SUPPRESS, help="Override registry directory.")
    chk_p.add_argument("-c", "--checkpoint", default=None, help="Checkpoint ID for show.")
    chk_p.add_argument("-j", "--json", dest="json_output", action="store_true", help="Emit JSON output.")

    q_p = subparsers.add_parser("queue", help="Inspect or recover the shared restoration queue.")
    q_p.add_argument(
        "queue_action",
        nargs="?",
        default="list",
        choices=["list", "recover", "resolve", "cancel", "reconcile"],
    )
    q_p.add_argument("-H", "--home", default=argparse.SUPPRESS, help="Override registry directory.")
    q_p.add_argument("-c", "--checkpoint", default=None, help="Filter by checkpoint ID.")
    q_p.add_argument("-e", "--entry", default=None, help="Queue entry ID for recover/resolve/cancel.")
    q_p.add_argument("-o", "--operator", default="operator", help="Operator ID.")
    q_p.add_argument("-r", "--reason", default="operator_action", help="Reason note.")
    q_p.add_argument("-O", "--outcome", default="failed", choices=["completed", "failed", "cancelled"], help="Ambiguous resolution outcome.")
    q_p.add_argument("-u", "--unresolved", action="store_true", help="List unresolved entries only.")
    q_p.add_argument("-j", "--json", dest="json_output", action="store_true", help="Emit JSON output.")
