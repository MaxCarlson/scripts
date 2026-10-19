# Resource Coordinator — Implementation Plan & Architecture Specification

**Plan Identifier:** `20261019-0915_resource-coordinator-core`  
**Target Module:** `modules/resource_coordinator`  
**Status:** In Implementation  
**Primary Author/Implementer:** Gemini Development Agent  
**Reviewer:** Codex Sol Medium  

---

## 1. Executive Summary & Architecture Reconciliation

This plan consolidates and reconciles the original GPU Coordinator specification and the Resource Coordinator Architecture Revision Addendum.

### Architectural Reconciliation
1. **Core Decoupling**: The core framework does not have hardcoded knowledge of LLMs, LM Studio, CUDA, or cryptocurrency mining. Instead, it defines:
   - **Triggers**: Event sources signaling incoming operations, resource telemetry, or timers.
   - **Conditions**: Predicates evaluating system state (processes running, metric thresholds, lease states, logical combinations).
   - **Actions**: Discrete operations (process start/stop, lease acquire/release, callbacks) with distinct outcomes (`SUCCESS`, `FAILURE`, `SKIPPED`, `INDETERMINATE`).
   - **Events**: Typed namespaced event bus with blocking lifecycle hooks and non-blocking observational listeners.
   - **Leases**: Named resource arbitration tracking active/pending usage, shared vs exclusive locks, and idle cooldown timers.
2. **Modular Adapters**:
   - `adapters/lmstudio/gateway.py`: Reverse proxy intercepting HTTP inference requests (`/v1/chat/completions`, etc.), requesting inference leases, and streaming SSE responses without buffering.
   - `adapters/miners/adapter.py`: Process supervisor adapter for Krig/Kryptex, handling graceful stops, stop verification, ownership tracking, and manual pause overrides.
   - `monitors/cpu.py` and `monitors/gpu.py`: Pluggable telemetry providers.
3. **Preserved Mining Invariants**:
   - Model residency does not block mining; only active inference or model loading blocks mining.
   - Mining is stopped and verified stopped before an inference request reaches LM Studio.
   - Mining is automatically resumed only if the coordinator owns the stop, no other leases are held, and the idle cooldown has elapsed without new requests.

---

## 2. Framework & Library Selection Justification

1. **`asyncio`**:
   - Coordination requires concurrency: concurrent HTTP requests, streaming SSE forwarding, cooldown timers, process status polling, and non-blocking callback dispatch.
   - Single-threaded `asyncio` eliminates multi-threaded race conditions around lease counts and process state while maximizing I/O throughput.
2. **`starlette` & `uvicorn`**:
   - High-performance, lightweight ASGI framework.
   - Transparent streaming support (`StreamingResponse`), exact header and status code reproduction, robust connection lifecycle management.
3. **`httpx.AsyncClient`**:
   - Full async HTTP/1.1 and streaming client.
   - Allows fine-grained chunk streaming (`aiter_bytes()`) directly from upstream to downstream client without buffering the full response in RAM.
4. **`psutil`**:
   - Cross-platform process and CPU telemetry.
   - Allows PID creation-time verification (`process.create_time()`) to protect against PID recycling vulnerabilities.
5. **`pyyaml`**:
   - Clean, human-readable policy declaration matching the user-specified configuration syntax.
6. **No Heavy Orchestrators**:
   - Workflow engines (Airflow, Celery, Temporal) introduce unnecessary network services, database dependencies, and worker processes. `resource_coordinator` is a lightweight, zero-external-dependency local daemon.

---

## 3. Generic Core API Design & Example Usage

### A. Events & Hooks
```python
from resource_coordinator.core.events import EventDispatcher, Event

dispatcher = EventDispatcher()

# Non-blocking observational listener
async def on_process_stopped(event: Event):
    print(f"Process {event.data['name']} stopped.")
dispatcher.on("process.stopped", on_process_stopped)

# Blocking pre-action hook (can inspect, delay, or raise VetoOperation)
async def before_inference(event: Event):
    # Verify preconditions or prepare state
    pass
dispatcher.on("operation.requested", before_inference, is_blocking=True)
```

### B. Leases & Arbitration
```python
from resource_coordinator.core.leases import LeaseManager, LeaseType

lease_mgr = LeaseManager(cooldown_seconds=60.0)

# Acquire shared lease for inference
async with lease_mgr.acquire("gpu.inference", lease_type=LeaseType.SHARED, holder_id="req-123"):
    # Inference is active; mining is held paused
    ...
# When all shared leases are released, cooldown starts automatically.
```

### C. Process Supervisor & Backends
```python
from resource_coordinator.core.processes import ProcessSupervisor, FakeProcessBackend

backend = FakeProcessBackend(name="miner", running=True)
supervisor = ProcessSupervisor(backend=backend)

# Stop with verification
stopped = await supervisor.stop(timeout=10.0)
assert stopped is True
assert supervisor.is_coordinator_owned is True
```

---

## 4. Policy Configuration Contract (`v1.0`)

```yaml
version: "1.0"

service:
  listen_host: "127.0.0.1"
  listen_port: 1235
  upstream_url: "http://127.0.0.1:1234"
  state_persistence_path: "~/.resource_coordinator/state.json"

resources:
  "gpu.inference":
    type: "shared"
    cooldown_seconds: 60.0

processes:
  krig:
    backend: "windows"
    executable: "C:\\Users\\mcarls\\src\\Mining\\vendor\\krig-miner-1.5.6\\krig-miner.exe"
    arguments:
      - "--coin"
      - "pearl"
      - "--url"
      - "stratum+ssl://prl-us.kryptex.network:8048"
      - "--user"
      - "krxXPVG8JN/Xeres"
    working_directory: "C:\\Users\\mcarls\\src\\Mining\\vendor\\krig-miner-1.5.6"
    stop_timeout_seconds: 10.0
    restart_cooldown_seconds: 60.0

policies:
  - name: prioritize-local-inference
    trigger:
      event: "lmstudio.inference_requested"
    condition:
      type: "process_running"
      process: "krig"
    actions:
      - type: "process.stop"
        target: "krig"
        wait_until_stopped: true
        timeout_seconds: 10.0
    on_failure: "reject_operation"
    lease:
      resource: "gpu.inference"
    release:
      when: "resource.gpu.inference.active_count == 0"
      cooldown_seconds: 60.0
    after_release:
      - type: "process.start"
        target: "krig"
        only_if_stopped_by_coordinator: true
```

---

## 5. Operational & Safety Limitations

1. **Direct Port 1234 Bypass**:
   Clients sending requests directly to `http://127.0.0.1:1234` bypass the gateway. The coordinator cannot intercept or coordinate unrouted traffic.
2. **Process Ownership & Adoption**:
   Processes started outside the coordinator are detected as `EXTERNAL_RUNNING`. The coordinator will not terminate or restart an external process unless explicit adoption configuration is set.
3. **PID Recycling Protection**:
   All process handles check PID + `create_time` before sending signals. If a PID has terminated and the OS reuses the PID, the coordinator recognizes the process as deceased rather than signalling an unrelated process.
4. **Streaming Disconnects**:
   If an HTTP client disconnects while streaming SSE, the gateway cancels the upstream request and releases the active lease, preventing leaked inference holds.
5. **Crash Recovery**:
   On coordinator restart, it inspects persisted state. If process ownership is uncertain or ambiguous, it logs a warning and does **not** restart the miner.
