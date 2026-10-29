# Sanitized OpenCode request-forwarding report

## Scope

OpenCode 1.19.3 was run with isolated config and environment against a loopback OpenAI-compatible mock. The capture script persisted only HTTP method/path, model ID, root field names, tool count, and allowlisted scalar parameters. It retained no prompts, request bodies, responses, headers, credentials, or source files. Results are in [`request_parameters.json`](request_parameters.json).

The mock returned a fixed successful streamed completion. It validates serialization from OpenCode to an OpenAI-compatible endpoint only. It does not test LM Studio or Qwen.

## Results

| Mock condition | Attempts / requests | Tool-bearing request | Result |
|---|---:|---|---|
| Existing alias shape, 8,192 output; tried no variant, low, medium, xhigh | 4 / 8 | 10 tools, `stream: true`, `max_tokens: 8192` | No `reasoning_effort` on any request |
| Existing alias shape, 16,384 output | 1 / 2 | 10 tools, `stream: true`, `max_tokens: 16384` | No `reasoning_effort` |
| Explicit model reasoning capability and low/medium/xhigh variants selected by OpenCode CLI | 3 / 6 | `reasoning_effort` matched each selected value; 10 tools | All three values forwarded |
| Explicit `none` model variant at 16,384 output | 1 / 2 | `reasoning_effort: "none"`; 10 tools | `none` serialized; meaning at LM Studio is unverified |
| Agent config `variant: low` | 1 / 2 | No `reasoning_effort` on the 10-tool request | `low` appeared on the no-tool request only; this path is not a reliable worker control in this probe |
| Model-level `options.reasoningEffort: low` | 1 / 2 | `reasoning_effort: "low"`; 10 tools | Forwarded on the tool-bearing request and the no-tool request |

All 11 `opencode run` attempts exited 0 and produced 22 sanitized requests. The earlier checkpoint count of 18 requests across nine CLI sessions covers the first four table conditions. The two later one-attempt scenarios (`agent variant: low` and model-level `options.reasoningEffort: low`) add two sessions and four requests, reconciling the current total to 22/11. The adapter path was `POST /v1/chat/completions`; every capture used `stream: true`. Configured output ceilings 8,192 and 16,384 appeared as matching `max_tokens` values. The no-tool and tool-bearing requests were not correlated to internal message/session roles, so the no-tool request is not attributed to a specific OpenCode subsystem.

The supported experiment profile therefore writes `reasoningEffort` to the exact model's project-local `options`, and records it as a **requested** value. It does not equate selection with delivery or model acceptance.

## Exact local model metadata

Read-only LM Studio 0.4.26.0 `/api/v1/models` metadata for `qwen38-27b-q4km` reports Q4_K_M, 98,304 context, reasoning `allowed_options: ["off", "on"]`, and default `"on"`. This is exact-model capability metadata. Direct `/v1/chat/completions` acceptance and behavior are reported separately in [`direct-model-findings.md`](direct-model-findings.md): `none` was supported and produced zero reasoning tokens in the probe; low/medium/xhigh were accepted but not behaviorally verified; literal off/on were rejected. These direct results do not establish live OpenCode request acceptance or coding reliability.

## Source cross-check

OpenCode v1.19.3 prepares options by merging provider, model, agent, and selected session-variant options before calculating `maxOutputTokens` and invoking the provider adapter ([request preparation](https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/packages/opencode/src/session/llm/request.ts)). Provider capability and variant generation depend on model reasoning metadata ([provider transform](https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/packages/opencode/src/provider/transform.ts)). The mock capture is the wire-level check for this exact OpenCode version; source review alone is not treated as proof of delivery.

## Reproduction

From the isolated worktree:

```powershell
python -B experiments/qwen_runtime_investigation/request_capture.py `
  --output-file experiments/qwen_runtime_investigation/evidence/request_parameters.json `
  --opencode-exe "$env:APPDATA/npm/node_modules/opencode-ai/bin/opencode.exe"
```

The run starts only synthetic OpenCode CLI sessions and an isolated local mock provider. No LM Studio inference or GPU work is performed.
