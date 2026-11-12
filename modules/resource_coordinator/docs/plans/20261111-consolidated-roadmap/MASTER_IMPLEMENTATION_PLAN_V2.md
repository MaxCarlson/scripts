# Resource Coordinator — Consolidated Implementation Roadmap (v2)

**Date:** November 11, 2026  
**Repositories:** `MaxCarlson/scripts`, `MaxCarlson/Mining`  
**Scope:** Resource Coordinator maintenance integration, CLI modernization and compaction, local inference and maintenance observability, evidence-based recovery, worktree defect remediation, Windows deployment, and controlled live acceptance  
**Status:** Master implementation plan v2 — incorporates CLI architecture refinements and confirmed `v0.14.0` codebase bug fixes; execute after verifying the current H3 agent's results and repository state

---

## Executive summary

The objective is to evolve Resource Coordinator (RC) from a safe but sometimes manually operated GPU arbitration system into an observable, maintainable, and increasingly autonomous control plane with a single, non-overlapping command interface.

The desired end state is:

- One command (`rc status`) provides an understandable view of RC, KRig, LM Studio, active inference, maintenance sessions, gaming state, and recovery blockers.
- The canonical `rc` CLI exposes a compact, non-overlapping top-level command catalog without redundant wrapper groups (`control` and `check` are retired to hidden compatibility aliases), while preserving 100% backward compatibility for all historical and Nov 6 command paths.
- All significant commands support polished, color-coded human output (never collapsing nested telemetry, setup, or acceptance results into generic `"N structured items (see --json)"` placeholders) and stable machine-readable JSON.
- RC determines whether requests are active, pending, completed, or uncertain using its own authoritative state and independent runtime observations.
- RC evaluates whether recovery (both inference inhibition and maintenance session holds) is justified without requiring the operator to inspect process listings or manually interpret multiple command outputs.
- When independently verified safe, RC reconciles a stale inhibition and permits normal Coordinator-managed miner restoration.
- When safety cannot be established, RC preserves protections, explains the precise uncertainty, and optionally sends an actionable notification.
- Confirmed `v0.14.0` worktree defects in status allowlisting, telemetry rendering/ownership, startup inhibition deduplication, and `psutil.AccessDenied` PID reconciliation are fixed before or during Parts 2–3.
- Existing GPU maintenance integration and Mining optimizer work reach source integration, Windows hardware qualification, and authorized controlled live acceptance.
- The design avoids introducing LLM Monitor as a mandatory dependency of RC safety decisions.

**Key architectural rule:** RC owns GPU admission, maintenance, process lifecycle, and minimal durable safety state. LLM Monitor owns detailed inference telemetry and historical analysis. LM Studio provides runtime observations where supported.

**Critical safety distinction:** A model reporting idle, a missing miner process, or zero active gateway requests is not sufficient by itself to prove that an interrupted upstream operation has terminated.

---

## Summary of v2 refinements and confirmed codebase defects

A code-level audit of `MASTER_IMPLEMENTATION_PLAN.md` against the `v0.14.0` candidate worktree (`737bc6b2db7b68c041abffb66017164f3c883228`) identified the following concrete issues that are resolved by this v2 plan:

1. **Unified top-level `rc` taxonomy (eliminating competing paradigms):**
   - The Nov 6 CLI refactor introduced 7 groups (`{status, control, service, system, config, check, logs}`) and hid flat commands (`miner`, `gaming`, `doctor`, `diagnose`, `recover`).
   - Promoting `miner`, `recover`, `doctor`, and `telemetry` back to the top level while leaving `control` and `check` visible creates overlapping commands in `--help`.
   - **v2 resolution:** Make the canonical visible top-level catalog a single, compact 10-command set (`status`, `doctor`, `telemetry`, `miner`, `gaming`, `recover`, `logs`, `service`, `system`, `config`, `help`) and demote `control` and `check` (alongside legacy root verbs like `serve`, `diagnose`, `restart`, `setup`, `upgrade`) to hidden compatibility aliases (`help=argparse.SUPPRESS`).
