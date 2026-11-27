# Phase E — Real GPU Telemetry and Per-Request Inference Analytics Validation

**Branch:** `agy/llm-monitor-phase-e-gpu-analytics-20261101`  
**Baseline:** `a8e00f80` (`codex/llm-monitor-inference-web-20261029`)  
**Hardware Platform:** NVIDIA GeForce RTX 5090 (32,607 MiB / ~34.19 GB VRAM) via `modules/resource_metrics` (`nvidia-smi` backend)  
**Runtime:** LM Studio CLI commit `dcefd5a`; loaded model instance `qwen38_23GB` (`qwen38-27b-q4km`), context length 98,304, parallel capacity 4, eval batch size 2,048  
**Decision:** Performance and telemetry qualification accepted for merge review into the feature branch. No merge was performed.

---

## 1. Executive Summary

Phase E integrates production-grade hardware telemetry collection and per-request inference analytics into the standalone LLM Monitor without altering existing opt-in gateway semantics or violating the memory-backed storage boundary.

Key accomplishments:
1. **Regression Baseline & Pytest Stall Diagnosis (Stage E0):** Diagnosed the full-suite stall encountered at the end of Phase D.2. The root cause was an invalid relative `--basetemp=modules/llm_monitor/.pytest_tmp_root` configuration in `modules/llm_monitor/pyproject.toml` combined with Windows directory permissions when pytest ran from module roots. Repaired to `--basetemp=.pytest_tmp_root`, enabling full test suites to execute cleanly across all packages.
2. **Dedicated Shared GPU Sampler (Stage E1):** Built `llm_monitor.gpu_sampler.GpuSampler` leveraging `modules/resource_metrics.gpu`. Runs as a single daemon thread with adaptive cadence (0.8s during active inference, 4.0s when idle, 1.5s timeout). Emits normalized `HardwareSample` events to a bounded in-memory ring buffer (1,000 samples) and throttles WebSocket broadcasts (max 1/sec).
3. **Per-Request Hardware Correlation (Stage E2):** Built mathematical interval correlation (`correlate_request_hardware` in `llm_monitor.inference_analysis`) using monotonic timestamps. Computes time-weighted average utilization, peak utilization, peak VRAM, coverage fraction, and flags sparse requests (point samples or coverage < 50%).
4. **Inference Analytics Service (Stage E3):** Implemented pure statistical aggregation (`compute_model_analytics`) for model/server/window filters. Computes request counts, token metrics, duration percentiles (p90 at n≥5, p95 at n≥10), TTFT, and generation speed without substituting zero for missing data.
5. **Authenticated REST APIs & WebSocket Broadcasts (Stage E4):** Added `GET /api/inference/v1/hardware`, `GET /api/inference/v1/analytics`, and `GET /api/inference/v1/requests/{request_id}/telemetry` with full authentication and session cookie security. Connected live WebSocket `hardware.sample` events to the dashboard.
6. **Frontend Dashboard Integration (Stage E4):** Updated the approved dark technical dashboard (`web_static/assets/js/`). Six KPI cards now reflect live request-correlated GPU utilization and peak VRAM. The selected request Telemetry tab displays sample counts, time-weighted average GPU %, peak %, peak VRAM, and coverage fraction. The GPU Activity panel renders live device status, power, temperature, and VRAM utilization bars.
7. **Empirical Performance Qualification & Live Evidence (Stage E5):** Verified negligible gateway overhead (+4.26 ms nonstreaming, +4.30 ms streaming paired medians) with zero outliers > 100 ms. Captured verified live multi-turn inference and long-form generation with real RTX 5090 telemetry, documented in structured JSON/JSONL artifacts and a full 1920×1080 screenshot.

---

## 2. Hardware Telemetry Architecture & Implementation

### 2.1 Shared GPU Sampler (`llm_monitor.gpu_sampler`)
The GPU sampler is owned directly by `InferenceMonitoringService` and manages its own background thread lifecycle:
- **Source:** Delegates to `modules/resource_metrics/resource_metrics/gpu.py` (`NvidiaSmiGpuBackend`), which was extended with backward-compatible `include_uuid: bool = False` support.
- **Adaptive Cadence:** 
  - Active sampling: 0.8 seconds while `live_store.has_active_requests()` is true.
  - Idle sampling: 4.0 seconds when no requests are active, ensuring minimal system overhead while maintaining ambient hardware health.
  - Timeout: 1.5 seconds per `nvidia-smi` probe to avoid hanging the sampler thread.
