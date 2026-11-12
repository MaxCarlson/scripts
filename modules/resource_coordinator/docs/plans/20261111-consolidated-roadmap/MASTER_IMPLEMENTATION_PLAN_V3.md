# Resource Coordinator — Consolidated Implementation Roadmap (v3)

**Date:** November 11, 2026  
**Repositories:** `MaxCarlson/scripts`, `MaxCarlson/Mining`  
**Scope:** Resource Coordinator maintenance integration, CLI modernization and compaction, local inference and maintenance observability, evidence-based recovery, worktree defect remediation, Windows deployment, and controlled live acceptance  
**Status:** Master implementation plan v3 — incorporates v2 review corrections (preserved root `recover -r` compatibility, separated `rc maintenance reconcile`, crash-safe startup inhibition canonicalization, two-stage recovery transaction, distinct reconciliation dispositions, and `no_action_required` recovery classification); execute after verifying the current H3 agent's results and repository state

---

## Executive summary

The objective is to evolve Resource Coordinator (RC) from a safe but sometimes manually operated GPU arbitration system into an observable, maintainable, and increasingly autonomous control plane with a single, non-overlapping command interface.

The desired end state is:

- One command (`rc status`) provides an understandable view of RC, KRig, LM Studio, active inference, maintenance sessions, gaming state, and recovery blockers.
- The canonical `rc` CLI exposes a compact, non-overlapping 12-command top-level catalog without redundant wrapper groups (`control` and `check` are retired to hidden compatibility aliases), while preserving 100% backward compatibility for all historical and Nov 6 command paths (including root `recover -r <resource> -n <reason>` vs. `service recover --resource <resource> -r <reason>`).
- All significant commands support polished, color-coded human output (never collapsing nested telemetry, setup, or acceptance results into generic `"N structured items (see --json)"` placeholders) and stable machine-readable JSON.
- RC determines whether requests are active, pending, completed, or uncertain using its own authoritative state and independent runtime observations.
- RC evaluates whether recovery (both inference inhibition and maintenance session holds) is justified without requiring the operator to inspect process listings or manually interpret multiple command outputs, and distinguishes a healthy system (`no_action_required`) from an active safety hold that can be cleared (`auto_recoverable`).
- When independently verified safe, RC reconciles a stale inhibition using a non-blocking two-stage recovery transaction, records an accurate reconciliation disposition (never conflating independent execution termination with HTTP protocol completion), and permits normal Coordinator-managed miner restoration.
- When safety cannot be established, RC preserves protections, explains the precise uncertainty, and optionally sends an actionable notification.
- Four confirmed `v0.14.0` worktree defects (identified for pending source repair during Parts 2–3) in status recursive sanitization/allowlisting, telemetry rendering/ownership, crash-safe startup inhibition canonicalization, and `psutil.AccessDenied` PID reconciliation are resolved.
- Existing GPU maintenance integration and Mining optimizer work reach source integration, Windows hardware qualification, and authorized controlled live acceptance.
- The design avoids introducing LLM Monitor as a mandatory dependency of RC safety decisions.

**Key architectural rule:** RC owns GPU admission, maintenance, process lifecycle, and minimal durable safety state. LLM Monitor owns detailed inference telemetry and historical analysis. LM Studio provides runtime observations where supported.

**Critical safety distinction:** A model reporting idle, a missing miner process, or zero active gateway requests is not sufficient by itself to prove that an interrupted upstream operation has terminated.

---

## Summary of v3 refinements and pending codebase defect repairs

A code-level audit of the `v0.14.0` candidate worktree (`737bc6b2db7b68c041abffb66017164f3c883228`) and subsequent peer review of v2 identified the following concrete requirements for this v3 plan (note: source defects listed below are **pending fixes to be implemented in Parts 2–3**, not already modified in source):

1. **Preserved root `recover -r` contract while sharing validation/dispatch (P0):**
   - Root `recover` in `cli_parser.py` binds `-r/--resource` and `-n/--reason` (explicitly tested by `test_cli_architecture.py`: `["recover", "-r", "gpu.inference", "-n", "reviewed"]`), whereas `service recover` binds `--resource` (long-only) and `-r/--reason`.
   - **v3 resolution:** Do not reassign `-r` on root `recover` or use value heuristics. Preserve exact short-flag bindings per command family:
     - Root `rc recover` / `resource-coordinator recover`: `-r/--resource`, `-n/--reason`
     - `rc service recover` / `resource-coordinator service recover`: `--resource`, `-r/--reason`
     Both share a parameterized parser helper (`_configure_recover_parser(parser, *, legacy_root_flags: bool)`) and identical validation/dispatch logic where `--reason` is optional at parse time (required only with `-f/--force`), and `-a/--apply` and `-f/--force` are mutually exclusive.
2. **Dedicated `rc maintenance` command family and exact release contract (P0):**
   - Maintenance sessions place a protective inhibition on `gpu.inference` (`holder_id="maintenance:<operation_id>"`) AND maintain a separate GPU maintenance admission fence (`_gpu_maintenance_owner`) and durable session state machine (`maintenance.py`). Treating maintenance as an ordinary `--resource gpu.maintenance` inhibition in `rc recover` is misleading.
   - **v3 resolution:** Add a dedicated `rc maintenance` top-level command (`rc maintenance status`, `rc maintenance reconcile [-f -r "reason"] [--operation-id ID] [--session-id ID] [--no-resume-miner]`). Keep `rc status maintenance` as the status view and allow `rc recover --maintenance` only as a convenience alias that delegates directly to the maintenance reconciliation handler—never to `gpu.inference` inhibition clearing. Specify the exact identity-discovery (`GET /_coordinator/maintenance/status`) and `POST /_coordinator/maintenance/release` payload contract required by `MaintenanceSessionManager.release()`.
3. **Crash-safe startup inhibition canonicalization and two-stage recovery transaction (P0):**
   - **Startup canonicalization:** In `durable_state.py`, `reconcile_startup_state()` currently restores `state.inhibitions` (`holder_id="coord-..."`) and also adds an unpersisted in-memory inhibition (`holder_id="crash_recovery:coord-..."`) for the same unresolved request. V3 specifies an atomic, idempotent startup canonicalization sequence that migrates any legacy `crash_recovery:<req_id>` holders to `<req_id>`, persists missing request holds without discarding unrelated holders (`additional_uncertain_holders`), restores all unique holds into `LeaseManager`, fails closed on any persistence error, and is verified by deterministic failure-injection tests across every persistence boundary.
   - **Two-stage recovery transaction:** `POST /_coordinator/recovery/auto` must not hold `LeaseManager._condition` while running external OS process checks or LM Studio probes. V3 specifies a two-stage transaction using an in-memory recovery fence (`_gpu_recovery_fence`) and state generation counter (`_state_generation`), with explicit cleanup guarantees across timeouts, cancellations, and crashes.
4. **Corrected automatic recovery state semantics and reconciliation dispositions (P1):**
   - **Separate `no_action_required` from `auto_recoverable`:** A healthy Coordinator with no active holds does not need recovery. V3 uses five classifications: `no_action_required`, `auto_recoverable`, `wait`, `operator_required`, and `blocked`.
   - **Do not falsify `TERMINAL_VERIFIED`:** Recording `RequestPhase.TERMINAL_VERIFIED` when an upstream runtime died without completing the HTTP response would falsify protocol completion evidence. V3 keeps `RequestPhase.TERMINAL_VERIFIED` strictly for verified protocol completion (`[DONE]` or verified non-streaming HTTP response), adds `RequestPhase.RECONCILED = "reconciled"` (or backward-compatible schema migration) with explicit `details["reconciliation_disposition"]` values (`protocol_terminal_verified`, `execution_termination_verified`, `not_forwarded_verified`, `operator_resolved`).
5. **Tightened status recursive sanitization, offline assessment guardrails, and CLI/versioning policy (P1/P2):**
   - **Recursive holder sanitization:** `gateway.py` `handle_coordinator_status()` now sanitizes both the primary `inhibition.details` and every nested entry in `details["additional_uncertain_holders"]` so multi-holder blockers remain visible without leaking unallowlisted fields.
   - **Offline recovery assessment guardrail:** When the Coordinator HTTP service is unreachable, `rc recover` may inspect the local journal for read-only diagnostics (`status="offline_diagnostic_only"`), can never report `auto_recoverable`, and refuses `-a/--apply` and `-f/--force`.
   - **Policy-compliant `1.0.0` version bump for `rc`:** To satisfy `SCRIPTS_REPO_STANDARDS.md` (which triggers `.venv/Scripts/*.cmd` wrapper regeneration via `python setup.py` on major version bumps), bump `resource_coordinator` from `0.14.0` to `1.0.0` in `pyproject.toml` and `resource_coordinator/__init__.py`.
   - **4 pending worktree bug repairs (`v0.14.0` baseline):**
     - **Pending Bug Fix 1 (`gateway.py` lines 629–656 & 714):** Restore the 6 stripped v0.12 diagnostic fields in `safe_request_detail_fields`, recursively sanitize `additional_uncertain_holders`, use `safe_inhibition` at line 714, and add safe non-mutating `gaming` status to `GET /_coordinator/status`.
     - **Pending Bug Fix 2 (`durable_state.py` lines 891–932):** Fix duplicate `coord-...` + `crash_recovery:coord-...` startup inhibitions via crash-safe canonicalization.
     - **Pending Bug Fix 3 (`durable_state.py` lines 937–942):** Stop catching `psutil.AccessDenied` in `_default_query()` so `reconcile_pid()` returns `ReconciliationOutcome.ACCESS_DENIED` instead of `NOT_RUNNING`.
     - **Pending Bug Fix 4 (`cli.py` lines 530–587 & `installation.py` line 3050):** Replace generic `render_result()` in `rc telemetry` with `render_telemetry_result()`, use running Coordinator process ownership when online (or label offline fallback as `ownership_unverifiable_offline` and close the local gateway), and define explicit exit-code semantics for `rc doctor` (`0` healthy, `1` degraded, `2` blocked).

---

## Existing work and project continuity

### Verified checkpoints

