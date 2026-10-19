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