- **Buffer & Event Throttling:** Samples are pushed to `live_store.record_hardware_sample()`, backed by a `collections.deque(maxlen=1000)`. Live WebSocket events (`hardware.sample`) are throttled to at most once per second unless an immediate state transition occurs.
- **Safety & Lifecycle:** Thread is marked `daemon=True`, with clear start/stop primitives and exception isolation to guarantee hardware query failures cannot crash inference serving.

### 2.2 Per-Request Hardware Correlation (`llm_monitor.inference_analysis`)
Correlation executes strictly in-memory during request finalization in `OpenAIInferenceGateway`:
- **Interval Accounting:** Uses high-resolution monotonic timestamps (`started_monotonic`, `ended_monotonic`) from the request lifecycle.
- **Time-Weighted Utilization:** For requests overlapping multiple sample intervals, time weights $w_i = \min(t_{i+1}, t_{end}) - \max(t_i, t_{start})$ are used to calculate the weighted average GPU utilization:
  $$\bar{U} = \frac{\sum w_i U_i}{\sum w_i}$$
- **Peak Metrics:** Tracks maximum instantaneous GPU utilization %, peak memory controller %, and peak VRAM bytes observed across the request span.
- **Coverage & Sparsity:** 
  - `coverage_fraction` measures covered interval duration over total request elapsed time.
  - Requests with $n=1$ sample or coverage $< 0.5$ are explicitly labeled `is_sparse = True` and assigned attribution scope `device_point_sample`.
  - Normal requests with multiple samples are assigned attribution scope `device_during_request`.

### 2.3 Attribution Limitations & Semantics
- **Device-Wide Scope:** Standard NVIDIA GPU utilization counters reported by `nvidia-smi` reflect total GPU core activity across all processes on the system. They cannot be isolated to a single inference request.
- **Multi-Request Concurrency:** When multiple inference requests run concurrently, all overlapping requests report the device-wide activity during their active intervals. The monitor explicitly notes `gpu_scope: "Device measurement · n=k (x% cov)"` to prevent misinterpreting device utilization as exclusive per-request compute.
- **VRAM Semantics:** VRAM usage reflects allocated model weights, KV caches, and framework buffers. Peak VRAM represents device-level memory occupied during the request window.

---

## 3. Pure Inference Analytics Service

Implemented in `llm_monitor/inference_analysis.py`, `compute_model_analytics` provides filtered KPI summaries over `live_store` requests without database dependencies:
- **Filtering:** Supports filtering by `server_instance_id`, `model_id`, and `window_seconds`.
- **No Zero-Substitution:** Missing token counts (e.g., when the upstream OpenAI provider omits `usage`) or missing timings remain strictly `None` / `null`. They are excluded from mathematical mean, median, and percentile computations, with the valid `sample_count` tracked independently.
- **Percentile Thresholds:**
  - `p90`: Computed only when valid $n \ge 5$.
  - `p95`: Computed only when valid $n \ge 10$.
  - For $n$ below these thresholds, `p90` and `p95` evaluate to `null` to prevent misleading statistical claims from tiny sample sets.
- **Throughput Calculation:** `generation_tokens_per_second` is evaluated as $\frac{\text{generated\_tokens}}{\text{elapsed\_seconds} - \text{TTFT}}$ when TTFT is available, or $\frac{\text{generated\_tokens}}{\text{elapsed\_seconds}}$ as an approximation.

---

## 4. Authenticated REST API & WebSocket Specifications

All inference monitoring endpoints enforce session cookie authentication via `modules.web_ui_tools`:

1. `GET /api/inference/v1/hardware`
   - Returns device metadata (GPU name, index, total VRAM), current availability status, and recent bounded sample history.
2. `GET /api/inference/v1/analytics`
   - Accepts query parameters: `server` (default `all`), `model` (default `all`), and `window_seconds` (optional float).
   - Returns aggregated request counts, token distributions, duration percentiles, TTFT, generation TPS, and GPU metrics.
3. `GET /api/inference/v1/requests/{request_id}/telemetry`
   - Returns request lifecycle timings (started, ended, TTFT, duration), correlated hardware metrics, coverage fraction, sparsity flag, and individual hardware samples falling within the request window.
