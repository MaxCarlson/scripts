# Phase D.1 — Gateway Performance and Transport Validation

**Branch:** `codex/llm-monitor-inference-web-20261029`
**Baseline:** `e592e1facb8618f009f491dcb17363592a7e25b6`
**Runtime:** LM Studio loopback API on `127.0.0.1:1234`; selected model `qwen38_23GB` (Qwen3.8 27B, configured context 98,304); `lms --version` reported `CLI commit: dcefd5a`. The exact LM Studio desktop/server build number was not independently exposed by the probed API. OpenCode on `127.0.0.1:4196` was left untouched.
**Persistence:** no telemetry database or transcript file was created by default monitoring or these live requests.

## Summary and gate

The earlier three-sample report showed a +1,584.7 ms median gateway delta, but its requests generated different token counts and the original request bodies/settings were not retained. A controlled 40-triplet trial matched each request body and generation limit across direct LM Studio, a minimal forwarding gateway, and the capture/observation gateway. It measured +2.86 ms median observed-vs-direct for streaming and −0.76 ms for nonstreaming. All 40 groups per mode returned the same 32 generated tokens across all three paths.

A separate 20-triplet repeat with the same alias also exposed large one-off delays before upstream response headers: 2.94 s and 3.44 s on minimal/observed gateway paths in one nonstreaming group, while the direct call in that group took 418 ms. This repeat had high variance and one scheduling/cache-order-sensitive group. The delay accrued while waiting for LM Studio's upstream response, not in request parsing/normalization; its cause is not proven. The 40-group run meets the provisional 50 ms median target, but the separate run prevents a stable performance conclusion. **Phase D.1 is not performance-ready for merge.**

Transport and browser-reconnect behavior were hardened and validated. The dashboard observer can disconnect without cancelling inference, and reconnect snapshots retained the same request identity and full captured content in the trials below. The implementation and test evidence support continuing to a focused LM Studio scheduling/cache experiment; they do not justify claiming that the original latency discrepancy has been causally explained.

## Implementation changes

- `gateway.py`: optional metadata-only monotonic timing checkpoints; immediate upstream-byte forwarding independent of SSE frame completion; bounded side-parser buffering; unchanged successful response bytes; explicit failure state and SSE error on upstream stream interruption; JSON content-type and browser Origin/Fetch Metadata checks; loopback resolution pinning for `localhost`.
- `web.py` and `cli.py`: opt-in `--gateway-timing` metadata logging, available only with the explicitly enabled gateway. Timing output contains request UUIDs, durations, and process resource metrics, never prompts, reasoning, or output.
- `gateway_benchmark.py`: explicit `--run-live` counterfactual harness. It warms the model and HTTP connections, then uses identical synthetic requests, counterbalanced direct/minimal/observed order, and persistent client connections for streaming and nonstreaming comparisons. Reports retain metadata only.
- `gateway_test.py`: transport, security, failure, timing-redaction, and request-isolation regressions, including concurrent gateway requests.

The gateway remains explicitly enabled and bound to loopback, with one fixed validated upstream. Normal `llm-monitor web` remains passive. No existing client was redirected, and no LM Studio/OpenCode setting was changed.

## Source and environment evidence

The local `/v1/models` response listed `qwen38_23GB` and the alias `qwen38-27b-q4km`; the benchmark used the exact `qwen38_23GB` alias for the principal comparison. The `lms` executable reports CLI commit `dcefd5a`; a distinct desktop/server version string was not available from the checked endpoints. The monitor remains connected only to loopback.

Two authorized, synthetic, real inference requests were used for browser reconnect validation:

1. A reasoning-heavy request was captured live. The dashboard tab was closed while reasoning continued; the request progressed from 761 to 1,054 captured reasoning characters and completed at its 256-token limit. A newly authenticated dashboard reconciled the same request UUID, ordered input, full final reasoning segment, provider usage, and terminal `length` state.
2. An output-heavy request had 911 output characters when the dashboard tab closed. The inference client continued, and the request later completed with 1,472 output characters, 384 completion tokens, and zero reported reasoning tokens. After reauthentication, the dashboard snapshot returned the same request UUID and complete output once. No duplicate text was visible.