2. **Resolved `rc recover` flag conflict (`-r` vs `-n` and `--reason` requiredness):**
   - In `cli_parser.py`, `service recover` uses `-r/--reason` and `--resource` (no short flag), whereas root `recover` uses `-r/--resource` and `-n/--reason` (tested in `test_cli_architecture.py`), and both mark `--reason` as `required=True` in `argparse`.
   - **v2 resolution:** Unify `recover` and `service recover` via a shared parser builder where `--reason` is optional at parse time (required only when `-f/--force` is used), `-a/--apply` and `-f/--force` are mutually exclusive, `-r/--reason` and `-R/--resource` are canonical, and `-n` is accepted as a hidden compatibility alias for `--reason` so both `rc recover -f -r "reason"` and legacy `recover -n "reason"` work.
3. **Avoided `argparse` subparser default-clobbering on `rc status`:**
   - In `cli_parser.py`, `_add_global_leaf_options()` skips parsers that have `_SubParsersAction` children. Turning `status` into a parent with subparsers (`miner`, `inference`, `gaming`) breaks `rc status -j` or causes parent defaults (`-u`, `-j`) to mask child flags.
   - **v2 resolution:** Keep `status` as a single leaf parser with an optional positional target: `status_parser.add_argument("status_target", nargs="?", choices=("miner", "inference", "gaming", "maintenance"))` plus `-a/--all`. Normalize `status_target` in `cli_dispatch.py`.
4. **Added missing CLI support for GPU maintenance sessions (`v0.13`/`v0.14` gap):**
   - `GET /_coordinator/status` includes `maintenance`, and `POST /_coordinator/recover` rejects maintenance holds with HTTP 409 (`"Maintenance ownership or recovery hold must be reconciled separately"`), yet the CLI currently has zero commands to view or reconcile maintenance sessions, and `render_coordinator_status()` drops `data["maintenance"]` completely.
   - **v2 resolution:** Render `maintenance` and `gpu_inference.recovery` in `rc status`, add `rc status maintenance`, and support audited operator reconciliation of `recovery_required` maintenance sessions via `rc recover --maintenance -f -r "reason"` (calling `POST /_coordinator/maintenance/release` with `operator_override: true`).
5. **Fixed 4 confirmed bugs in the current `v0.14.0` worktree:**
   - **Bug 1 (`gateway.py` lines 629–649 & 714):** `safe_request_detail_fields` in `handle_coordinator_status()` omits `outcome`, `upstream_elapsed_seconds`, `upstream_timeout_seconds`, `timeout_semantics`, `lease_acquisition_timeout_seconds`, and `model_load_reported_seconds` (stripping fields promised by `RESOURCE_MONITOR_CONTRACT.md`), puts unfiltered `inhibition.to_dict()` into `gpu_inference.inhibition`, and omits `gaming` state from `GET /_coordinator/status`.
   - **Bug 2 (`durable_state.py` lines 891–932):** `reconcile_startup_state()` restores `state.inhibitions["gpu.inference"]` with `holder_id="coord-..."` AND then loops over `state.requests` to add a second in-memory inhibition with `holder_id="crash_recovery:coord-..."` for the same request. When Part 3 clears exact holder `"coord-..."`, the duplicate `"crash_recovery:coord-..."` holder remains in memory and permanently blocks miner restart.
   - **Bug 3 (`durable_state.py` lines 937–942):** `_default_query()` in `reconcile_startup_state()` catches `psutil.AccessDenied` and returns `None`, violating `reconcile_pid()`'s contract and misclassifying an inaccessible running process as `NOT_RUNNING` instead of `ACCESS_DENIED`.
   - **Bug 4 (`cli.py` lines 530–587 & `installation.py` line 3050):** `cmd_diagnose` (`rc telemetry`) passes nested GPU/gateway/miner structures to generic `render_result()`, printing `"1 structured items (see --json)"` instead of GPU metrics, and instantiates an unclosed local `build_system(config)` that misreports a Coordinator-owned miner as `unmanaged`/`external`. In `installation.py`, `doctor` (`rc doctor`) unconditionally returns exit code `0` even when `status` is `"blocked"` or `"unhealthy"`.

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
| New work — CLI compaction, inference/maintenance status, bug fixes, and automated recovery | Planned here | Parts 2 and 3 |

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

