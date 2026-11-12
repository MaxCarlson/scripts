# Resource Coordinator — Consolidated Implementation Roadmap

**Date:** November 11, 2026  
**Repositories:** `MaxCarlson/scripts`, `MaxCarlson/Mining`  
**Scope:** Resource Coordinator maintenance integration, CLI modernization, local inference observability, evidence-based recovery, Windows deployment, and controlled live acceptance  
**Status:** Master implementation plan — execute after verifying the current H3 agent's results and repository state

---

## Executive summary

The objective is to evolve Resource Coordinator (RC) from a safe but sometimes manually operated GPU arbitration system into an observable, maintainable, and increasingly autonomous control plane.

The desired end state is:

- One command provides an understandable view of RC, KRig, LM Studio, active inference, and recovery blockers.
- All significant commands support polished, color-coded human output and stable machine-readable JSON.
- RC determines whether requests are active, pending, completed, or uncertain using its own authoritative state and independent runtime observations.
- RC evaluates whether recovery is justified without requiring the operator to inspect process listings or manually interpret multiple command outputs.
- When independently verified safe, RC reconciles a stale inhibition and permits normal Coordinator-managed miner restoration.
- When safety cannot be established, RC preserves protections, explains the precise uncertainty, and optionally sends an actionable notification.
- Existing GPU maintenance integration and Mining optimizer work reach source integration, Windows hardware qualification, and authorized controlled live acceptance.
- The design avoids introducing LLM Monitor as a mandatory dependency of RC safety decisions.

**Key architectural rule:** RC owns GPU admission, maintenance, process lifecycle, and minimal durable safety state. LLM Monitor owns detailed inference telemetry and historical analysis. LM Studio provides runtime observations where supported.

**Critical safety distinction:** A model reporting idle, a missing miner process, or zero active gateway requests is not sufficient by itself to prove that an interrupted upstream operation has terminated.

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
| New work — CLI, inference status, and automated recovery | Planned here | Parts 2 and 3 |

The current status of an agent process cannot be established from GitHub alone. Before taking ownership, inspect the agent's actual report, working tree, and published checkpoint. Do not duplicate H3 while it remains active.

### Repository references

**Resource Coordinator**

- Repository: `MaxCarlson/scripts`
- Candidate branch: `agent/resource-coordinator-v013-integration-restoration-20261111`
- Pinned candidate: `737bc6b2db7b68c041abffb66017164f3c883228`
- Package: RC v0.14.0
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
2. Reconcile the RC candidate with current `scripts/main` using a safe integration branch.
3. Confirm that newer unrelated modules and active agent work are preserved.
4. Rerun the RC maintenance, restoration, lifecycle, CLI, gateway, installation, and relevant regression suites.
5. Integrate the validated Mining candidate into its own mainline through an independently reviewed change.
6. Revalidate the pinned cross-repository contracts against the integrated source commits.
7. Preserve historical H2/H3 status reports and update the handoff indexes.

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

# Part 2 — Simplified CLI, Unified Status, and Inference Visibility

**Objective:** Make the Coordinator understandable to humans and agents through one consistent command system.

This part combines CLI modernization, unified inference status, LM Studio runtime observation, and the initial read-only recovery assessor.

## 2.1 Canonical CLI design

Provide a short `rc` launcher or alias after verifying that the name does not collide with another installed command or script.

Keep `resource-coordinator` fully functional.

### Proposed canonical commands

| Command | Function |
|---|---|
| `rc status` | Unified system overview |
| `rc status -j` | Structured system overview |
| `rc status miner` | Detailed miner lifecycle, ownership and restart state |
| `rc status inference` | Local inference activity, pending operations and uncertainty |
| `rc status gaming` | Gaming-mode state |
| `rc status --all` | Expanded human-readable diagnostic snapshot |
| `rc doctor` | Health, installation, configuration and runtime diagnostics |
| `rc telemetry` | CPU/GPU and related telemetry |
| `rc miner start` | Coordinator-managed start |
| `rc miner stop` | Coordinator-managed stop |
| `rc miner pause` | Existing timed and GPU-idle pause semantics |
| `rc miner resume` | Existing guarded resume |
| `rc recover` | Read-only comprehensive recovery assessment |
| `rc recover -j` | Machine-readable assessment and recommended actions |
| `rc recover -a` | Apply only independently verified recovery |
| `rc recover -f -r "reason"` | Existing authenticated, audited operator override |
| `rc logs miner` | Miner log inspection |
| `rc help` | Discoverable command catalog and examples |