These are separate request trials; together they demonstrate reconnect reconciliation for reasoning and output. The browser did not receive the intermediate deltas during its disconnection. Since the completed snapshot contained the full coalesced content, no transcript corruption occurred. A snapshot does not recreate the timing/order of missed intermediate browser events; exact event replay across reconnect is not promised.

The genuine Phase D request screenshot is retained at [`screenshots/phase-d-real-gateway-request.png`](screenshots/phase-d-real-gateway-request.png). Reconnect identity/content evidence was inspected in the authenticated browser and API state during the live trials; a separate screenshot file for the reconnect state was not saved.

## Benchmark methodology

The harness is explicitly opt-in and accepted only an IPv4 loopback upstream. Both runs used a fixed one-message synthetic prompt, temperature 0, `max_tokens=32`, identical streaming/nonstreaming payloads, warmed model and connections, and six-order counterbalanced triplets. The observed path captured and published inference events; the minimal path forwarded without monitoring capture. Direct, minimal, and observed requests were issued sequentially within each counterbalanced group, so provider cache and scheduling order remain experimental factors. No prompt or generated text was written to benchmark artifacts.

### Principal 40-triplet comparison

Artifact: [`PHASE_D1_BENCHMARK.json`](PHASE_D1_BENCHMARK.json), with metadata-only per-request timing records in [`PHASE_D1_BENCHMARK_gateway_timings.jsonl`](PHASE_D1_BENCHMARK_gateway_timings.jsonl).

| Mode/path | Samples | Median total (ms) | p95 total (ms) | Median headers (ms) | Median first data (ms) | Median generated tokens |
|---|---:|---:|---:|---:|---:|---:|
| Nonstream direct | 40 | 420.394 | 484.354 | 420.201 | 420.249 | 32 |
| Nonstream minimal | 40 | 422.764 | 485.819 | 422.584 | 422.661 | 32 |
| Nonstream observed | 40 | 419.634 | 484.188 | 419.476 | 419.544 | 32 |
| Streaming direct | 40 | 422.577 | 487.605 | 2.297 | 104.650 | 32 |
| Streaming minimal | 40 | 429.252 | 489.379 | 4.244 | 105.708 | 32 |
| Streaming observed | 40 | 425.433 | 494.609 | 4.454 | 105.107 | 32 |

| Median difference | Nonstream | Streaming |
|---|---:|---:|
| Minimal gateway minus direct | +2.370 ms | +6.675 ms |
| Observed minus minimal (capture/monitoring) | −3.130 ms | −3.820 ms |
| Observed gateway minus direct | −0.760 ms | +2.856 ms |

Each 40-triplet mode had 40/40 groups with exactly matched 32-token outputs across all paths. Streaming client-observed time to first data was 104.65 ms direct, 105.71 ms minimal, and 105.11 ms observed. Provider TTFT was not emitted in a field supported by this harness and remains unavailable. Negative paired differences are ordinary sample variation, not evidence that the gateway accelerates inference.

### Independent 20-triplet repeat and variance

Artifact: [`PHASE_D1_PROCESS_METRICS.json`](PHASE_D1_PROCESS_METRICS.json) plus [`PHASE_D1_PROCESS_METRICS_gateway_timings.jsonl`](PHASE_D1_PROCESS_METRICS_gateway_timings.jsonl). This run used the same model alias, request settings, and 20 triplets per mode. It confirmed 20/20 matched output groups but showed extreme nonstreaming variance and three >1 s samples. In the affected group, order was observed → minimal → direct: upstream response-header times were 3,440 ms, 2,939 ms, and 418 ms respectively, with 32 tokens each. Another direct-first group had a 1,103 ms direct sample followed by 452 ms minimal and 418 ms observed. These order-sensitive cases are consistent with model scheduling/cache effects, but do not prove a cause. The run is reported separately and is not pooled with the principal trial.

This repeat means that the small apparent median overhead in the 40-group run is not yet a reproducible performance guarantee. Measurements do not support attributing the earlier +1.58 s median specifically to gateway CPU or monitoring-event publication. The old three-sample request lengths differed and do not allow a controlled causal replay.

