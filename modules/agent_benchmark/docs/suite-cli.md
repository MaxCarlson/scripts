# Agent Benchmark Suite CLI

`agent-bench suite` manages persistent cohort runs on top of the existing Harbor runner. Planning, status and reporting are read-only. Every inference-producing `run` or `resume` requires `-x/--execute`.

## Cohorts and plans

```powershell
agent-bench suite list
agent-bench suite plan -c aider-python-10 -a opencode -m openai/qwen38_23GB
```

`aider-python-10` is frozen in its original order at Harbor dataset source revision `f30b14415dd733c83627204bad0af69a89ceb46f`. The plan includes the agent/model, endpoint and API format, retry policy, task identities and a stable manifest SHA-256. Harbor's own lock supplies authoritative source task checksums after a job completes; the pre-run task identity key is explicitly labeled as an identity hash, not a content digest. `-M/--manifest` accepts JSON with `id`, `dataset`, `source_revision`, and an ordered, unique `tasks` array.

The current shared Harbor runner does not expose the task Git commit override in its execution API. The suite therefore verifies the exact source revision from Harbor's lock after each one-task job and classifies any mismatch as infrastructure-invalid. A registry drift could consume inference before that mismatch is detected; use a controlled preflight or a runner with an explicit pre-dispatch commit pin when that risk is unacceptable.

## Monitored execution

LLM Monitor must already be running with its gateway enabled. Suite preflight queries the gateway `/models` endpoint, the monitor inference status, and recording status. It requires the active mode selected with `-R`; `off` never enables recording. The preflight does not send a model inference request. OpenCode runs through the Harbor `--api-format openai_chat_completions` override; conflicting `--api-format`, `--base-url`, or non-OpenAI provider model settings are rejected. There is no direct-inference fallback.

Supply `LLM_MONITOR_AUTHORIZATION` or `LLM_MONITOR_SESSION_COOKIE` when the local monitor API requires authentication. These values are used only for the preflight request and are never copied to run evidence. Keep the monitor dashboard bound to its configured local authenticated interface.

```powershell
agent-bench suite plan -c aider-python-10 -a opencode -m openai/qwen38_23GB `
  -L -R content
```

The run command below is the fully monitored ten-task replay command. It requires Docker, Harbor, the monitor gateway at `http://host.docker.internal:8788/v1`, and the monitor already configured for content recording. The command does not turn recording on.

```powershell
agent-bench suite run -c aider-python-10 `
  -a opencode -m openai/qwen38_23GB -L -R content -j 1 -F -B -x
```

Use `-U/--monitor-url` if the gateway has a different URL. Use `-A/--api-format` for explicit non-OpenCode protocol selection. With `-L`, OpenCode is pinned to Chat Completions to prevent a Responses API request from reaching a Chat Completions-only gateway.

## Foreground, background, status, resume

Omit `-B` to run in the foreground. `-B` starts a detached worker, redirects its output to the run's log directory, and returns its stable run ID and PID. Atomic launcher and worker locks prevent duplicate starts. The Windows detached-process lifecycle is fixture-tested. POSIX uses a new session in code but has not been validated here. Survival after OS shutdown, forced process-tree termination, or host restart is not promised.

```powershell
agent-bench suite status -r <RUN_ID> -F
agent-bench suite resume -r <RUN_ID> -F -x
agent-bench suite resume -r <RUN_ID> --retry-invalid -x
agent-bench suite report -r <RUN_ID> -F
agent-bench suite report -r <RUN_ID>
```

Status reconciles the recorded worker PID and lock with the durable checkpoint. A run interrupted between tasks can resume pending tasks without redispatching accepted completed trials. Valid coding failures and timeouts remain completed scored outcomes. `--retry-invalid` permits one explicit retry of each infrastructure-invalid task and preserves the previous attempt in checkpoint history. A task left in `running` after a worker crash is treated as uncertain and is not automatically replayed; reconcile its native Harbor job and evidence before changing that checkpoint.

## Compact agent output and evidence

`-F/--llm-friendly` disables tables/progress and emits compact JSON output, including one `started` event, one `task_done` event per task and one `finished` summary. It redirects Harbor stdout/stderr to per-task logs (merged as `logs/<task>.log`) and never prints prompts, generated code, or reasoning. `external run -F` uses the same file-backed capture behavior without changing its execution semantics.

Each run directory contains:

- `manifest.json`: immutable resolved workload, configuration, source identity, protocol provenance and fingerprint.
- `checkpoint.json`: atomic task-level state, timestamps, verifier status, trial IDs, artifacts, errors and retry history.
- `report.json`: compact aggregate and per-task evidence summary.
- `monitor-preflight.json`: effective gateway and recording configuration when monitoring is required.
- `logs/`: task, worker stdout and worker stderr logs.
- `harbor-jobs/` and `results/`: native Harbor jobs and imported canonical records.

The preserved historical OpenCode evaluation remains untouched under `reports/harbor/opencode-baseline-10/`. Its reclassified outcome is three valid passes and seven infrastructure-invalid attempts; the original raw Harbor failures remain available beside the forensic classification. The suite CLI does not rewrite or silently import that historical record.

Pass rate uses only valid scored attempts. Infrastructure-invalid attempts are separate; coverage is reported against planned tasks. Harbor and LLM Monitor token metrics are reported separately when available, with discrepancies listed rather than silently choosing a source. Coordinator output token reduction is explicitly `not_measured`; it is distinct from model inference token usage. Monitor preflight verifies reachability, effective selected URL/protocol, model inventory, availability, live request capture, and recording health. Around each sequential task, the runner snapshots request IDs and requires at least one new ID before treating its result as captured. This is temporal evidence that the gateway observed a request; exact request-to-task attribution remains unavailable without trustworthy correlation IDs and is not inferred from GPU activity or database row counts.

## Methodology boundary and common setup failures

Presentation options `-F` and `-B` do not change task order, prompts, model, context, tool policy, verifier, scoring protocol, timeout, attempt count, or inference-output limits. `-j` controls actual concurrency; suite execution defaults to `1` and currently rejects unsupported concurrency values in the Harbor task scheduler.

Common failures include Docker or Harbor unavailable, monitor authentication required, gateway `/models` unavailable, Responses protocol selected for OpenCode, model absent from the gateway inventory, and recording mode/health mismatch. Monitoring failures block dispatch and leave a checkpoint with `blocked_monitor` status and `MONITOR_PREFLIGHT_FAILED` code. See the run directory and referenced logs before inspecting full artifacts.

## Agent handoff examples

Codex or AGY can start the authorized background run, retain the returned run ID, and poll only when needed:

```powershell
$run = agent-bench suite run -c aider-python-10 -a opencode -m openai/qwen38_23GB `
  -L -R content -F -B -x
agent-bench suite status -r <RUN_ID> -F
agent-bench suite report -r <RUN_ID> -F
```

For a compact external single-dataset run, `agent-bench external run ... -F` writes verbose Harbor output under the selected jobs directory and emits the imported summary.
