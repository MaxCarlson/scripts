# Phase 09 Implementation Plan — Adoption, Release Integration, and Operational Readiness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Phase 09 by integrating Notifications into Scheduler and existing script workflows, establishing stable command/installation pathways, creating unified read-only release diagnostics, auditing release documentation, running end-to-end synthetic validation, and preparing controlled operator acceptance runbooks without activating public exposure or live Resource Coordinator recovery.

**Architecture:** A non-intrusive consumer integration that replaces PowerShell string interpolation in `modules/scheduler/scheduler/notifier.py` with the structured Notifications broker while preserving platform independence and graceful fallback; integration into `scripts_help`'s catalog; a unified read-only release check CLI; and exhaustive operational runbooks distinguishing synthetic verification from live operator-approved gates.

**Tech Stack:** Python 3.10+, SQLite (WAL mode), FastAPI / Starlette, PowerShell 7 / Windows 11 Toast API, Tailscale CLI (Funnel/Serve).

**Spec:** `C:\Users\mcarls\Downloads\scripts_notifications_remote_control_master_plan_2026-11-11\scripts-notifications-remote-control-plan\phases\PHASE_09_ADOPTION_AND_RELEASE.md`

## Global Constraints

- Resource Coordinator source (`modules/resource_coordinator/`) is strictly 100% read-only.
- Zero cloud spending ($0 spend); no paid hosting, domains, or third-party subscriptions.
- Public Tailscale Funnel remains disabled throughout testing.
- No live Telegram messages or external Healthchecks account mutations without operator authorization.
- No Windows Scheduled Tasks registered or modified in production during automated execution (dry-run only).
- All status/diagnostic tools must be 100% read-only (`mode=ro` SQLite, zero file modifications, zero process spawning).
- Preserve existing public APIs and cross-platform behavior (Termux, Linux, macOS).

## Review Focus

1. **PowerShell Injection Remediation:** Scheduler's Windows balloon notification interpolated untrusted strings into PowerShell; replaced with structured broker events and safe parameterized fallback.
2. **Missing Broker Fallback:** If `notifications` package is not importable or broker storage is temporarily locked, scheduler must degrade gracefully without hanging or crashing tasks.
3. **Task Deduplication & Resolution:** Repeated scheduler failures must not create notification storms (deduplicated by `incident_key`), and subsequent task success must cleanly resolve the active incident.
4. **Documentation Discrepancies:** Preflight and setup guides must accurately reflect CLI argument rules (e.g., `--skip-listener-check` is forbidden during `--apply`).
5. **Operational Evidence Integrity:** Strict delineation between synthetic test passing (mocks/in-memory) and real-world workstation/cellular validation requiring operator sign-off.

---

### Task 1: Operational Inventory and Release Contract (Stage A)

**Files:**
- Create: `docs/notifications-remote-control/release-readiness.md`
- Test/Verify: Documentation review against codebase

**Interfaces:**
- Documents entrypoints, secrets, dependencies, status commands, retention, failure behavior, and rollback for all 8 subsystems.
- Defines 5-level evidence scale: 1 (Unit tested), 2 (Synthetic integration), 3 (Workstation local), 4 (Real external service), 5 (Pending/Blocked).

- [ ] **Step 1: Draft the Operational Inventory and Release Matrix in `docs/notifications-remote-control/release-readiness.md`**
- [ ] **Step 2: Verify all paths, ports (1235, 1236, 1238, 8443), and commands match implemented code**
- [ ] **Step 3: Commit Stage A deliverable**

---

### Task 2: Adopt Notifications in Scheduler and Existing Workflows (Stage B)

**Files:**
- Modify: `modules/scheduler/scheduler/config.py`
- Modify: `modules/scheduler/scheduler/notifier.py`
- Create: `modules/scheduler/tests/test_notifications_integration.py`
- Modify: `modules/scheduler/tests/test_notifier.py`

**Interfaces:**
- Consumes: `notifications.publisher.Publisher`, `notifications.models.EventEnvelopeV1`, `notifications.storage.StorageEngine`
- Produces: `Notifier._notify_via_broker(title, message, urgency, event_data) -> bool`
- Config: `SchedulerConfig.use_notifications_broker: bool = True`

- [ ] **Step 1: Write failing tests in `modules/scheduler/tests/test_notifications_integration.py`**
  - Verify task failure emits critical incident with key `scheduler:task:<name>`.
  - Verify task success resolves existing incident with `lifecycle="resolve"`.
  - Verify schedule trigger emits info incident with key `scheduler:schedule:<name>`.
  - Verify fallback behavior when broker unavailable or disabled.
  - Verify safe Windows fallback without PowerShell string interpolation.
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Update `modules/scheduler/scheduler/config.py` with `use_notifications_broker` option**
- [ ] **Step 4: Update `modules/scheduler/scheduler/notifier.py` to route Windows notifications through Notifications broker with safe fallback**
- [ ] **Step 5: Run tests to verify they pass**
- [ ] **Step 6: Run existing `modules/scheduler/tests/` to verify zero regression**
- [ ] **Step 7: Commit Stage B deliverable**

---

### Task 3: Stable Command, Installation Pathways & Registry Integration (Stage C)

