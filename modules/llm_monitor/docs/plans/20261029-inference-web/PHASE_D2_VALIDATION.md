# Phase D.2 — Final Gateway Performance Qualification

**Branch:** `codex/llm-monitor-inference-web-20261029`
**Baseline:** `8b1195d423b589911f4e706195572d5579393eeb` (Phase D.1)
**Runtime:** LM Studio CLI commit `dcefd5a`; model `qwen38-27b-q4km`, loaded instance `qwen38_23GB`; context 98,304; parallel capacity 4; eval batch 2,048.
**Decision:** Performance and functional gates accepted for merge review. No merge was performed.

## Result

The seconds-scale response-header stalls from D.1 did not recur in the D.2 controlled trials. In the principal repeated comparison (20 paired triplets per mode), observed gateway versus direct had a median paired delta of **−2.33 ms** nonstreaming (bootstrap 95% median interval −5.85 to +2.44 ms) and **+2.08 ms** streaming (interval +0.33 to +7.52 ms). No paired observed-minus-direct difference exceeded 100 ms, and no request on any path exceeded one second in these trials. The extra observation path over the minimal forwarder added a +1.04 ms nonstreaming median and +1.74 ms streaming median.

This qualifies the gateway under the acceptance rule in the D.2 assignment: there is no reproducible gateway-specific regression, the median remains well inside the provisional 50 ms target, and the prior tails are characterized without asserting an unverified LM Studio defect. It does **not** identify the precise cause of the earlier rare stalls.

## Method and principal paired comparison

The existing opt-in `gateway_benchmark.py` harness was extended, not replaced. It uses the same synthetic request body within each direct/minimal/observed triplet, warms each route, reuses clients for the main run, counterbalances all six route orders, and reports triplet-level differences. It records monotonic stage timings and bounded metadata only; prompts and completion text are not written. Each paired confidence interval is a deterministic 2,000-resample bootstrap interval for the median paired difference. `p95` and worst case below are over the paired deltas, not raw group medians.

| Mode and comparison | n | Median added latency | 95% median interval | p95 paired delta | Worst paired delta | >100 ms / >500 ms |
|---|---:|---:|---:|---:|---:|---:|
| Nonstream, minimal − direct | 20 | −2.55 ms | [−5.74, +1.90] ms | +12.11 ms | +15.51 ms | 0 / 0 |
| Nonstream, observed − direct | 20 | −2.33 ms | [−5.85, +2.44] ms | +19.79 ms | +25.20 ms | 0 / 0 |
| Nonstream, observed − minimal | 20 | +1.04 ms | [−3.95, +7.41] ms | +18.30 ms | +21.86 ms | 0 / 0 |
| Stream, minimal − direct | 20 | +2.14 ms | [−3.36, +5.31] ms | +7.97 ms | +9.38 ms | 0 / 0 |
| Stream, observed − direct | 20 | +2.08 ms | [+0.33, +7.52] ms | +10.70 ms | +16.02 ms | 0 / 0 |
| Stream, observed − minimal | 20 | +1.74 ms | [−0.52, +5.31] ms | +12.65 ms | +16.30 ms | 0 / 0 |

Output-token counts matched across all three paths in 20/20 groups for both modes. All six request orders occurred three or four times in each mode. The short fixed, short varied, long streaming, concurrent, and fresh-connection diagnostics are recorded in separate JSON artifacts and were not pooled into the principal estimate.

## Bounded diagnostic cases

