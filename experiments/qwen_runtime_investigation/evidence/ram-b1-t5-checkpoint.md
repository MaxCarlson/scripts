# RAM and B1/T5 reliability checkpoint

Date: 2026-10-29. This report adds new analogue and repeat evidence; it does
not modify the preserved historical Runmux B1 verdict. All trials used the
exact Qwen3.8-27B Q4_K_M key `qwen38-27b-q4km`, OpenCode 1.19.3 on isolated
port 4196, LM Studio 0.4.26.0 on 1234, and the Agent Benchmark runner.

## Host RAM and model residency

At 98,304 context, parallelism 4, max GPU offload, F16 K/V cache, flash
attention, batch 2,048 / physical batch 512, GPU KV offload, and speculative
MTP up to 3 tokens, graceful unload of only `qwen38_23GB` changed host RAM from
81.7% used / 11.26 GiB available to 53.0% / 28.93 GiB available. The 17.67 GiB
increase in available memory is attributable to unloading the model server
allocation; dedicated GPU use fell from 30,076 to 5,264 MiB (24,812 MiB
reclaimed). The server working set disappeared. Memory Compression also fell
from 5.33 to 1.82 GiB.

Reloading the same model key and identifier at 98,304 context restored about
80.3% host use / 12.14 GiB available, 29,860 / 32,607 MiB dedicated GPU use,
and a 16.56 GiB `llama-server` working set. Runtime flags confirmed full GPU
layer offload, context 98,304, F16 K/V, `--kv-offload`, and flash attention.
LM Studio reported the matching loaded-instance settings, including parallel
4 and GPU KV offload.

During the new B1/T5 trials, host use ranged from 65.6% to 83.1%, always below
the preserved 90% guard. Sampled `llama-server` working sets grew from about
16.6 GiB after load to 18.1 GiB during the first B1 run and as high as 25.75
GiB during later T5 activity. Post-trial host availability varied widely
(11.25–21.06 GiB); it did not move consistently with server working set or
trial completion. Thus model residency is a large, measured part of pressure,
and inference can add several GiB, but the remaining host-memory variation is
not fully attributed. No unrelated process was stopped. Current evidence does
not require reducing the 98K context: all dispatched trials stayed under the
guard. Keep the guard because the available headroom depends on host state.

## Controlled B1 analogue

This is a synthetic regression analogue, not an exact replay: the original B1
prompt and dispatch-time permissions are unavailable. Both runs used the same
fixture, 98,304 context, 16,384 output, `extended-180s` budget, `file-tools-v1`,
and no seed. The runtime profile was omitted/default in the first run and
explicit `reasoning_effort=none` in the second.

| Run | Inferences and session tokens | Finish/tool activity | First edit | Worker time | Independent result |
|---|---|---|---:|---:|---|
| `EXP_20261029_173937` default | 5; input 22,100; reasoning 16,438; ordinary output 587 | `tool-calls` ×4, then `length`; 7 successful reads; no write/edit | none | 160.7 s | Failed; final inference alone used 16,384 reasoning and 0 ordinary output tokens |
| `EXP_20261029_174653` `none` | 11; input 71,371; reasoning 0; ordinary output 3,196 | `tool-calls` ×10, then `stop`; 9 reads, 1 write, 3 edits | 18.084 s | 31.8 s | Failed assertion: visible resume after an in-flight response produced 1 sample, expected 2 |

The failed `none` implementation is a model logic error, not a fixture or
missing-context problem. Its `setVisible(true)` returns while a request is in
flight but does not remember that visibility resumed. When the request
completes it schedules the normal interval instead of issuing the required one
immediate poll. The fixture instruction explicitly requires immediate resume.
The original first-attempt verdict remains failed; it has not been repaired or
rescored.

The default run reproduces the historical class of reasoning-only exhaustion:
OpenCode surfaced the final `finish=length`, the worker made no edit, and the
benchmark recorded an ordinary model failure. There is no evidence here of a
bridge or response-delivery defect. The default run's 16,438 reasoning tokens
are a session sum; only the final inference consumed the 16,384-token output
ceiling.

