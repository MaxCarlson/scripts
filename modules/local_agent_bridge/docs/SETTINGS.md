# Local-model settings

Preserve the working baseline. Creating these resources does not change settings.

## Baseline from this session

The Python loader defaults to `qwen/qwen3.8-27b@q6_k`, context 32768 and GPU
offload `max`. Earlier read-only LMS output reported loaded alias `qwen38_23GB`,
Q6_K, context 32768 and parallelism 4. It also emitted home-directory EPERM warnings.
Those are point-in-time observations, not a fresh health/performance check.

| Category | Recommendation |
| --- | --- |
| Load: model, GPU, context, TTL | Keep the user's current values and existing CLI options |
| Inference: thinking and effort | Keep current behavior; verify parameter forwarding before changing it |
| Inference: sampling/output limits | Record effective values; use upstream settings only as comparison points |
| Handoff: context and task size | Supply relevant source; leave room for tool output, reasoning and response |
| Concurrency | Preserve current model configuration; begin evaluation with one worker task at a time |
| KV cache / flash attention | No changes required for skill setup or the module port |

The downloaded model key, registered GGUF variant and loaded API alias are distinct.
Use the alias OpenCode advertises for the handoff's model ID, not a guessed filename.

## Upstream comparison points

The [official Qwen3.8-27B model card](https://huggingface.co/Qwen/Qwen3.8-27B)
recommends these sampling baselines:

| Mode | Temperature | top_p | top_k |
| --- | --- | --- | --- |
| Thinking | 1.0 | 0.95 | 20 |
| Non-thinking | 0.7 | 0.80 | 20 |

The card documents `reasoning_effort` low/medium/xhigh and preserved thinking.
Support varies by inference framework. Transformers/vLLM examples do not prove
that LM Studio's installed GGUF runtime or the OpenCode provider forwards an option.
Do not copy unsupported request keys into the loader or force xhigh automatically.

Larger advertised context does not establish that a larger loaded context is useful
or fits available memory. Quantization size does not establish task accuracy.
Keep sampling/GPU configuration outside the prose worker prompt.

## Tool use and coordinator settings

Use the model's normal LM Studio chat template unless tool-call evidence shows a
formatting problem. A worker system prompt describes its job; a chat template
encodes roles and tool calls. Changing one does not replace the other. Check
[LM Studio tool support](https://lmstudio.ai/docs/developer/openai-compat/tools)
and [template guidance](https://lmstudio.ai/docs/app/advanced/prompt-template)
before treating malformed calls as a sampling problem.

The MCP `essential` profile retains the core handoff and recovery tools with fewer
advertised definitions. It changes discovery, not the OpenCode worker's permissions.
Keep it as the baseline. Configure actual worker capabilities in OpenCode.

Align observation waits with the coordinator's MCP timeout. Codex documents
`tool_timeout_sec = 60` by default; OpenCode MCP 3.0.0's `opencode_run` defaults to
600 seconds. The skill uses prompt dispatch and bounded observation to avoid that
mismatch. Confirm actual client settings before changing them; this update does
not modify running services, sampling, model context or user profiles.

## When a change is justified

First inspect the task context, actual tool errors and output. If a setting is
suspected, compare one setting at a time on the same small task. Record model/alias,
quantization, runtime, context, parallelism, effective inference options, prompt,
completion quality, total latency, retries and memory. Preserve the previous values
so the experiment is reversible. No inference/tuning has been performed here.