| Workstream | State | Evidence / next action |
|---|---|---|
| H1 / H2A — Durable GPU maintenance sessions and RC integration | Complete in feature source | RC maintenance acquisition, admission fencing, durable recovery, release |
| H2C — RC trusted restoration verification | Complete in feature source | RC v0.14.0, commit `737bc6b2db7b68c041abffb66017164f3c883228` |
| H2B — Mining maintenance client compatibility | Complete in feature source | Commit `8f53e3d32d2bce560a2b35c802e6ac1c3fbfa7db` |
| H2D — Mining scope and process-registration compatibility | Complete and pushed | Commit `4787f9bac06d811ca82a8a3752a61c69f181aafb`; 190 optimizer tests and 13 shared-package tests passed |
| H3 — Cross-repository simulated acceptance | Assigned/current work | Agent was handed the task; no final H3 checkpoint was found on the inspected Mining branch |
| Original next milestone — Source integration | Pending H3 | Review and integrate validated RC and Mining candidates |
| Original H4 — Windows upgrade and hardware qualification | Pending | Scheduled Task upgrade, process attribution, NVML setting readback, deployment acceptance |
| Original H5 — Controlled live acceptance | Pending | One bounded, separately authorized test before broader optimizer activity |
| Original H6 — Notifications/watchdog and deferred automation | Pending | Reuse verified recovery/health events; avoid duplicate agent intervention |
| New work — CLI compaction, inference/maintenance status, pending worktree bug fixes, and automated recovery | Planned here | Parts 2 and 3 |

The current status of an agent process cannot be established from GitHub alone. Before taking ownership, inspect the agent's actual report, working tree, and published checkpoint. Do not duplicate H3 while it remains active.

### Preservation of roadmap artifacts across worktrees

> [!IMPORTANT]
> This roadmap directory (`modules/resource_coordinator/docs/plans/20261111-consolidated-roadmap/`) currently resides as untracked files inside the `resource-coordinator-v013-integration-restoration-20261111` worktree. A newly created Git worktree will not inherit untracked files automatically. Before spawning or handing off to the next implementation worktree, either commit this finalized v3 roadmap to the active RC feature branch (once authorized) or copy the `20261111-consolidated-roadmap/` folder into the new agent's authorized working branch.

### Repository references

**Resource Coordinator**

- Repository: `MaxCarlson/scripts`
- Candidate branch: `agent/resource-coordinator-v013-integration-restoration-20261111`
- Pinned candidate: `737bc6b2db7b68c041abffb66017164f3c883228`
- Package baseline: RC v0.14.0 (target v1.0.0 in Part 2 for `rc` console-script wrapper generation)
- The candidate is currently reported as 9 commits ahead and 8 behind `scripts/main`.
- Newer mainline changes did not overlap RC paths in the examined diff; reconciliation is still required.

**Mining**

- Repository: `MaxCarlson/Mining`
- Candidate branch: `agent/mining-rc-maintenance-compat-20261111`
- Pinned H2D: `4787f9bac06d811ca82a8a3752a61c69f181aafb`
- Candidate is 2 commits ahead and 0 behind Mining `master` at the inspected checkpoint.

The older RC upgrade-reliability feature branch was reported 0 ahead and 37 behind `scripts/main`. Inspect current mainline before reviving any historical upgrade fixes; an old branch name does not establish unfinished work.

### Original roadmap preserved

Before this plan, the expected sequence was:

**H3 offline acceptance → source integration → H4 Windows/Scheduled Task and GPU capability acceptance → H5 controlled live optimizer acceptance → H6 notifications/watchdog.**

This remains the baseline. The new capabilities are inserted as a coordinated improvement track rather than replacing or indefinitely delaying that path.

### Execution and ownership rules

- Do not interrupt H3 or any other productive active assignment.
- Verify actual branches, worktrees, dirty files, dependencies, and validated commits before Git operations.
- Prefer isolated branches/worktrees, with RC source owned by the RC agent and Mining source owned by the Mining integration agent.
- Never reset, overwrite, delete, or clean unrelated work to simplify integration.
- Commit/push validated feature work within scope; merge only with authorization.
- Tests must default to fake services, simulated GPUs, harmless processes, and isolated durable state.
- Do not mutate live RC services, KRig, LM Studio, Windows tasks, WSL, models, or GPU configuration without separate authorization.

---

# Part 1 — Finish Current Integration and Establish a Validated Baseline

**Objective:** Finish the work already in progress and deliver a stable shared baseline for the remaining RC enhancements.

**Dependencies:** H3 completion or an evidenced H3 blocker.

## 1.1 Complete H3 without restarting it

Accept the existing agent's H3 work as the starting point.

H3 should validate actual Mining-to-RC protocol interaction using the real client and server handlers with simulated hardware and processes.

Required coverage includes:

- Maintenance acquisition and exclusive GPU admission.
- Correct `tuning_scope` and baseline capture.
- Managed-miner stop before grant.
- Trial child creation suspended on Windows.
- Exact process registration before execution.
- Ownership revalidation before child resume.
- Multiple registered trials.
- Process termination and independent simulated restoration verification.
- Strict authoritative release disposition.
- Cooldown and normal Coordinator-owned miner resumption.
- Lost HTTP responses, stale sessions, uncertain releases, and recovery holds.

H3 does not establish readiness of the installed RTX 5090, NVML process attribution, Scheduled Tasks, or live optimizer execution.

Collect the final H3 report, commit, tests, and unresolved findings. Resolve only confirmed blockers.

## 1.2 Integrate validated RC and Mining sources

After successful H3:

1. Inspect fresh branch/worktree and mainline state for both repositories.
2. Ensure this roadmap (`20261111-consolidated-roadmap/MASTER_IMPLEMENTATION_PLAN_V3.md`) is committed or transferred into the integration branch so it is not stranded in an old worktree.
3. Reconcile the RC candidate with current `scripts/main` using a safe integration branch.
4. Confirm that newer unrelated modules and active agent work are preserved.
5. Rerun the RC maintenance, restoration, lifecycle, CLI, gateway, installation, and relevant regression suites.
6. Integrate the validated Mining candidate into its own mainline through an independently reviewed change.
7. Revalidate the pinned cross-repository contracts against the integrated source commits.
8. Preserve historical H2/H3 status reports and update the handoff indexes.

A merge conflict, new regression, or unverified diff is a blocker. A clean text merge alone is insufficient.

Integration requires authorization; this roadmap is not that authorization.

## 1.3 Preserve the original operational gates

Do not activate the new maintenance protocol immediately after merging.

The existing concerns remain:

- Historical Windows Scheduled Task upgrade `WinError 206`.
- Potential launcher/restart ownership conflicts.
- Real process identity, process-group, and descendant verification.
- Installed RC version and configured/runtime source consistency.
- Windows/NVML GPU process-attribution support.
- Independent readback of actual GPU power and clock offsets.
- Fixed/locked-clock modes without trusted restoration proof.
- Startup/restart cooldown and durable recovery behavior.
- Uncertain direct LM Studio or WSL clients bypassing the Coordinator.

Capture these in a deployment readiness ledger.

## Part 1 acceptance criteria

- H3 is accepted with reproducible cross-repository evidence, or blocked findings are explicitly recorded.
- No current agent work was duplicated or discarded.
- RC and Mining source integration is completed only when authorized, with test evidence.
- Integrated source commits and protocol versions are recorded.
- Production deployment and actual hardware mutation remain separate, gated operations.

**Checkpoint:** Validated source baseline ready for feature development and independent Windows readiness work.

---

# Part 2 — Compacted CLI, Unified Status, Inference/Maintenance Visibility, and Pending Worktree Bug Fixes

**Objective:** Make the Coordinator understandable to humans and agents through one compact, non-overlapping command system while preserving 100% legacy CLI compatibility, and repair confirmed status/presentation/telemetry defects in the worktree.

This part combines CLI compaction, parser deduplication, dedicated maintenance reconciliation commands, unified inference and maintenance status, LM Studio runtime observation, the initial read-only recovery assessor, and remediation of confirmed `v0.14.0` CLI/status bugs.

## 2.1 Canonical CLI design, versioning, and taxonomy consolidation

Provide a short `rc` console script entry point alongside `resource-coordinator` and `gpu-coordinator` in `pyproject.toml`:

```toml
[project.scripts]
rc = "resource_coordinator.cli:main"
resource-coordinator = "resource_coordinator.cli:main"
gpu-coordinator = "resource_coordinator.cli:main"
```

Verify that `rc` does not collide with another installed command in normal PowerShell sessions (note: Windows Kits `rc.exe` is only on `PATH` inside Visual Studio Developer shells; keep `resource-coordinator` and `gpu-coordinator` fully functional everywhere).

### Policy-compliant major version transition (`1.0.0`)

Per repository standards (`docs/agent/SCRIPTS_REPO_STANDARDS.md` and `REPO_LLM_INSTRUCTIONS.md`), adding a new `[project.scripts]` entry point (`rc`) and consolidating the canonical CLI surface requires a **MAJOR version bump** so `python setup.py` automatically detects the major transition, runs `pip install -e .`, and generates `.venv/Scripts/rc.cmd` and `~/.local/bin/rc.cmd` shims:

- Bump `version = "1.0.0"` in `modules/resource_coordinator/pyproject.toml` and `__version__ = "1.0.0"` in `modules/resource_coordinator/resource_coordinator/__init__.py`.
- Register `resource_coordinator` (`rc` / `resource-coordinator`) under `"System & Monitoring"` in `modules/scripts_help/scripts_help/registry/registry.py`.
- Keep `validation-targets.json` and `Invoke-Tests.ps1` aligned with the module test suite.

### Consolidated 12-command top-level catalog

To prevent two competing CLI hierarchies from appearing in `--help` at the same time, **retire `control` and `check` to hidden compatibility aliases (`help=argparse.SUPPRESS`)** and expose a single, flat-first 12-command canonical catalog in `rc --help`:

1. `status`
2. `doctor`
3. `telemetry`
4. `miner`
5. `gaming`
6. `maintenance`
7. `recover`
8. `logs`
9. `service`
10. `system`
11. `config`
12. `help`