| Case | Groups; matched | Observed − direct median | p95 / worst paired delta | 95% median interval | Absolute requests >1 s |
|---|---:|---:|---:|---:|---:|
| Short fixed, nonstream | 12; 12 | +3.76 ms | +8.06 / +11.61 ms | [+0.14, +5.30] ms | 0 |
| Short fixed, stream | 12; 12 | −1.57 ms | +11.13 / +18.09 ms | [−5.65, +5.40] ms | 0 |
| Short varied, nonstream | 12; 12 | +1.45 ms | +64.83 / +74.53 ms | [−29.28, +51.39] ms | 0 |
| Short varied, stream | 12; 12 | +4.68 ms | +57.57 / +59.52 ms | [−23.03, +52.26] ms | 0 |
| Longer generation, stream | 6; 6 | +4.08 ms | +14.35 / +14.35 ms | [+0.32, +12.26] ms | 0 |
| Two requests/path, stream | 5; 5 | +0.47 ms | +35.50 / +35.50 ms | [−0.93, +35.50] ms | 0 |
| Fresh connections, stream | 8; 8 | −0.55 ms | +18.77 / +18.77 ms | [−23.50, +15.09] ms | 0 |

The varied-prompt intervals are wide at these small sample sizes, but their median deltas are small and no >100 ms paired added-latency event occurred. The concurrent estimate uses each path's median over two simultaneous requests per group. Fresh mode disables upstream keepalive in the gateway and creates a new client connection for each sample; it did not show a systematic gateway penalty. A further within-run alternating fixed/varied trial was attempted after these runs, but the harness refused because the model was no longer confirmed loaded. The already completed fixed and varied runs remain independent conditions; no alternating-trial result is claimed.

## Tail-latency evidence and root-cause assessment

D.1's separate repeat recorded an observed-first triplet with upstream response-header waits of 3,440 ms (observed gateway), 2,939 ms (minimal forwarder), and 418 ms (direct), all with 32 generated tokens. Another direct-first group recorded 1,103 ms direct, then 452 ms minimal and 418 ms observed. Those delays occurred before upstream response headers. The gateway's request parsing, normalization, and dispatch stages were sub-millisecond; therefore those samples do not show time spent in the gateway's content/event processing. They show time awaiting the upstream response, but that alone does not prove model computation was the cause.

Across all D.2 principal and diagnostic artifacts, there were no requests over 1,000 ms on any path and no paired observed-minus-direct outlier over 100 ms. The principal run's gateway timing medians were approximately 0.09 ms normalization, 0.13 ms upstream dispatch, 5.41 ms to upstream headers, 70.29 ms to first upstream byte, and 70.41 ms to first downstream byte. Median content-store update was 1.88 ms; event publication was 0.21 ms. This is consistent with very little local gateway overhead, though stage values are sampled summaries and not causal decomposition of provider compute.

