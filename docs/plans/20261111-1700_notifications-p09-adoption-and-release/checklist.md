# Phase 09 Plan Checklist

- [x] **Stage A: Operational Inventory and Release Contract**
  - [x] Operational inventory for all 8 subsystems in `release-readiness.md`
  - [x] 5-level evidence scale applied and verified against codebase
  - [x] Stage A commit created

- [x] **Stage B: Consumer Adoption (Scheduler)**
  - [x] Failing unit tests written in `modules/scheduler/tests/test_notifications_integration.py`
  - [x] Configurable `use_notifications_broker` option in `SchedulerConfig`
  - [x] Scheduler `Notifier` updated to route Windows notifications via `notifications.publisher.Publisher`
  - [x] Safe fallback for Windows without PowerShell string interpolation
  - [x] Cross-platform behavior preserved for Termux, Linux, macOS
  - [x] Deduplication and automatic incident resolution on task success
  - [x] Tests pass (126 scheduler tests passing)
  - [x] Stage B commit created

- [x] **Stage C: Installation Pathways & Registry Integration**
  - [x] Version tag `<!-- version: 0.1.0 -->` added to `modules/remote_control/README.md`
  - [x] `remote-control (module)` registered in `modules/scripts_help/scripts_help/registry/registry.py`
  - [x] `scripts_help` test suite passes (55 tests)
  - [x] Scheduled task stability tests written and passing
  - [x] Stage C commit created

- [x] **Stage D: Release Diagnostics and Supportability**
  - [x] Read-only release check implementation in `modules/notifications/notifications/diagnostics.py`
  - [x] CLI subcommand `scripts-notify release-check` with `-j/--json`
  - [x] Diagnostic unit tests in `modules/notifications/tests/test_release_diagnostics.py` pass
  - [x] CLI smoke test verified
  - [x] Stage D commit created

- [x] **Stage E: Documentation and Command Accuracy**
  - [x] `docs/notifications-remote-control/public-https-setup.md` audited and corrected
  - [x] `docs/notifications-remote-control/operator-quickstart.md` created
  - [x] `docs/notifications-remote-control/acceptance-results.md` created
  - [x] `docs/notifications-remote-control/rollback-and-recovery.md` created
  - [x] `docs/notifications-remote-control/current-state.md` updated
  - [x] Stage E commit created

- [x] **Stage F: Full Integration Validation**
  - [x] Synthetic E2E scenario in `modules/notifications/tests/test_phase09_synthetic_e2e.py` passes
  - [x] Full regression suites (`notifications`, `remote_control`, `scheduler`, `scripts_help`, `resource_coordinator`) pass
  - [x] Verify zero diff against `modules/resource_coordinator/`
  - [x] Stage F commit created

- [x] **Stage G: Controlled Operational Acceptance**
  - [x] Operator acceptance runbooks and verification gates prepared
  - [x] Final plan status and checklist updated
  - [x] Feature branch pushed to `origin`

- [x] **Stage H: Release Correctness and Final Stabilization**
  - [x] Correct action resource barrier query to match actual schema (`resource_key, execution_id, barrier_status, reason, created_at WHERE cleared_at IS NULL`)
  - [x] Align outbox status categories with actual state machine (`pending, attempting, provider_accepted, retryable_error, terminal_error`)
  - [x] Use canonical path helpers without token leakage; remove always-true boolean check
  - [x] Separate configured public exposure, observed Funnel state, and uninspected status without fabricating disabled state
  - [x] Explicit `ok`, `ready_for_release`, `warnings`, `blockers`, and `unknowns` semantics in `release-check`
  - [x] Scheduler non-zero exit returncode checks in `_notify_platform`
  - [x] Single fallback path avoiding duplicate broker attempts in `notify_task_result`
  - [x] Stable SHA-256 generic incident keys across processes/restarts
  - [x] Task success incident resolution in broker even when `notify_on_success=False`
  - [x] Full authenticated FastAPI guarded acknowledgement test in `test_phase09_synthetic_e2e.py`
  - [x] Audited all documentation examples against real argparse parsers
  - [x] All test suites pass (559 passed, 1 skipped, 0 failed)
  - [x] Stage H commit created and pushed to `origin`
