# Status

**State:** Offline infrastructure and request-contract phases complete; direct LM Studio behavior probes complete; Stage A T1 screening started with two passed agentic attempts; T2 and repeatability remain pending.
**Branch:** `experiment/qwen-runtime-investigation-20261029`
**Base:** `268805c41fe4b3b0c1107452298a8a4a79978ad3`
**Worktree:** `.worktrees/qwen-runtime-investigation-20261029`

## Environment and ownership

- OpenCode CLI is 1.19.3; local-agent is 3.5.1; LM Studio is 0.4.26.0 (local executable metadata) and `lms` CLI commit `dcefd5a`.
- LM Studio API read-only metadata identifies exact loaded model key `qwen38-27b-q4km`, Q4_K_M, context 98,304, reasoning allowed options `off`/`on`, default `on`. `lms ps` reports it IDLE. This is capability metadata, not proof that OpenAI-compatible request fields are honored.
- LM Studio is reachable on 1234. The pre-existing OpenCode 1.19.3 server on 4096 was left untouched. The isolated OpenCode 1.19.3 server was started on 4196 with separate XDG config/data/cache/state under the evidence directory. The exact model was already loaded and IDLE, so `local-agent run` did not reload it. Keep inference serial and verify service state before future runs.
- GPU memory remains a device-level measurement without PID attribution; it was near 30 GiB used. No unrelated active LM Studio inference was observed. Keep inference serial and record the attribution limit.
- The merged LLM Monitor 0.6.0 source exposes the new `live` CLI. The venv executable is `C:\Users\mcarls\src\scripts\.venv\Scripts\llm-monitor.exe`; the tests used `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe`. Both import the main-tree source at `modules/llm_monitor/llm_monitor`, whose `__version__` is 0.6.0; installed distribution metadata still reports 0.1.0. Persisted `history` and `report --history` captured complete history for both T1 sessions in the independent `evidence/telemetry.sqlite3`; use `--url http://127.0.0.1:4196` to disambiguate stored sessions. `compare` output is preserved in `evidence/t1-monitor-comparison.json`. A 40-second live SSE attempt connected but did not terminate within its deadline; source inspection shows deadline checks surround, but do not interrupt, the blocking SSE iterator. The coordination agent found no direct LLM Monitor developer channel; it reports the Monitor source remains clean/pushed and the suspected defect is still present. No live OpenCode incremental event delivery is yet validated.

## Request and response contract

- The sanitized OpenCode 1.19.3 mock evidence is `experiments/qwen_runtime_investigation/evidence/request_parameters.json`; tooling is `experiments/qwen_runtime_investigation/request_capture.py`.
- Six mock configurations made 11 OpenCode CLI attempts and captured 22 sanitized `POST /v1/chat/completions` requests. All attempts exited 0. No prompts, response bodies, credentials, headers, or source content were retained.
- The configured alias with no reasoning capability/variants sent no `reasoning_effort` for requested `low`, `medium`, or `xhigh`. Explicit model variants sent each effort on tool-bearing requests. Explicit `none` also serialized as `reasoning_effort: "none"`.
- OpenCode agent `variant: low` appeared on the no-tool request but was absent from the tool-bearing request in this CLI capture. Do not use that field as the benchmark's control. A model-level `options.reasoningEffort: low` appeared on both requests and is the isolated profile mapping used by Agent Benchmark.
- OpenCode forwarded configured output limits 8,192/16,384 as matching `max_tokens`; requests used `stream: true`. The worker request exposed 10 tools. The mock response test did not establish LM Studio acceptance or Qwen behavior.
- Existing Agent Benchmark bridge tests cover provider errors, `finish=length` versus HTTP rejection, incomplete tools, terminal structured output, and fail-closed malformed observations. Live response streaming behavior remains unverified.

## Direct LM Studio behavior

- First direct probes against `qwen38_23GB` are recorded in `experiments/qwen_runtime_investigation/evidence/direct-model-findings.md` and the adjacent sanitized attempt JSON files. Exact loaded model identity, context, quantization, and advertised `off/on` capability were checked before probing.
- `reasoning_effort=none` returned a correct answer with zero reported reasoning tokens. `low`, `medium`, and `xhigh` were accepted but produced identical outputs/token counts to the omitted-field baseline under temperature 0 and seed 17 on the controlled prompt. Their effect is therefore unverified, not honored. Literal `off`/`on` were rejected with HTTP 400 on `/v1/chat/completions`, despite the inventory metadata vocabulary.
- The direct streaming request delivered separated reasoning and ordinary answer deltas, usage, `finish_reason=stop`, and `[DONE]`. This validates LM Studio's direct streaming response for the exact model, not OpenCode's parser or the Monitor's SSE observer.
- Unseeded token counts varied; they are preserved but not used as proof of effort-level effect. The direct prompt is simple and does not establish coding reliability.

## Benchmark infrastructure

