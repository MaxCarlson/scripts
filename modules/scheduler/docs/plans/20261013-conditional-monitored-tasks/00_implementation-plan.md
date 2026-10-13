# Monitored Process Rules

## Objective

Add a generic, opt-in scheduler feature that periodically runs a user-authored monitor command, evaluates conditions against its structured output, and starts/stops a configured process according to rule state. The motivating example is a miner that starts when other GPU activity has been low for a sustained window and stops when competing GPU activity rises.

The feature is named **Monitored Process** in the CLI/TUI. It is distinct from finite shell tasks: a monitored process is a supervised long-running executable, while its monitor command is a short-lived probe.

## Current-State Evidence

- `scheduler/service.py` owns the daemon loop; scheduled task execution is synchronous.
- `TaskExecutor.execute()` captures a finite shell command's output and returns an `ExecutionResult`; it is not a long-running process supervisor.
- `Task`, `Schedule`, and `StorageManager` use backward-compatible JSON persistence.
- The Windows background runner separates a limited daemon from an elevated Admin worker. Monitoring should remain unprivileged where possible and must not trigger UAC per poll.
- A user-provided PowerShell `Get-Counter '\GPU Engine(*)\Utilization Percentage'` probe, run elevated on this machine, reported `krig-miner` PID 38868 at 101% on engine `3d`, while Task Manager showed GPU 1 at 100%. This confirms process attribution works for the target workload. Clamp values above 100 to 100 for thresholds.
- A read performed in the agent's non-elevated execution token failed. Windows supports read-only counter access for non-admin users with appropriate performance-monitor group membership; the feature must probe access in the actual daemon account and explain missing access rather than elevating the daemon silently.

## Product and UX Design

One Monitored Process definition contains:

1. A process executable, arguments, and optional working directory.
2. A monitor shell environment and script. Each invocation must emit exactly one JSON value/object to stdout and exit successfully. Stderr is diagnostic only.
3. A polling interval and command timeout.
4. A start condition and a stop condition referring to typed fields in the JSON output. Conditions support comparisons and an optional rolling aggregation window (`latest`, `average`, `min`, `max`) or a continuous `for` duration.

To make creation approachable, add a **Test Monitor**/preview action that runs the command once, validates the JSON, and displays available field paths/types and values. Ship a Windows GPU monitor script/template that emits ready-to-use metrics such as `other_gpu_3d_pct`, excluding the configured process PID. Users can customize or replace it; the condition engine remains independent of GPU/NVIDIA APIs.

Suggested CLI shape: `scheduler monitor create|list|show|status|test|enable|disable|start|stop|delete`. The TUI gets a **Monitored Processes** entry with a guided create/edit/status flow. Provide CLI and TUI parity. Use an imported JSON definition/config for advanced or multi-condition CLI creation if flags become unwieldy; do not force long JSON expressions into common TUI paths.

## Rule Semantics

- Start only when the configured process is not already running and the start condition passes with a complete, fresh sample window.
- If the process was already running before the rule launched it, report it as external, do not duplicate it, and do not stop it. Adoption must be a separate explicit future feature.
- When the process is owned by this rule, evaluate the stop condition at each successful poll. On a match, run the optional graceful stop action, then stop only the owned PID after validating PID, creation time, and executable identity. A configured timeout may fall back to terminating that verified PID.
- After an automatic stop, restart only when the start condition passes again. Use separate start/stop thresholds, a stop debounce, and restart cooldown to avoid flapping.
- A failed/timed-out command, nonzero exit, invalid JSON, missing field, stale reading, or permission error is `unknown`; it never satisfies start or stop conditions.
- Disabled rules stop polling but do not silently terminate a process already running; the UI must show this. Explicit Stop remains available.
- Cap a utilization reading at 100 for threshold math. Do not sum unlike GPU engines. GPU templates report each engine as a separate field; the caller chooses 3D/Compute or a deliberate same-engine aggregate.

## Process Ownership and State

- Launch the target executable directly (no shell wrapper) with argument list and `shell=False`, to preserve an unambiguous process identity.
- Persist process ID, creation time, executable path, and rule ID in a small atomic runtime-state file beside scheduler data. Do not store telemetry samples in the main config.
- Use `psutil` for process creation-time/path validation and cross-platform process inspection/termination; declare it as a direct dependency.
- Reconcile runtime state on daemon restart. PID reuse, missing processes, or identity mismatch clear stale ownership without terminating anything.
- Prevent duplicate monitors for the same rule and prevent conflicting enabled rules from managing the same executable identity.
- Monitor command timeouts and non-overlap must not stall schedule evaluation. Log state transitions and monitor failures with rate limiting; do not log every successful sample or notify on every poll.
- No elevation delegation in MVP. If GPU counter reads need a permission adjustment, provide a clear one-time preflight instruction and retest under the daemon's actual token. Never request interactive elevation every poll.

## Implementation Stages

### 1. Persisted definition, validation, and condition evaluator

- Add monitor/condition models, JSON validation, storage CRUD, and atomic process ownership state.
- Implement pure condition evaluation and rolling-window tracking, including full-window, stale-data, missing-path, type, debounce, and cooldown rules.
- Preserve existing scheduler data files and task/schedule behavior.

### 2. Monitor execution and preview

- Run monitor scripts using existing configured shell resolution with a finite timeout and strict JSON stdout contract.
- Prevent overlapping probes and keep slow probes from blocking time-based scheduling.
- Add CLI/TUI create/test/status flows and a GPU usage template that reports per-process GPU-engine activity excluding the target miner.
- Preflight monitor execution/read access under the actual daemon account; show the required least-privilege performance-counter membership if unavailable.

### 3. Owned-process supervision and daemon integration

- Add direct executable launch, state persistence, restart reconciliation, external-process detection, graceful stop, verified termination fallback, and restart backoff.
- Integrate polling on each rule's cadence without blocking normal schedule checks.
- Record lifecycle state and transitions; ensure failures fail closed.

### 4. Complete management UX and docs

- Complete CLI/TUI list/show/edit/enable/disable/manual-start/manual-stop/delete and parity.
- Document JSON monitor output, condition paths/operators/windows, process ownership, permission setup, and the miner example.
- Bump the scheduler minor version and update the help registry.

### 5. Focused verification and manual validation

- Add focused model/storage/evaluator/runner/supervision/service/CLI/TUI tests, including failure and PID-reuse cases.
- Run scheduler-targeted tests, Ruff, compile, CLI help, JSON compatibility, and diff checks.
- Manually validate monitor output under the installed daemon account and confirm a supervised process can be started/stopped without changing Windows runner registration during automated checks.

## Acceptance Criteria

- Existing scheduler JSON loads without migration loss and existing schedules/tasks behave unchanged.
- A user can preview command output and build conditions against discovered JSON fields.
- A valid condition starts one managed process at most; a stop condition stops only that rule's verified process instance.
- External processes are never duplicated or terminated by default.
- Unknown/bad/stale output cannot start or stop a process; probe timeout does not block scheduled tasks or overlap itself.
- Windowed averages require a full fresh window; threshold hysteresis/cooldown prevent rapid restart cycles.
- The miner example can start below its configured non-miner GPU usage threshold and stop above the selected threshold using process-attributed readings.
- CLI and TUI both support the feature, and a regular limited-privilege daemon works whenever its account has the required read permission.

## Approval and Publication

Implementation is authorized by the user. No commit, push, merge, Windows runner registration, or automatic local group membership change is authorized.
