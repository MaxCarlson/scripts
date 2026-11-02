# LM Studio Passive Capture Trial

**Date:** 2026-10-29
**Branch baseline:** `692164f90d3f171e3bea1c5b97254ef1c610e8fe`
**LM Studio CLI:** commit `dcefd5a`
**Model:** `qwen38_23GB` / `local/qwen38-27b-q4km/Qwen3.8-27B-Q4_K_M.gguf`
**Request:** one synthetic OpenAI-compatible streaming chat completion; `max_tokens=32`
**Recording:** in-memory CLI output only; no telemetry DB or transcript fixture saved.

## Sanitized source evidence

The read-only command `lms log stream --json --source model --filter input,output --stats` emitted two newline-delimited JSON records after the client request ended:

```json
{"timestamp":1793327135836,"data":{"type":"llm.prediction.input","input":"[rendered system + synthetic user prompt + assistant think prefix]","modelPath":"[local model path]","modelIdentifier":"qwen38_23GB"}}
{"timestamp":1793327135837,"data":{"type":"llm.prediction.output","output":"[completed generated text containing reasoning; redacted]","stats":{"stopReason":"maxPredictedTokensReached","tokensPerSecond":144.4198050798502,"timeToFirstTokenSec":0.301478,"totalTimeSec":0.51613,"promptTokensCount":65,"predictedTokensCount":32,"totalTokensCount":97,"totalDraftTokensCount":26,"acceptedDraftTokensCount":22,"rejectedDraftTokensCount":4},"modelIdentifier":"qwen38_23GB"}}
```

The source events had adjacent timestamps one millisecond apart and the same model identifier, but no request ID, response ID, lifecycle ID, or shared correlation token. Do not use timestamp adjacency as a general join key. This single sequential sample says nothing reliable about concurrent-request correlation. The log exposed a rendered prompt rather than structured messages. The output log was completion-only; it included generated reasoning text in a single output field. The client-facing SSE response separately streamed `reasoning_content` chunks and ended with `finish_reason=length`; the 32-token limit was consumed by reasoning before a final answer. The LM Studio log therefore does not reproduce the live client event stream.

The log contained provider statistics for this sample: prompt 65, predicted 32, total 97 tokens; TTFT 0.301478 s; total 0.51613 s; decode rate 144.4198 tokens/s; and speculative-draft counters. These values are source-reported for this request event, but cannot be attached to a stable passive request record because the event has no request identity. No usage convention for reasoning/output overlap was established by this sample.

## Capability matrix

| Capability | Trial result | Confidence / boundary |
|---|---|---|
| Input observation | Rendered prompt observed | Direct, one request; original structured messages not available. |
| Output observation | Full completed generated text observed, including reasoning text | Direct, one request; redacted from saved evidence. Completion-only in passive stream. |
| Reasoning/output separation | Not available in passive log schema | Client SSE exposed `reasoning_content` deltas; passive output combined generated reasoning in `output`. |
| Provider request identity | Not emitted | Not observed; model identifier is not request identity. |
| Start/end boundaries | Input/output event types and event timestamps observed | No stable lifecycle ID; cannot safely pair under concurrency. |
| Token usage | Prompt/predicted/total and draft counts observed | Direct for output event; accounting overlap/meaning unverified. |
| Timing | TTFT, total time, tokens/sec observed | Direct for output event; relative to provider stats; concurrent correlation unavailable. |
| Streaming behavior | Client SSE was incremental; passive model log emitted completed records | Verified for this sample only; no passive live text deltas observed. |
| Concurrent correlation | Not tested and source lacks a visible correlation field | Must be treated unavailable; do not correlate by neighboring timestamps. |

## Gate and recommendation

The passive source contains useful completed prompt/output/statistics observations, but cannot reliably identify or correlate an individual request. The existing `InferenceRequest` and dashboard require request-level records; assigning synthetic IDs or pairing logs by time/model would fabricate identity. No passive request collector was added and no real request was inserted into the dashboard. The request-observation gate therefore fails on identity/correlation.

Next phase should be an explicitly configured, loopback-only OpenAI-compatible inference gateway with a fixed authorized upstream. Assign an internal request UUID at ingress, preserve the upstream SSE stream byte/event ordering and cancellation, and publish ordered monitor events keyed by that UUID. Keep clients opt-in; do not redirect existing traffic. Passive log events may remain uncorrelated diagnostics unless a provider version exposes a verified common request identifier.
