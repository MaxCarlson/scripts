# Phase D Gateway Validation

**Baseline:** `966c3476a6448fcdbd095390d0c706308d8915ae`
**Branch:** `codex/llm-monitor-inference-web-20261029`
**Runtime:** LM Studio at `127.0.0.1:1234`; Qwen3.8 27B alias `qwen38_23GB`, context 98,304; OpenCode 1.19.3 at `127.0.0.1:4196`
**Gateway:** opt-in `llm-monitor web --gateway` on loopback monitor port 8788; fixed default upstream `http://127.0.0.1:1234`
**Persistence:** in-memory only; no telemetry database created.

## Implementation

- Added an explicitly enabled OpenAI-compatible `/v1/chat/completions` proxy. It forwards the original JSON body and supported request headers to one validated loopback upstream, disables redirects, preserves upstream status/body, and streams SSE frames incrementally.
- Generates an internal UUID per ingress and retains the provider response ID where returned. Structured message input, reasoning, output, tool-argument deltas, token usage, finish reason, start/end timestamps and gateway elapsed time enter the bounded `LiveInferenceStore`.
- Provider completion totals remain `generated_tokens`. Reasoning tokens are separate when the provider reports them. Visible `output_tokens` are null when reasoning shares the completion total because subtraction/accounting has not been authoritatively established.
- Added bounded per-observer WebSocket event queues at authenticated same-origin `/api/inference/v1/stream`, per-request monotonic event sequences, overflow/malformed-stream gap signals and reconnect snapshot reconciliation in the browser.
- Default `llm-monitor web` remains inventory-only. No client is redirected and no LM Studio/OpenCode configuration is changed.

## Verification results

- LLM Monitor: `python -m pytest -q -o addopts= --basetemp=.pytest_tmp_root\gw-final2 tests` — 157 passed, 1 skipped.
- Final focused gateway/API edge tests — included in the full suite; cancellation, oversize rejection, malformed/unsupported events, queue overflow and observer-capacity checks pass.
- Ruff on gateway, request models, store, web integration and gateway tests — passed.
- `web_ui_tools` suite — 14 passed.
- Runmux monitor API/integration regressions — 19 passed; Runmux monitor frontend suites — all 8 passed; standalone frontend contract test — passed.
- Real nonstreaming request through the gateway returned HTTP 200 and provider usage; API snapshot exposed a gateway UUID, provider ID, structured input, reasoning, terminal `finish_reason`, elapsed time and usage.
- Real streaming requests through the gateway returned HTTP 200 SSE with reasoning and ordinary output deltas, final usage, and terminal state. The authenticated browser connected before a real request, observed it in the request list, and displayed its input/reasoning/output; no browser page errors. Genuine screenshot: [`phase-d-real-gateway-request.png`](screenshots/phase-d-real-gateway-request.png).
- Two concurrent real synthetic requests completed with distinct provider IDs and internal UUIDs; captured ALPHA/BETA inputs remained isolated.
- One real request stopped at the provider output-token limit (`finish_reason=length`). A client cancellation unit test verifies cancelled state; an interrupted browser test also left a cancelled request, but a separate controlled midstream client-disconnect trial was not completed.
- Loopback-only upstream validation rejects non-loopback, credential-bearing, path-qualified, and portless upstream URLs. Malformed SSE produces a gap event; unknown reasoning fields are ignored. Oversized request bodies are rejected before forwarding.
- Event observer capacity is limited to eight browsers, each with a 128-event queue; event frames larger than 64 KiB are marked as gaps instead of retained in observer queues. Captured content remains bounded by the existing 2 MB store budget.
- Startup runs without gateway by default and existing lifecycle tests continue to assert no SQLite file creation.

## Performance observation

Three sequential alternating nonstreaming calls using the same PowerShell HTTP client measured direct LM Studio wall times of 932.6, 423.6 and 444.2 ms (median 444.2 ms), versus gateway wall times of 2031.3, 2025.4 and 2028.9 ms (median 2028.9 ms). The observed median delta is +1584.7 ms / 4.56× end-to-end latency. Provider generated-token counts differed between repetitions (31–43), so this is a small noisy trial, not an overhead acceptance result. The gateway path needs profiling and repeatable performance work before production performance claims.

## Remaining validation gaps

- Browser observer disconnect/reconnect during an active request has not been exercised as a dedicated trial. The implementation relies on independent bounded observer queues and snapshot polling on reconnect.
- A deterministic mock covers malformed SSE and fragmented CRLF boundaries; a controlled real truncated-upstream stream was not exercised.
- No gateway-versus-direct repeated throughput/TTFT benchmark with workload matching has been completed. The measured latency delta above is concerning and remains open.
- Matched repeated performance trials have not been completed; the existing small timing sample remains a warning, not an accepted overhead estimate.
- Multi-tool-call semantics are currently captured as concatenated argument text; tool index/name reconstruction is not implemented. Unsupported OpenAI endpoint variants are rejected by routing.

## Gate assessmen

The real end-to-end dashboard slice is demonstrated for streaming and nonstreaming calls, including concurrency and token-limit completion. Request identity is gateway-generated and stable. Provider-reported reasoning accounting is kept separate from visible-output token counts. Performance is not accepted: the small trial shows an unexplained ~1.6 s median overhead. Complete reconnect, disconnect and matched performance validation remains required before this gateway should be described as production-ready.
