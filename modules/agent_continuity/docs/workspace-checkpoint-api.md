# Workspace Checkpoint, Restoration Queue, and Lifecycle API (LLMD-42..45)

This document defines the Agent #3-owned workspace checkpoint, shared restoration queue, topology restoration, bounded owned-session shutdown, and integration adapters/handlers in `agent_continuity`.

## Modules

- [`agent_continuity.workspace_checkpoint`](../agent_continuity/workspace_checkpoint.py) (LLMD-42)
- [`agent_continuity.restoration_queue`](../agent_continuity/restoration_queue.py) (LLMD-43)
- [`agent_continuity.workspace_lifecycle`](../agent_continuity/workspace_lifecycle.py) (LLMD-44, LLMD-45, and `WorkspaceCheckpointCoordinator`)
- [`agent_continuity.workspace_adapters`](../agent_continuity/workspace_adapters.py) (`DispatcherWorkspaceAdapter`, `DispatcherSlotExecutionGuard`, `TerminalLauncherRestoreAdapter`, `DispatcherLaunchCommandBuilder`, `canonical_llmd_pane_command`, `build_manual_restore_command`, `is_managed_terminal_available`)
- [`agent_continuity.workspace_cli`](../agent_continuity/workspace_cli.py) (`handle_save`, `handle_restore`, `handle_checkpoints`, `handle_queue`, `register_workspace_subcommands`)

## Agent #1 Integration Guide

### 1. Parser Registration (`dispatcher_cli.py`)
Call `register_workspace_subcommands(subparsers)` on `llmd`'s `subparsers` to register:
- `llmd save [-H HOME] [-g GUI] [-l LABEL] [-s] [-t TIMEOUT] [-d] [-a] [-j]`
- `llmd restore [-H HOME] [-g GUI] [-c CHECKPOINT] [-o OPERATOR] [-m] [-N] [-d] [-a] [--allow-unmanaged-unknown] [--allow-reserved-claude] [-j]`
- `llmd checkpoints [list|show] [-H HOME] [-c CHECKPOINT] [-j]`
- `llmd queue [list|recover|resolve|cancel|reconcile] [-H HOME] [-c CHECKPOINT] [-e ENTRY] [-o OPERATOR] [-r REASON] [-O completed|failed|cancelled] [-u] [-d] [-a] [--verified-abandoned] [--abandoned-reason NOTE] [-j]`

Note: Add `save`, `restore`, `checkpoints`, `queue` to `modules/scripts_help/scripts_help/registry/registry.py` when wiring into `llmd` CLI.

### 2. Constructor Dependencies & Canonical Execution Path
- **Dispatcher adapter**: `adapter = DispatcherWorkspaceAdapter(dispatcher)`
  - Resolves `runtime_kind` from `dispatcher.materializer.list_environments()` (never from `env_wsl_` naming prefixes; returns `"unknown"` if missing).
  - Correlates `launch_settings` and `worktree` by exact `(slot_id, provider, native_session_id, environment_id)` identity.
  - Requires explicit `pane_id` in `associations_for_session` (never infers `pane_id` from `launch_id`).
  - Surfaces `pending_launch_id`, `pending_provider`, `lifecycle_state`, `profile_revision`, and `authorization_valid` so `revalidate_checkpoint` blocks pending transitions, terminal slots, profile drift, and revoked authorizations.