# Part 2 — Compacted CLI, Unified Status, Inference/Maintenance Visibility, and Worktree Bug Fixes

**Objective:** Make the Coordinator understandable to humans and agents through one compact, non-overlapping command system, and fix existing status/presentation/telemetry defects in the worktree.

This part combines CLI compaction, parser deduplication, unified inference and maintenance status, LM Studio runtime observation, the initial read-only recovery assessor, and remediation of confirmed `v0.14.0` CLI/status bugs.

## 2.1 Canonical CLI design and taxonomy consolidation

Provide a short `rc` console script entry point alongside `resource-coordinator` and `gpu-coordinator` in `pyproject.toml`:

```toml
[project.scripts]
rc = "resource_coordinator.cli:main"
resource-coordinator = "resource_coordinator.cli:main"
gpu-coordinator = "resource_coordinator.cli:main"
```

Verify that `rc` does not collide with another installed command in normal PowerShell sessions (note: Windows Kits `rc.exe` is only on `PATH` inside Visual Studio Developer shells; keep `resource-coordinator` and `gpu-coordinator` fully functional everywhere).

Per repository standards (`docs/agent/SCRIPTS_REPO_STANDARDS.md` and `REPO_LLM_INSTRUCTIONS.md`):

- Adding a new `[project.scripts]` entry point (`rc`) requires either a `MAJOR` version bump (`1.0.0`) so `python setup.py` automatically regenerates `.venv/Scripts/*.cmd` wrappers, or an explicit `pip install -e .` wrapper-regeneration step documented in setup/handoff if remaining on `0.x` pre-release numbering.
- Register `resource_coordinator` (`rc` / `resource-coordinator`) under `"System & Monitoring"` in `modules/scripts_help/scripts_help/registry/registry.py`.

### Consolidated top-level command catalog

To prevent two competing CLI hierarchies from appearing in `--help` at the same time, **retire `control` and `check` to hidden compatibility aliases (`help=argparse.SUPPRESS`)** and expose a single, flat-first canonical catalog in `rc --help`:

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
| `rc miner start\|stop\|pause\|resume` | Coordinator-managed miner lifecycle and timed/GPU-idle pause controls | `rc control miner <action>` |
| `rc gaming on\|off\|status` | Coordinate gaming mode and local-model memory (`start`/`stop` accepted as aliases) | `rc control gaming on\|off\|status`, `rc gaming start\|stop` |
| `rc recover` | Read-only comprehensive recovery assessment (inference + maintenance + process holds) | `rc service recover` (when used with `-f -r`) |
| `rc recover -j` | Machine-readable recovery assessment and recommended actions | `rc -j recover` |
| `rc recover -a` / `--apply` | Apply only independently verified automatic recovery | `rc service recover -a` |
| `rc recover -f -r "reason"` | Authenticated, audited operator override for inference inhibition | `rc service recover -f -r "reason"`, `rc recover -f -n "reason"` |
| `rc recover -M -f -r "reason"` | Authenticated, audited operator override for a `recovery_required` maintenance session (`-M/--maintenance`) | `rc maintenance recover -f -r "reason"` |
| `rc logs [process_name] [-f] [-b N]` | Read or follow captured process output (`process_name` defaults to `"miner"`) | `rc logs miner`, `rc logs krig` |
| `rc service restart\|shutdown\|abort\|run` | Coordinator daemon lifecycle (`serve` preserved as alias for `service run`) | `rc restart`, `rc shutdown`, `rc abort`, `rc serve` |
| `rc system setup\|upgrade\|repair\|teardown\|startup\|recovery\|auth\|preflight\|accept` | Host installation, Windows task management, upgrade recovery, auth, preflight, and acceptance trials | `rc setup`, `rc upgrade`, `rc repair`, `rc teardown`, `rc startup ...`, `rc auth ...`, `rc check preflight\|accept`, `rc preflight`, `rc accept` |
| `rc config show\|validate` | Inspect or validate configuration YAML | `resource-coordinator config show\|validate` |
| `rc help [command]` | Discoverable command catalog, architecture summary, and examples | `rc --help`, `rc <command> --help` |