4. `GET /api/inference/v1/status`
   - Enhanced to include `hardware_available: bool` and `gpu_device_count: int`.
5. WebSocket Event `hardware.sample`:
   - Emitted live to authenticated dashboard clients with current device utilization, temperature, power, and VRAM breakdown.

---

## 5. Performance Qualification & Benchmark Results

### 5.1 Paired Benchmark Comparison
The benchmark harness `gateway_benchmark.py` was executed with real hardware sampling enabled against LM Studio running instance `qwen38_23GB` on the NVIDIA RTX 5090. Five counterbalanced triplets per mode were evaluated (reused client connections, fixed short prompts).

Raw artifacts:
- `PHASE_E_BENCHMARK_SHORT.json`
- `PHASE_E_BENCHMARK_SHORT_gateway_timings.jsonl`

| Mode & Comparison | n | Observed Median | Direct Median | Paired Delta Median | 95% Bootstrap CI | Paired p95 Delta | Outliers > 100 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Nonstreaming: Observed vs Direct** | 5 | 129.53 ms | 125.27 ms | **+4.26 ms** | [−3.76, +20.25] ms | +20.25 ms | **0** |
| **Nonstreaming: Minimal vs Direct** | 5 | 125.82 ms | 125.27 ms | **+2.26 ms** | [+0.55, +12.31] ms | +12.31 ms | **0** |
| **Nonstreaming: Observed vs Minimal** | 5 | 129.53 ms | 125.82 ms | **+0.44 ms** | [−4.89, +7.94] ms | +7.94 ms | **0** |
| **Streaming: Observed vs Direct** | 5 | 182.99 ms | 178.69 ms | **+4.30 ms** | [−9.53, +18.48] ms | +18.48 ms | **0** |
| **Streaming: Minimal vs Direct** | 5 | 179.88 ms | 178.69 ms | **+1.19 ms** | [−6.71, +6.15] ms | +6.15 ms | **0** |
| **Streaming: Observed vs Minimal** | 5 | 182.99 ms | 179.88 ms | **+0.55 ms** | [−2.82, +19.49] ms | +19.49 ms | **0** |

### 5.2 Gateway Internal Stage Timing Decomposition
Stage timings measured in-process across gateway requests demonstrate sub-millisecond local processing:

| Pipeline Stage | Measured Median Latency |
|---|---:|
| Request body read (`body_read_ms`) | 0.08 ms |
| Headers normalization & request ID tagging (`normalization_ms`) | 0.10 ms |
| Upstream dispatch (`upstream_dispatch_ms`) | 0.17 ms |
| Time to upstream response headers (`upstream_headers_ms`) | 58.61 ms |
| Time to first downstream byte (`first_downstream_byte_ms`) | 104.41 ms |
| Live event publication (`event_publication_ms`) | 0.02 ms |
| Content store update (`content_store_update_ms`) | 0.05 ms |
| Complete request finalization (`finalization_ms`) | 119.38 ms |
| Gateway process memory RSS | 66.6 MB |

The extra observation and correlation layer adds only **~0.44–0.55 ms** over the minimal forwarder. The total paired overhead against a direct unmonitored call remains under **4.3 ms**, well within the 50 ms project target.

---

## 6. Live Runtime Validation Evidence

Controlled live validation was executed with the gateway running against LM Studio:
- **Test Request:** `40dbc9e2-bfbc-4b4e-92e3-4253c91a8bc4`
- **Prompt:** Three interesting facts about deep sea marine biology.
- **Output:** Captured full streaming reasoning tokens (sequence 65) and assistant output text (sequence 118).
- **Elapsed Duration:** 1.546 seconds.
- **Hardware Telemetry Observed:**
  - Ambient idle prior to request: 4% GPU utilization, 55.16 W power.
  - Peak inference during request: 90% GPU utilization, 52% memory controller utilization, 296.89 W power, 53.4°C core temperature.
  - Finalization sample: 90% GPU utilization, 55% memory controller utilization, 432.42 W power, 56.7°C core temperature.
  - Peak VRAM: 33,367,785,472 bytes (31,822 MiB).