- **Canonical LLMD-managed execution (`DispatcherLaunchCommandBuilder` & `DispatcherOwnershipVerifier`)**:
  - `python -m agent_continuity` routes through the legacy `cli.py`; `canonical_llmd_dispatcher_entrypoint` uses the installed `llmd` dispatcher entry point (`agent_continuity.dispatcher_cli:main`).
  - `TerminalLauncherRestoreAdapter` fails closed (`require_exact_session_support=True`) unless supplied with a `DispatcherLaunchCommandBuilder` whose `supports_exact_session=True` asserts exact `(provider, native_session_id, environment_id, cwd)` identity (Agent #1 additive flags on `pane-run`: `--expected-provider`, `--expected-session-id`, `--expected-environment`, `--cwd`).
  - `DispatcherOwnershipVerifier.verify_ownership(request, *, launch_id, pane_id) -> (ownership_ok, association_ok)` separates relay spawn acknowledgment (`spawn_acknowledged`) from dispatcher ownership acknowledgment and exact-session association; `association_confirmed` is never inferred from a spawned relay process alone.
  - `TerminalLauncherRestoreAdapter` groups eligible requests by `(target_window, requested_tab_index)` (with deterministic `<=2`-pane fallback when tab/pane indices are absent, flagging `geometry_fallback_used=True`) and submits via `WindowsTerminalBackend.launch_managed`.
  - `build_manual_restore_command` emits exact-ID native resume commands until Agent #1 adds exact-session flags to `llmd continue` (`exact_llmd_supported=True`).
- **Terminal Launcher dependency floor (`>=0.1.1,<0.3`)**:
  - All `terminal_launcher.managed` and `launch_managed` imports are isolated behind `is_managed_terminal_available()`. Inspection (`checkpoints`, `queue`) and manual (`restore -m`) workflows operate cleanly on `0.1.1` without `0.2.0`.

### 3. Lock Acquisition Order & Ownership Transfer Protocol
1. `RestorationQueue.claim` (`.restoration_queue.lock`) — atomically claims `(checkpoint_id, slot_id)` and enforces cross-checkpoint slot exclusion.
2. `DispatcherSlotExecutionGuard.acquire_slot` (`<home_dir>/locks/slot_<slot_id>.lock`) — acquires cooperating cross-process slot lock. Agent #1 should acquire this same lock in `start`/`continue`/`switch`/`review`/`return`.
3. Fresh under-guard revalidation — `slot_provider(slot_id)` + fresh `RuntimeDiscovery` (`snapshots=None`) + `authorization_check`.
4. `RestorationQueue.mark_launching` — durably records `LAUNCHING` before invoking `launcher`.
5. `TerminalLauncherRestoreAdapter.launch_grouped` / `WindowsTerminalBackend.launch_managed` — reserves panes (`ManagedProcessStore.reserve_launch`), submits to terminal, and awaits relay `_pane_runner.py` acknowledgment (`spawn_acknowledged=True`).
6. `RestorationQueue.complete` (only when `spawn_confirmed=True`), `record_failure` (positive rejection), or `mark_ambiguous` (`LaunchStatus.AMBIGUOUS`, backend exception, or accepted-without-spawn).
7. Release `SlotExecutionGuard` leases in `finally` after durable outcomes are recorded.

### 4. CLI Exit Status & Recovery Safeguards
- `handle_save -s -a` returns exit code `2` if any target fails/times out/is refused.
- `handle_restore -a` constrains execution strictly to `-g/--gui` when supplied, and returns exit code `2` on any `failed`, `ambiguous`, or `accepted_unconfirmed` outcome.
- `handle_queue` requires `-a/--apply` for `recover`, `resolve`, `cancel`, and `reconcile`; `recover` refuses without `--verified-abandoned` or an `abandonment_verifier` callback.
- Failed `fsync` or rollback marks `.restoration_queue.uncertain` and blocks further mutations until `llmd queue reconcile -a`.

### 5. Outstanding Shared-Schema / Agent #1 Items
- **Parser & help registry**: Wire `register_workspace_subcommands` in `dispatcher_cli.py` and register commands in `scripts_help`.
- **Dispatcher slot lock integration**: Acquire `<home_dir>/locks/slot_<slot_id>.lock` (or share `_mutation_lock`) in ordinary `llmd` launch/resume commands.
- **v2.3.0 (`8892e900`)**: `DispatcherWorkspaceAdapter` already reads `workflow_type`, `profile_id`, `profile_revision`, and `agent_number` from slot dicts when present.
- **Claude `SessionStore`**: Until supplied, Claude `--session-id` remains `reserved_unconfirmed` and requires `--allow-reserved-claude`.
- **Window/pane geometry**: Never inferred; unsupported geometry uses deterministic fallback (`geometry_fallback_used=True`).


## Durable Ownership Transfer (`workspace_ownership.py`)

- **Canonical slot lock**: `canonical_slot_lock_path(home_dir, slot_id)` resolves to `<home_dir>/slot-<slot_id>.lock` (aligned with Agent #1's dispatcher slot lock). `ReservationSlotExecutionGuard` / `DispatcherSlotExecutionGuard` acquires the OS lock only around atomic lease/reservation inspection and releases it before spawning child processes, avoiding parent-holds-lock/child-acquires-lock deadlocks.
- **Durable reservation**: `RestorationReservationStore(home_dir)` persists exact-session reservations under `<home_dir>/restoration_reservations/` correlated to `checkpoint_id`, `queue_entry_id`, `attempt`, `slot_id`, `provider`, `native_session_id`, `environment_id`, `launch_id`, and `pane_id`.
- **Atomic consumption & conflict protection**: While a reservation is `reserved`, `submitted`, or `ambiguous`, competing slot guard acquisitions and new reservations fail closed. `consume_reservation(...)` validates token, slot, provider, native session, environment, launch, and pane IDs under `slot-<slot_id>.lock` and records `dispatcher_ownership_acknowledged=True`.
- **Completion & queue schema v3**: `RestorationQueue` (`QUEUE_SCHEMA_VERSION = 3`, with backward-compatible `ALTER TABLE` migration from v2) and `RestoreItemOutcome` track `relay_spawn_acknowledged`, `dispatcher_ownership_acknowledged`, `association_confirmed`, `current_liveness`, and `resumability_confirmed` separately. Managed restoration requires `dispatcher_ownership_acknowledged=True` by default (`require_dispatcher_ownership=True`).
- **Manual fallback & entrypoint safety**: `build_manual_restore_command` fails closed with `RESUME_UNSUPPORTED` unless `exact_llmd_supported=True` or `allow_direct_native_fallback=True` (`--direct-native`). `canonical_llmd_dispatcher_entrypoint` verifies that any installed `llmd` matches `agent_continuity.__version__` before selecting it.

### Minimal Agent #1 Dispatcher Hooks

1. In `pane-run` / `continue` exact-session execution, accept `--reservation-id`, `--reservation-token`, `--checkpoint-id`, `--provider`, `--session-id`, and `--environment`, calling `RestorationReservationStore(home_dir).consume_reservation(...)` under `slot-<slot_id>.lock` before launching the provider.
2. Check `RestorationReservationStore(home_dir).get_active_for_slot(slot_id)` under `slot-<slot_id>.lock` on ordinary `llmd continue` / `pane-run` launches and refuse when an active/ambiguous restoration reservation is present.
