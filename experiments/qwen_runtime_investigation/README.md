# Qwen runtime investigation artifacts

This directory holds request-capture tooling, staged experiment settings, and their evidence. Reusable tasks and independent verifiers live in `modules/agent_benchmark/agent_benchmark/tasks/` and use the normal `agent-bench` trial lifecycle, S0/S1 snapshots, scope audit, hidden verifier, scoring, durable state, and benchmark_core reports.

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

Stage A began on `qwen-file-creation`. Two fresh trials at context 98,304/output 8,192 passed independent verification: the unconfigured reasoning baseline and explicit `reasoning_effort=none`. Each task used a single successful write. These two one-off completions are not reliability evidence. The Monitor captured complete persisted histories and a comparison in `evidence/telemetry.sqlite3` and `evidence/t1-monitor-comparison.json`; per-inference values and limitations are summarized in [`evidence/t1-monitor-findings.md`](evidence/t1-monitor-findings.md). The Monitor's `live` SSE command connected but exceeded its 40-second deadline, so incremental OpenCode event delivery is still unverified.

For future live observation, run the benchmark with `--pause-before-dispatch`. The `MONITOR_SESSION_READY` JSON includes the exact endpoint, project directory, session, run and benchmark trial IDs, plus a unique `monitor_trial_id`. Start the read-only observer before pressing Enter, using that value with `-T`:

```powershell
llm-monitor live `
  --url http://127.0.0.1:4196 `
  --project-directory '<project_directory>' `
  --session '<session_id>' `
  --trial-id '<monitor_trial_id>' `
  --observe-seconds 120 --format json
```

Reasoning display remains off by default. The current observer deadline issue means use persisted Monitor history for bounded trials until the observer is fixed; do not wait on or treat absent SSE deltas as evidence of no model activity.

The paired T2 repair and T4 state-machine screening is recorded in [`evidence/t2-t4-comparison.md`](evidence/t2-t4-comparison.md). Both omitted/default and explicit `none` passed both fixtures. `none` used zero reasoning tokens and fewer inferences/read-only tools, but the sample is too small to establish reliability or show a correctness difference. The next useful test is a bounded paired comparison on the async fixture; do not expand to a full matrix. Keep the 16,384 output limit as a separate variable. Use the six task definitions in `taskset.json`; do not substitute framework defaults for model, context, output, or reasoning profile.

Each `--inference-profile` is explicit and validated. Pair it with `-c 98304`; a mismatch fails before dispatch. Pass the exact LM Studio `modelKey` to `-m`, not the OpenCode alias. The profile writes the effort to the exact model's project-local `options.reasoningEffort`; mock request capture proves this reaches tool-bearing requests, while direct LM Studio and the T1/T2/T4 Monitor histories show `none` disables reported reasoning. This still does not prove the field was present on each live provider request. For one task/profile, use the normal experiment runner with dedicated state and evidence paths.

This environment's venv has an editable Agent Benchmark finder pointing at the main tree. To run the just-checked-out worktree version, remove that finder before importing the CLI:

```powershell
$env:PYTHONPATH = 'modules/agent_benchmark'
$bench = 'import sys; sys.meta_path=[f for f in sys.meta_path if "__editable___agent_benchmark" not in repr(f)]; from agent_benchmark.cli import main; main()'
python -c $bench experiment plan `
  -m qwen38-27b-q4km -t qwen-file-creation -r 1 -c 98304 `
  --inference-profile experiments/qwen_runtime_investigation/configs/qwen-unconfigured-output-8192.json
python -c $bench experiment run -x `
  -m qwen38-27b-q4km -t qwen-file-creation -r 1 -c 98304 `
  --inference-profile experiments/qwen_runtime_investigation/configs/qwen-unconfigured-output-8192.json `
  -o experiments/qwen_runtime_investigation/evidence/runs `
  -s experiments/qwen_runtime_investigation/evidence/state
```

To use the explicit no-reasoning profile, substitute `configs/qwen-none-output-8192.json` for the profile path in both commands. Monitor reports from the persisted evidence database require the endpoint to disambiguate sessions:

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
- The merged Monitor's persisted history and comparison were validated for two T1 trials. Its bounded live SSE observer failed to stop at the observation deadline while the stream remained open. Coordinate the required incremental-event check after the observer issue is resolved.
- The two T1 task successes are not enough to establish reliability or recommend an effort level. T2, output-limit comparisons, repeats, and moderate tasks remain pending.
- The harness's GPU/RAM samples are device/host-level and do not attribute usage to one model request. OpenCode token and finish-reason details depend on bridge observations; persisted Monitor history is the per-inference source.
- Benchmark comparisons remain ineligible for strict leaderboard ranking while effective runtime inference settings are unknown.