*Note on `rc recover` vs. `rc system recovery`:* `rc recover` is for runtime GPU/inference/maintenance holds, whereas `rc system recovery` (also aliased as `rc system upgrade-recovery`) is for interrupted Windows host upgrades (`upgrade-receipt.json`). `rc recover` must check for an active `upgrade-receipt.json` and, if present, display a clear note directing the operator to `rc system recovery`.

### Parser architecture and compatibility requirements

- **Eliminate duplicated parser definitions in `cli_parser.py`:** Currently `cli_parser.py` defines subparsers twice (once in `_add_canonical_commands()` and once for legacy root commands), which caused flag drift between `recover` and `service recover` and between `gaming start|stop` and `control gaming on|off`. Refactor `cli_parser.py` to use shared argument-configuration helpers (`_configure_miner_parser`, `_configure_gaming_parser`, `_configure_recover_parser`, `_configure_serve_parser`, `_configure_accept_parser`, etc.) so canonical and alias paths cannot drift.
- **Implement `rc status [target]` without nested subparsers:** Define `status_target` on `status_parser` using `nargs="?", choices=("miner", "inference", "gaming", "maintenance")` and `-a/--all` (`action="store_true"`). Do **not** attach `_SubParsersAction` to `status_parser`; this keeps `status_parser` a leaf parser so `_add_global_leaf_options()` attaches `-j/--json`, `-v/--verbose`, and `-C/--color` without default-masking bugs.
- **Unify `gaming` action spellings:** Both `rc gaming` and `rc control gaming` must accept `status`, `on`, `off`, `start`, and `stop` (`start` normalizes to `on`/`start`, `stop` normalizes to `off`/`stop`).
- **Unify `recover` flags safely:**
  - Make `-a/--apply` and `-f/--force` a mutually exclusive group (`add_mutually_exclusive_group(required=False)`). When neither `-a` nor `-f` is passed, `rc recover` executes the read-only recovery assessment (`operation_id="recover.assess"`).
  - Do not set `required=True` on `--reason` at the `argparse` level; enforce that `--reason` is non-empty when `-f/--force` is selected (returning exit code `2` via `parser.error()` if `-f` is given without `-r/--reason`).
  - Use `-r/--reason` and `-R/--resource` (default `"gpu.inference"`) as canonical flags, plus `-M/--maintenance` (or `--resource gpu.maintenance`) for maintenance recovery override. Keep `-n` as a hidden alias (`"-r", "-n", "--reason"`) so legacy `recover -n "reason"` calls continue to work. Update the single conflicting test row in `tests/test_cli_architecture.py` (`["recover", "-r", "gpu.inference", "-n", "reviewed"]`) only if needed, or detect when `-n` is passed alongside `-r gpu.*`.
- **Default `rc logs` process name:** Change `logs_parser.add_argument("process_name", nargs="?", default="miner", ...)` so `rc logs` and `rc logs -f` work without requiring `miner` explicitly.
- **Short and long flags:** Ensure all new and modified user-facing options provide both short and long forms per `PYTHON_REPO_STANDARDS.md` (e.g., `-a/--all` on `status`, `-M/--maintenance` on `recover`, `-b/--tail-bytes` on `logs`, `-C/--color` global option).
- ** meaningful exit codes:** Fix `handle_installation_command()` in `installation.py` so `rc doctor` (`check.health`), `setup`, and `repair` return non-zero (`1`) when `result.get("status")` is in `{"blocked", "unhealthy", "failed", "error"}` (verify and update any affected unit test expectations in `tests/test_installation.py`).

## 2.2 Mandatory human-readable presentation and worktree output fixes

Every command exposing `-j/--json` must also provide an intentional, polished default presentation.

### Presentation design

- Rich tables and aligned fields, with consistent headings and spacing.
- Green: verified healthy/successful.
- Yellow: pending, waiting, or uncertain.
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

### Specific worktree bugs to fix in Part 2.2