## T5 8,192-token repeats

All repeats used the same `qwen-async-behavior` fixture, 98,304 context,
`canonical-120s`, `file-tools-v1`, no seed, and the 90% guard. The first row in
each condition is the earlier baseline; the next two are fresh repeats.

| Condition / run | Inferences; input / reasoning / output tokens | Finish and tool activity | First successful write | Worker time | Verdict |
|---|---|---|---:|---:|---|
| default `EXP_20261029_162023` | 7; input not retained in summary / 6,564 / 1,586 | 6 `tool-calls`, `stop`; read ×6, glob, write, read | 71.953 s | 84.3 s | pass |
| default `EXP_20261029_174944` | 4; 14,059 / 8,284 / 358 | `tool-calls` ×3, `length`; read ×4, glob; no edit | none | 87.0 s | fail; final inference used 8,192 reasoning tokens and left `NotImplementedError` unchanged |
| default `EXP_20261029_175231` | 7; 53,482 / 8,365 / 1,685 | `tool-calls` ×3, `length`, `tool-calls` ×2, `stop`; read ×6, malformed write, valid write | 90.922 s | 100.3 s | unscored; code verifier passed, but one malformed/missing write target made scope unknown |
| `none` `EXP_20261029_162237` | 5; input not retained in summary / 0 / 1,404 | 4 `tool-calls`, `stop`; read, write ×2, read | 6.928 s | 16.6 s | pass |
| `none` `EXP_20261029_175528` | 7; 28,751 / 0 / 1,669 | 6 `tool-calls`, `stop`; read ×6, write ×2 | 8.834 s | 18.2 s | fail; implementation passed scope but rejected because `worker` was not awaitable |
| `none` `EXP_20261029_175658` | 3; 9,443 / 0 / 604 | 2 `tool-calls`, `stop`; read, write | 5.394 s | 9.1 s | pass |

The repeated default condition produced one no-edit `finish=length` and one
code-positive but scope-unscored outcome; the earlier baseline passed. The
repeated `none` condition produced one incorrect implementation and one pass;
the earlier baseline also passed. Among scored attempts, default was 1/2 and
`none` was 2/3. This small sample is not a reliability claim. `none` consistently
reported zero reasoning and reached a successful write much sooner, but did
not guarantee correctness. Default reasoning was slower and reproduced a
no-edit exhaustion. Stop further default repetitions here.

## Telemetry, request evidence, and current recommendation

Historical Monitor recording was started before each dispatched trial. All
eight queried B1/T5 histories are idle with complete one-page coverage and zero
reported gaps; histories contain per-inference token counts, finish reasons,
and tool states. Device GPU readings are device-wide and cannot be assigned to
one process or inference. The one
`llm-monitor live` observer on the completed default B1 session produced no
snapshot by its 120-second deadline and was terminated; SSE deltas remain
unobserved, not absent. The imported Monitor source is 0.6.0 from the main
worktree while installed distribution metadata reports 0.1.0; telemetry here
came from that imported source.

The prior mock-provider evidence still shows that the standard OpenCode alias
omits `reasoning_effort` for selected `low`/`medium`/`xhigh`; explicit
per-model configuration serializes it. Direct probes of this exact GGUF show
`none` is behaviorally effective and direct history confirms zero reasoning in
these agent runs. `low`/`medium`/`xhigh` remain behaviorally unverified.
Numerical thinking-budget enforcement independent of `max_tokens` has not yet
been tested against this loaded GGUF/runtime.

Keep 98K context and the 90% guard. Treat explicit `none` at 8K as the leading
screening profile for small bounded tasks with an independent verifier, not as
a general reliability fix. The actionable next experiment is a fresh B1
`none` implementation with the original failed verdict preserved, one bounded
repair using the verifier's exact visible-resume assertion, and a separate
second verification. Report initial and repaired correctness, extra inference
tokens, and time independently. Do not start a larger workflow matrix until
that checkpoint is reviewed. No bridge code change is justified yet.
