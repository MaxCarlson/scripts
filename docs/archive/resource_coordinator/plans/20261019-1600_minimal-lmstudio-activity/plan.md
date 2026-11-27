# Minimal LM Studio Activity Automation

## Goal

Use the existing LM Studio gateway and lease lifecycle to stop one configured process before inference or a supported model load, then restart it after a configurable verified idle cooldown only when the coordinator owns the stop decision.

## Architecture

Reuse `PolicyConfig`, `ProcessSupervisor`, `LeaseManager`, and the gateway reservation lifecycle. Put model loads and inference on the same `gpu.inference` resource; model loads use exclusive leases. Keep unload and unknown mutations fail-closed. Add an injectable monotonic clock to the existing cooldown mechanism for deterministic tests. Generalize explicit service startup/shutdown and CLI flags while retaining legacy miner aliases.

Use the existing YAML configuration. It already represents process identity, executable, arguments, working directory, stop/restart permissions, and cooldown seconds. Do not add a second JSON registry or timer subsystem.

## Global constraints

- Preserve the Phase D terminal restart latch, identity checks, admission rechecks, abort authentication, uncertain-operation inhibition, and shutdown behavior.
- No real process, live model, LM Studio configuration, Kryptex configuration, merge, or push operations.
- Keep process ownership and timeout behavior explicit; initial process start remains opt-in.
- Direct LM Studio requests that bypass the gateway remain outside coordinator visibility.

## Review focus

- Managed model-load admission must be tied to a blocking stop policy and share arbitration with inference.
- Load and inference completion uncertainty must inhibit restart on the same resource.
- New reservations must cancel cooldown, and the final start action must preserve coordinator ownership and manual override rules.
- Generic service lifecycle selection must be unambiguous for the initial one-process mode.
- Legacy miner API/CLI callers and existing Phase B/C/D safety tests must retain behavior.

## Tasks

### 1. Pin missing contract with focused tests

Add tests for managed model-load admission and stop-before-forward ordering, exclusive load versus inference, generic-named process start/stop, and deterministic cooldown advancement. Update Phase D model-mutation expectations only for the reviewed load routes; unload remains denied.

### 2. Generalize explicit process lifecycle wiring

Update `CoordinatorService` to explicitly start/stop the sole configured supervisor when requested. Add generic serve flags with legacy aliases. Keep default startup inert and reject ambiguous multi-process lifecycle requests.

### 3. Protect model loads on the shared GPU resource

Classify only recognized load routes as `MODEL_LOAD`; map them to exclusive `gpu.inference` reservations and model-load events. Permit managed loads only when a matching blocking stop/restart policy targets a configured process on that same resource. Keep unload and unknown mutations rejected. Preserve stream/non-stream completion and inhibition handling.

### 4. Make cooldown tests deterministic

Inject monotonic-time and async-sleep callables into `LeaseManager`, defaulting to production clocks. Add deterministic coverage for reset, expiry, active/pending claims, failures, and overlapping process operations.

### 5. Validate and hand off

Run the full resource-coordinator offline suite, Ruff check/format, Mypy, and whitespace checks. Update user documentation and handoff with the minimal configuration shape, route limits, direct-bypass limitation, and the Sol Medium safety-review focus. Commit only reviewed task files.

## Safety review boundary

Allowing managed model loads changes a Phase D fail-closed gate and resource arbitration. The implementation must use the same GPU resource with an exclusive lease and matching verified stop policy. This change is specifically flagged for Sol Medium review; offline test success does not authorize live operation.