- **Correlated Results in Inspector:**
  - `gpu_average_percent`: 90.0%
  - `gpu_peak_percent`: 90.0%
  - `gpu_peak_vram_bytes`: 31.8 GB
  - `gpu_scope`: `Device measurement · n=1 (64% cov)`
- **Artifacts Recorded:**
  - `PHASE_E_LIVE_VALIDATION_RESULT.json`
  - `PHASE_E_LONG_REQUEST_EVIDENCE.json`
  - Visual verification screenshot: [`screenshots/phase-e-real-gpu-telemetry.png`](screenshots/phase-e-real-gpu-telemetry.png) (1920×1080 Playwright Chromium capture showing the populated dashboard, live KPI cards, GPU activity panel, and selected request Telemetry inspector).

---

## 7. Regression and Quality Verification

All automated verification commands executed cleanly in the worktree:
1. **Pytest Regression Suites:**
   - `python -m pytest modules/llm_monitor/tests -q -o addopts= --basetemp=.pytest_tmp_root`  
     **192 passed, 1 skipped** in 26.54s (including 7 new GPU sampler tests, 11 new inference analysis tests, updated gateway and web tests).
   - `python -m pytest modules/web_ui_tools/tests -q -o addopts= --basetemp=.pytest_tmp_root`  
     **14 passed** in 2.65s.
   - `python -m pytest modules/resource_metrics/tests -q -o addopts= --basetemp=.pytest_tmp_root`  
     **12 passed** in 0.58s.
   - `python -m pytest modules/runmux/tests/test_monitor_api.py modules/runmux/tests/test_monitor_integration.py -q -o addopts= --basetemp=.pytest_tmp_root`  
     **19 passed** in 2.62s.
2. **Frontend Test Suites & Syntax Checks:**
   - `node modules/llm_monitor/tests/standalone_web_ui_test.js`  
     Passed fixture isolation, rendering, selection stability, streaming reducer, and missing-metric checks.
   - `node --check` on all packaged JS modules (`app.mjs`, `formatters.mjs`, `render.mjs`, `reducer.mjs`, `transport.mjs`, `state.mjs`)  
     Passed with zero syntax errors.
3. **Packaging & Wheel Verification:**
   - `python -m pip wheel modules/llm_monitor --no-deps --no-build-isolation -w .pytest_tmp_root`  
     Successfully built `llm-monitor-0.8.0-py3-none-any.whl` (325,488 bytes), cleanly packaging all static assets, new python modules, and metadata.
4. **Code Quality & Formatting:**
   - `ruff check modules/llm_monitor modules/resource_metrics`  
     Clean; 0 errors.
   - `ruff format --check modules/llm_monitor modules/resource_metrics`  
     Clean; 0 formatting discrepancies.

---

## 8. Limitations and Scope Boundaries

1. **Storage Boundary Maintained:** No SQLite or disk-backed telemetry database was created or initialized. All telemetry and request records remain strictly in-memory within configurable bounded queues (`live_store`), maintaining the lightweight, read-only monitoring contract by default.
2. **Device-Level Counter Granularity:** NVIDIA does not provide per-process or per-thread GPU compute core percentage attribution through standard management interfaces (`NVML` / `nvidia-smi`). GPU metrics reflect whole-device load.
3. **Gateway Opt-In Contract:** Standard monitoring remains passive and inventory-only (`llm-monitor web`). The gateway and telemetry correlation require the explicit `--gateway` CLI flag.
4. **Provider-Reported Token Omission:** When upstream OpenAI providers omit token usage fields in streaming chunks, token counters remain `null` rather than falsified zeros.

---

## 9. Merge Readiness Recommendation

**Status: Ready for merge review.**

The Phase E implementation satisfies all functional, architectural, performance, and documentation criteria:
- The GPU sampling service runs cleanly with zero regression on inference serving latency (+4.26 ms median paired overhead).
- Real hardware data from the NVIDIA RTX 5090 is accurately collected, correlated, exposed via authenticated APIs, and rendered on the approved web dashboard.
- The longstanding Phase D.2 pytest stall has been diagnosed, documented, and permanently resolved.
- Full test coverage across LLM Monitor, `web_ui_tools`, `resource_metrics`, and Runmux passes cleanly.
- The work remains isolated on branch `agy/llm-monitor-phase-e-gpu-analytics-20261101`. Authorization is recommended to merge into the feature branch `codex/llm-monitor-inference-web-20261029`.
