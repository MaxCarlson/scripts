# T5 asynchronous behavior comparison

Date: 2026-10-29. Runtime/model stayed at OpenCode 1.19.3, LM Studio 0.4.26.0, exact Qwen3.8-27B Q4_K_M key `qwen38-27b-q4km`, 98,304 context, `canonical-120s`, and the same `qwen-async-behavior` fixture with `file-tools-v1` permissions. Fixture and verifier fingerprints were `485eaf02ff324a6bf6fecd91b89a650be20790611b970c351a16aa8fe1373a67` and `ef8ef868a71de78027c581eaaa8076e87e7509f3edaa99aacbc98cad6db1bcd9` in all dispatched runs.

## Dispatched attempts

| Output ceiling | Requested reasoning | Experiment / session | Inferences | Session reasoning total | Ordinary output total | Finish reasons | Tool sequence | First edit after first inference | Worker wall time | Verifier |
|---:|---|---|---:|---:|---:|---|---|---:|---:|---|
| 8,192 | omitted/default | `EXP_20261029_162023` / `ses_e778985f5ffetcL9oDcc8lw5V2` | 7 | 6,564 | 1,586 | 6 `tool-calls`, 1 `stop` | read ×5, glob, read, write, read | 71.953 s | 84.3 s | pass |
| 8,192 | explicit `none` | `EXP_20261029_162237` / `ses_e77877a1bffegvTQ9XEDMweIYy` | 5 | 0 | 1,404 | 4 `tool-calls`, 1 `stop` | read, write, write, read | 6.928 s | 16.6 s | pass |
| 16,384 | omitted/default | `EXP_20261029_162427` / `ses_e7785c9c0ffex6Z06PQm28SEg5` | 6 | 5,716 | 1,560 | 5 `tool-calls`, 1 `stop` | read ×5, edit, read | 57.210 s | 69.8 s | pass |
| 16,384 | explicit `none` | `EXP_20261029_162618` | 0 | — | — | — | — | — | — | not dispatched |

The token totals in the table are session sums across the stated number of inferences; they are **not** a single inference's use of its output allowance. At 8,192, the baseline's longest inference was 63.086 s with 6,077 reasoning and 516 ordinary output tokens (6,593 combined), ending `tool-calls`. At 16,384, the baseline's longest inference was 50.317 s with 5,170 reasoning and 683 ordinary output tokens (5,853 combined), also ending `tool-calls`. Neither baseline had `finish=length`. The `none` 8,192 run reported zero reasoning in each inference. Per-inference inputs, outputs, reasoning, finish reasons and timing are preserved in the associated `monitor-report-t5-*.json` files.

The 16,384 `none` launch was stopped by the benchmark's pre-dispatch RAM safety check at 90.2% host utilization against the configured 90% limit. It created no worker session and dispatched no inference. The safety limit was not overridden and the condition was not retried. The resulting experiment record is infrastructure, not model evidence.

## Interpretation

On this fixture, explicit `none` preserved correctness at 8,192 while reducing first-edit delay from about 72 seconds to about 7 seconds, reducing the session from 7 to 5 inferences, and eliminating the baseline's five reads before its first write. The default 8,192 run spent 6,077 reasoning tokens in one inference before producing the write tool call. This is a strong efficiency signal from one matched pair; it did not produce a reasoning-only `finish=length` failure, so it does not yet prove prevention of the historical failure.

The default 16,384 attempt also passed, with 5,170 reasoning tokens in its longest inference and an edit after about 57 seconds. Because the matched `none` 16,384 attempt was blocked before dispatch, there is no agentic evidence that suppression changes correctness or latency at that ceiling. Do not infer a 16,384 benefit from the larger allowance alone.

## Monitoring and request settings

Monitor persisted history coverage is complete for all three dispatched sessions; recording started before dispatch. Device telemetry sampled the RTX 5090 at roughly 28.78–28.88 GiB used and 1–97% load for baseline 8,192, 28.82–29.04 GiB and 1–89% for `none` 8,192, and 28.80–29.36 GiB and 7–97% for baseline 16,384. These measurements include pre/post windows and are device-level, not attributable to one process or inference. Process GPU-memory records did not provide usable memory values.

Trial-local configs recorded the output ceilings and reasoning modes. The scalar-only LM Studio log observer yielded no live request fields. OpenCode's mock-provider capture verifies the expected `max_tokens` and optional `reasoning_effort` serialization path, but the actual fields on these three LM Studio requests remain unverified. The `none` behavioral effect is independently supported by direct probes of this exact GGUF and by zero reported reasoning in the agentic 8,192 run.

## Decision

Keep `reasoning_effort=none`, context 98,304, and output 8,192 as the leading Qwen screening candidate. Do not yet call it reliable: one T5 `none` success is still one observation. A future paired 16,384 experiment should wait until the benchmark's RAM preflight clears naturally. For the next engineering step, repeat the 8,192 `none` async condition only after the host safety guard permits it; then target a reproducible no-edit fixture matching the historical combined lifecycle/polling workload. Defer alternative models and automatic prompt rewriting. The observed five-read delay under default justifies evaluating a bounded reconnaissance/early-edit workflow if `none` is unavailable or the combined regression still stalls, but this comparison did not change task instructions and is not a controlled workflow intervention.

## Fresh repeats after RAM unload/reload

The later repeats, including per-attempt input/reasoning/output totals, finish
sequences, first successful write latency, scope status, RAM observations, and
the B1 analogue, are recorded in [`ram-b1-t5-checkpoint.md`](ram-b1-t5-checkpoint.md).
In brief: default produced one new no-edit 8K `finish=length` and one code-pass
that was correctly left unscored after a malformed write target; its earlier
baseline passed. `none` produced one incorrect async contract and one pass; its
earlier baseline also passed. Among scored attempts, default was 1/2 and `none`
was 2/3. The default unscored attempt stays outside the denominator. Neither
condition is established as reliable.