1. **Fix `gateway.py` `handle_coordinator_status()` allowlist and payload completeness:**
   - Add `"outcome"`, `"upstream_elapsed_seconds"`, `"upstream_timeout_seconds"`, `"timeout_semantics"`, `"lease_acquisition_timeout_seconds"`, and `"model_load_reported_seconds"` to `safe_request_detail_fields` in `gateway.py` (lines 629–649) so `GET /_coordinator/status` stops stripping the v0.12 diagnostic fields documented in `RESOURCE_MONITOR_CONTRACT.md`.
   - Use `safe_inhibition` (instead of unfiltered `inhibition.to_dict()`) for `gpu_inference.inhibition` at line 714 of `gateway.py`.
   - Add `"gaming": await svc.gaming_control("status") if svc else {"state": "inactive"}` (or a non-mutating synchronous snapshot of gaming state) to `handle_coordinator_status()` so `rc status` has complete system visibility in a single HTTP request.
2. **Update `render_coordinator_status()` in `presentation.py`:**
   - Display `maintenance` state when active, acquiring, releasing, or `recovery_required` (or summarize `Idle` / show full details under `rc status --all` and `rc status maintenance`).
   - Display `gaming` state when active/transitioning (or in `rc status --all`).
   - When `gpu_inference.is_restart_inhibited` or `gpu_inference.recovery.required` is true, render the unresolved request IDs, phase, model, elapsed time, and recovery recommendation from `gpu_inference.recovery` instead of only printing the raw reason string.
3. **Fix `cmd_diagnose` (`rc telemetry`) in `cli.py` and add `render_telemetry_result()` in `presentation.py`:**
   - In `_async_diagnose()` (`cli.py` lines 552–558), when `gateway_online` is true and `gateway_data.get("processes")` is present, use the running coordinator's authoritative process status instead of instantiating an unclosed local `build_system(config)` that falsely reports a Coordinator-owned miner as `unmanaged`/`external`. When offline fallback is used, ensure `await system.gateway.close()` is called.
   - Add a dedicated `render_telemetry_result()` in `presentation.py` that renders a Rich table of GPUs (Device ID, Utilization %, VRAM Used / Total MiB, Power Draw W), CPU utilization %, Gateway status, and Managed Miner status instead of calling generic `render_result()` (which currently prints `"1 structured items (see --json)"`).
4. **Add dedicated human renderers for remaining commands using generic `render_result()`:**
   - `rc status inference` (`render_inference_status`)
   - `rc status maintenance` (`render_maintenance_status`)
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

Expose via `GET /_coordinator/inference/status` (and embed summary in `GET /_coordinator/status`) for `rc status inference` and `rc status --all`.

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

If direct SDK/REST observation proves safer and more reliable, use a replaceable adapter interface; do not make the safety engine depend on a specific subprocess implementation.

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

Review journal growth and retention. Terminal, safely resolved records (`terminal_verified`, `operator_resolved`, `auto_recovered`) may have bounded retention (e.g., latest N records or bounded age); unresolved safety records (`reserved`, `possibly_forwarded`, `uncertain`) must **never** be pruned merely because they are old.

Audit all configured request routes, particularly `/v1/chat/completions`, `/v1/responses`, other inference endpoints, model loading, and direct LM Studio access. Record coverage gaps rather than assuming all traffic is intercepted.

## 2.6 Read-only recovery assessment

Proposed module:

`resource_coordinator/core/recovery_assessment.py`

Implement the diagnosis engine that combines inference status with miner lifecycle, maintenance session state, and recovery state.

Include:

- RC readiness and terminal failure state.
- Interrupted host upgrade state (`upgrade-receipt.json` check so upgrade issues point to `rc system recovery`).
- Current active/pending GPU work.
- Known unresolved requests and inhibition holders.
- LM Studio observations and exact runtime identity.
- OS process inventory and configured miner identity.
- PID and process creation-time correlation.
- Owned/external/unmanaged process distinctions.
- Gaming/manual holds, cooldowns, and maintenance session ownership (`idle`, `acquiring`, `active`, `releasing`, `recovery_required`).
- Crash restart backoff and policy restrictions.
- Durable journal validity.
- Whether the system has sufficient evidence to reconcile automatically.

Use four recovery classifications:

| Classification | Decision |
|---|---|
| `auto_recoverable` | All required proof exists (or no hold is active and system is healthy) |
| `wait` | Legitimate operation or cooldown is ongoing |
| `operator_required` | Termination, hardware restoration, or ownership remains uncertain |
| `blocked` | Conflicting work, failed service state, or unsafe condition |

Create a read-only assessment API (`GET /_coordinator/recovery/assessment`, with offline local-journal fallback when the coordinator HTTP service is unreachable) and `rc recover` presentation, with explicit reason codes and recommended canonical `rc` commands.

The read-only assessor (`rc recover` without `-a` or `-f`) must not clear holds, stop processes, or resume KRig.

## Part 2 acceptance criteria

- `rc` entry point and consolidated top-level CLI catalog coexist with all existing public commands and hidden compatibility aliases.
- `cli_parser.py` uses shared argument builders with zero flag drift between canonical and compatibility paths.
- Confirmed `v0.14.0` bugs in `gateway.py` (`safe_request_detail_fields`, `gaming` status), `cli.py` (`_async_diagnose` local supervisor and renderer), `presentation.py` (`maintenance` and `recovery` rendering), and `installation.py` (`doctor` exit code) are fixed and covered by regression tests.
- Default output is polished, readable, and color-coded across all commands supporting `-j`.
- Every relevant JSON command passes formatting, redaction, and schema tests.
- `rc status` and `rc recover` display consolidated inference, maintenance, gaming, and recovery information.
- LM Studio runtime probes are bounded, read-only, and instance-aware.
- Missing/ambiguous observations fail closed.
- No new mandatory dependency on LLM Monitor.
- No recovery mutation occurs in read-only `rc recover`.

**Checkpoint:** Compacted CLI, read-only diagnostics, and recovery classification validated, ready to support automatic reconciliation.

---

# Part 3 — Verified Automatic Recovery, Startup Reconciliation Fixes, and Reliable Completion Evidence

**Objective:** Eliminate repetitive manual diagnosis and recovery for cases that can actually be verified safe, while preserving strict protection for uncertain GPU operations.

## 3.1 Verified recovery operation and maintenance override routing

Build a separate authenticated recovery operation instead of weakening the existing `/_coordinator/recover` operator-override endpoint.

Proposed API distinction:

- `GET /_coordinator/recovery/assessment` — read-only comprehensive recovery assessment.
- `POST /_coordinator/recovery/auto` — independently verified automatic recovery (`rc recover -a`).
- Existing `POST /_coordinator/recover` — explicit audited operator override for `gpu.inference` (`rc recover -f -r "reason"`), unchanged in authority.
- Existing `POST /_coordinator/maintenance/release` (with `operator_override: true`, `override_reason: "..."`) — explicit audited operator override for a `recovery_required` maintenance session, now reachable via `rc recover -M -f -r "reason"` (`--maintenance`).

A caller flag requesting automatic recovery (`-a`) must never count as termination evidence.

## 3.2 Atomic recovery workflow and startup reconciliation fixes

### Prerequisite bug fixes in `durable_state.py`

Before implementing exact-holder automatic recovery, fix two bugs in `resource_coordinator/core/durable_state.py`:

1. **Deduplicate startup inhibition holders (`reconcile_startup_state`, lines 891–932):**
   - Currently, Step 1 restores `state.inhibitions[resource]` with `holder_id="coord-..."` (and any `additional_uncertain_holders`), and Step 2 iterates over unresolved `state.requests` and calls `lease_manager.inhibit_restart(..., holder_id=f"crash_recovery:{req_id}")`.
   - When `req_id` is already the primary or an additional holder in `state.inhibitions[resource]`, Step 2 creates a duplicate `"crash_recovery:<req_id>"` inhibition holder in memory that is not on disk, preventing exact-holder clearing (`clear_inhibition_holder`) from ever unblocking the resource!
   - **Fix:** In `reconcile_startup_state()`, use `holder_id=req_id` (not `f"crash_recovery:{req_id}"`), skip calling `inhibit_restart` if `req_id` is already present in the restored `state.inhibitions[req.resource]` holders, and if an unresolved request (e.g., a `RESERVED` request interrupted by a crash before `record_inhibition`) was not yet in `state.inhibitions`, persist its inhibition into `state.inhibitions` using `holder_id=req_id` so disk and in-memory holder identities match 1:1.