GPU samples were device-wide `nvidia-smi` observations at roughly one-second intervals, not per-request attribution. In the principal trial, 38 samples showed 0–87% GPU utilization and about 29,319–29,604 MiB of 32,607 MiB in use. Utilization varied substantially, so unrelated work cannot be excluded. LM Studio inventory confirmed the model instance and its parallel capacity before/after each run, but the API did not expose a live queue/request counter. The [model inventory API](https://lmstudio.ai/docs/developer/rest/list) documents loaded instance configuration and parallel prediction capacity. Runtime settings remained unchanged. Provider response timings were `null` in the matched `/v1/chat/completions` responses, so provider-reported TTFT and generation speed were unavailable; LM Studio's [REST endpoint documentation](https://lmstudio.ai/docs/developer/rest/endpoints) describes timing statistics available through its native response surface, which were not present in these OpenAI-compatible responses.

The evidence supports these conclusions:

- **Gateway transport:** no repeated gateway-specific long wait found. Reused and fresh-connection comparisons both show small medians; observed processing added about 1–2 ms in the principal run.
- **LM Studio scheduling/cache:** order dependence in the D.1 anomaly is compatible with scheduling, cache, or warm-up effects, but no live queue signal or controlled internal cache counter was available. These remain plausible, unproven explanations.
- **Prompt effects:** fixed and varied short prompts both had small paired medians. The varied cases had wider uncertainty and no severe tail. No causal cache claim is made.
- **External activity/platform:** device-wide GPU samples cannot rule out other local inference activity, and Windows scheduling/local network effects were not separately traced.
- **Prior anomaly:** characterized as a rare upstream-header wait that was not reproduced in D.2; exact cause remains unknown.

## Client disconnect, browser reconnect, and regression evidence

The real TCP client-disconnect probe closed the inference client's response socket after its first text delta. The monitor recorded terminal state `cancelled`, retained the same internal request identity and captured in-memory content, and observed the upstream response stream's `aclose()` complete. The request began with HTTP 200; this is an actual client socket disconnect, separate from the D.1 browser-observer WebSocket disconnect test. D.1 browser reconnect validation remains intact: inference continued while the browser was disconnected, and snapshot reconciliation restored the same request/content without duplicated deltas.

D.1 validation covers SSE LF/CRLF fragmentation, mixed delimiters, large valid events, partial final frames, malformed monitor parsing, tool calls, concurrent streams, cancellation, upstream failures, observer queue overflow, gateway Origin/content-type checks, fixed-loopback routing, and authenticated monitor APIs. No gateway/security implementation changed in D.2; only the benchmark harness and its tests changed.

## Limitations and acceptance

- The attempted alternating-prompt run did not execute because the model was no longer confirmed loaded; no automatic load was performed.
- Five diagnostic concurrent groups and six long-generation groups are characterization, not high-confidence tail quantification.
- Device GPU metrics are coarse and global; this run cannot attribute activity to a request or identify another process.
- Provider TTFT/TPS and LM Studio queue depth were unavailable from the observed OpenAI-compatible responses/interfaces.
- Default monitoring/database behavior and authenticated API behavior were previously validated in D.1 and regression suites. The benchmark itself wrote only metadata JSON/JSONL artifacts.

**Functional acceptance: accepted.** Real TCP client disconnect cancels the request and closes the upstream stream; browser observer reconnection remains snapshot-based and independent. Existing D.1 stream-fidelity and security validations remain green.

**Performance acceptance: accepted for merge review.** The D.1 seconds-scale event did not recur; repeated paired medians are within the provisional 50 ms target, no gateway-specific regression is reproducible, and the remaining tail cause is explicitly unresolved. The available evidence does not justify blocking subsequent development pending proof of an LM Studio internal cause.

**Merge readiness: ready for review, not merged.** The feature branch remains isolated. Recommended next development priority remains real GPU/per-request analytics and historical recording, as directed; retain this report and raw metadata artifacts for later comparison.

## Artifacts and validation

- `PHASE_D2_BASELINE.json` and `_gateway_timings.jsonl`
- `PHASE_D2_SHORT_FIXED.json` and `_gateway_timings.jsonl`
- `PHASE_D2_SHORT_VARIED.json` and `_gateway_timings.jsonl`
- `PHASE_D2_LONG_STREAMING.json` and `_gateway_timings.jsonl`
- `PHASE_D2_CONCURRENT.json` and `_gateway_timings.jsonl`
- `PHASE_D2_FRESH_CONNECTIONS.json` and `_gateway_timings.jsonl`
- `PHASE_D2_SOCKET_DISCONNECT.json`
- `python -m pytest tests/gateway_benchmark_test.py -q -o addopts= --basetemp=.pytest_tmp_d2_focus2` — 10 passed.
- `python -m ruff check llm_monitor/gateway_benchmark.py tests/gateway_benchmark_test.py` — passed.
- Full module and `web_ui_tools` test commands were attempted, but the sessions stopped producing output after initial collection/execution and no pytest process remained to return a summary; they were interrupted and are not counted as passing. The combined gateway/inference-web focused invocation behaved the same way. D.1's recorded regressions were green at that checkpoint (LLM Monitor 170 passed/1 skipped, `web_ui_tools` 14 passed, Runmux API/integration 19 passed). D.2 changed only the benchmark harness and its tests; its changed-code tests and Ruff pass.
- `node tests/standalone_web_ui_test.js` — passed.