| Canonical Command | Function | Compatibility Aliases (Hidden in `--help`) |
|---|---|---|
| `rc status` | Unified system overview (RC, miner, inference, gaming, maintenance, recovery) | `resource-coordinator status` |
| `rc status -j` | Structured system overview JSON | `rc -j status` |
| `rc status miner` | Detailed miner lifecycle, ownership, holds, and restart state | `rc miner status`, `rc control miner status` |
| `rc status inference` | Local inference activity, pending operations, coverage, and uncertainty | `rc check inference` |
| `rc status gaming` | Gaming-mode state and saved models | `rc gaming status`, `rc control gaming status` |
| `rc status maintenance` | GPU maintenance session state, owner, lease expiry, registered processes, and restoration | `rc maintenance status` |
| `rc status -a` / `--all` | Expanded human-readable diagnostic snapshot across all subsystems | `rc status --all` |
| `rc doctor [-j]` | Health, installation, configuration, credentials, task, and runtime diagnostics | `rc check health`, `resource-coordinator doctor` |
| `rc telemetry [-c CFG] [-u URL] [-j]` | CPU/GPU hardware metrics and coordinator telemetry | `rc check telemetry`, `resource-coordinator diagnose` |
| `rc miner start\|stop\|pause\|resume\|status` | Coordinator-managed miner lifecycle and timed/GPU-idle pause controls | `rc control miner <action>` |
| `rc gaming on\|off\|status` | Coordinate gaming mode and local-model memory (`start`/`stop` accepted as aliases) | `rc control gaming on\|off\|status`, `rc gaming start\|stop` |
| `rc maintenance status\|reconcile` | Inspect GPU maintenance sessions or perform audited reconciliation of `recovery_required` maintenance holds | `rc status maintenance`, `rc recover --maintenance` |
| `rc recover` | Read-only comprehensive recovery assessment (inference + maintenance + process holds) | `resource-coordinator recover` |
| `rc recover -j` | Machine-readable recovery assessment and recommended actions | `rc -j recover` |
| `rc recover -a` / `--apply` | Apply only independently verified automatic inference recovery | `rc service recover -a` |
| `rc recover -f -n "reason"` (or `--reason "reason"`) | Authenticated, audited operator override for inference inhibition (`-r/--resource` selects resource, default `gpu.inference`) | `rc service recover -f -r "reason" [--resource RES]` |
| `rc logs [process_name] [-f] [-b N]` | Read or follow captured process output (`process_name` defaults to `"miner"`) | `rc logs miner`, `rc logs krig` |
| `rc service restart\|shutdown\|abort\|recover\|run` | Coordinator daemon lifecycle (`serve` preserved as alias for `service run`) | `rc restart`, `rc shutdown`, `rc abort`, `rc serve` |
| `rc system setup\|upgrade\|repair\|teardown\|startup\|recovery\|auth\|preflight\|accept` | Host installation, Windows task management, upgrade recovery, auth, preflight, and acceptance trials | `rc setup`, `rc upgrade`, `rc repair`, `rc teardown`, `rc startup ...`, `rc auth ...`, `rc check preflight\|accept`, `rc preflight`, `rc accept` |
| `rc config show\|validate` | Inspect or validate configuration YAML | `resource-coordinator config show\|validate` |
| `rc help [command]` | Discoverable command catalog, architecture summary, and examples | `rc --help`, `rc <command> --help` |

*Note on `rc recover`, `rc maintenance reconcile`, and `rc system recovery`:*
- `rc recover` assesses all runtime holds and performs inference inhibition recovery (`gpu.inference` / `gpu.model_loading`).
- `rc maintenance reconcile` resolves stuck (`recovery_required`) GPU maintenance sessions and their admission fence.
- `rc system recovery` inspects or restores interrupted Windows host upgrades (`upgrade-receipt.json`). `rc recover` must check for an active `upgrade-receipt.json` and, if present, display a clear note directing the operator to `rc system recovery`.

### 2.1.1 Preserving the `recover` flag contract without heuristics

In the existing codebase (`cli_parser.py` and `tests/test_cli_architecture.py`), root `recover` and `service recover` have distinct short-flag bindings:

| Command family | Resource flag | Reason flag | Mode flags |
|---|---|---|---|
| Root `recover` (`rc recover`, `resource-coordinator recover`) | `-r` / `--resource` (default `"gpu.inference"`) | `-n` / `--reason` | `-a` / `--apply` vs. `-f` / `--force` (mutually exclusive; neither = read-only assessment) |
| `service recover` (`rc service recover`, `resource-coordinator service recover`) | `--resource` (default `"gpu.inference"`, long-only) | `-r` / `--reason` | `-a` / `--apply` vs. `-f` / `--force` (mutually exclusive; neither = read-only assessment) |

**Strict compatibility rules:**
- **Never** reassign `-r` to `--reason` on root `recover`, **never** infer flag meaning from the value string (e.g., checking for `gpu.*`), and **never** weaken or delete the existing `test_cli_architecture.py` test (`["recover", "-r", "gpu.inference", "-n", "reviewed"]`).
- Implement a shared parser helper `_configure_recover_parser(parser, *, legacy_root_flags: bool)`:
  - When `legacy_root_flags=True` (used by root `recover`): bind `-r`/`--resource` (`dest="resource"`, default `"gpu.inference"`) and `-n`/`--reason` (`dest="reason"`, default `None`).
  - When `legacy_root_flags=False` (used by `service recover`): bind `--resource` (`dest="resource"`, default `"gpu.inference"`) and `-r`/`--reason` (`dest="reason"`, default `None`).
  - Both attach `-u`/`--url`, mutually exclusive `-a`/`--apply` and `-f`/`--force`, and hidden compatibility flag `--maintenance` (which delegates to `maintenance.reconcile`).
  - Neither sets `required=True` on `--reason` in `argparse`. Instead, when `-f`/`--force` is passed (or when legacy invocation `recover -r gpu.inference -n "reviewed"` passes a non-empty `reason` without `-a`, which preserves legacy override behavior or requires `-f` per existing handler rules), validate in dispatch/CLI that `reason` is non-empty when `-f` is used (exiting with code `2` via `parser.error("--reason (-n/-r) is required with --force")` if missing).
  - *Backward-compatibility note for `test_cli_architecture.py`:* In `tests/test_cli_architecture.py`, `parse_args(["recover", "-r", "gpu.inference", "-n", "reviewed"])` and `parse_args(["service", "recover", "--reason", "reviewed"])` only test `parse_args()` and `normalize_dispatch()`. Because `reason` is optional at `parse_args()` time, both calls continue to parse cleanly with `operation_id="service.recover"` (or normalized recovery dispatch) and `args.reason == "reviewed"`.

### 2.1.2 Canonical `rc maintenance` interface and release payload contract

Because a maintenance session owns both a `gpu.inference` restart inhibition (`holder_id="maintenance:<operation_id>"`) and a dedicated admission fence (`LeaseManager._gpu_maintenance_owner`) plus durable session state (`MaintenanceSessionManager._record`), maintenance reconciliation must have its own first-class CLI surface rather than masquerading as an ordinary inference resource.

#### CLI surface

- `rc maintenance status [-u URL] [-j]` (identical to `rc status maintenance`):
  - Queries `GET /_coordinator/maintenance/status` and renders state (`idle`, `acquiring`, `active`, `releasing`, `recovery_required`), owner, `operation_id`, `session_id`, lease expiration, `recovery_required_reason`, `registered_process_count`, `restoration` verification summary, and `last_disposition`.
- `rc maintenance reconcile [-u URL] [-f/--force] [-r/--reason REASON] [-o/--operation-id ID] [-s/--session-id ID] [--no-resume-miner] [-j]`:
  - **Without `-f/--force` (default read-only mode):**
    - Fetches `GET /_coordinator/maintenance/status` (and `GET /_coordinator/status`).
    - If `state == "idle"`, reports `no_action_required` (exit code `0`).
    - If `state in {"acquiring", "active", "releasing"}`, reports active session details and whether the lease is still valid (`wait`, exit code `1`).
    - If `state == "recovery_required"`, reports the exact `operation_id`, `session_id`, `owner`, `recovery_required_reason`, `registered_process_count`, and hardware `restoration` status, and prints the exact command required to override once the operator has verified that external tuning processes have exited and GPU clocks/power are safe:
      `rc maintenance reconcile -f -r "Operator verified external process termination and GPU restoration"` (exit code `2`).
  - **With `-f/--force` (authenticated operator override):**
    - Requires a non-empty bounded `-r/--reason` (1..512 chars).
    - **Step 1 — Identity resolution and state verification:** Calls `GET /_coordinator/maintenance/status`.
      - Verifies that `state == "recovery_required"`. If `state == "idle"`, returns a clean `no_action_required` message without mutating state. If `state in {"acquiring", "active", "releasing"}`, refuses override with exit code `1` unless the session has already transitioned to `recovery_required` (because `MaintenanceSessionManager.release()` only permits tokenless `operator_recovery` when `self.state == "recovery_required"`).
      - Extracts `active_operation_id = status.get("operation_id")` and `active_session_id = status.get("session_id")`.
      - If the caller passed `-o/--operation-id` or `-s/--session-id`, verifies that it matches the active `recovery_required` record before sending the release request; otherwise defaults to the discovered `operation_id` and `session_id` from `GET /_coordinator/maintenance/status`.
      - Requires at least one of `operation_id` or `session_id` to be a non-empty string (note: an interrupted acquisition in `recovery_required` has `operation_id` but `session_id=None`, whereas an expired/failed active session has both `operation_id` and `session_id`; `MaintenanceSessionManager.release()` lines 559–562 and 673–679 accepts `session_id=None` when `operation_id` matches `self._record.get("operation_id")`).
    - **Step 2 — Audited release call:** Sends `POST /_coordinator/maintenance/release` authenticated with `Authorization: Bearer <operator_token>` and the exact JSON payload required by `MaintenanceSessionManager.release()`:
      ```json
      {
        "operator": "<resolved_operator_identity>",
        "operation_id": "<resolved_operation_id>",
        "session_id": "<resolved_session_id_or_null>",
        "restoration_verified": false,
        "resume_miner": true,
        "operator_override": true,
        "override_reason": "<operator_reason>",
        "restoration_evidence": {}
      }
      ```
      *(where `resume_miner` is `False` if `--no-resume-miner` was passed, and `session_id` is omitted or `null` when `None`).*
    - **Step 3 — Result handling:** Renders the returned `disposition` (including `miner_restart_eligible` and `restart_not_before` cooldown) or any server-side safety rejection (e.g., if the managed miner is not verified stopped).