Where useful, preserve compatibility aliases such as `rc check inference`, `resource-coordinator control miner status`, and `resource-coordinator service recover`.

The existing command structure should be treated as a compatibility interface, not deleted.

### Compatibility requirements

- Preserve current public functions, operational semantics, and established successful command behavior.
- Preserve existing JSON schemas on old commands.
- New canonical commands may use versioned, richer schemas.
- Do not silently change the meaning of `-f/--force` or `-a/--apply`.
- Do not combine an operator override with an independently verified automatic-recovery mode.
- Preserve explicit `-r/--reason`, `-j/--json`, and other existing switches.
- Add short forms alongside long flags where not conflicting.
- Centralize command definitions, alias resolution, help, argument validation, and dispatch.
- Keep CLI errors actionable and use meaningful exit codes.

The existing `cli_parser.py`, `cli_dispatch.py`, and handler mapping should be extended/refactored rather than duplicated.

## 2.2 Mandatory human-readable presentation

Every command exposing `-j/--json` must also provide an intentional, polished default presentation.

### Presentation design

- Rich tables and aligned fields, with consistent headings and spacing.
- Green: verified healthy/successful.
- Yellow: pending, waiting, or uncertain.
- Red: failed, blocked, or unsafe.
- Cyan/blue: neutral informational values.
- Summary and important blockers first; verbose evidence afterward.
- Distinguish observed facts from inferred conclusions.
- Clearly explain what needs intervention.
- Hide irrelevant empty sections without hiding uncertainty.
- Do not overwhelm default output with raw internal structures.
- Respect `--color auto|always|never` and `NO_COLOR`.
- Remain readable in Windows Terminal, PowerShell 7, narrow terminals, and redirected output.
- Do not expose operator tokens, request content, or credentials.

### JSON design

- Exactly one valid JSON document to stdout.
- No ANSI escapes, decorative banners, or progress messages in JSON mode.
- Stable field names and status enums.
- Version new public response schemas.
- Include provenance, timestamp, evidence coverage and reason codes where relevant.
- Errors remain parseable; diagnostics/logging go to stderr as appropriate.
- Non-JSON and JSON representations derive from the same structured result object.

### Output audit

Inventory every existing command with `-j`.

Prioritize:

- `status`
- Miner status/control results
- Inference status
- Recovery assessment/results
- Gaming status
- Health/doctor
- Telemetry
- Installation and startup status
- Configuration validation
- System upgrade/reconciliation status

Add formatting tests for normal, waiting, uncertain, blocked, error, and unavailable states, plus JSON compatibility and redaction.

Do not regress presentation that is already well implemented. Reuse the existing `presentation.py` utilities.

## 2.3 Unified inference status

Create a read-only inference-status aggregator using existing RC data.

Proposed module:

`resource_coordinator/core/inference_status.py`

Inputs:

- Active/pending GPU leases.
- Inference and model-load request journal.
- Forwarded, terminal-verified, and unresolved request phases.
- Restart-inhibition owners.
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

## 2.4 LM Studio activity adapter

Proposed module:

`resource_coordinator/monitors/lmstudio_activity.py`

Use a read-only, bounded adapter for LM Studio's model runtime processing state.

Candidate initial mechanism:

`lms ps --json --host <configured-instance>`

The documented CLI supports JSON model state and remote-host selection. See:

- https://lmstudio.ai/docs/cli/local-models/ps
- https://lmstudio.ai/docs/developer/api-changelog

### Qualification before relying on observations

The implementation agent must test:

- Installed CLI and LM Studio versions.
- Exact JSON fields and supported generation states.
- Queue counts and parallel prediction behavior.
- Correct target LM Studio instance.
- Windows versus WSL service selection.
- Read-only behavior and whether CLI invocation can wake/start a daemon.
- Bounded subprocess timeouts.
- Missing CLI, inaccessible endpoint, invalid JSON, unsupported fields, and partial results.
- Concurrent inference, streaming, prompt processing, model loading, embedding, cancellation, and timeout behavior.