2. **Preserve `psutil.AccessDenied` in `_default_query` (`reconcile_startup_state`, lines 937–942):**
   - Currently `_default_query()` catches `(psutil.NoSuchProcess, psutil.AccessDenied)` and returns `None`, causing `reconcile_pid()` to return `ReconciliationOutcome.NOT_RUNNING` instead of `ReconciliationOutcome.ACCESS_DENIED`.
   - **Fix:** Catch only `psutil.NoSuchProcess` in `_default_query()` (returning `None`) and allow `psutil.AccessDenied` to propagate into `reconcile_pid()` where it is properly classified as `ReconciliationOutcome.ACCESS_DENIED`.
3. **Preserve durable state schema compatibility (`RequestPhase`):**
   - When recording a verified automatic recovery in `coordinator_state.json`, either add `AUTO_RECOVERED = "auto_recovered"` to `RequestPhase` (with explicit state-version/rollback handling) or transition the request to `RequestPhase.TERMINAL_VERIFIED` with `details["recovery_disposition"] = "auto_recovered"` and `details["resolved_by"] = "verified_auto_recovery"` so older schema readers cannot crash on startup.

### Server atomic recovery workflow (`POST /_coordinator/recovery/auto`)

At the server:

1. Identify the exact targeted inhibition and request/operation owner(s).
2. Establish a serialized admission/recovery boundary under the `LeaseManager` condition lock.
3. Prevent conflicting new GPU work during the final check.
4. Verify active/pending leases and outstanding model-load operations.
5. Verify maintenance, gaming, manual-pause, service, and crash-backoff states.
6. Inspect independently observed process and LM Studio runtime state.
7. Require authoritative termination proof for previously forwarded uncertain operations.
8. Re-read durable state and validate the exact holder/session identity.
9. Persist the recovery disposition and clear only the eligible inhibition holder(s) via `_remove_inhibition_holder` / `clear_inhibition_holder`.
10. Apply the normal cooldown.
11. Allow the existing RC supervisor to resume eligible Coordinator-owned miner operation.
12. Verify and report the resulting state.

A previous CLI assessment snapshot must never authorize a later recovery without fresh server-side checks.

### Evidence hierarchy

Automatic recovery may be possible when the system can prove:

- The relevant request was never forwarded (`RequestPhase.RESERVED` prior to upstream dispatch, or pre-send failure where `forwarded is False`), OR
- The exact operation reached an independently verified terminal state, OR
- The associated upstream runtime definitively terminated and the required process/instance identity and coverage guarantees are satisfied, AND
- No other protected work or ineligible inhibition owner remains.

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
- Bounded upstream-stream draining after downstream disconnect (currently gated by `bounded_drain_seconds` raising `ValueError` in `LMStudioGateway.__init__` until cancellation-safe draining is verified).
- Safe cancellation of operations with verified cancellation handles.
- Explicit differentiation between downstream cancellation and upstream execution termination.
- Durable transition from uncertain to terminal-verified when later authoritative evidence arrives (e.g., background upstream stream finishes with `[DONE]` or `model_load.end` during a bounded post-disconnect drain window).
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

- Verified terminal request followed by a stale inhibition.
- Persistently verified not-forwarded (`RESERVED`) request recovered after coordinator restart (verifying no phantom `crash_recovery:` holder remains).
- Pending inference or model load.
- Timed-out forwarded operation with unknown termination.
- Active generation despite no downstream client (and bounded post-disconnect drain completion vs. drain timeout).
- Unavailable or malformed LM Studio activity response.
- Wrong LM Studio instance.
- Model idle but unresolved request.
- External miner or mismatched PID/create time, plus `psutil.AccessDenied` during startup PID reconciliation.
- Manual pause and gaming hold.
- Active maintenance session or `recovery_required` maintenance session (verifying `rc recover -a` refuses to auto-clear unverified maintenance holds while `rc recover -M -f -r` performs audited maintenance override).
- Multiple inhibition holders, only one eligible (verifying promotion of remaining holder).
- Concurrent inference arriving during recovery.
- Service crash between decision and journal commit.
- Journal corruption or persistence failure.
- Ambiguous recovery HTTP response.
- Repeated recovery request/idempotency.
- Post-release cooldown and delayed restart.
- Failed or exhausted miner restart.
- Operator override path (`rc recover -f -r`) remains independent.