**Files:**
- Modify: `modules/remote_control/README.md`
- Modify: `modules/scripts_help/scripts_help/registry/registry.py`
- Create: `modules/notifications/tests/test_task_stability.py`

**Interfaces:**
- Registers `remote-control` in `scripts_help` under "Process & Task Automation".
- Verifies Scheduled Task definitions use absolute Python interpreter, decoupled working directory (`Path.home()`), and safe argument quoting.

- [ ] **Step 1: Add version metadata `<!-- version: 0.1.0 -->` to `modules/remote_control/README.md`**
- [ ] **Step 2: Register `remote-control (module)` in `modules/scripts_help/scripts_help/registry/registry.py`**
- [ ] **Step 3: Run `scripts_help` test suite to verify registry consistency**
- [ ] **Step 4: Write unit test in `modules/notifications/tests/test_task_stability.py` validating Scheduled Task commandline safety and path stability**
- [ ] **Step 5: Run task stability test to verify pass**
- [ ] **Step 6: Commit Stage C deliverable**

---

### Task 4: Unified Read-Only Release Diagnostics (Stage D)

**Files:**
- Create: `modules/notifications/notifications/diagnostics.py`
- Modify: `modules/notifications/notifications/cli.py`
- Create: `modules/notifications/tests/test_release_diagnostics.py`

**Interfaces:**
- Produces: `run_release_check(json_output: bool = False) -> dict[str, Any]`
- CLI: `scripts-notify release-check [-j/--json]`
- Read-only inspection of: storage, outbox, telegram, windows toast, healthchecks, coordinator observer, remote control auth, listener health, barriers, funnel.

- [ ] **Step 1: Write failing tests in `modules/notifications/tests/test_release_diagnostics.py`**
  - Verify read-only enforcement (`mode=ro`).
  - Verify JSON schema and comprehensive status coverage.
  - Verify no state mutation or process startup.
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement `run_release_check` in `modules/notifications/notifications/diagnostics.py`**
- [ ] **Step 4: Wire `release-check` subcommand into `modules/notifications/notifications/cli.py`**
- [ ] **Step 5: Run tests to verify they pass**
- [ ] **Step 6: Run CLI command smoke test `python -m notifications.cli release-check --json`**
- [ ] **Step 7: Commit Stage D deliverable**

---

### Task 5: Documentation Audit and Accuracy Updates (Stage E)

**Files:**
- Modify: `docs/notifications-remote-control/public-https-setup.md`
- Create: `docs/notifications-remote-control/operator-quickstart.md`
- Create: `docs/notifications-remote-control/acceptance-results.md`
- Create: `docs/notifications-remote-control/rollback-and-recovery.md`
- Modify: `docs/notifications-remote-control/current-state.md`

**Interfaces:**
- Reconciles CLI parser reality with documentation (removes `--skip-listener-check` with `--apply`).
- Provides quickstart, acceptance results ledger, rollback runbook, and current-state milestone record.

- [ ] **Step 1: Audit and correct `docs/notifications-remote-control/public-https-setup.md`**
- [ ] **Step 2: Create `docs/notifications-remote-control/operator-quickstart.md`**
- [ ] **Step 3: Create `docs/notifications-remote-control/acceptance-results.md`**
- [ ] **Step 4: Create `docs/notifications-remote-control/rollback-and-recovery.md`**
- [ ] **Step 5: Update `docs/notifications-remote-control/current-state.md`**
- [ ] **Step 6: Commit Stage E deliverable**

---

### Task 6: Full Integration Validation & End-to-End Scenario (Stage F)

**Files:**
- Create: `modules/notifications/tests/test_phase09_synthetic_e2e.py`

**Interfaces:**
- Tests 10-step synthetic lifecycle: Scheduler failure -> Broker persistence -> Incident open -> Outbox queued -> Fake provider delivery -> Remote Control query -> Guarded TOTP acknowledgement -> Incident acknowledged -> Scheduler retry success -> Incident resolved.

- [ ] **Step 1: Write `modules/notifications/tests/test_phase09_synthetic_e2e.py`**
- [ ] **Step 2: Run E2E test to verify it passes**
- [ ] **Step 3: Run full regression suites across `notifications`, `remote_control`, `scheduler`, `scripts_help`, and `resource_coordinator` (contracts)**
- [ ] **Step 4: Confirm zero diff against `modules/resource_coordinator/`**
- [ ] **Step 5: Commit Stage F deliverable**

---

### Task 7: Controlled Operational Acceptance Preparation (Stage G)

**Files:**
- Modify: `docs/notifications-remote-control/acceptance-results.md`
- Update: `docs/plans/20261111-1700_notifications-p09-adoption-and-release/` status and checklist

**Interfaces:**
- Prepares operator-controlled acceptance sequence for local workstation, Telegram, Healthchecks, and Android cellular without performing unauthorized public actions.

- [ ] **Step 1: Review acceptance gates and document explicit approval requirements**
- [ ] **Step 2: Finalize dated plan status and checklist**
- [ ] **Step 3: Commit Stage G deliverable and push branch to `origin`**
- [ ] **Step 4: Produce comprehensive final completion report**