### Timing and resource profile

The 40-group capture timing file has 82 records (40 measured requests plus one warmup per mode). Stage fields are monotonic elapsed offsets from ingress unless called an accumulated counter. Medians: body read 0.054 ms; normalization 0.069 ms; upstream dispatch setup 0.152 ms; event publication accumulated 0.053 ms; content-store update accumulated 2.797 ms. Median first downstream-yield was 0.231 ms after first upstream byte. Median upstream-headers and body-completion offsets were 206.542 ms and 420.191 ms. Most end-to-end time is spent awaiting upstream inference; the app's measured parse/dispatch and event publication costs are far below the seconds-scale outliers.

The same-alias 20-group resource/timing artifact sampled capture-process RSS in-process: median 66.4 MB, maximum 66.6 MB across 42 warmup+measured timing records. `time.process_time_ns()` was also sampled in-process, but Windows process-time granularity produced a median of 0 ms and a p95 step of 15.625 ms; this is too coarse for per-request CPU attribution. The external `psutil` child-process CPU/RSS figures in the harness JSON are platform-inconsistent (roughly 4.4 MB RSS and 0 ms CPU versus ~66 MB in-process RSS), so they are explicitly excluded from this assessment. Gateway process CPU is therefore measured only as a coarse instrumented bound, not a reliable utilization percentage. A higher-resolution OS process counter or longer isolated block measurement is still needed for CPU acceptance.

### Original discrepancy assessment

The +1,584.7 ms figure is not a valid causal estimate: it was based on three samples, different generated token counts, and no preserved request/configuration. The matched 40-group run did not reproduce it. A later repeated trial showed rare gateway-path delays before the upstream response headers while the gateway's own measured normalization/dispatch stages remained sub-millisecond. This localizes those stalls to waiting on the upstream response, but the order dependence and small repeat do not separate LM Studio scheduling, prompt-cache state, or connection effects. Therefore the correct finding is **not reproduced and not causally resolved**, not “gateway overhead eliminated.”

## Streaming, cancellation, and failure matrix

| Case | Evidence | Result |
|---|---|---|
| Fragmented SSE event | `test_stream_is_byte_exact_and_forwards_before_sse_frame_finishes` | First chunk forwarded before frame completion; final successful client bytes exactly equal upstream bytes. |
| LF, CRLF, mixed delimiters | Boundary tests in `gateway_test.py` | Parser recognizes fragmented and mixed delimiters without changing forwarded bytes. |
| Large valid event | 100 KB event test | Forwarded incrementally; bounded side parser does not require full-response buffering. |
| Malformed SSE JSON | `test_malformed_sse_is_forwardable_but_marks_a_gap_and_unsupported_reasoning_is_ignored` | Frame bytes remain forwardable; monitor emits a gap rather than treating malformed content as success data. |
| Partial final frame | SSE boundary tests and normal iterator finalization | No invented completion; incomplete parse state is not used to fabricate content. |
| Upstream failure after response starts | `test_stream_marks_midstream_upstream_failure_and_emits_client_error_frame` | Client receives explicit SSE error; request terminal state is `failed`; upstream iterator closes. |
| Nonstream error-body interruption | `test_nonstream_upstream_error_body_interruption_is_not_reported_as_success` | Returns 502; request is failed, not completed. |
| Client cancellation | `test_client_cancellation_closes_upstream_and_marks_request_cancelled` | Cancelling downstream iteration closes upstream and records `cancelled`. A real socket-level inference-client disconnect was not separately exercised in this phase. |
| Concurrent requests | New `test_concurrent_requests_keep_inputs_and_outputs_isolated`; two concurrent real requests were also validated in Phase D | Distinct provider/internal IDs; alpha/beta input and output remain isolated. |
| Observer queue overflow | `test_observer_queues_are_bounded_and_signal_overflow` | Queue is bounded and emits explicit telemetry gap; inference lifecycle is independent of observer queue. |
| Browser disconnect during generation | Two real dashboard-tab disconnect/reconnect trials described above | Inference continued; snapshot reconciliation restored the same request and final content once. |

