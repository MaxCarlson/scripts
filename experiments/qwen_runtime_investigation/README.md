# Qwen runtime investigation artifacts

This directory holds request-capture tooling, staged experiment settings, and their evidence. Reusable tasks and independent verifiers live in `modules/agent_benchmark/agent_benchmark/tasks/` and use the normal `agent-bench` trial lifecycle, S0/S1 snapshots, scope audit, hidden verifier, scoring, durable state, and benchmark_core reports.

## Latest checkpoint

The RAM-policy fix is committed as `d1e6342a` on the isolated branch. The current B1 workflow
comparison is in [`evidence/b1-workflow-comparison.md`](evidence/b1-workflow-comparison.md): three
fresh `none` trials (single-stage, one repair, and a task-derived checklist) all completed with
actionable edits but failed independent correctness. One earlier revision-1.0.0 repair passed, so
repair is feasible but not yet reliable. The comparison includes code-level causes and costs.

The RAM unload/reload measurements, controlled B1 analogue comparison, and completed T5 repeats are summarized in [`evidence/ram-b1-t5-checkpoint.md`](evidence/ram-b1-t5-checkpoint.md). The B1 default analogue reproduced reasoning-only `finish=length`; explicit `none` reached edits but failed one lifecycle assertion. In the 8K T5 repeats, both conditions had a scored pass and a scored failure; `none` was faster and reported zero reasoning, but is not yet a general reliability fix. The report preserves the distinction between the historical B1 failure and its synthetic analogue.

The bounded B1 repair, numeric reasoning-budget probes, and one plan-then-execute comparison are recorded in [`evidence/b1-repair-budget-plan-comparison.md`](evidence/b1-repair-budget-plan-comparison.md). The original `none` failure remains frozen; a separate single repair passed, while two fresh B1 attempts still failed different lifecycle assertions. Numeric `reasoning_budget` and `thinking_budget` fields were accepted but did not cap reasoning on the exact Qwen GGUF. Planning did not establish a correctness benefit.

## Offline request forwarding

Run from the isolated investigation worktree:

```powershell
python experiments/qwen_runtime_investigation/request_capture.py `
  --output-file experiments/qwen_runtime_investigation/evidence/request_parameters.json `
  --opencode-exe "$env:APPDATA/npm/node_modules/opencode-ai/bin/opencode.exe"
```

This starts OpenCode against a disposable local mock endpoint. It records an allowlist of scalar request settings and never saves prompts, request bodies, responses, or credentials. The existing capture proves OpenCode 1.19.3 serializes `max_tokens` from model output metadata. A reasoning effort is absent for an unconfigured alias and is forwarded when a reasoning capability and matching variant are explicitly configured. It cannot establish whether LM Studio or this GGUF accepts those fields.

## Direct LM Studio result

The exact loaded Q4_K_M model was probed directly. The sanitized results, acceptance classification, stream counts and reproduction commands are in [`evidence/direct-model-findings.md`](evidence/direct-model-findings.md). In brief, `reasoning_effort=none` disabled reported reasoning; low/medium/xhigh were accepted but showed no effect under fixed sampling on the probe prompt; literal off/on were HTTP 400. Direct streaming delivered separate reasoning and answer deltas. These are LM Studio observations and do not establish OpenCode or coding-task reliability.

## Staged OpenCode procedure

The isolated OpenCode 1.19.3 server ran at `http://127.0.0.1:4196`, with LM Studio at 1234 and separate XDG configuration/data/cache/state under the evidence directory. `local-agent run` verified the exact Q4_K_M model was already loaded and IDLE, so it was not reloaded. Keep the existing 4096 server untouched and run only one GPU inference at a time. Recheck model and port state before resuming.

Stage A began on `qwen-file-creation`. Two fresh trials at context 98,304/output 8,192 passed independent verification: the unconfigured reasoning baseline and explicit `reasoning_effort=none`. These two one-off completions are not reliability evidence. The Monitor captured complete persisted histories and a comparison in `evidence/telemetry.sqlite3` and `evidence/t1-monitor-comparison.json`; per-inference values and limitations are summarized in [`evidence/t1-monitor-findings.md`](evidence/t1-monitor-findings.md). A later live observation with the merged Monitor 0.6.0 observed incremental text deltas during inference. It saw no reasoning-delta events, and its effective-options report disagreed with the project config, so actual outbound reasoning-field delivery remains unverified.

For future live observation, run the benchmark with `--pause-before-dispatch`. The `MONITOR_SESSION_READY` JSON includes the exact endpoint, project directory, session, run and benchmark trial IDs, plus a unique `monitor_trial_id`. Start the read-only observer before pressing Enter, using that value with `-T`:

```powershell
llm-monitor live `
  --url http://127.0.0.1:4196 `
  --project-directory '<project_directory>' `
  --session '<session_id>' `
  --trial-id '<monitor_trial_id>' `
  --observe-seconds 120 --format json
```

Reasoning display remains off by default. The fixed observer exits at its bounded deadline. Use persisted Monitor history for completed inference details, and treat a live snapshot as incomplete when its observation window ends before the session does.

The paired T2 repair and T4 state-machine screening is recorded in [`evidence/t2-t4-comparison.md`](evidence/t2-t4-comparison.md). Both omitted/default and explicit `none` passed both fixtures. `none` used zero reasoning tokens and fewer inferences/read-only tools, but the sample alone did not establish reliability or a correctness difference.