- Six primary tasks are defined by `experiments/qwen_runtime_investigation/taskset.json`: `qwen-file-creation`, `py-focused-bug-fix`, `py-test-development`, `qwen-session-state`, `qwen-async-behavior`, and `py-multifile-change`. A supplemental existing-code feature task remains available as `qwen-existing-code-modification`.
- New reusable tasks and hidden verifiers are under `modules/agent_benchmark/agent_benchmark/tasks/`. The normal benchmark runner supplies fresh Git workspaces, S0/S1 evidence, scope checks, hidden verifier, first-attempt scores, durable trial records and benchmark_core reports.
- Added allowlisted `--inference-profile FILE` support to `agent-bench experiment plan/run`. It records requested context, output limit, reasoning mode/provenance and profile SHA, writes settings only to fresh project configs, and refuses a context mismatch. Profile files (98,304 context, 8,192/16,384 outputs, unconfigured/none/low/medium/xhigh) are in `experiments/qwen_runtime_investigation/configs/`.
- Async fixture verification passes inside the benchmark's isolated verifier process. The apparent hang was specific to the restricted sandbox's Windows asyncio startup; with full local execution the verifier/reference suite completed. A later full test run exposed that earlier fixture tests had generated `__pycache__` inside the shared `py-grep-smoke` seed; `prepare_workspace` copied it into workers. Seed copying now excludes `__pycache__`, `.pyc`, and `.pyo` while checkpoints still retain generated worker files for scope/audit evidence. Regression tests cover bytecode isolation. No worker or verifier process remains unresolved.
- The prior Git failure was not an ACL denial: Git for Windows reported `Filename too long` writing `.git/objects` because nested pytest temp paths exceeded its path limit. Running the same tests with a short `%TEMP%\abq-*` basetemp resolves it; no product Git workaround was justified.
- Focused validation: 218 passed, 2 skipped across new tasks/profiles/comparison, existing efficiency fixtures, verifier timeout, bridge response parsing, dispatch-timeout evidence, scheduler, runner, telemetry, and seed bytecode isolation. Ruff, `compileall`, and `git diff --check` passed. Tests explicitly bypassed the ambient editable-install finder to import this worktree's Agent Benchmark source. Running inside the restricted Windows sandbox stalls at Proactor `socketpair()` initialization; the approved local run passed.

## First agentic coding results (separate from direct probes)

- Isolated OpenCode 1.19.3 dispatched two fresh T1 (`qwen-file-creation`) trials against the exact loaded Q4_K_M model, 98,304 context, and 8,192 output limit. Independent Agent Benchmark verification passed both: baseline with no explicit reasoning profile (`EXP_20261029_152214`) and `reasoning_effort=none` (`EXP_20261029_152614`). Each made one successful write; the baseline made one read and used 3 inferences, while `none` made two reads plus one glob and used 4 inferences. Both ended with `finish=stop` and no failed tools.
- Monitor history reports complete coverage: baseline per-inference reasoning tokens were 15/45/95 and output tokens 80/135/151, with finish reasons tool-calls/tool-calls/stop. `none` reported zero reasoning tokens in all four inferences, output tokens 107/179/84/77, with finish reasons tool-calls/tool-calls/tool-calls/stop. Monitor captured timing and tool outcomes. These are one-off T1 outcomes, not reliability claims or strict comparison scores; Agent Benchmark correctly marks effective runtime settings unknown for leaderboard eligibility.
- `EXP_20261029_152031` is an infrastructure failure before dispatch caused by the monitor callback accessing a missing bridge endpoint property. The property was added with a regression test. No inference was sent; do not count it as a model failure.
- Device telemetry is present in the shared experiment database but is device-level and cannot be attributed to these sessions or the model process. Monitor evidence does not retain prompt or completion text.

## Remaining

- [x] Run a direct, short LM Studio probe for this exact GGUF: identify whether `reasoning_effort` low/medium/xhigh/none and off/on are rejected, ignored, or behaviorally effective; preserve only sanitized settings/usage/finish/timing.
- [ ] Coordinate one OpenCode inference with the LLM Monitor developer when its SSE observer is ready, to validate OpenCode incremental event delivery. Persisted Monitor history is validated for T1; its bounded `live` observer currently hangs past the deadline. No direct developer channel was available to relay the suspected defect; the user can forward the summary from `evidence/t1-monitor-findings.md`.
- [ ] Continue Stage A on T1 and T2 with bounded serial attempts and selected conditions; repeat only informative configurations. T1 has two independent one-off passes (unconfigured and `none`). T2 has not yet run. Advance complexity only when results justify it.
- [ ] Collect per-inference and session telemetry, independent correctness, time-to-first-edit, tool outcomes, and monitoring/device-attribution gaps.
- [ ] Produce root-cause categories and operating-profile recommendations. No live correctness/reliability claim is established yet.
- [ ] Review diff/status and create the requested isolated checkpoint commit when coherent and focused tests pass; do not merge. Push only after the checkpoint is verified.