- **Relationship to `rc recover`:**
  - `rc recover` (read-only) always inspects and reports maintenance blockers alongside inference holds, recommending `rc maintenance reconcile -f -r "..."` when `maintenance.state == "recovery_required"`.
  - If an operator invokes `rc recover --maintenance ...`, CLI dispatch routes the call directly to the `rc maintenance reconcile` handler—never to `POST /_coordinator/recover`.

### 2.1.3 Additional parser and exit-code specifications

- **Eliminate duplicated parser definitions in `cli_parser.py`:** Refactor `cli_parser.py` to use shared argument-configuration helpers (`_configure_miner_parser`, `_configure_gaming_parser`, `_configure_recover_parser`, `_configure_maintenance_parser`, `_configure_serve_parser`, `_configure_accept_parser`, etc.) so canonical top-level commands and hidden compatibility aliases (`control`, `check`, legacy root verbs) share one definition.
- **Implement `rc status [target]` without nested subparsers:** Define `status_target` on `status_parser` using `nargs="?", choices=("miner", "inference", "gaming", "maintenance")` and `-a/--all` (`action="store_true"`). Do **not** attach `_SubParsersAction` to `status_parser`; this keeps `status_parser` a leaf parser so `_add_global_leaf_options()` attaches `-j/--json`, `-v/--verbose`, and `-C/--color` without default-masking bugs.
- **Unify `gaming` action spellings:** Both `rc gaming` and `rc control gaming` must accept `status`, `on`, `off`, `start`, and `stop` (`start` normalizes to `on`/`start`, `stop` normalizes to `off`/`stop`).
- **Default `rc logs` process name:** Change `logs_parser.add_argument("process_name", nargs="?", default="miner", ...)` so `rc logs` and `rc logs -f` work without requiring `miner` explicitly.
- **Short and long flags:** Ensure all new and modified user-facing options provide both short and long forms per `PYTHON_REPO_STANDARDS.md` (e.g., `-a/--all` on `status`, `-b/--tail-bytes` on `logs`, `-C/--color` global option, `-o/--operation-id` and `-s/--session-id` on `maintenance reconcile`).
- **Explicit exit-code semantics for `rc doctor` and installation commands:**
  - In `installation.py`, `classify_doctor()` returns `"healthy"`, `"degraded"`, or `"blocked"`.
  - Update `handle_installation_command()` so `rc doctor` (`check.health`) returns:
    - `0` when `status == "healthy"`
    - `1` when `status == "degraded"`
    - `2` when `status in {"blocked", "recovery-required", "unhealthy", "failed", "error"}`
    *(matching the `0` / `1` / `2` convention already used by `manager.recovery()` at lines 3015–3017 of `installation.py`).*
  - Update `setup`, `repair`, `teardown`, and `startup` in `handle_installation_command()` to return `1` when `result.get("status")` is in `{"blocked", "recovery-required", "failed", "error"}` and `0` otherwise. Update any affected test assertions in `tests/test_installation.py`.

## 2.2 Mandatory human-readable presentation and pending worktree bug fixes

Every command exposing `-j/--json` must also provide an intentional, polished default presentation.

### Presentation design

- Rich tables and aligned fields, with consistent headings and spacing.
- Green: verified healthy/successful.
- Yellow: pending, waiting, degraded, or uncertain.
- Red: failed, blocked, or unsafe.
- Cyan/blue: neutral informational values.
- Summary and important blockers first; verbose evidence afterward.
- Distinguish observed facts from inferred conclusions.
- Clearly explain what needs intervention, using the new canonical `rc ...` command names in recommendations and error messages.
- Hide irrelevant empty sections without hiding uncertainty.
- Never collapse primary command output into generic `render_result()` `"N structured fields/items (see --json)"` placeholders.
- Respect `-C/--color auto|always|never` and `NO_COLOR`.
- Remain readable in Windows Terminal, PowerShell 7, narrow terminals, and redirected output.
- Do not expose operator tokens, request content, or credentials.

### Pending worktree defects to repair in Part 2.2

1. **Pending Fix 1 — `gateway.py` `handle_coordinator_status()` allowlist, recursive holder sanitization, and safe gaming status:**
   - **Allowlist restoration:** Add `"outcome"`, `"upstream_elapsed_seconds"`, `"upstream_timeout_seconds"`, `"timeout_semantics"`, `"lease_acquisition_timeout_seconds"`, `"model_load_reported_seconds"`, `"reconciliation_disposition"`, `"resolved_by"`, and `"resolved_at"` to `safe_request_detail_fields` in `gateway.py` (lines 629–649) so `GET /_coordinator/status` stops stripping the v0.12 diagnostic fields documented in `RESOURCE_MONITOR_CONTRACT.md`.
   - **Recursive inhibition holder sanitization:** Write a dedicated helper `_sanitize_inhibition_dict(raw_inhibition: Dict[str, Any], allowed_detail_keys: Set[str]) -> Dict[str, Any]` that:
     1. Copies top-level safe inhibition keys (`resource`, `reason`, `holder_id`, `inhibited_at`).
     2. Filters `details` to `allowed_detail_keys` plus safe structural keys (`maintenance_operation_id`, `restored_inhibited_at`, `snapshot_updated_at`, `persisted_at`, `phase`, `path`).
     3. **Preserves and recursively sanitizes `details["additional_uncertain_holders"]`:** Each item in `additional_uncertain_holders` is sanitized with `_sanitize_inhibition_dict()` so secondary inhibition holders (e.g., a second uncertain request or a concurrent maintenance hold) are never stripped or concealed from operators, while still ensuring no unallowlisted details leak.
     4. Uses the resulting `safe_inhibition` in both `recovery["inhibition"]` (line 659) and `gpu_inference["inhibition"]` (line 714).
   - **Safe, non-mutating `gaming` status:** Add a helper on `CoordinatorService` (or wrap `await svc.gaming_control("status")` in `handle_coordinator_status()`) that catches `(OSError, ValueError, RuntimeError)` when reading `StateCodec.load(path).gaming_mode` and returns `{"state": "unavailable", "status": "unavailable", "error": "Durable gaming state is unreadable"}` rather than raising an unhandled 500 error that breaks `GET /_coordinator/status`.
2. **Pending Fix 2 — Update `render_coordinator_status()` in `presentation.py`:**
   - Display `maintenance` state when `state != "idle"` (or summarize `Idle` / show full details under `rc status --all` and `rc status maintenance`).
   - Display `gaming` state when `state != "inactive"` (or in `rc status --all`), including a clear warning if `state == "unavailable"`.
   - When `gpu_inference.is_restart_inhibited` or `gpu_inference.recovery.required` is true, render the primary holder, any `additional_uncertain_holders` (count and holder IDs/reasons), and the unresolved request table (`request_id`, `phase`, `model`, `elapsed_seconds`, `failure_kind`, and `recommendation`) from `gpu_inference.recovery`.