## Security review

- Gateway listener is loopback-only and opt-in. Upstream is fixed at startup, restricted to loopback HTTP(S), base origin only, no credentials/query/fragment; `localhost` resolution is checked and pinned to a loopback IP. Redirect following is disabled on the gateway's HTTP client.
- Inference clients do not need dashboard cookies. The gateway rejects non-JSON content, cross-site Fetch Metadata, and a mismatched `Origin`; requests with no `Origin` remain permitted for CLI/non-browser clients. No permissive CORS path was added.
- The authenticated browser monitoring API and WebSocket continue to use `web_ui_tools` protections. Tests cover unauthenticated access, same-origin behavior, WebSocket protection, and app-scoped cookie behavior in their respective suites.
- Generic gateway logs contain route/status and metadata-only timing JSON, not request bodies, reasoning, or generated text. The timing sink test asserts prompt and output sentinels are absent.
- Authorization headers are forwarded only to the configured upstream; arbitrary browser-provided upstreams are not accepted. User-supplied inference content is not echoed in error details.
- Residual limitation: API compatibility is limited to supported OpenAI chat-completions behavior; tool call assembly is partial, and no real malicious-browser-origin trial was performed beyond request-header and API security tests.

## Test and runtime validation

- `python -m pytest modules/llm_monitor/tests --basetemp=modules/llm_monitor/.pytest_tmp_d1_final -o addopts= -q` — 170 passed, 1 skipped.
- `python -m pytest modules/llm_monitor/tests/gateway_test.py -q -o addopts= --basetemp=modules/llm_monitor/.pytest_tmp_gateway` — 18 passed.
- `python -m pytest tests -q -o addopts= --basetemp=.pytest_tmp_d1` from `modules/web_ui_tools` — 14 passed.
- Runmux `llm_monitor_integration_test.py` and `web_llm_monitor_api_test.py` — 19 passed; `node tests/llm_monitor_view_test.js` — all 8 frontend suites passed.
- `python -m llm_monitor.gateway_benchmark --help` — passed; benchmark refuses live model activity unless `--run-live` is explicit and refuses fewer than 20 samples.
- `python -m ruff check llm_monitor/gateway.py llm_monitor/gateway_benchmark.py llm_monitor/web.py llm_monitor/cli.py tests/gateway_test.py tests/gateway_benchmark_test.py` — passed.
- `node tests/standalone_web_ui_test.js` — passed; Runmux `node tests/llm_monitor_view_test.js` — all 8 suites passed.
- `git diff --check` — pending final publication validation.
- Ordinary startup remained database-free by construction; no telemetry `.sqlite3` file appeared in the worktree. No full-content recording was enabled.

The full-suite first attempt used an incorrect current directory and then encountered a Windows locked pytest scratch log. Re-running from repository root with an isolated `--basetemp` completed successfully.

## Remaining limitations and merge readiness

1. Performance: median overhead below 50 ms was observed in the 40-group run, but a separate 20-group repeat had high variance and seconds-scale upstream-header waits. A controlled experiment must separate LM Studio scheduling/prompt-cache state, upstream HTTP connection reuse, and gateway route before the performance gate can close.
2. CPU attribution: Windows process-time granularity was too coarse for a stable per-request CPU percentage; in-process RSS is available. Do not use the inconsistent external psutil child-process values.
3. Client disconnect: iterator cancellation behavior is covered, but no separate real client socket disconnect was run. Browser-observer disconnect is independently validated and does not cancel inference.
4. Browser replay: reconnect reconciles bounded final snapshots; it does not guarantee replay of each missed delta or original inter-delta timing.
5. Compatibility: tool-call argument text is captured, but robust multiple-tool-call assembly and full OpenAI API parity remain outside scope.

**Assessment:** Transport and browser-observer behavior are materially hardened and test-covered. The feature remains unmerged and the Phase D.1 performance gate is open. Commit/push the validated implementation and evidence to the authorized feature branch, then stop for the next explicitly approved decision.
