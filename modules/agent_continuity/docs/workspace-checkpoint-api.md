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
   - `TopologyRestorer.execute_restore(...)` runs fresh identity, runtime, worktree, and optional `authorization_check` revalidation **after** acquiring both the queue claim and `SlotExecutionGuard` lease. Unknown runtime evidence does not establish inactivity unless `allow_unknown_runtime=True`.

3. **Session launcher callback (`SessionLauncher`)**:
   - `launch_session(request: RestoreLaunchRequest) -> RestoreLaunchOutcome`
   - `RestoreLaunchOutcome` distinguishes `accepted` from `spawn_confirmed`, `association_confirmed`, and `resumability_confirmed`. Accepted launches without confirmed spawn transition the queue entry to `AMBIGUOUS` (`accepted_unconfirmed`) rather than `COMPLETED` (`restored`), and launcher exceptions transition to `AMBIGUOUS` with a durable `RestoreRecoveryRecord`.
   - Agent #1's dispatcher CLI implements `SessionLauncher` to resume exact sessions (and optionally invoke Terminal Launcher) without `workspace_lifecycle.py` importing `dispatcher.py` or `schema.py`.
   - When `RestoreLaunchOutcome.launch_id` is returned and `ManagedShutdownStoreProtocol` (`terminal_launcher.managed.ManagedProcessStore`) is provided, `TopologyRestorer` records the LLMD-40 `ObservedLaunchReceipt` separately from `requested_topology`.

4. **Crash-consistent restoration queue (`RestorationQueue`)**:
   - `restoration_queue.events.jsonl` is the single authoritative durability log (fsynced under lock before SQLite projection updates), with deterministic replay, interrupted-tail truncation, concurrent `rebuild_index()`, slot-wide exclusion across checkpoints, and explicit `recover_abandoned_claim(...)` / `resolve_ambiguous(...)` transitions without blind retries.

5. **Bounded owned-session shutdown (`OwnedShutdownCoordinator`) & operator workflow (`WorkspaceCheckpointCoordinator`)**:
   - `preview_shutdown_for_checkpoint(checkpoint, ...)` restricts shutdown targets strictly to the successfully persisted checkpoint's exact identities, revalidates ownership immediately before signaling and during observation, and distinguishes `interrupt_delivered` from `provider_exit_verified` and `provider_metadata_finalized`.
   - `preview_save`, `save`, `preview_restore`, and `restore` on `WorkspaceCheckpointCoordinator` expose the operator workflow (`preview_*` performs zero persistent mutations).

## Remaining Dependencies

- **Agent #1 CLI & dispatcher integration**: Wire `llmd save` / `llmd restore` (or final chosen command names) to `WorkspaceCheckpointCoordinator`, construct `WorkspaceSlotInput` from dispatcher registry + v2.3.0 metadata, and supply a `SessionLauncher` implementation.
- **Claude resumability verification**: `RuntimeDiscovery` reports Claude `--session-id` as `session_identity_state="reserved"` (`resumability_state="reserved_unconfirmed"`) until a Claude `SessionStore` confirms durable transcript existence. `TopologyRestorer` blocks `reserved_unconfirmed` entries by default unless `allow_reserved_claude=True`.
- **Window/pane geometry**: `ObservedTopologyEvidence` never infers window ownership or pane geometry; exact UI pane closure/geometry remains gated on Terminal Launcher managed receipts.