For every important failure, assert durable state, active lease state, restart inhibition, process state, and audit outcome—not merely the error response.

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

- Startup reconciliation holder deduplication and `AccessDenied` fixes in `durable_state.py` pass unit and integration tests.
- Verified recovery (`POST /_coordinator/recovery/auto` / `rc recover -a`) works against real RC handlers with simulated clients and state.
- No automatic recovery based solely on idle snapshots.
- Exact-holder inhibition clearing is race-safe and durable across coordinator restarts.
- Unrelated holds survive.
- Stale sessions and incorrect process identities cannot authorize recovery.
- Valid recoveries allow normal miner restoration.
- Uncertain cases remain blocked and produce actionable explanations.
- Existing operator overrides (`rc recover -f -r` for inference and `rc recover -M -f -r` for maintenance) remain functional, explicit, and audited.
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
- Service instance/version identity.
- Actual launcher source checkout and configured executable (including `rc` entry-point wrapper generation).
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

Integrate with already active notification services (`modules/notifications`) rather than building another competing notification server.

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

**Final checkpoint:** RC operates as a reliable local GPU control plane, with consolidated `rc` CLI and status, guarded recovery, integrated Mining maintenance, controlled Windows deployment, and optional unattended incident handling.

---

## Cross-part implementation dependencies

| Component | Depends on | Can proceed in parallel? |
|---|---|---|
| H3 simulated acceptance | Existing H2 candidates | Already assigned |
| Part 1 source integration | H3 validated results | No; follow H3 |
| Part 2 CLI compaction, inference/maintenance status, and worktree bug fixes | Stable RC source baseline | Yes, alongside Windows read-only readiness |
| Part 3 recovery engine and `durable_state.py` startup fixes | Part 2 evidence interfaces | `durable_state.py` bug fixes and reliability research/tests may start immediately in Part 2/3 |
| H4 Windows upgrade qualification | Validated integrated source | Yes, after Part 1 |
| H5 controlled live optimizer | H3/source integration, hardware and deployment gates, explicit authorization | Does not require unattended auto-recovery |
| H6 notifications/unattended automation | Part 3 recovery and host capability acceptance | Notification UI may be prepared earlier |

## Global engineering requirements

All implementation parts must preserve:

- Backward-compatible commands, public APIs, state schemas, and user configuration.
- Short and long flags for all user-facing CLI arguments (`REPO_LLM_INSTRUCTIONS.md`).
- Synchronized `pyproject.toml` and `resource_coordinator.__version__` versions, plus registration in `modules/scripts_help/scripts_help/registry/registry.py`.
- Atomic, recoverable durable writes.
- Explicit identity and ownership verification.
- Read-only and dry-run defaults.
- Authorization boundaries for mutations.
- No accidental live LM Studio daemon startup from probes.
- No unqualified GPU safety claims.
- Fail-closed operation on incomplete evidence.
- Complete and readable human output (no generic `"N structured items (see --json)"` dumps).
- Stable and clean JSON output.
- Windows 11/PowerShell 7 compatibility.
- Isolated, deterministic test environments using `--basetemp=modules/resource_coordinator/.pytest_tmp_root/...`.
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
- [RC CLI dispatch](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/cli_dispatch.py)
- [RC CLI presentation](https://github.com/MaxCarlson/scripts/blob/737bc6b2db7b68c041abffb66017164f3c883228/modules/resource_coordinator/resource_coordinator/presentation.py)
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

Then reconcile its report and repository checkpoint against this v2 document and initiate **Part 1's integration review**, rather than issuing a duplicate H3 task.

After the validated source baseline exists, initiate Part 2's CLI compaction, worktree bug fixes, and inference/maintenance-status implementation, and independently continue the original Windows readiness gates.

The resulting workflow should require operator intervention only when a decision genuinely cannot be established from independent evidence or when explicit authority is required for a consequential live action.
