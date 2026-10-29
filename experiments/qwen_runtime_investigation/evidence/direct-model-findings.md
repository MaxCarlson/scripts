# Direct LM Studio findings

Date: 2026-10-29 (UTC)

## Runtime identity and scope

- LM Studio: 0.4.26.0; OpenAI-compatible route: `POST /v1/chat/completions`.
- Loaded API model alias: `qwen38_23GB`; exact local key: `qwen38-27b-q4km`.
- Model: Qwen3.8 27B, GGUF, Q4_K_M; LM Studio reported 98,304 context, IDLE, parallelism 4.
- `/api/v1/models` advertised reasoning choices `off` and `on`, default `on`.
- GPU snapshot: RTX 5090 at 30,045 / 32,607 MiB, 6% utilization. WDDM did not provide inference-level attribution; no claim that this memory belongs to these probes.
- The existing OpenCode server on 4096 was left untouched. It reported no active sessions before probes. These were direct LM Studio calls; no OpenCode worker ran.

Each probe used the same short arithmetic prompt, temperature 0, seed 17, and `max_tokens=8192` for the deterministic comparison. The prompt and generated text were not retained. Sanitized per-attempt records are the adjacent `direct-*.json` files.

## Reasoning-effort acceptance and behavior

| `reasoning_effort` | HTTP | Finish | Reasoning tokens | Completion tokens | Correct answer | Interpretation |
|---|---:|---|---:|---:|---|---|
| omitted, seed 17 | 200 | stop | 65 | 71 | yes | Baseline reasoning on |
| `low`, seed 17 | 200 | stop | 65 | 71 | yes | Accepted; no observed effect in this deterministic prompt |
| `medium`, seed 17 | 200 | stop | 65 | 71 | yes | Accepted; no observed effect in this deterministic prompt |
| `xhigh`, seed 17 | 200 | stop | 65 | 71 | yes | Accepted; no observed effect in this deterministic prompt |
| `none`, seed 17, 8,192 max | 200 | stop | 0 | 4 | yes | Accepted and behaviorally effective; reasoning output was disabled |
| `none`, seed 17, 16,384 max | 200 | stop | 0 | 4 | yes | Accepted; same short completion, so this verifies ceiling acceptance only |
| `off`, seed 17 | 400 | — | — | — | — | Rejected by this API request; error body not retained |
| `on`, seed 17 | 400 | — | — | — | — | Rejected by this API request; error body not retained |

Preliminary unseeded calls varied substantially: omitted produced 46 reasoning / 52 completion tokens; `low` produced 26 / 32; `medium` 71 / 77; `xhigh` 62 / 68. Since the same prompt became identical under fixed sampling for omitted/low/medium/xhigh, the unseeded differences are not evidence that those effort values were honored. Current classification: `none` is supported and behaviorally verified; low/medium/xhigh are accepted but their effect is unverified and absent in the deterministic probe; literal off/on are rejected on this route even though inventory metadata advertises them.

This is a one-prompt behavioral probe, not proof that effort levels can never affect another task or decoding configuration. It does show that the metadata choice vocabulary does not map literally to this OpenAI-compatible field. The distinct catalog item `qwen/qwen3.8-27b` advertises different capabilities and is not evidence about this loaded Q4_K_M instance.

## Streaming response

The seeded, omitted-effort streaming probe returned HTTP 200, `finish_reason=stop`, and `[DONE]`. It delivered 65 reasoning deltas (186 reasoning characters) separately from 3 ordinary-content deltas (3 characters), with 65 reasoning and 71 completion tokens in usage. First event arrived at 0.172 s; stream ended at 0.781 s. The final answer was independently checked as `437`. No prompt or generated text was persisted.

Both `max_tokens=8192` and `max_tokens=16384` returned HTTP 200. Because the deterministic answer used only four completion tokens with reasoning disabled, this confirms request acceptance, not sustained generation or coding performance at either ceiling.

This confirms the direct LM Studio streaming API can deliver separated reasoning and answer events for the exact model. It does not validate OpenCode's SSE handling; that requires the coordinated OpenCode inference when the LLM Monitor observer is ready.

## Reproduction

From the isolated investigation worktree, run one request at a time:

```powershell
python experiments/qwen_runtime_investigation/direct_probe.py --max-tokens 8192 --output experiments/qwen_runtime_investigation/evidence/direct-baseline.json
python experiments/qwen_runtime_investigation/direct_probe.py --effort none --max-tokens 8192 --output experiments/qwen_runtime_investigation/evidence/direct-none.json
python experiments/qwen_runtime_investigation/direct_probe.py --effort low --max-tokens 8192 --output experiments/qwen_runtime_investigation/evidence/direct-low.json
python experiments/qwen_runtime_investigation/direct_probe.py --max-tokens 8192 --stream --output experiments/qwen_runtime_investigation/evidence/direct-stream.json
```

The script fixes temperature at 0 and seed at 17. It stores only request scalars, status, token counts, finish reason, safe content-presence/count fields, correctness, event counts, and timings. HTTP error bodies, prompts, and completion text are discarded.
