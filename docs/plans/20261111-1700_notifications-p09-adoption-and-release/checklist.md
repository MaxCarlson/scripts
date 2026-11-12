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

- [ ] **Stage C: Installation Pathways & Registry Integration**
  - [ ] Version tag `<!-- version: 0.1.0 -->` added to `modules/remote_control/README.md`
  - [ ] `remote-control (module)` registered in `modules/scripts_help/scripts_help/registry/registry.py`
  - [ ] `scripts_help` test suite passes (55 tests)
  - [ ] Scheduled task stability tests written and passing
  - [ ] Stage C commit created

- [ ] **Stage D: Release Diagnostics and Supportability**
  - [ ] Read-only release check implementation in `modules/notifications/notifications/diagnostics.py`
  - [ ] CLI subcommand `scripts-notify release-check` with `-j/--json`
  - [ ] Diagnostic unit tests in `modules/notifications/tests/test_release_diagnostics.py` pass
  - [ ] CLI smoke test verified
  - [ ] Stage D commit created

- [ ] **Stage E: Documentation and Command Accuracy**
  - [ ] `docs/notifications-remote-control/public-https-setup.md` audited and corrected
  - [ ] `docs/notifications-remote-control/operator-quickstart.md` created
  - [ ] `docs/notifications-remote-control/acceptance-results.md` created
  - [ ] `docs/notifications-remote-control/rollback-and-recovery.md` created
  - [ ] `docs/notifications-remote-control/current-state.md` updated
  - [ ] Stage E commit created

- [ ] **Stage F: Full Integration Validation**
  - [ ] Synthetic E2E scenario in `modules/notifications/tests/test_phase09_synthetic_e2e.py` passes
  - [ ] Full regression suites (`notifications`, `remote_control`, `scheduler`, `scripts_help`, `resource_coordinator`) pass
  - [ ] Verify zero diff against `modules/resource_coordinator/`
  - [ ] Stage F commit created

- [ ] **Stage G: Controlled Operational Acceptance**
  - [ ] Operator acceptance runbooks and verification gates prepared
  - [ ] Final plan status and checklist updated
  - [ ] Feature branch pushed to `origin`
  - [ ] Completion report delivered