Never infer unsupported states from empty lists or null values.

The adapter must not start/stop LM Studio, load/unload models, make inference requests, or alter configuration.

The CLI result is observational evidence, not an authoritative per-request completion receipt.

If direct SDK observation proves safer and more reliable, use a replaceable adapter interface; do not make the safety engine depend on a specific subprocess implementation.

## 2.5 Request storage and coverage

Keep RC's existing durable request journal as the safety source of truth.

Store only:

- Request/operation ID.
- Request type and model/runtime identity.
- Admission/dispatch/terminal phase.
- Start/update/end timestamps.
- Terminal evidence and confidence.
- Related inhibition owner.
- Recovery disposition and audit details.

No prompt/response content or unnecessary telemetry should be stored in RC.

Use LLM Monitor for rich timing, tokens, hardware telemetry, dashboards, and long-term inference history.

Optional future correlation may connect an LLM Monitor request to its RC request ID, but Monitor must remain non-authoritative for miner restart safety.

Review journal growth and retention. Terminal, safely resolved records may have bounded retention; unresolved safety records must not be pruned merely because they are old.

Audit all configured request routes, particularly `/v1/chat/completions`, `/v1/responses`, other inference endpoints, model loading, and direct LM Studio access. Record coverage gaps rather than assuming all traffic is intercepted.

## 2.6 Read-only recovery assessment

Proposed module:

`resource_coordinator/core/recovery_assessment.py`

Implement the diagnosis engine that combines inference status with miner lifecycle and recovery state.

Include:

- RC readiness and terminal failure state.
- Current active/pending GPU work.
- Known unresolved requests and inhibition holders.
- LM Studio observations and exact runtime identity.
- OS process inventory and configured miner identity.
- PID and process creation-time correlation.
- Owned/external/unmanaged process distinctions.
- Gaming/manual holds, cooldowns, maintenance ownership.
- Crash restart backoff and policy restrictions.
- Durable journal validity.
- Whether the system has sufficient evidence to reconcile automatically.

Use four recovery classifications:

| Classification | Decision |
|---|---|
| `auto_recoverable` | All required proof exists |
| `wait` | Legitimate operation or cooldown is ongoing |
| `operator_required` | Termination or ownership remains uncertain |
| `blocked` | Conflicting work, failed service state, or unsafe condition |

Create a read-only assessment API and `rc recover` presentation, with explicit reason codes and recommended actions.

The assessor must not clear holds, stop processes, or resume KRig.

## Part 2 acceptance criteria

- New CLI aliases coexist with all existing public commands.
- Default output is polished, readable and color-coded.
- Every relevant JSON command passes formatting and schema tests.
- One command displays consolidated inference and recovery information.
- LM Studio runtime probes are bounded, read-only, and instance-aware.
- Missing/ambiguous observations fail closed.
- No new mandatory dependency on LLM Monitor.
- No recovery mutation occurs in this part.

**Checkpoint:** Read-only diagnostics and recovery classification validated, ready to support automatic reconciliation.

---

# Part 3 — Verified Automatic Recovery and Reliable Completion Evidence

**Objective:** Eliminate repetitive manual diagnosis and recovery for cases that can actually be verified safe, while preserving strict protection for uncertain GPU operations.

## 3.1 Verified recovery operation

Build a separate authenticated recovery operation instead of weakening the existing `/_coordinator/recover` operator-override endpoint.

Proposed API distinction:

- `GET /_coordinator/recovery/assessment` — read-only.
- `POST /_coordinator/recovery/auto` — independently verified recovery.
- Existing `POST /_coordinator/recover` — explicit audited override, unchanged in authority.

These are proposed interfaces, not current routes. Final endpoint naming should be checked for consistency before publishing.

`rc recover -a` should request the verified path.

A caller flag requesting automatic recovery must never count as termination evidence.

## 3.2 Atomic recovery workflow

At the server:

