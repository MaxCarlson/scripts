# Durable GPU Maintenance Sessions — Status

## Current checkpoint

- Baseline: `3d1cefa0596cfba5a68e436589f3bba7edc04a53` (`origin/main` at branch creation).
- Remote main observed during final review: `bdd8429e252a2264357dc94fa603e7e9e6398f63`; it advanced after the requested baseline. This feature remains intentionally based on `3d1cefa` and has not been merged/rebased onto newer main. Integration must reassess the intervening commits.
- Branch: `agent/resource-coordinator-gpu-maintenance-20261111`.
- Worktree: `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-gpu-maintenance-20261111`.
- Source package version: `0.13.0`.
- Current work is uncommitted; no push, merge, deployment, or production operation has occurred.
- Root `main` checkout's pre-existing dirty paths remain untouched.
- Runtime used: Windows (`platform win32`), Python 3.12.10, pytest 9.0.3, pytest-asyncio 1.3.0; package imports resolve to this feature worktree.

## Implemented

- `LeaseManager` now provides one condition-lock admission fence across all `gpu.*` reservations and idle-guarded transitions. Acquisition is rejected while active/pending claims, cooldown, inhibition, global restart blocking, or a non-idle gaming state exists.
- `MaintenanceSessionManager` provides durable `idle`, `acquiring`, `active`, `releasing`, and `recovery_required` transitions; bounded (30–3600 second) server leases; request identity; process-local cryptographic tokens with constant-time verification; renewals; expiry; operator reconciliation; and sanitized status/events.
- Acquisition persists intent and restart inhibition before stopping the miner. It grants a token only after verifying a Coordinator-owned managed miner is stopped. External/unowned or unverifiable processes are never stopped or adopted.
- Cancellation, expiry, failed stop/release, persistence errors, Coordinator shutdown, and restart revoke token authority and retain/re-establish the GPU fence and restart hold. A changed payload cannot reuse an active `request_id` to retrieve a token.
- Release rejects the client Boolean by itself. It requires a configured server restoration verifier or an authenticated, reasoned operator override, and independently verifies the managed miner is stopped. Only the maintenance holder is removed; unrelated holds are preserved.
- A persisted `restart_not_before` re-arms cooldown after Coordinator restart. Startup suppresses immediate launch and schedules the existing supervised resume path for after cooldown when restoration policy permits a restart.
- Durable maintenance records retain a bounded history of the latest 64 completed operation dispositions. This keeps completed acquisition IDs from being replayed as new sessions and lets a retried release return its recorded disposition without reviving an old token.
- Inference/model-load admission checks maintenance ownership before loaded-model reuse. Manual miner mutation, gaming transitions, recovery, GPU-idle actions, policies, and supervisor restart paths share the fence or durable hold.
- `CoordinatorState` accepts legacy v0.12 journals without maintenance fields; new records are allowlisted and validated. Raw tokens are not persisted or sent in status/events/logs. Multi-owner inhibition updates preserve each unresolved holder.
- Canonical authenticated `/_coordinator/maintenance/*` routes and additive status data are documented in `docs/MAINTENANCE_SESSIONS.md`.
- Mining reference was read-only and verified at `4b1f2a57b0bac536d250a7018df1f8a20c78e1c5`. The client contract gaps are documented; Mining files were not changed.

## Validation evidence

Final relevant suite, candidate source (rerun after the completed-operation history and failed-acquisition reconciliation changes):

```powershell
python -m pytest --override-ini addopts= tests\test_maintenance.py tests\test_leases.py tests\test_durable_state.py tests\test_gateway.py tests\test_admission.py tests\test_factory_gateway_integration.py tests\test_service_lifecycle.py tests\test_integration_phase_d.py tests\test_policies.py tests\test_actions.py tests\test_processes.py tests\test_miner_adapter.py tests\test_phase2_miner_lifecycle.py tests\test_config.py tests\test_operator_credentials.py tests\test_cli.py -k "not test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window" -q -ra --basetemp C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-gpu-maintenance-20261111\modules\resource_coordinator\.pytest_tmp_maintenance_counts
```

- Result: **214 passed, 1 deselected in 28.13s** (exit 0). The deselected GPU-idle restart test was run on both this candidate and unchanged baseline `3d1cefa`; it fails identically in both due its existing persisted manual-hold/restart behavior. The maintenance branch did not change the failing GPU-idle sampling or manual pause implementation.
- `test_operator_can_reconcile_failed_acquisition_without_a_session_token`: **1 passed in 0.58s** after allowing a completed disposition with no `session_id` when an acquisition failed before a session was created. This preserves operation-ID-based operator reconciliation and retry history.
- Maintenance, lease, and durable-state subset also passed before final expansion: **38 passed**. New focused coverage includes concurrent acquisition, cancellation during acquisition and release, startup recovery, cooldown recovery after restart, stale fencing, token redaction, persistence failure, unrelated holds, and operator recovery.
- `test_supervised_acceptance_readiness.py::test_acceptance_harness_durable_journal_and_lock_contention` passed independently (1 passed); its full-suite run had a Windows lock/temp failure under suite load.
- `ruff check` on changed Python files: passed.
- `python -m compileall -q resource_coordinator tests`: passed.
- `git diff --check`: passed.
- One exploratory whole-module run reported 729 passed, 7 skipped, 1 deselected, 6 failures. The failures were: two stale architecture tests expecting CLI helpers absent from unchanged `cli.py`; loopback acceptance blocked because port 1235 was occupied; a too-short test cooldown window subsequently lengthened; acceptance-harness temp lock/timing flakiness (isolated test passes); and the live-mode harness safety guard correctly refusing because it detected the already-running `krig-miner.exe`. The live harness did not start or stop a process. These were not counted as passing evidence.
- Default sandbox execution stalled before pytest output; the same tests pass with the narrowly approved normal-permission runner. No global permissions changed.

## Protocol and compatibility limits

- The merged Mining client uses the canonical route names and 3600-second duration, but is not production-compatible yet. It must add a stable request identity and 202 polling; consume server `expires_at`; redact token from dataclass serialization, journal/trial payloads, and CLI logs; require a strict matching `released` response; remove alternate/legacy miner-control fallback for supervised GPU writes; and supply restoration evidence accepted by a configured RC verifier or direct the operator to authenticated RC recovery.
- RC has no built-in independent verifier for arbitrary GPU clock/power restoration. Until an embedding deployment configures one, an authenticated, reasoned operator override is required to clear a maintenance recovery hold. A client Boolean alone does not release it.
- Logical fencing excludes RC-managed workloads only. A stale external optimizer process can still call GPU driver APIs directly.
- This is source implementation evidence only. No real mining, model load, GPU mutation, Scheduled Task, UAC, Windows upgrade, or production deployment acceptance was performed. The separate Windows upgrade `WinError 206` / elevated task acceptance gate remains.

## Next actions

1. Complete final diff/security review and final static/test checks.
2. Commit only Resource Coordinator maintenance implementation, regression tests, docs, and plan evidence.
3. Push this feature branch to origin. Do not merge or deploy.
4. Ask Mining owner to implement the documented client changes and schedule cross-repository mock acceptance. Production optimizer readiness requires that work plus separately approved Windows and hardware validation.
