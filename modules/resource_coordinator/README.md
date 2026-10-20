# Resource Coordinator

A general-purpose, event-driven local resource coordination framework, process supervisor, and transparent proxy gateway.

## Overview

`resource_coordinator` provides deterministic arbitration for competing system resources (CPU, GPU, memory, external processes). It allows high-priority workloads (such as local LLM inference or interactive applications) to automatically suspend background workloads (such as cryptocurrency miners or heavy batch jobs), track active resource claims across concurrent requests, observe idle cooldowns, and safely resume background workloads once resource pressure subsides.

The module is generic and extensible, treating local LLM inference and cryptocurrency mining as modular adapters rather than core assumptions.

## Core Concepts

- **Triggers**: Events that signal incoming work or state transitions (HTTP inference requests, telemetry thresholds, timers, custom events).
- **Conditions**: Predicates evaluating whether actions should execute (process running, lease held, metric thresholds, composite logical expressions).
- **Actions**: Discrete operations with verified outcomes (process stop/start, lease acquire/release, callbacks).
- **Events & Callbacks**: Namespaced event dispatch separating non-blocking observational listeners from blocking lifecycle hooks.
- **Resource Leases**: Reference-counted claims on named resources (exclusive or shared), supporting atomic reservation and configurable idle cooldowns.

## CLI Usage

```powershell
# Run the coordination gateway service
resource-coordinator serve --listen 127.0.0.1:1235 --upstream http://127.0.0.1:1234

# Check active leases, managed processes, and coordinator status
resource-coordinator status

# View or validate policy configuration
resource-coordinator config show
```

The alias `gpu-coordinator` is also provided for backward compatibility.

## Phase B review checkpoint

Version 0.2.0 has passed 99 offline tests. Actual Windows/Krig/LM Studio integration remains unverified. See [review findings and readiness](docs/PHASE_B_REVIEW.md) before selecting a supervised experiment or unattended deployment.

Recovery is disabled unless the service has `RESOURCE_COORDINATOR_RECOVERY_TOKEN`; the operator CLI needs the same environment token:

```powershell
resource-coordinator recover --force --reason "Independently verified all earlier upstream execution has stopped"
```

Recovery is an explicit operator override, not proof of upstream idle. Active/pending claims reject recovery. Standalone `miner pause/resume` are disabled because they cannot read the running daemon's safety state. Forceful Windows stop requires explicit `allow_force_termination: true`; external stop and restart permissions remain separate. Enabled persistence/bounded-drain settings are rejected until implemented safely. Unknown state-mutating HTTP routes return 501. Reinstall editable package metadata/dependencies for the 0.2.0 minor version before a separately authorized operational test.

## Phase C safety checkpoint

Current preparation version: **0.3.0**, with 151 passing offline tests. **NO-GO for a supervised live test** until the missing coordinator-owned startup/admission path and deployment prerequisites are reviewed. The template denies external adoption/control and force, uses inherited-console group mode, and requires local placeholder replacement. Persistence helpers do not provide service crash recovery. See [Phase C review](docs/PHASE_C_SAFETY_REVIEW.md) for prioritized findings and [blocked acceptance checklist](docs/SUPERVISED_LIVE_ACCEPTANCE_PLAN.md). Telemetry T1 remains on its separate branch; it has not been merged here.
# Single-process LM Studio activity automation

The gateway can coordinate one configured process with inference and explicit model-load requests. Both operations use the shared `gpu.inference` arbitration resource: inference takes a shared lease, while model loading takes an exclusive lease. A pending model load blocks later inference admission until the load is admitted, and both paths use the same idle timeout. The existing process supervisor records whether it stopped a running process; a process already stopped when the request arrives is not automatically restarted.

Use the existing YAML configuration. Configure an inference stop policy and, when managed model loading is desired, a matching model-load policy. Their target process and cooldown must match:

```yaml
processes:
  background_worker:
    backend: windows
    executable: 'C:\Tools\worker.exe'
    arguments: []
    working_directory: 'C:\Tools'
    allow_external_stop: false
    allow_external_restart: false
    allow_force_termination: false
policies:
  - name: stop-for-inference
    trigger_event: lmstudio.inference_requested
    target_process: background_worker
    resource: gpu.inference
    lease_type: shared
    cooldown_seconds: 300
  - name: stop-for-model-load
    trigger_event: lmstudio.model_load_requested
    target_process: background_worker
    resource: gpu.inference
    lease_type: exclusive
    cooldown_seconds: 300
```

Model unload and unknown mutating routes remain rejected. Clients must use the coordinator gateway to receive this protection; requests sent directly to LM Studio bypass the coordinator and cannot be observed. No process is started at coordinator startup unless an operator explicitly supplies `--start-process NAME`. Generic lifecycle flags are available as `--fake-process`, `--start-process NAME`, and `--stop-process-on-shutdown NAME`; the legacy miner flags remain supported.

An opt-in Windows test uses a disposable process and the real coordinator HTTP listener with mocked upstream responses. A separate opt-in live test is gated on a preloaded model and explicit authorization; it has not been run. See [Windows LM Studio HTTP integration](docs/WINDOWS_LMSTUDIO_HTTP_INTEGRATION.md) for commands, evidence, and the live request/cleanup procedure.
