# Phase A Findings — Provider and Host Feasibility

**Audit baseline:** `33040f00e7324d7b6ac02eae4d2e7f6ac281e667` (`main`, 2026-10-29)
**Supplied reviewed baseline:** `eeb40e8468d5fb33816caa5a8ec45f20b639c4f8`, ancestor of the audit baseline.
**Scope:** Read-only repository, CLI-help, and documentation review. No inference request, server/model mutation, database write, or production configuration change.

## Existing contracts

- `llm_monitor.providers.LMStudioClient.list_models()` uses GET `/api/v1/models` with GET `/api/v0/models` fallback. The v1 normalization distinguishes not-loaded from loaded models and reports loaded-instance counts and unambiguous configured contexts. Keep this public interface and reuse it.
- `ObservabilityService` is OpenCode session oriented. `SessionSummary` exposes `cumulative_tokens` and a token scope; `SessionDetail.context_utilization` is a list of evidence-bearing per-inference samples. It is not a canonical arbitrary-inference request model.
- `TelemetryStore` remains schema v2 and must not be instantiated by the new default web startup. Existing OpenCode tables and CLI paths remain unchanged.
- `RunmuxMonitoringAdapter` is a bounded, privacy-projected read adapter. It reads persisted alert states and does not evaluate alerts or start recording.
- `web_ui_tools.create_app` already enforces loopback-capable trusted hosts, same-origin auth, HTTP session cookies, protected WebSocket handshakes, and no-store API responses. Its cookie constant is currently fixed to `web_ui_session` in both middleware paths. Add an optional cookie name while preserving that default.
- `web_ui_tools` targets Python 3.10; `llm_monitor` requires Python 3.11+. Runmux's optional monitor integration performs guarded imports from its service methods, so an unavailable/newer-only `llm_monitor` remains optional to the Runmux package itself.

## LM Studio evidence and limitations

| Capability | Evidence | Phase B treatment |
|---|---|---|
| Model inventory | Existing client implements native v1 GET and v0 fallback; API overview recommends v1 and lists `/api/v1/models` as GET. | Automatic read-only probe at configured/default endpoint; failures are explicit `unavailable`. |
| JSON CLI log stream | Current `lms log stream` docs describe `--json` as newline-separated JSON; installed CLI help confirms `--json`, `--stats`, `--source`, and `--filter`. | Phase B does not consume logs. Preserve as a Phase C feasibility item. |
| Input log meaning | Docs call this the “formatted user input,” so it is not evidence of the original structured request. | Never label passive input as original API messages. |
| Output timing | Docs say output is emitted once the message completes; stats are included only when available. | Do not promise incremental passive output or per-request timing. |
| Stable request ID / concurrency correlation | Neither the current CLI docs nor installed help defines a stable request identifier or correlation behavior. | Treat as unknown; no request deduplication claim. |
| Native `/api/v1/chat` stream | Current docs define ordered SSE events including `chat.start`, prompt processing, `reasoning.start/delta/end`, message deltas, tool events, errors, and `chat.end`. `chat.end` contains an aggregated result. | This proves a client-facing streaming API, not passive visibility. Gateway support is deferred. |
| Native output structure | Chat docs list message, reasoning, and tool-call output item types and a loaded `model_instance_id`. | Source evidence for later gateway work only; no live request was issued. |
| Runtime event sample | Installed CLI was observed for five seconds with output-only JSON mode. No event arrived. No content was captured and the spawned CLI was stopped. | Runtime schema/concurrency/cancellation remain experimentally unverified. |

Primary sources:

- https://lmstudio.ai/docs/cli/serve/log-stream
- https://lmstudio.ai/docs/developer/rest
- https://lmstudio.ai/docs/developer/rest/chat
- https://lmstudio.ai/docs/developer/rest/streaming-events

## Verified compatibility mismatches

1. **Token summary:** Runmux renders `total_tokens` or `tokens.total`; the current `SessionSummary` returns `cumulative_tokens` as separately named categories and provides `cumulative_token_scope`. Display category values and scope; do not invent a total by summing categories whose accounting relationship is unknown.
2. **Context utilization:** Runmux checks for a scalar or ratio object; the API returns a list of per-inference objects with `utilization_percent` and observed/unknown status. Render the latest measured sample only.
3. **Loaded model identity:** `SystemSummary.loaded_models` is derived from models named by observed sessions, not a provider inventory. Expose/label those as observed session model identities; do not present them as a live loaded-model inventory.
4. **Empty alerts:** The API reads persisted alert states. An empty result means no returned persisted rows; it is not evidence of system health. The current UI says “System healthy” and must be corrected.
5. **Alert scoping:** The UI requests global persisted active alerts while displaying one selected session. Alert records include provider-instance and session identifiers; filter to the selected tuple before rendering.
6. **Cookie collision:** `web_ui_tools` hardcodes `web_ui_session`. A configurable cookie name can isolate applications; existing callers must continue to use the original default.
7. **Python floor:** `llm_monitor` requires Python 3.11 while Runmux supports 3.10. Keep web dependencies optional in `llm_monitor`; keep all `web_ui_tools` edits valid on Python 3.10; do not make Runmux import `llm_monitor` at module import time.

## Phase B boundary

The initial standalone monitor can truthfully show server reachability, model inventory, loaded instances, available context metadata, and explicitly unavailable request-capture capabilities. It cannot claim passive request transcripts, stable log correlation, live reasoning, output deltas, or measured request metrics. UI request fixtures are synthetic test inputs and are not seeded into production memory.

## Phase D/D.1 gateway capability update

These are capabilities experimentally observed through the explicitly configured OpenAI-compatible gateway, not passive LM Studio observer capabilities.

| Capability | D.1 evidence | State and limits |
|---|---|---|
| Structured input | Real requests were submitted through the gateway and reconciled from authenticated API snapshots. | Available for requests intentionally sent to the gateway; ordinary clients remain invisible. |
| Request identity/lifecycle | Gateway UUID, provider response ID, live start and terminal states observed. | Stable within the monitor; provider identity may be absent. |
| Reasoning deltas | Real Qwen requests emitted separate reasoning content, including across dashboard disconnect/reconnect. | Only when the upstream model/runtime emits a supported reasoning field. |
| Output deltas | Real output-only and mixed reasoning/output requests displayed incrementally. | Only content exposed by the upstream response is captured. |
| Tool-call deltas | Parser supports observed OpenAI-compatible tool argument deltas. | Tool-call index/name reconstruction and broad API semantics remain incomplete. |
| Usage | Provider `prompt_tokens`, `completion_tokens`, and reasoning detail fields were captured when emitted. | Completion total semantics preserved; visible output tokens remain null if reasoning accounting is not authoritative. |
| Timing | Gateway ingress, body, normalization, dispatch, upstream headers/first byte, downstream-yield, completion, event/content update, and finalization monotonic timings recorded. | First downstream time is immediately before ASGI yield, not a socket-level client receipt. Provider TTFT is null unless explicitly emitted. |
| Transport | Fragmented/mixed LF and CRLF, large frame, malformed JSON side parsing, partial upstream failure, and cancellation verified by deterministic tests. | Upstream bytes remain byte-exact on successful streaming; after a stream failure the gateway emits an explicit SSE error and records failure. |
| Browser reconnect | Closing the dashboard tab did not cancel inference; a newly authenticated dashboard reconciled request identity and full captured snapshot. | Missing intermediate deltas cannot be reconstructed from a snapshot, although tested reconnects had complete final text without duplication. |
| Persistence | Default/passive web operation and gateway test execution remain memory-backed. | No full-content persistence was introduced. |
