# T2 and T4 reasoning comparison

Date: 2026-10-29. Runtime: OpenCode 1.19.3 at `127.0.0.1:4196`, LM Studio 0.4.26.0 at `127.0.0.1:1234`, model key `qwen38-27b-q4km` (`qwen38_23GB`), Qwen3.8-27B Q4_K_M. All valid trials used context 98,304, output ceiling 8,192, `canonical-120s`, the same task fixture within each pair, and the benchmark's default `file-tools-v1` permissions. The model was idle before each dispatch and returned idle afterward. Trials ran serially.

Agent Benchmark recorded matching fixture and verifier fingerprints within each pair: T2 task `423c6b6a3b5e389f989cbce99fd995fc99616eca00748b2f5dc9e35731eb17c7`, verifier `1c43d430fcaff51d538355ac20520cb3387b4a446402e403a36d91d1dbb3565e`; T4 task `61dff43acae297754d08a1bd1ed11e08eb68f5210f84f1bc2c950d0154b15aae`, verifier `3f0af46198d8f5ed2113f2efba80b80cfde93dcb96f7e5f687363605e59cb672`.

## Results

| Task | Requested reasoning | Experiment / session | Inferences | Reasoning tokens | Ordinary output tokens | Finish reasons | Tool sequence | First edit after first inference | Worker wall time | Independent verifier |
|---|---|---|---:|---:|---:|---|---|---:|---:|---|
| T2 `py-focused-bug-fix` | omitted/default | `EXP_20261029_160726` / `ses_e77956060ffev9rdsXHtpgpOvz` | 5 | 339 | 544 | 4 `tool-calls`, 1 `stop` | read, glob, edit, read | 9.000 s | 14.2 s | pass; `score.py` changed |
| T2 `py-focused-bug-fix` | explicit `none` | `EXP_20261029_161042` / `ses_e77926235ffecfe7XB8TvkO1rP` | 3 | 0 | 322 | 2 `tool-calls`, 1 `stop` | read, edit | 4.696 s | 7.4 s | pass; `score.py` changed |
| T4 `qwen-session-state` | omitted/default | `EXP_20261029_161226` / `ses_e7790cd16ffeo3fyfL4HqurQpb` | 6 | 909 | 1,025 | 5 `tool-calls`, 1 `stop` | read, read, read, read, write, read | 12.293 s | 19.3 s | pass; `src/session_state.py` changed |
| T4 `qwen-session-state` | explicit `none` | `EXP_20261029_161327` / `ses_e778fe00effeuPdLN1cUixvRY6` | 3 | 0 | 549 | 2 `tool-calls`, 1 `stop` | read, write | 5.749 s | 8.9 s | pass; `src/session_state.py` changed |

The first-edit measure is relative to the first observed inference start, not to coordinator setup. Reasoning and ordinary-output columns are session sums across the listed inference counts; they are not single-inference budget consumption. Per-inference input/output/reasoning counts, durations, tool events, finish reasons, and coverage are in the paired `monitor-report-t2-*.json` and `monitor-report-t4-*.json` files. Ordinary output is Monitor's completed-message output count; reasoning is kept separate and is not included in that column. There were no `finish=length` results in these four valid trials.

Both profiles passed both tasks in this small sample. Explicit `none` produced zero reported reasoning tokens, fewer inferences and fewer read-only calls, and an earlier first edit in both pairs. The baseline also completed correctly, including T4 after 909 reasoning tokens. These four successes are promising screening evidence, not reliability estimates and not evidence that `none` is necessary for these fixtures.

## Settings and request evidence

The exact trial-local OpenCode project configs were checked. Omitted/default had output 8,192 and no `reasoningEffort`; explicit none had output 8,192, `reasoning: true`, and `options.reasoningEffort: "none"`. The matching profile hashes were `53b62d405bae38aacc43a64171e0c33ae7e6512f5f805d6f98e8cbdd55162ac0` (omitted) and `8442a059ee9809772b8e6cc149750e877549ef8f933a97bb5bcddb151c826dc6` (none). The model identity, Q4_K_M quantization, 98,304 context and 8,192 output were recorded in each benchmark `run.json`.

These are effective project configuration observations, not a live outbound-request capture. The sanitized OpenCode 1.19.3 mock capture shows this model-level `options.reasoningEffort` mapping is serialized as `reasoning_effort`, and the output ceiling as `max_tokens`. Direct LM Studio probes against this exact GGUF show `reasoning_effort=none` is accepted and reports zero reasoning tokens. However, `lms log stream --json` with both `server` and `model` sources exposed no request setting fields during the trials; the safe scalar observer retained no entries. Therefore the actual T2/T4 transport fields remain unverified at the LM Studio boundary. Do not promote the mock mapping to a per-trial transport fact.

## Monitoring and attribution

Monitor persisted history coverage is complete for all four sessions. T2 baseline history was recovered retrospectively after dispatch; its hardware telemetry is absent. T2 none and both T4 trials were attached before dispatch. Their device-level samples measured approximately 29.10–29.24 GiB used (21 points), 29.13–29.29 GiB (31 points), and approximately 29.13 GiB (22 points), respectively; observed GPU load ranged from 2–85%, 0–97%, and 0–97%. These device readings cannot be attributed to one process or inference. Process-level GPU-memory samples did not provide usable memory values. The report JSON contains the complete sampled records and coverage.

The live SSE observer was not used: the previously identified deadline issue remains unresolved, and no separate Monitor developer channel was available to relay a patch request directly. Incremental reasoning/text SSE delivery is still unverified. No prompts, assistant text, or raw reasoning were included in this comparison report.

## Infrastructure record and interpretation

`EXP_20261029_161015` is a preserved explicit-none T2 pre-dispatch infrastructure failure. A non-interactive invocation closed stdin while `--pause-before-dispatch` awaited confirmation; the harness recorded `INFRASTRUCTURE_ERROR` and no inference was sent. It is excluded from the model outcome denominator. The next fresh attempt used an interactive terminal and an attached recorder; it is separately identified above. This was not a model retry.

The two pairs support continuing with `none` as a promising candidate, but they do not yet show that reasoning suppression prevents the known Runmux exhaustion on a more demanding asynchronous task. Keep alternative-model testing deferred. Next, use the existing async fixture with one matched omitted/default versus `none` screening pair only if the active runtime remains idle and monitor capture is ready; compare first edits, repeated reconnaissance, finish reasons, and independent correctness. If both complete, repeat informative configurations before recommending a profile. If `none` still fails through no-edit exhaustion, test task decomposition/early-edit guidance before switching models.