The T5 async and output-limit screen is recorded in [`evidence/t5-async-comparison.md`](evidence/t5-async-comparison.md). At 8,192, both profiles passed once, with `none` reaching its first write in about 7 seconds versus 72 seconds for default and reporting zero reasoning. Default at 16,384 also passed. One matched `none` 16,384 attempt was pre-dispatch blocked under the then-configured 90% guard; it is an infrastructure event, not a model result. That arbitrary default guard has since been removed by `d1e6342a`; current trials record RAM as diagnostics, retain explicit user-configured thresholds, and preserve measured allocation-failure handling. Keep `none` at 8,192 as a candidate, not a proven reliable profile.

The historical Runmux B1 lifecycle/visibility no-edit failure is documented in [`evidence/historical-b1-reproduction.md`](evidence/historical-b1-reproduction.md). Its exact source baseline, selected variant, limits and per-inference exhaustion are recovered from preserved evidence; its full worker prompt and dispatch-time permission snapshot are missing. The closest reproducible analogue is the supplemental `agent_benchmark` task `qwen-runmux-polling-lifecycle`. Its reference implementation passes the independent checks; the starter intentionally fails. The T5 repeat phase is in [`evidence/t5-repeat-attempts.md`](evidence/t5-repeat-attempts.md). Pre-dispatch RAM guard rejections and a cancelled inference are infrastructure/incomplete records, not model results. The historical default-reasoning B1 and T5 attempts did reproduce `finish=length`; the newer `none` B1 trials did not.

Each `--inference-profile` is explicit and validated. Pair it with `-c 98304`; a mismatch fails before dispatch. Pass the exact LM Studio `modelKey` to `-m`, not the OpenCode alias. The profile writes the effort to the exact model's project-local `options.reasoningEffort`; mock request capture proves this reaches tool-bearing requests, while direct LM Studio and the T1/T2/T4 Monitor histories show `none` disables reported reasoning. This still does not prove the field was present on each live provider request. For one task/profile, use the normal experiment runner with dedicated state and evidence paths.

This environment's venv has an editable Agent Benchmark finder pointing at the main tree. To run the just-checked-out worktree version, remove that finder before importing the CLI:

```powershell
$env:PYTHONPATH = 'modules/agent_benchmark'
$bench = 'import sys; sys.meta_path=[f for f in sys.meta_path if "__editable___agent_benchmark" not in repr(f)]; from agent_benchmark.cli import main; main()'
python -c $bench experiment plan `
  -m qwen38-27b-q4km -t qwen-file-creation -r 1 -c 98304 `
  -u http://127.0.0.1:4196 `
  --inference-profile experiments/qwen_runtime_investigation/configs/qwen-unconfigured-output-8192.json
python -c $bench experiment run -x `
  -m qwen38-27b-q4km -t qwen-file-creation -r 1 -c 98304 `
  -u http://127.0.0.1:4196 `
  --inference-profile experiments/qwen_runtime_investigation/configs/qwen-unconfigured-output-8192.json `
  -o experiments/qwen_runtime_investigation/evidence/runs `
  -s experiments/qwen_runtime_investigation/evidence/state
```

To use the explicit no-reasoning profile, substitute `configs/qwen-none-output-8192.json` for the profile path in both commands. Always pass `-u http://127.0.0.1:4196`; the benchmark CLI defaults to 4096, which belongs to the preserved Runmux pilot. Monitor reports from the persisted evidence database require the endpoint to disambiguate sessions:

```powershell
llm-monitor history --session <SESSION_ID> `
  --database experiments/qwen_runtime_investigation/evidence/telemetry.sqlite3 `
  --url http://127.0.0.1:4196 --format json
llm-monitor report --session <SESSION_ID> `
  --database experiments/qwen_runtime_investigation/evidence/telemetry.sqlite3 `
  --url http://127.0.0.1:4196 --history --format json
```

Run one profile at a time. Keep the plan output, exact profile file and SHA-256, `RunInfo`, per-trial lifecycle/runtime/session evidence, trial JSONL, monitor export, and independent test result together. The framework records the requested profile and exact resolved model identity; `/provider` and `/agent` observations record configured values. Request-level delivery and LM Studio acceptance require separate correlated evidence. Do not label a requested setting as effective unless the outbound request or runtime independently confirms it.

## Current limitations

- Direct LM Studio acceptance and behavior have been probed for the exact loaded Qwen3.8-27B Q4_K_M GGUF. Mock OpenCode captures establish serialization, but no live outbound request-parameter capture is correlated with an agentic trial.
- The bounded live SSE observer now works and observed text deltas during inference. It reported zero reasoning-delta events for the `none` trial. Persisted Monitor history was complete; the live snapshot was deadline-limited. The live observer's effective model options disagreed with the trial-local configuration, and no actual outbound request capture is correlated with these coding sessions.
- The matched B1 single-stage, checklist, and one-repair workflows each have one fresh trial and all failed correctness. An earlier repair on task revision 1.0.0 passed. These small samples establish neither reliability nor a robust benefit from checklist or repair.
- No local numerical reasoning-budget field tested so far was behaviorally enforced. `low`, `medium`, and `xhigh` remain unverified for this local GGUF.
- The harness's GPU/RAM samples are device/host-level and do not attribute usage to one model request. OpenCode token and finish-reason details depend on bridge observations; persisted Monitor history is the per-inference source.
- Benchmark comparisons remain ineligible for strict leaderboard ranking while effective runtime inference settings are unknown.
