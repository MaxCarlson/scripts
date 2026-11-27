# Workspace Checkpoint, Restoration Queue, and Lifecycle API (LLMD-42..45)

This document defines the Agent #3-owned workspace checkpoint, shared restoration queue, topology restoration, and bounded owned-session shutdown interfaces in `agent_continuity`.

## Modules

- [`agent_continuity.workspace_checkpoint`](../agent_continuity/workspace_checkpoint.py) (LLMD-42)
- [`agent_continuity.restoration_queue`](../agent_continuity/restoration_queue.py) (LLMD-43)
- [`agent_continuity.workspace_lifecycle`](../agent_continuity/workspace_lifecycle.py) (LLMD-44, LLMD-45, and operator coordinator)

## Exact Integration Interfaces for Agent #1

1. **Candidate slot input (`WorkspaceSlotInput` / `WorkspaceSnapshotSource`)**:
   - Required immutable identity: `slot_id`, `gui_id`, `provider`, `native_session_id`, `environment_id`, `runtime_kind`.
   - Lifecycle vs process separation: `lifecycle_state` (`active`/`paused`/etc.) is stored separately from `RuntimeDiscovery` `process_liveness`.
   - Worktree & launch context: `WorkspaceWorktreeEvidence` (`requested_cwd`, `effective_cwd`, `native_cwd`, `git_repository`, `git_worktree`, `git_branch`, `git_commit`) and `launch_settings` (validated against the explicit `ALLOWED_LAUNCH_SETTINGS` non-secret allowlist schema; arbitrary options, credentials, raw prompts, and permission escalation values are rejected).
   - Topology request: `WorkspaceTopologyRequest` (`launch_id`, `pane_id`, `terminal_session_id`, `target_window`, `requested_layout`, `requested_tab_index`, `requested_pane_index`), kept separate from `ObservedTopologyEvidence` (`window_ownership_inferred=False`, `pane_geometry_inferred=False`).
   - Minimal v2.3.0 (`8892e900`) metadata contract (`WorkspaceSlotMetadata`): optional `workflow_type`, `profile_id`, `profile_revision`, `agent_number`.
   - Cross-GUI transfer (`LLMD-55`) compatibility: `slot_id` is the immutable primary identity across checkpoints and queue deduplication `(checkpoint_id, slot_id)`; `gui_id` is membership context and drift is surfaced as `cross_gui_transferred=True` during `revalidate_checkpoint(...)`.

2. **Slot-wide exclusion & authorization contracts (`SlotExecutionGuard`)**:
   - `SlotExecutionGuard.acquire_slot(slot_id, *, operator_id, checkpoint_id, queue_entry_id) -> SlotGuardLease` and `release_slot(lease)` coordinate slot-wide exclusion across checkpoints and ordinary LLMD `start`/`resume`/`switch` operations.
   - `TopologyRestorer.execute_restore(...)` obtains fresh slot state (`slot_provider`) and fresh runtime observations under the execution guard, rather than reusing caller-supplied preview snapshots.

3. **Session launcher callback (`SessionLauncher`)**:
   - `launch_session(request: RestoreLaunchRequest) -> RestoreLaunchOutcome`
   - `RestoreLaunchOutcome` distinguishes `accepted` from `spawn_confirmed`, `association_confirmed`, and `resumability_confirmed`. Accepted launches without confirmed spawn transition the queue entry to `AMBIGUOUS` (`accepted_unconfirmed`) rather than `COMPLETED` (`restored`), and launcher exceptions transition to `AMBIGUOUS` with a durable `RestoreRecoveryRecord`.
   - Agent #1's dispatcher CLI implements `SessionLauncher` to resume exact sessions (and optionally invoke Terminal Launcher) without `workspace_lifecycle.py` importing `dispatcher.py` or `schema.py`.

4. **Crash-consistent restoration queue (`RestorationQueue`)**:
   - `restoration_queue.events.jsonl` is the single authoritative durability log (fsynced under lock before SQLite projection updates; fsync failures are never suppressed). Sequence continuity is enforced and corrupt complete records are rejected.
   - `list_entries` and `get_entry` are strictly read-only even with populated queues, unapplied log events, and interrupted tails.
   - `recover_abandoned_claim` requires explicit `ClaimRecoveryEvidence(verified_abandoned=True, ...)` and refuses to release live operator claims; `complete` requires positive `spawn_confirmed=True`.

5. **Bounded owned-session shutdown (`OwnedShutdownCoordinator`) & operator workflow (`WorkspaceCheckpointCoordinator`)**:
   - `preview_shutdown_for_checkpoint(checkpoint, ...)` restricts shutdown targets strictly to the successfully persisted checkpoint's exact identities, revalidates ownership immediately before signaling and during observation, and distinguishes `interrupt_delivered` from `provider_exit_verified` and `provider_metadata_finalized`.
   - `preview_save`, `save`, `preview_restore`, and `restore` on `WorkspaceCheckpointCoordinator` expose the operator workflow (`preview_*` performs zero persistent mutations).

## Remaining Dependencies & Safeguard Matrix

| Safeguard / Dependency | Classification | Owner & Behavior |
|---|---|---|
| `llmd save` / `llmd restore` CLI wiring & `WorkspaceSlotInput` mapping | **Required** | Agent #1 maps dispatcher slots + v2.3.0 metadata into `WorkspaceSlotInput` and wires `WorkspaceCheckpointCoordinator`. |
| `SessionLauncher.launch_session(RestoreLaunchRequest) -> RestoreLaunchOutcome` | **Required** | Agent #1 implements exact session launch and sets `spawn_confirmed=True` only on positive spawn acknowledgment. |
| `SlotExecutionGuard` (`acquire_slot` / `release_slot`) | **Required for concurrent/partial-enum restore** | Agent #1 coordinates slot-wide exclusion with ordinary `llmd start`/`resume`/`switch`. Required on Windows when `PsutilProcessEnumerator` is `PARTIAL`. |
| `slot_provider(slot_id) -> WorkspaceSlotInput \| None` | **Required for race-safe restore** | Agent #1 supplies fresh under-guard slot state so `TopologyRestorer` never relies on stale preview inputs. |
| `authorization_check(RestorePlanItem) -> (bool, reason)` | **Optional** | Revalidates operator/profile authorization at the execution boundary after acquiring the claim and slot guard. |
| `ManagedShutdownStoreProtocol` (`terminal_launcher.managed.ManagedProcessStore`) | **Optional (Required for LLMD-45 shutdown & LLMD-40 receipts)** | Supplies exact PID + creation-FILETIME receipts and `request_interrupt(pane_id)` for bounded owned-session shutdown. |
| Claude `SessionStore` | **Optional (Required for confirmed Claude resumability)** | Until supplied, Claude `--session-id` remains `reserved_unconfirmed` and is blocked on restore unless `allow_reserved_claude=True`. |
| Window/pane geometry | **Unsupported** | Never inferred; exact UI pane geometry/closure remains gated on Terminal Launcher managed receipts. |