3. **Pending Fix 3 — Fix `cmd_diagnose` (`rc telemetry`) ownership and rendering in `cli.py` and `presentation.py`:**
   - In `_async_diagnose()` (`cli.py` lines 552–558):
     - When `gateway_online` is true and `gateway_data.get("processes")` is present, extract the miner process status directly from `gateway_data["processes"]` (which reflects the running Coordinator's authoritative ownership) with `"ownership_verified": True`.
     - When the gateway is offline, inspect local process state via a properly closed temporary system (`try: ... finally: await system.gateway.close()`), and explicitly set `"ownership_verified": False` and `"ownership_note": "ownership_unverifiable_offline (Coordinator service unreachable)"` so offline telemetry never falsely claims that a running process is `unmanaged` or `external`.
   - Add `render_telemetry_result()` in `presentation.py` that renders a Rich table of GPUs (Device ID, Utilization %, VRAM Used / Total MiB, Power Draw W), CPU utilization %, Gateway status, and Managed Miner status (including the offline ownership caveat when applicable) instead of calling generic `render_result()`.
4. **Pending Fix 4 — Add dedicated human renderers for remaining commands using generic `render_result()`:**
   - `rc status inference` (`render_inference_status`)
   - `rc status maintenance` / `rc maintenance status` (`render_maintenance_status`)
   - `rc maintenance reconcile` (`render_maintenance_reconcile_result`)
   - `rc recover` read-only assessment and recovery results (`render_recovery_assessment`)
   - `rc system setup` / `rc system repair` / `rc system teardown` (`render_setup_result`)
   - `rc system preflight` and `rc system accept` (`render_preflight_result`, `render_acceptance_result`)

### JSON design

- Exactly one valid JSON document to stdout.
- No ANSI escapes, decorative banners, or progress messages in JSON mode.
- Stable field names and status enums; preserve existing JSON keys on legacy/existing commands.
- Version new public response schemas (`schema_version`).
- Include provenance, timestamp, evidence coverage, and reason codes where relevant.
- Errors remain parseable; diagnostics/logging go to stderr as appropriate.
- Non-JSON and JSON representations derive from the same structured result object.

## 2.3 Unified inference status

Create a read-only inference-status aggregator using existing RC data.

Proposed module:

`resource_coordinator/core/inference_status.py`

Inputs:

- Active/pending GPU leases.
- Inference and model-load request journal.
- Forwarded, terminal-verified, reconciled, and unresolved request phases.
- Restart-inhibition owners (including `additional_uncertain_holders`).
- Maintenance session status.
- Gaming state.
- Runtime identity and coverage information.
- Optional direct LM Studio runtime observations.

### Proposed execution classifications

- `active`
- `pending`
- `quiescent`
- `uncertain`
- `unavailable`

Separate `coverage` from state, using `complete`, `partial`, or `unknown`.

`quiescent` means that the covered operations are currently observed as inactive with no known unresolved operations. It must not be represented as unconditional proof that the physical GPU is idle.

The output should identify the exact requests and evidence gaps responsible for uncertainty.

Expose via `GET /_coordinator/inference/status` (and embed summary in `GET /_coordinator/status`) for `rc status inference` and `rc status --all`.

## 2.4 LM Studio activity adapter

Proposed module:

`resource_coordinator/monitors/lmstudio_activity.py`

Use a read-only, bounded adapter for LM Studio's model runtime processing state.

Candidate initial mechanism:

`lms ps --json --host <configured-instance>`

The documented CLI supports JSON model state (including generation and queue information) and remote-host selection (`--host`). See:

- https://lmstudio.ai/docs/cli/local-models/ps
- https://lmstudio.ai/docs/developer/api-changelog

### Mandatory no-wake and observational qualification

> [!WARNING]
> While official LM Studio documentation confirms that `lms ps --json` reports generation and queue status and supports `--host`, it does **not** guarantee that invoking `lms ps` will never start or wake an LM Studio backend/daemon. In light of earlier WSL/LM Studio auto-start investigations, the implementation agent must treat `lms ps` as **strictly observational** and must empirically verify its no-wake behavior before enabling subprocess invocation by default.

The implementation agent must test and enforce:

- **Pre-probe liveness guard:** Never invoke `lms ps` unless RC has already verified via a non-waking socket/HTTP check (or OS process table inspection) that the target LM Studio server instance is currently running, OR use LM Studio's direct REST endpoints (`/api/v1/models` / native status endpoints) when subprocess invocation cannot be proven non-waking.
- Installed CLI and LM Studio versions.
- Exact JSON fields and supported generation states.
- Queue counts and parallel prediction behavior.
- Correct target LM Studio instance (`--host`), distinguishing Windows vs. WSL instances.
- Bounded subprocess timeouts.
- Missing CLI, inaccessible endpoint, invalid JSON, unsupported fields, and partial results.
- Concurrent inference, streaming, prompt processing, model loading, embedding, cancellation, and timeout behavior.

Never infer unsupported states from empty lists or null values.

The adapter must not start/stop LM Studio, load/unload models, make inference requests, or alter configuration.

The CLI result is observational evidence, not an authoritative per-request completion receipt.

Provide a clean protocol/interface (`LMStudioActivityObserver`) so the safety engine never depends on a specific subprocess implementation.

## 2.5 Request storage and coverage

Keep RC's existing durable request journal as the safety source of truth.

Store only:

- Request/operation ID.
- Request type and model/runtime identity.
- Admission/dispatch/terminal phase (`RequestPhase`).
- Start/update/end timestamps.
- Terminal evidence, reconciliation disposition, and confidence.
- Related inhibition owner.
- Recovery disposition and audit details.

No prompt/response content or unnecessary telemetry should be stored in RC.

Use LLM Monitor for rich timing, tokens, hardware telemetry, dashboards, and long-term inference history.

Optional future correlation may connect an LLM Monitor request to its RC request ID, but Monitor must remain non-authoritative for miner restart safety.

Review journal growth and retention. Terminal, safely resolved records (`terminal_verified`, `reconciled`, `operator_resolved`) may have bounded retention (e.g., latest N records or bounded age); unresolved safety records (`reserved`, `possibly_forwarded`, `uncertain`) must **never** be pruned merely because they are old.

Audit all configured request routes, particularly `/v1/chat/completions`, `/v1/responses`, other inference endpoints, model loading, and direct LM Studio access. Record coverage gaps rather than assuming all traffic is intercepted.

## 2.6 Read-only recovery assessment and `no_action_required` semantics

Proposed module:

`resource_coordinator/core/recovery_assessment.py`

Implement the diagnosis engine that combines inference status with miner lifecycle, maintenance session state, and recovery state.

Include:

- RC readiness and terminal failure state.
- Interrupted host upgrade state (`upgrade-receipt.json` check so upgrade issues point to `rc system recovery`).
- Current active/pending GPU work and active recovery fences.
- Known unresolved requests and all inhibition holders (primary and `additional_uncertain_holders`).
- LM Studio observations and exact runtime identity.
- OS process inventory and configured miner identity.
- PID and process creation-time correlation.
- Owned/external/unmanaged process distinctions.
- Gaming/manual holds, cooldowns, and maintenance session ownership (`idle`, `acquiring`, `active`, `releasing`, `recovery_required`).
- Crash restart backoff and policy restrictions.
- Durable journal validity.
- Whether a safety hold is present and whether the system has sufficient evidence to reconcile it automatically.

### Five recovery classifications (separating healthy state from actionable recovery)

A healthy system with no active holds must **never** be classified as `auto_recoverable` (which would mislead automation, notifications, and operators into triggering no-op recovery mutations). Use five distinct classifications:

| Classification | Decision / Meaning | Recommended Exit Code (`rc recover` read-only) |
|---|---|---|
| `no_action_required` | No restart inhibition, no stuck maintenance session, no unresolved requests, and service is healthy (or miner is running/intentionally paused by user) | `0` |
| `auto_recoverable` | An active restart inhibition or unresolved request hold exists AND all required independent proof exists to clear it safely via `rc recover -a` | `0` (action available; `rc recover -a` will apply) |
| `wait` | Legitimate operation (active/pending inference, model load, active maintenance lease, or post-activity cooldown) is ongoing | `1` |
| `operator_required` | A safety hold (`gpu.inference` inhibition or `recovery_required` maintenance session) is active, and upstream termination, hardware restoration, or process ownership remains uncertain | `2` |
| `blocked` | Conflicting external work, corrupt durable state, failed/terminal service state, or offline service prevents safe recovery | `2` |

### Strict offline assessment guardrails

When the Coordinator HTTP service (`GET /_coordinator/recovery/assessment`) is unreachable:
- `rc recover` (read-only) may inspect the local durable state file (`coordinator_state.json`) and local `upgrade-receipt.json` for diagnostic reporting only.
- The offline assessment must set `service_reachable = False`, `assessment_mode = "offline_diagnostic_only"`, and `classification = "blocked"` (with reason code `"coordinator_service_unreachable"`).
- An offline snapshot **cannot** certify that the service or upstream runtime is idle, **must never** return `auto_recoverable` or `no_action_required`, and **must never** authorize `rc recover -a` or `rc recover -f`.

The read-only assessor (`rc recover` without `-a` or `-f`) must never clear holds, stop processes, or resume KRig.

## Part 2 acceptance criteria

- `rc` entry point, `1.0.0` version bump, and consolidated 12-command top-level CLI catalog coexist with all existing public commands and hidden compatibility aliases.
- Root `recover -r <resource> -n <reason>` and `service recover --resource <resource> -r <reason>` both work without value heuristics, and all existing tests in `tests/test_cli_architecture.py` pass without weakening compatibility assertions.
- `rc maintenance status` and `rc maintenance reconcile` provide a dedicated, contract-complete CLI for GPU maintenance sessions.
- Pending `v0.14.0` bugs in `gateway.py` (`safe_request_detail_fields`, recursive `additional_uncertain_holders` sanitization, non-mutating `gaming` status), `cli.py` (`_async_diagnose` ownership verification and gateway cleanup), `presentation.py` (`maintenance`, `recovery`, and `telemetry` rendering), and `installation.py` (`doctor` `0`/`1`/`2` exit codes) are repaired and covered by regression tests.
- Default output is polished, readable, and color-coded across all commands supporting `-j`.
- Every relevant JSON command passes formatting, redaction, and schema tests.
- `rc status` and `rc recover` display consolidated inference, maintenance, gaming, and recovery information, distinguishing `no_action_required` from `auto_recoverable`.
- Offline `rc recover` diagnostics are explicitly labeled `offline_diagnostic_only` and never authorize recovery.
- LM Studio runtime probes are bounded, read-only, non-waking, and instance-aware.
- Missing/ambiguous observations fail closed.
- No new mandatory dependency on LLM Monitor.
- No recovery mutation occurs in read-only `rc recover`.

**Checkpoint:** Compacted CLI, read-only diagnostics, and recovery classification validated, ready to support automatic reconciliation.

---

# Part 3 — Verified Automatic Recovery, Crash-Safe Startup Canonicalization, and Two-Stage Recovery Transaction

**Objective:** Eliminate repetitive manual diagnosis and recovery for cases that can actually be verified safe, while preserving strict protection and lock responsiveness for uncertain GPU operations.

## 3.1 Verified recovery endpoints and separation of concerns

Build a separate authenticated automatic-recovery endpoint instead of weakening the existing `/_coordinator/recover` operator-override endpoint or conflating inference recovery with maintenance release.

API distinction:

- `GET /_coordinator/recovery/assessment` — read-only comprehensive recovery assessment (`no_action_required`, `auto_recoverable`, `wait`, `operator_required`, `blocked`).
- `POST /_coordinator/recovery/auto` — independently verified two-stage automatic recovery for inference/request holds (`rc recover -a`). If no hold is active (`no_action_required`), returns HTTP 200 with `{"status": "no_action_required", "cleared_holders": []}` without mutating cooldowns or state.
- Existing `POST /_coordinator/recover` — explicit audited operator override for `gpu.inference` (`rc recover -f -n "reason"` / `rc service recover -f -r "reason"`), unchanged in authority.
- Existing `POST /_coordinator/maintenance/release` — explicit audited release or operator override for a `recovery_required` maintenance session (`rc maintenance reconcile -f -r "reason"`).

A caller flag requesting automatic recovery (`-a`) must never count as termination evidence.

## 3.2 Crash-safe startup reconciliation, reconciliation dispositions, and two-stage recovery transaction

### 3.2.1 Pending Bug Fixes in `durable_state.py`: Crash-safe startup inhibition canonicalization and `AccessDenied` propagation

Before implementing exact-holder automatic recovery, repair two defects in `resource_coordinator/core/durable_state.py`:

1. **Crash-safe startup inhibition canonicalization (`reconcile_startup_state`, lines 891–932):**
   - **Current defect:** Step 1 restores `state.inhibitions[resource]` with `holder_id="coord-..."` (and any `additional_uncertain_holders`), and Step 2 iterates over unresolved `state.requests` and calls `lease_manager.inhibit_restart(..., holder_id=f"crash_recovery:{req_id}")`. This creates a duplicate `"crash_recovery:<req_id>"` holder in memory that is not on disk, preventing `clear_inhibition_holder(resource, req_id)` from ever unblocking the resource. Furthermore, if a crash occurred after `record_request_phase(RESERVED)` but before `record_inhibition()`, the request hold was not persisted in `state.inhibitions`.
   - **Required atomic canonicalization sequence (`reconcile_startup_state`):**
     1. **Inspect and normalize persisted holders:** For each resource in `state.inhibitions`, inspect the primary `holder_id` and every entry in `details["additional_uncertain_holders"]`.
        - If any persisted holder has a legacy `crash_recovery:<req_id>` prefix where `<req_id>` corresponds to a known request ID (or `coord-` request prefix), normalize its `holder_id` to the canonical `<req_id>` while preserving its `reason`, `inhibited_at`, and `details` (recording `details["migrated_from_holder_id"] = "crash_recovery:<req_id>"`).
        - Preserve all non-request holders (such as `maintenance:<operation_id>`, operator abort holders, or genuine independent holds) untouched, deduplicating only exact `holder_id` matches on the same resource.
     2. **Construct complete canonical set of unique holds:** Scan `state.requests` for any request in `UNRESOLVED_PHASES` (`reserved`, `possibly_forwarded`, `uncertain`). Ensure each unresolved `req_id` is present as either the primary `holder_id` or an entry in `additional_uncertain_holders` for `req.resource` in `state.inhibitions`, using canonical `holder_id = req_id` (never `f"crash_recovery:{req_id}"`).
     3. **Persist canonicalized holds atomically before in-memory restoration:** If Step 1 or Step 2 modified `state.inhibitions` (e.g., added a missing unresolved request hold or normalized a legacy `crash_recovery:` holder), persist the updated `CoordinatorState` via `StateCodec.save_atomic(state, state_path)` **before** restoring holds into `LeaseManager`.
     4. **Restore single canonical set into `LeaseManager`:** For each resource in the canonicalized `state.inhibitions`, restore the primary holder and each entry in `additional_uncertain_holders` into `lease_manager.inhibit_restart(...)` so in-memory and on-disk holder lists are 1:1 identical.
     5. **Fail closed on incomplete persistence or restoration:** If loading, canonicalizing, saving to disk (`save_atomic`), or restoring into `LeaseManager` raises any exception, `CoordinatorService.start()` must refuse normal startup (`ServiceState.FAILED` / `RECONCILIATION_REQUIRED`) and latch `block_restarts()`.
   - **Mandatory failure-injection test requirement:** Add deterministic startup-reconciliation tests in `tests/test_durable_state.py` that:
     - Inject `OSError` / simulated crash at each persistence boundary (after `RESERVED` before `record_inhibition`, during `save_atomic` in startup canonicalization, and during `inhibit_restart`),
     - Repeat `reconcile_startup_state()` across multiple restarts, and
     - Verify idempotency: zero duplicate holders, preservation of unrelated holders (`maintenance:...`, second uncertain request), migration of legacy `crash_recovery:coord-...` snapshots, and exact unblock when all holders are cleared via `clear_inhibition_holder()`.
2. **Preserve `psutil.AccessDenied` in `_default_query` (`reconcile_startup_state`, lines 937–942):**
   - **Current defect:** `_default_query()` catches `(psutil.NoSuchProcess, psutil.AccessDenied)` and returns `None`, causing `reconcile_pid()` to return `ReconciliationOutcome.NOT_RUNNING` instead of `ReconciliationOutcome.ACCESS_DENIED`.
   - **Fix:** Catch only `psutil.NoSuchProcess` in `_default_query()` (returning `None`) and allow `psutil.AccessDenied` to propagate into `reconcile_pid()` where it is classified as `ReconciliationOutcome.ACCESS_DENIED`. In `CoordinatorService.start()`, verify that `ReconciliationOutcome.ACCESS_DENIED` is treated as an unverifiable/ambiguous process state that blocks normal startup rather than assuming the process is stopped.

### 3.2.2 Evidence-backed reconciliation dispositions (never falsifying `TERMINAL_VERIFIED`)

Automatic or operator recovery must never overwrite `RequestPhase` with `TERMINAL_VERIFIED` when HTTP protocol completion was not actually observed. Preserving the distinction between *"the HTTP response completed normally"* and *"the request failed/disconnected, and we later proved the upstream runtime stopped executing it"* is essential for post-incident diagnosis.

- **Extend `RequestPhase` and request details cleanly:**
  - Keep `RequestPhase.TERMINAL_VERIFIED = "terminal_verified"` strictly for requests whose protocol completion was directly verified by the gateway (`[DONE]` SSE sentinel or verified complete non-streaming HTTP response).
  - Keep `RequestPhase.OPERATOR_RESOLVED = "operator_resolved"` for manual operator overrides (`POST /_coordinator/recover`).
  - Add `RequestPhase.RECONCILED = "reconciled"` to `RequestPhase` in `durable_state.py` for requests resolved via verified automatic reconciliation (with backward-compatible deserialization so any unknown future resolved phase or v1.0 journal loads cleanly).
  - Record an explicit `details["reconciliation_disposition"]` enum on every resolved/terminal request:
    - `"protocol_terminal_verified"` — normal streaming/non-streaming completion verified by gateway (`phase == "terminal_verified"`).
    - `"not_forwarded_verified"` — request was in `RESERVED` phase (or failed prior to upstream dispatch with `forwarded == False`) and never reached the upstream runtime (`phase == "reconciled"`).
    - `"execution_termination_verified"` — request was forwarded (`POSSIBLY_FORWARDED` or `UNCERTAIN`), protocol completion was not observed, but RC independently proved that the upstream execution terminated (e.g., verified upstream runtime process exit/restart or verified post-disconnect stream drain completion) (`phase == "reconciled"`).
    - `"operator_resolved"` — resolved by explicit authenticated operator override without independent runtime proof (`phase == "operator_resolved"`).
  - None of `protocol_terminal_verified`, `not_forwarded_verified`, or `execution_termination_verified` may ever be inferred merely from a client timeout, empty queue, or idle GPU/model snapshot.

### 3.2.3 Two-stage server recovery transaction (`POST /_coordinator/recovery/auto`)

Holding `LeaseManager._condition` across slow or blocking OS process inspections and LM Studio probes would stall gateway admission, delay lease releases, and risk lock-order deadlocks.

Implement `POST /_coordinator/recovery/auto` as a **two-stage recovery transaction** with an in-memory recovery fence and state generation counter:

1. **LeaseManager state generation and recovery fence primitives (`leases.py`):**
   - Maintain a monotonic integer `self._state_generation: int = 0` on `LeaseManager` that increments under `self._condition` whenever any lease is reserved/promoted/released, any inhibition is added/modified/cleared, or any maintenance/recovery fence changes.
   - Maintain `self._gpu_recovery_fence: Optional[Dict[str, Any]] = None` (`{"fence_id": str, "holder_ids": list[str], "started_monotonic": float, "deadline_monotonic": float, "snapshot_generation": int}`).
   - While `self._gpu_recovery_fence` is active (and `monotonic_clock() < deadline_monotonic`), new GPU lease reservations (`reserve()`) wait or reject with a transient 503/conflict (or block promotion in `_promote_reservation()`), and manual miner/gaming mutations (`run_if_idle`) return `False` so no new GPU work can slip in while external observations are running.
2. **Stage 1 — Fence acquisition and snapshot (under `LeaseManager._condition`, non-blocking):**
   - Verify that the service is `READY` (or `RECONCILIATION_REQUIRED` due solely to the targeted inhibition), `maintenance_manager.state == "idle"`, `gpu_maintenance_owner is None`, and no active or pending GPU leases exist.
   - If another recovery fence is already active and not expired, reject with HTTP 409 (`"recovery_in_progress"`).
   - Load the durable journal snapshot, identify the targeted inhibition holder(s) on `resource` (`gpu.inference`), and record `snapshot_generation = self._state_generation`.
   - If no inhibition or unresolved request exists, return `{"status": "no_action_required"}` immediately without setting a fence.
   - Otherwise, set `self._gpu_recovery_fence` with a bounded TTL (`recovery_fence_timeout_seconds`, e.g., `10.0s`) and release `self._condition`.
3. **Stage 2 — Bounded external observations (lock released, fence active):**
   - Inside a `try ... finally` block (shielded on cleanup), perform bounded read-only observations using `asyncio.wait_for(..., timeout=...)`:
     - Re-verify unresolved request phases and evidence in `coordinator_state.json`.
     - Query OS process table (`reconcile_pid`) for managed miner and upstream runtime PIDs/creation times.
     - Query the bounded `LMStudioActivityObserver` when required by the evidence rule.
   - Determine which specific `holder_id`s have complete, authoritative proof of non-execution (`not_forwarded_verified` or `execution_termination_verified`).
4. **Stage 3 — Revalidation, durable commit, and holder clearing (reacquire `LeaseManager._condition`):**
   - Reacquire `self._condition`.
   - Verify that `self._gpu_recovery_fence` still belongs to this `fence_id`, has not expired, `self._state_generation == snapshot_generation`, no active/pending leases appeared, and the durable journal's `updated_at` / holder identities match the Stage 1 snapshot.
   - Verify that all gathered observations are fresh (observed after the request's last state transition and within `max_observation_age_seconds`).
   - Persist the exact `RequestPhase.RECONCILED` transition and `details["reconciliation_disposition"]` (`not_forwarded_verified` or `execution_termination_verified`), and clear **only** the verified `holder_id`(s) via `_remove_inhibition_holder` / `clear_inhibition_holder`.
   - Clear `self._gpu_recovery_fence = None` and `notify_all()`.
   - If all inhibitions on `gpu.inference` are now cleared (no remaining `additional_uncertain_holders`), start the normal post-activity cooldown and allow the existing RC supervisor to resume eligible Coordinator-owned miner operation.
5. **Failure, cancellation, timeout, and crash behavior of the recovery fence:**
   - **Cancellation or timeout during Stage 2:** The `finally` block reacquires `self._condition` under `anyio.CancelScope(shield=True)` (or `asyncio.shield`) and clears `self._gpu_recovery_fence`, leaving all durable and in-memory inhibitions intact (fail-closed).
   - **Deadline expiration safety net:** If a worker task hangs past `deadline_monotonic`, any subsequent `LeaseManager` operation checks `self._ monotonic_clock() >= fence["deadline_monotonic"]`, logs a warning, clears the expired in-memory fence, and keeps the restart inhibition latched.
   - **Service crash during recovery:** Because `self._gpu_recovery_fence` is purely in-memory and durable state is updated atomically in Stage 3 (`save_atomic`), a crash before Stage 3 `save_atomic` leaves the prior inhibition and unresolved request intact on disk; a crash after Stage 3 `save_atomic` leaves the reconciled state on disk.

### Evidence hierarchy

Automatic recovery may clear a holder **only** when the system can prove:

- **Case A (`not_forwarded_verified`):** The request was recorded in `RequestPhase.RESERVED` (or failed before upstream bytes were sent with `forwarded is False`), and no upstream request was ever dispatched for that `request_id`, OR
- **Case B (`execution_termination_verified` — post-disconnect stream completion):** The request was forwarded, downstream disconnected, and RC's own bounded upstream stream drain observed the authoritative protocol completion sentinel (`[DONE]` or `model_load.end`), OR
- **Case C (`execution_termination_verified` — runtime instance termination):** The request was forwarded to a known local LM Studio runtime process identity (`pid` + `create_time`), and RC independently verifies that the exact upstream runtime process has terminated (`NOT_RUNNING` or `PID_RECYCLED`) and no replacement runtime is executing that request, AND
- No other protected work or ineligible inhibition owner remains (or if another holder remains in `additional_uncertain_holders`, only the proven holder is removed while the remaining holder is promoted and continues inhibiting restart).

Insufficient evidence by itself (must **never** authorize automatic recovery of a `POSSIBLY_FORWARDED` or `UNCERTAIN` request):

- LM Studio currently reports idle (`lms ps` shows `idle` or `0` queued requests).
- GPU utilization is low.
- KRig is not running.
- The original HTTP request timed out.
- The client/agent disconnected.
- A telemetry recorder (LLM Monitor) marked the request failed/cancelled.
- The elapsed time exceeds an estimated generation duration.

These observations improve diagnosis in `rc recover`, but they cannot silently resolve a previously forwarded request because an idle poll cannot distinguish *"finished 100ms ago"* from *"never ran"* or *"paused between tool calls / model reload"* without request-specific or process-termination proof.

## 3.3 Reliable termination tracking

Reduce unnecessary recovery holds by improving how RC observes upstream completion.

Investigate and implement, where validated:

- Request-specific terminal protocol evidence.
- Bounded upstream-stream draining after downstream disconnect (currently gated by `bounded_drain_seconds` raising `ValueError` in `LMStudioGateway.__init__` until cancellation-safe draining is verified).
- Safe cancellation of operations with verified cancellation handles.
- Explicit differentiation between downstream cancellation and upstream execution termination.
- Durable transition from `UNCERTAIN` to `RECONCILED` (`reconciliation_disposition="execution_termination_verified"`) or `TERMINAL_VERIFIED` when later authoritative completion evidence arrives on the retained upstream stream during the bounded drain window.
- Recovery after RC restart without inventing terminal evidence.
- Model-load operation tracking separate from generation tracking.

Do not assume that closing an HTTP connection cancels GPU work.

The existing gateway already has `StreamCompletionDetector`, terminal verification, and uncertainty logic. Extend it carefully rather than introducing a second independent lifecycle engine.

Potentially intrusive stream-handling changes must be isolated and accompanied by cancellation, timeout, memory, shutdown, and concurrency tests.

If retaining the upstream connection is unsafe or unsupported for a route, document the limitation and retain the uncertain state.

## 3.4 Miner restoration

Recovery should normally finish the operational lifecycle, not merely clear an inhibition.

After a verified reconciliation:

- Respect cooldowns and restart policy.
- Restore only through the existing RC-controlled supervisor.
- Preserve intentional manual stops and gaming holds.
- Preserve crash-backoff limits.
- Never adopt or terminate an externally owned miner implicitly.
- Distinguish restart eligibility from actual restart completion.
- Report final PID, creation time, ownership, and reason if still stopped.

No separate direct KRig launcher should be used.

A legitimate miner crash without uncertain LM Studio activity should follow the existing supervised crash policy. Automatic recovery must not defeat the crash retry budget.

## 3.5 Fault injection and safety tests

Required simulated cases:

- Healthy system with no holds returns `no_action_required` (and `POST /_coordinator/recovery/auto` is a safe no-op).
- Verified terminal request followed by a stale inhibition.
- Persistently verified not-forwarded (`RESERVED`) request recovered after coordinator restart (`reconciliation_disposition="not_forwarded_verified"`), verifying no phantom `crash_recovery:` holder remains.
- Deterministic startup-reconciliation failure injection at every persistence boundary (crash before `record_inhibition`, crash during startup `save_atomic`, repeated startup with legacy `crash_recovery:coord-...` holders, and preservation of unrelated `additional_uncertain_holders`).
- Pending inference or model load arriving during Stage 2 of the two-stage recovery transaction (verifying the recovery fence blocks conflicting admission and Stage 3 aborts if generation changed).
- Slow/hanging external observation in Stage 2 (verifying `LeaseManager._condition` is **not** held during Stage 2, timeout cleans up `_gpu_recovery_fence`, and inhibitions remain latched).
- Timed-out forwarded operation with unknown termination (`operator_required`).
- Active generation despite no downstream client (and bounded post-disconnect drain completion vs. drain timeout).
- Unavailable or malformed LM Studio activity response.
- Wrong LM Studio instance.
- Model idle (`lms ps` reports idle) but unresolved `POSSIBLY_FORWARDED` / `UNCERTAIN` request (must remain `operator_required`, never `auto_recoverable`).
- External miner or mismatched PID/create time, plus `psutil.AccessDenied` during startup PID reconciliation (`ReconciliationOutcome.ACCESS_DENIED`).
- Manual pause and gaming hold.
- Active maintenance session (`wait`) or `recovery_required` maintenance session (verifying `rc recover -a` refuses to clear maintenance holds while `rc maintenance reconcile -f -r "..."` verifies session/operation identity and performs audited maintenance release).
- Multiple inhibition holders (`additional_uncertain_holders`), only one eligible (verifying exact removal of the eligible holder and promotion of the remaining holder).
- Service crash between Stage 2 observation and Stage 3 journal commit.
- Journal corruption or persistence failure.
- Offline CLI recovery assessment (`service_reachable=False`) refusing `-a` and `-f`.
- Repeated recovery request/idempotency.
- Post-release cooldown and delayed restart.
- Failed or exhausted miner restart.
- Legacy operator override paths (`rc recover -r gpu.inference -n "reason"` and `rc service recover --resource gpu.inference -r "reason"`) remain independent and functional.

For every important failure, assert durable state, active lease state, recovery fence state, restart inhibition, process state, and audit outcome—not merely the error response.

Use injected clocks, fake processes, simulated LM Studio state, and isolated filesystem state.

## 3.6 Readiness separation

Maintain independent capability flags for:

- Safe inference-state observation.
- Complete request-path coverage.
- Verified termination mechanisms.
- Recovery mutation eligibility.
- Independent GPU maintenance restoration verification.

Automatic inference recovery approval must not be used to approve Mining optimizer restoration.

Likewise, the maintenance verifier's lack of actual RTX 5090 attribution qualification must not be hidden by a healthy LM Studio inference report.

## Part 3 acceptance criteria

- Crash-safe startup canonicalization and `AccessDenied` fixes in `durable_state.py` pass unit and boundary failure-injection tests.
- Two-stage recovery transaction (`POST /_coordinator/recovery/auto` / `rc recover -a`) releases the arbitration lock during external probes while fencing conflicting GPU admission.
- Reconciled requests record `RequestPhase.RECONCILED` with accurate `reconciliation_disposition` (`not_forwarded_verified` vs. `execution_termination_verified`), never falsifying `TERMINAL_VERIFIED`.
- No automatic recovery based solely on idle snapshots.
- Exact-holder inhibition clearing is race-safe and durable across coordinator restarts.
- Unrelated holds (`additional_uncertain_holders`, maintenance holds) survive.
- Stale sessions and incorrect process identities cannot authorize recovery.
- Valid recoveries allow normal miner restoration.
- Uncertain cases remain blocked and produce actionable explanations.
- Existing operator overrides (`rc recover -f -n` / `rc service recover -f -r` for inference and `rc maintenance reconcile -f -r` for maintenance) remain functional, explicit, and audited.
- The new recovery operation is not enabled unattended until operational qualification.

**Checkpoint:** Verified recovery mechanism implemented and tested offline.

---

# Part 4 — Windows Qualification, Controlled Live Acceptance, and Unattended Operations

**Objective:** Finish the original H4/H5/H6 roadmap while qualifying the new diagnostic/recovery features for actual deployment.

**Scheduling:** H4 readiness investigation may begin after Part 1 and run in parallel with Parts 2–3 using isolated work ownership. The original controlled live optimizer milestone must not be artificially blocked by optional CLI improvements if its own independent safety gates are satisfied. Unattended auto-recovery, however, requires Parts 2–3 and separate operational acceptance.

## 4.1 Windows installation and upgrade acceptance — Original H4

Reconcile the historical Windows RC upgrade problems, including:

- `WinError 206` and Windows command-line/task-length handling.
- Task Scheduler task definitions and relaunch behavior.
- Logon versus SYSTEM identity, token-file ACL, and credential discovery.
- Service instance/version identity (`1.0.0`).
- Actual launcher source checkout and configured executable (including `rc` entry-point wrapper generation via `python setup.py`).
- Graceful service restart and shutdown.
- Process group/descendant ownership.
- Crash and unclean shutdown recovery.
- Persistent journal/state migrations (`RequestPhase.RECONCILED` and canonical holder IDs).
- No second unowned Coordinator or independent KRig launcher.
- Rollback to the previous working installed version.

Check whether the existing mainline upgrade-reliability work already resolves each issue. Do not replay old feature branches without verifying the current code and real Windows evidence.

Installation mutation requires separate approval.

## 4.2 Hardware and LM Studio qualification — Original H4

Perform independently verified, initially read-only capability assessment on the actual Windows host.

### GPU qualification

Verify on the installed RTX 5090 and driver:

- Exact GPU UUID and PCI identity.
- NVML access.
- Power-limit readback.
- Graphics and memory offset readback.
- GPU-process attribution completeness under Windows/WDDM.
- Known-miner process inventory completeness.
- Whether the required `power_offsets` scope can be independently verified.
- Observer timeout and access-denied behavior.

Do not enable `gpu_process_attribution_confirmed` without evidence.

If capabilities are incomplete, leave automatic trusted maintenance release disabled and preserve audited operator reconciliation (`rc maintenance reconcile -f -r "..."`).

Fixed/locked-clock optimizer modes remain unsupported for automatic trusted release until their independent restoration contract is separately implemented and validated.

### LM Studio qualification

Verify:

- Exact installed LM Studio and `lms` versions.
- Bound runtime instance/host.
- Generation and queue status semantics (`lms ps --json --host`).
- Empirical verification of whether `lms ps` can start or wake a stopped LM Studio backend/daemon on Windows or WSL.
- Direct inference clients and routing coverage.
- OpenCode/Codex/AGY effective runtime endpoints where relevant.
- Windows and WSL LM Studio instances and possible duplicate ownership.
- Interaction with existing WSL startup and model-autoload behavior.
- LM Studio/KRig GPU memory headroom.

Do not restart WSL, load models, or mutate live runtime state merely to gather observational evidence.

An existing WP04-style failure investigation should remain independent until its evidence is preserved. Do not clear its inhibition or restart mining simply because this roadmap exists.

## 4.3 Controlled live optimizer acceptance — Original H5

After source integration, necessary Windows readiness, hardware capability review, and explicit live authorization:

1. Pin exact running software and configuration versions.
2. Verify no competing miner, watchdog, task, or uncoordinated GPU client.
3. Check live RC, LM Studio, miner, and GPU baseline.
4. Validate the intended maintenance/recovery path on this hardware.
5. Run only the authorized bounded live experiment.
6. Exercise acquisition, miner stop, GPU tuning, registered child execution, restoration, and release.
7. Observe cooldown and actual supervisor resumption.
8. Stop on the first failure, unexpected process, timeout, ownership uncertainty, or verification gap.
9. Preserve complete diagnostic evidence.
10. Return to a known safe state using the approved operator procedure.

The initial supervised RC inference acceptance and the first live optimizer run are distinct experiments; neither automatically authorizes the other.

Do not expand to longer sweeps or multiple miners until the initial bounded test is accepted.

## 4.4 Notifications and watchdog — Original H6

Once read-only assessments and recovery mechanisms are validated, integrate them with the existing notification/remote-control workflow.

Event-driven behavior should prioritize:

- Miner crash requiring intervention.
- Persistent inference uncertainty.
- Automatic recovery attempted/completed (never firing on `no_action_required`).
- Automatic recovery blocked with exact reason codes.
- Maintenance lease loss or `recovery_required` transition.
- Unsupported GPU verification capability.
- Service restart/recovery-required state.
- Repeated failure/backoff exhaustion.

Keep notifications compact and actionable.

Example desired notification:

> Resource Coordinator: automatic miner recovery blocked. No active gateway requests, but one previously forwarded LM Studio request lacks verified termination. Miner remains stopped; GPU restart inhibition preserved. Review request `coord-...` using `rc recover`.

The notification should include the relevant status command and safe operator action, not a list of unrelated manual process-inspection commands.

Use event IDs, deduplication, rate limits, and persistence to prevent alert storms.

Integrate with already active notification services (`modules/notifications`) rather than building another competing notification server.

## 4.5 Optional unattended reconciliation

After explicit operational acceptance, enable an opt-in policy that periodically or eventfully evaluates recovery eligibility.

Requirements:

- Disabled by default.
- Minimum backoff and bounded retry policy.
- No polling storm.
- Independent current evidence on each attempt.
- Idempotent state transitions (`no_action_required` produces zero writes/events).
- Complete audit trail.
- No unsafe inference admission race (uses the two-stage recovery transaction).
- No forced miner termination.
- No bypass of maintenance restoration or manual controls.
- Automatic notification when intervention is required.
- Operator-configurable disable/rollback.
- Clear metrics for successful recovery, blocked recovery, unnecessary interventions, and unresolved holds.

The automatic policy should perform verified operations only; it must not simply invoke the legacy `--force` recovery command.

## 4.6 Final acceptance and rollout

Success requires demonstrated behavior across three distinct boundaries:

**Offline source validation**

- Full relevant regression suites pass.
- Cross-repository tests pass.
- Recovery safety invariants and boundary failure-injection tests pass.
- CLI output, legacy flag compatibility, and JSON compatibility pass.

**Windows/host qualification**

- Correct installed and running version (`1.0.0`).
- Verified process and startup ownership.
- Qualified supported hardware observations.
- Reproducible upgrade/rollback.
- No independent restart source bypasses RC.

**Live operational acceptance**

- Explicitly authorized test succeeds.
- No inference/miner overlap violating admission rules.
- Hardware baseline restored and independently checked where supported.
- Correct miner lifecycle and cooldown behavior.
- Uncertain operations remain inhibited.
- Recovery and notification behavior are auditable.
- Unattended behavior is enabled only for validated evidence classes.

**Final checkpoint:** RC operates as a reliable local GPU control plane, with consolidated `rc` CLI and status, guarded two-stage recovery, dedicated maintenance reconciliation, integrated Mining maintenance, controlled Windows deployment, and optional unattended incident handling.

---

## Cross-part implementation dependencies

| Component | Depends on | Can proceed in parallel? |
|---|---|---|
| H3 simulated acceptance | Existing H2 candidates | Already assigned |
| Part 1 source integration | H3 validated results | No; follow H3 |
| Part 2 CLI compaction (`1.0.0`), `rc maintenance`, inference/maintenance status, and pending worktree bug fixes | Stable RC source baseline | Yes, alongside Windows read-only readiness |
| Part 3 two-stage recovery engine, reconciliation dispositions, and `durable_state.py` startup fixes | Part 2 evidence interfaces | `durable_state.py` bug fixes and reliability research/tests may start immediately in Part 2/3 |
| H4 Windows upgrade qualification | Validated integrated source | Yes, after Part 1 |
| H5 controlled live optimizer | H3/source integration, hardware and deployment gates, explicit authorization | Does not require unattended auto-recovery |
| H6 notifications/unattended automation | Part 3 recovery and host capability acceptance | Notification UI may be prepared earlier |

## Global engineering requirements

All implementation parts must preserve:

- Backward-compatible commands (including root `recover -r <resource> -n <reason>` and `service recover --resource <resource> -r <reason>`), public APIs, state schemas, and user configuration.
- Short and long flags for all user-facing CLI arguments (`REPO_LLM_INSTRUCTIONS.md`), except where long-only `--resource` on `service recover` is required to preserve `-r/--reason` compatibility.
- Synchronized `pyproject.toml` and `resource_coordinator.__version__` (`1.0.0`) versions, plus registration in `modules/scripts_help/scripts_help/registry/registry.py`.
- Atomic, recoverable durable writes and crash-safe startup inhibition canonicalization.
- Non-blocking two-stage recovery transactions that never hold the main arbitration lock across external process/runtime probes.
- Distinct reconciliation dispositions (`protocol_terminal_verified`, `not_forwarded_verified`, `execution_termination_verified`, `operator_resolved`).
- Explicit identity and ownership verification (including labeling offline telemetry as `ownership_unverifiable_offline` and offline recovery assessments as `offline_diagnostic_only`).
- Read-only and dry-run defaults.
- Authorization boundaries for mutations.
- No accidental live LM Studio daemon startup from probes.
- No unqualified GPU safety claims.
- Fail-closed operation on incomplete evidence.
- Complete and readable human output (no generic `"N structured items (see --json)"` dumps).
- Stable and clean JSON output.
- Windows 11/PowerShell 7 compatibility.
- Isolated, deterministic test environments using `--basetemp=modules/resource_coordinator/.pytest_tmp_root/...`.
- No secret or transcript leakage into general diagnostics (including recursive sanitization of `additional_uncertain_holders`).
- No conflicting remote/local Git edits, and explicit transfer/commit of this roadmap before switching worktrees.
- No live test or deployment without specific approval.

## Required evidence from every implementation part

Each completing agent should report:

- Starting repository, branch, worktree, dirty state, and pinned dependencies.
- Exact work performed and files modified.
- Architectural decisions or deviations.
- Executed validation commands and exit codes.
- Test counts, skips, deselections, and failures.
- Platform/runtime and test import provenance.
- Confirmed defects versus hypotheses.
- Safety and failure-injection evidence.
- Final commit and push status.
- Outstanding blockers.
- Recommendation for the next dependency-ready phase.

Do not create new assignments solely to generate more handoffs. When work is complete and integrated, advance to the next genuinely required gate.

## Primary references

**Resource Coordinator**

- [RC maintenance contract](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/docs/MAINTENANCE_SESSIONS.md)
- [RC CLI parser](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/cli_parser.py)
- [RC CLI dispatch](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/cli_dispatch.py)
- [RC CLI presentation](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/presentation.py)
- [RC gateway](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/adapters/lmstudio/gateway.py)
- [RC durable state](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/core/durable_state.py)
- [RC maintenance manager](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/core/maintenance.py)
- [RC trusted restoration verification](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/core/restoration.py)
- [RC H2C status](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/docs/plans/20261111-restoration-verification/STATUS.md)

**Mining**

- [Mining H2D status](https://github.com/MaxCarlson/Mining/blob/4787f9bac06d811ca82a8a3752a61c69f181aafb/docs/plans/20261111-h2d-rc-v014-compat/STATUS.md)

**LM Studio and monitoring**

- [LM Studio `lms ps`](https://lmstudio.ai/docs/cli/local-models/ps)
- [LM Studio API changelog](https://lmstudio.ai/docs/developer/api-changelog)
- [LM Studio REST API](https://lmstudio.ai/docs/developer/rest)
- [LLM Monitor gateway](https://github.com/MaxCarlson/scripts/blob/main/modules/llm_monitor/llm_monitor/gateway.py)
- [LLM Monitor SQLite telemetry store](https://github.com/MaxCarlson/scripts/blob/main/modules/llm_monitor/llm_monitor/storage.py)

## Immediate next action

Allow the current H3 agent to finish its assigned simulated cross-repository acceptance.

Ensure this `MASTER_IMPLEMENTATION_PLAN_V3.md` is preserved (committed or copied into the active integration branch) before switching or creating worktrees, then reconcile the H3 report and repository checkpoint against this v3 document and initiate **Part 1's integration review**.

After the validated source baseline exists, initiate Part 2's CLI compaction (`1.0.0`), pending worktree bug fixes, and inference/maintenance-status implementation, and independently continue the original Windows readiness gates.

The resulting workflow should require operator intervention only when a decision genuinely cannot be established from independent evidence or when explicit authority is required for a consequential live action.
