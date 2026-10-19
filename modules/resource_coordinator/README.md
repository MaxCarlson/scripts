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