1. Identify the exact targeted inhibition and request/operation owner.
2. Establish a serialized admission/recovery boundary.
3. Prevent conflicting new GPU work during the final check.
4. Verify active/pending leases and outstanding model-load operations.
5. Verify maintenance, gaming, manual-pause, service and crash-backoff states.
6. Inspect independently observed process and LM Studio runtime state.
7. Require authoritative termination proof for previously forwarded uncertain operations.
8. Re-read durable state and validate the exact holder/session identity.
9. Persist the recovery disposition and clear only the eligible inhibition holder.
10. Apply the normal cooldown.
11. Allow the existing RC supervisor to resume eligible Coordinator-owned miner operation.
12. Verify and report the resulting state.

A previous CLI assessment snapshot must never authorize a later recovery without fresh server-side checks.

### Evidence hierarchy

Automatic recovery may be possible when the system can prove:

- The relevant request was never forwarded.
- The exact operation reached an independently verified terminal state.
- The associated upstream runtime definitively terminated and the required process/instance identity and coverage guarantees are satisfied.
- No other protected work or inhibition owner remains.

Insufficient evidence by itself:

- LM Studio currently reports idle.
- The model queue is empty.
- GPU utilization is low.
- KRig is not running.
- The original HTTP request timed out.
- The agent stopped responding.
- A telemetry recorder marked the request failed/cancelled.
- The elapsed time exceeds an estimated generation duration.

These observations improve diagnosis, but they cannot silently resolve a previously forwarded request.

## 3.3 Reliable termination tracking

Reduce unnecessary recovery holds by improving how RC observes upstream completion.

Investigate and implement, where validated:

- Request-specific terminal protocol evidence.
- Bounded upstream-stream draining after downstream disconnect.
- Safe cancellation of operations with verified cancellation handles.
- Explicit differentiation between downstream cancellation and upstream execution termination.
- Durable transition from uncertain to terminal-verified when later authoritative evidence arrives.
- Recovery after RC restart without inventing terminal evidence.
- Model-load operation tracking separate from generation tracking.

Do not assume that closing an HTTP connection cancels GPU work.

The existing gateway already has terminal verification and uncertainty logic. Extend it carefully rather than introducing a second independent lifecycle engine.

Potentially intrusive stream-handling changes must be isolated and accompanied by cancellation, timeout, memory, shutdown and concurrency tests.

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

- Verified terminal request followed by a stale inhibition.
- Persistently verified not-forwarded request.
- Pending inference or model load.
- Timed-out forwarded operation with unknown termination.
- Active generation despite no downstream client.
- Unavailable or malformed LM Studio activity response.
- Wrong LM Studio instance.
- Model idle but unresolved request.
- External miner or mismatched PID/create time.
- Manual pause and gaming hold.
- Active maintenance session or recovery-required maintenance.
- Multiple inhibition holders, only one eligible.
- Concurrent inference arriving during recovery.
- Service crash between decision and journal commit.
- Journal corruption or persistence failure.
- Ambiguous recovery HTTP response.
- Repeated recovery request/idempotency.
- Post-release cooldown and delayed restart.
- Failed or exhausted miner restart.
- Operator override path remains independent.

For every important failure, assert durable state, active lease state, restart inhibition, process state, and audit outcome—not merely the error response.

Use injected clocks, fake processes, simulated LM Studio state and isolated filesystem state.

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

- Verified recovery works against real RC handlers with simulated clients and state.
- No automatic recovery based solely on idle snapshots.
- Exact-holder inhibition clearing is race-safe and durable.
- Unrelated holds survive.
- Stale sessions and incorrect process identities cannot authorize recovery.
- Valid recoveries allow normal miner restoration.
- Uncertain cases remain blocked and produce actionable explanations.
- Existing operator override remains functional, explicit and audited.
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
- Logon versus SYSTEM identity, token-file ACL and credential discovery.
- Service instance/version identity.
- Actual launcher source checkout and configured executable.
- Graceful service restart and shutdown.
- Process group/descendant ownership.
- Crash and unclean shutdown recovery.
- Persistent journal/state migrations.
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

If capabilities are incomplete, leave automatic trusted maintenance release disabled and preserve audited operator reconciliation.

Fixed/locked-clock optimizer modes remain unsupported for automatic trusted release until their independent restoration contract is separately implemented and validated.

### LM Studio qualification

Verify:

