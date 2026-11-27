# Workspace Checkpoint, Restoration Queue, and Lifecycle API (LLMD-42..45)

This document defines the Agent #3-owned workspace checkpoint, shared restoration queue, topology restoration, bounded owned-session shutdown, and integration adapters/handlers in `agent_continuity`.

## Modules

- [`agent_continuity.workspace_checkpoint`](../agent_continuity/workspace_checkpoint.py) (LLMD-42)
- [`agent_continuity.restoration_queue`](../agent_continuity/restoration_queue.py) (LLMD-43)
- [`agent_continuity.workspace_lifecycle`](../agent_continuity/workspace_lifecycle.py) (LLMD-44, LLMD-45, and `WorkspaceCheckpointCoordinator`)
- [`agent_continuity.workspace_adapters`](../agent_continuity/workspace_adapters.py) (`DispatcherWorkspaceAdapter`, `DispatcherSlotExecutionGuard`, `TerminalLauncherRestoreAdapter`, `build_manual_restore_command`)
- [`agent_continuity.workspace_cli`](../agent_continuity/workspace_cli.py) (`handle_save`, `handle_restore`, `handle_checkpoints`, `handle_queue`, `register_workspace_subcommands`)

## Agent #1 Integration Guide

### 1. Parser Registration (`dispatcher_cli.py`)
Call `register_workspace_subcommands(subparsers)` on `llmd`'s `subparsers` to register:
- `llmd save [-H HOME] [-g GUI] [-l LABEL] [-s] [-t TIMEOUT] [-d] [-a] [-j]`
- `llmd restore [-H HOME] [-g GUI] [-c CHECKPOINT] [-o OPERATOR] [-m] [-d] [-a] [--allow-unmanaged-unknown] [--allow-reserved-claude] [-j]`
- `llmd checkpoints [list|show] [-H HOME] [-c CHECKPOINT] [-j]`
- `llmd queue [list|recover|resolve|cancel|reconcile] [-H HOME] [-c CHECKPOINT] [-e ENTRY] [-o OPERATOR] [-r REASON] [-O completed|failed|cancelled] [-u] [-j]`

Note: Add `save`, `restore`, `checkpoints`, `queue` to `modules/scripts_help/scripts_help/registry/registry.py` when wiring into `llmd` CLI.

### 2. Constructor Dependencies & Wiring
```python
from agent_continuity.workspace_adapters import (
    DispatcherSlotExecutionGuard,
    DispatcherWorkspaceAdapter,
    TerminalLauncherRestoreAdapter,
)
from agent_continuity.workspace_cli import handle_checkpoints, handle_queue, handle_restore, handle_save
```
- **Dispatcher adapter**: `adapter = DispatcherWorkspaceAdapter(dispatcher)` supplies `list_candidate_slots(...)`, `slot_provider(slot_id)` (using `get_slot_by_id`), and `associations_for_session(key)` (joining `list_recent_terminal_launches`).
- **Slot-wide exclusion**: `guard = DispatcherSlotExecutionGuard(dispatcher.home_dir)` acquires non-blocking per-slot locks under `<home_dir>/locks/slot_<slot_id>.lock`. Agent #1 should also acquire this same lock (or integrate it with `_mutation_lock`) in `start`/`continue`/`switch`/`review`/`return` to exclude ordinary LLMD resume operations during restoration.
- **Terminal Launcher integration (optional 0.2.0)**:
  - `agent-continuity` retains `terminal-launcher>=0.1.1,<0.3`.
  - When Terminal Launcher 0.2.0 is installed, construct `ManagedProcessStore()` and `TerminalLauncherRestoreAdapter(backend=WindowsTerminalBackend(), managed_store=managed_store)` for `handle_restore(..., launcher=launcher, managed_store=managed_store)`.
  - Pass `managed_store` to `handle_save(..., managed_store=managed_store)` for bounded owned-session shutdown (`-s -a`).
  - When Terminal Launcher 0.2.0 is absent or sessions are unmanaged, `handle_restore -m` (`--manual`) emits exact provider resume commands (`build_manual_restore_command`).

### 3. Guard, Receipt, and Durability Invariants
- **Preview vs. execution**: `preview_save`, `preview_restore`, `checkpoints`, and `queue list` perform zero persistent mutations even with populated queues, unapplied log events, and interrupted tails. Preview availability of a `SlotExecutionGuard` never implies an acquired lease; entries needing guarded verification surface as `conditional_restore`.
- **Execution-boundary revalidation**: `TopologyRestorer.execute_restore` fails closed if `checkpoint` or `slot_guard` is missing (`require_slot_guard=True`), acquires `RestorationQueue` claim + `SlotExecutionGuard` lease, then obtains fresh `slot_provider(slot_id)` and fresh `RuntimeDiscovery` evidence under the guard.
- **Partial-enumeration safety on Windows**: Absence of a managed receipt never implies verified exit. `partial_enum_safe_via_guard_and_receipts` requires both an acquired `SlotExecutionGuard` and a correlated exited receipt in `obs.historical_managed_panes`. Unmanaged sessions under partial enumeration remain blocked (`unmanaged_partial_enum_unverified`) until the operator passes `--allow-unmanaged-unknown` (`allow_unknown_runtime=True`).
- **Launch acceptance vs. spawn confirmation**: `TerminalLauncherRestoreAdapter` sets `accepted=True` on backend submission and `spawn_confirmed=True` only when `ManagedProcessRecord.spawn_acknowledged` is `True`. Unconfirmed launches transition the queue entry to `AMBIGUOUS` (`accepted_unconfirmed`) rather than `COMPLETED`.
- **Queue `fsync` & uncertainty quarantine**: Failed `fsync` or rollback marks `.restoration_queue.uncertain` and blocks further queue mutations until `llmd queue reconcile` (`queue.reconcile()`).
- **Shutdown semantics**: `OwnedShutdownCoordinator` restricts targets strictly to the persisted checkpoint's exact identities, revalidates PID/creation-time immediately before signaling and during polling, and never claims `provider_exit_verified` or `provider_metadata_finalized` solely from an interrupt receipt.

### 4. Outstanding Shared-Schema / Agent #1 Items
- **v2.3.0 (`8892e900`)**: `DispatcherWorkspaceAdapter` already reads `workflow_type`, `profile_id`, `profile_revision`, and `agent_number` from slot dicts when present; once v2.3.0 is merged, those fields flow into checkpoints automatically.
- **Claude `SessionStore`**: Until Agent #1 supplies a verified Claude transcript `SessionStore` to `RuntimeDiscovery`, Claude `--session-id` entries remain `reserved_unconfirmed` and require `--allow-reserved-claude` to restore.
- **Window/pane geometry**: Never inferred; exact UI pane geometry/closure remains gated on Terminal Launcher managed receipts.