- Exact installed LM Studio and `lms` versions.
- Bound runtime instance/host.
- Generation and queue status semantics.
- Read-only probe behavior.
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
8. Stop on the first failure, unexpected process, timeout, ownership uncertainty or verification gap.
9. Preserve complete diagnostic evidence.
10. Return to a known safe state using the approved operator procedure.

The initial supervised RC inference acceptance and the first live optimizer run are distinct experiments; neither automatically authorizes the other.

Do not expand to longer sweeps or multiple miners until the initial bounded test is accepted.

## 4.4 Notifications and watchdog — Original H6

Once read-only assessments and recovery mechanisms are validated, integrate them with the existing notification/remote-control workflow.

Event-driven behavior should prioritize:

- Miner crash requiring intervention.
- Persistent inference uncertainty.
- Automatic recovery attempted/completed.
- Automatic recovery blocked with exact reason codes.
- Maintenance lease loss.
- Unsupported GPU verification capability.
- Service restart/recovery-required state.
- Repeated failure/backoff exhaustion.

Keep notifications compact and actionable.

Example desired notification:

> Resource Coordinator: automatic miner recovery blocked. No active gateway requests, but one previously forwarded LM Studio request lacks verified termination. Miner remains stopped; GPU restart inhibition preserved. Review request `coord-...` using `rc recover`.

The notification should include the relevant status command and safe operator action, not a list of unrelated manual process-inspection commands.

Use event IDs, deduplication, rate limits, and persistence to prevent alert storms.

Integrate with already active notification services rather than building another competing notification server.

## 4.5 Optional unattended reconciliation

After explicit operational acceptance, enable an opt-in policy that periodically or eventfully evaluates recovery eligibility.

Requirements:

- Disabled by default.
- Minimum backoff and bounded retry policy.
- No polling storm.
- Independent current evidence on each attempt.
- Idempotent state transitions.
- Complete audit trail.
- No unsafe inference admission race.
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
- Recovery safety invariants pass.
- CLI output and JSON compatibility pass.

**Windows/host qualification**

- Correct installed and running version.
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

**Final checkpoint:** RC operates as a reliable local GPU control plane, with consolidated status, guarded recovery, integrated Mining maintenance, controlled Windows deployment, and optional unattended incident handling.

---

## Cross-part implementation dependencies

| Component | Depends on | Can proceed in parallel? |
|---|---|---|
| H3 simulated acceptance | Existing H2 candidates | Already assigned |
| Part 1 source integration | H3 validated results | No; follow H3 |
| Part 2 CLI/inference status | Stable RC source baseline | Yes, alongside Windows read-only readiness |
| Part 3 recovery engine | Part 2 evidence interfaces | Some reliability research/tests may parallelize |
| H4 Windows upgrade qualification | Validated integrated source | Yes, after Part 1 |
| H5 controlled live optimizer | H3/source integration, hardware and deployment gates, explicit authorization | Does not require unattended auto-recovery |
| H6 notifications/unattended automation | Part 3 recovery and host capability acceptance | Notification UI may be prepared earlier |

## Global engineering requirements

All implementation parts must preserve:

- Backward-compatible commands, public APIs, state schemas and user configuration.
- Atomic, recoverable durable writes.
- Explicit identity and ownership verification.
- Read-only and dry-run defaults.
- Authorization boundaries for mutations.
- No accidental live LM Studio daemon startup from probes.
- No unqualified GPU safety claims.
- Fail-closed operation on incomplete evidence.
- Complete and readable human output.
- Stable and clean JSON output.
- Windows 11/PowerShell 7 compatibility.
- Isolated, deterministic test environments.
- No secret or transcript leakage into general diagnostics.
- No conflicting remote/local Git edits.
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
- [RC gateway](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/adapters/lmstudio/gateway.py)
- [RC durable state](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/core/durable_state.py)
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

Then reconcile its report and repository checkpoint against this document and initiate **Part 1's integration review**, rather than issuing a duplicate H3 task.

After the validated source baseline exists, initiate Part 2's CLI/inference-status implementation and independently continue the original Windows readiness gates.

The resulting workflow should require operator intervention only when a decision genuinely cannot be established from independent evidence or when explicit authority is required for a consequential live action.
