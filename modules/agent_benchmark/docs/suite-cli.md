# Agent Benchmark Suite CLI

`agent-bench suite` manages persistent cohort runs on top of the existing Harbor runner. Planning, status, diagnostics, and reporting are read-only. Every inference-producing `run` or `resume` requires `-x/--execute`.

## Environment Diagnostics (`suite doctor`)

Use `agent-bench suite doctor` to inspect the local execution context, managed LLM Monitor, authentication channel, LM Studio inference provider, Docker daemon, gateway mapping, and recorder health before planning or running a benchmark:

```powershell
# Standard diagnostic overview (human-readable text)
agent-bench suite doctor

# Structured, non-mutating preflight JSON output
agent-bench suite doctor -f json

# Bounded deep diagnostics (checking loaded model catalog and Docker daemon)
agent-bench suite doctor -F --full -f json -H http://127.0.0.1:8788 -U http://host.docker.internal:8788/v1
```

### Diagnostics Characteristics
- **Strictly Non-Mutating**: `doctor` never restarts Docker, never unloads/loads models, never restarts the Monitor, never writes credentials to disk, and **never dispatches benchmark inference** (`inference_dispatched: false`).
- **Context-Aware Failure Taxonomy**: Distinguishes between:
  - `LOCAL_SOCKET_RESTRICTED` / `DOCKER_PIPE_ACCESS_DENIED`: Context-level permission denials (recommends `USE_APPROVED_HOST_CONTEXT`; does not retry).
  - `MONITOR_NOT_RUNNING`: Verified absence of local monitor service (recommends `START_MANAGED_MONITOR`).
  - `MONITOR_UNMANAGED_LISTENER`: Port occupied by an unverified foreign listener (recommends `CHECK_MANAGED_MONITOR`; never kills).
  - `MONITOR_CONFIG_MISMATCH`: Port occupied by a monitor with conflicting gateway or recording settings (recommends `FIX_CONFIGURATION`; never restarts silently).
  - `MONITOR_CONTROL_PERMISSION_DENIED`: Local named pipe / socket ACL denied (recommends `USE_APPROVED_HOST_CONTEXT`).
  - `MONITOR_RECORDER_UNHEALTHY`: Dropped observations or database flush errors (recommends `REPAIR_RECORDER`).
  - `LM_STUDIO_UNREACHABLE`: Provider refused connection or timed out (recommends `CHECK_PROVIDER`).
- **Exit Codes**: `0` when all required dependencies are ready; `1` when a known blocker is detected; `2` on invocation/argument errors.

## Cohorts and plans

```powershell
agent-bench suite list
agent-bench suite plan -c aider-python-10 -a opencode -m openai/qwen38_23GB
```

`aider-python-10` is frozen in its original order at Harbor dataset source revision `f30b14415dd733c83627204bad0af69a89ceb46f`. The plan includes the agent/model, endpoint and API format, retry policy, task identities and a stable manifest SHA-256. Harbor's own lock supplies authoritative source task checksums after a job completes; the pre-run task identity key is explicitly labeled as an identity hash, not a content digest. `-M/--manifest` accepts JSON with `id`, `dataset`, `source_revision`, and an ordered, unique `tasks` array.

Before any task is dispatched, the suite asks Harbor 0.25.0's `DatasetConfig` registry resolver for the selected task configs and verifies every task's repository and commit. It saves the exact registry bytes and their SHA-256 in the run evidence, then passes that same file to Harbor with `--registry-path`. If Harbor is unavailable, the tasks cannot be resolved, or any URL/commit differs, the run stops before inference with `DATASET_REVISION_PREFLIGHT_FAILED`. After each task, the imported Harbor lock is still checked against the pinned revision as defense in depth. Manifests targeting the frozen Aider dataset and revision receive the same pre-dispatch validation.

For a bounded revision/routing smoke once Docker and the monitor environment are available, create `aider-revision-smoke.json` with one cohort task:

```json
{
  "id": "aider-revision-smoke",
  "dataset": "aider/aider-polyglot",
  "source_revision": "f30b14415dd733c83627204bad0af69a89ceb46f",
  "tasks": ["polyglot_python_beer-song"]
}
```

First inspect route and plan, then explicitly authorize the one-task measured run:

```powershell
agent-bench suite plan -M .\aider-revision-smoke.json `
  -a opencode -m openai/qwen38_23GB -L -R content -A openai_chat_completions
agent-bench suite run -M .\aider-revision-smoke.json `
  -a opencode -m openai/qwen38_23GB -L -R content -A openai_chat_completions -j 1 -F -x
```

This smoke verifies one scored task and does not launch the full ten-task cohort. Check `manifest.json` for registry resolution and snapshot hash, `registry/registry.json` for the exact dispatched registry, the Harbor lock for its source revision, and LLM Monitor request evidence for gateway routing and recording. A successful plan or synthetic preflight alone does not establish live inference capture.

## Monitored execution & Bounded Recovery

When running a monitored benchmark suite (`-L/--llm-monitor`), the suite performs preflight verification of the gateway and recorder.

### Bounded Local Recovery (`-r / --recover-local`)
- **Authorization Separation**: `-r/--recover-local` is a dedicated authorization flag distinct from inference authorization (`-x/--execute`).
  - `suite plan -r`: If the managed Monitor is absent, starts it once with verified identity and settings, but **never dispatches inference**.
  - `suite run -r -x`: Authorizes both starting an absent Monitor (if needed) and executing benchmark trials.
  - `suite run -x` (without `-r`): Strictly fails closed if the Monitor is absent, outputting the exact start command.
- **Fail-Closed Guarantees**:
  - If a foreign listener occupies the port: fails closed (`MONITOR_UNMANAGED_LISTENER`); never kills the process.
  - If an existing Monitor has conflicting configuration: fails closed (`MONITOR_CONFIG_MISMATCH`); never restarts or alters recording mode.
  - If context denies access to Docker or local pipes: fails closed with `USE_APPROVED_HOST_CONTEXT`.
- **Automatic Auth Bootstrap**:
  - Local clients automatically acquire short-lived scoped read capabilities over the protected local control channel (Windows SID Named Pipe or POSIX AF_UNIX socket).
  - Manual cookie extraction and browser startup code entry are eliminated for local benchmark runs.
- **Task-Boundary Recorder Checks**:
  - Before each task in the cohort, the runner pings the recorder status.
  - If dropped observations increase or recording reports degraded health, the runner immediately halts dispatch and marks the task `infrastructure_invalid` with `MONITOR_RECORDER_UNHEALTHY`, preserving completed trial checkpoints and evidence.

On Windows with Docker Desktop, `-U` defaults to `http://host.docker.internal:8788/v1` for the container, while host checks use `http://127.0.0.1:8788`. Use `-H/--monitor-host-url` if the host API has a different address; older run manifests use the same loopback mapping on resume. A session cookie must come from a login to the monitor; keep it private. For example, start the monitor with `llm-monitor web -p 8788 -e http://127.0.0.1:1234 --gateway --gateway-upstream http://127.0.0.1:1234 -R content -n`, authenticate locally, and provide the resulting session cookie through `LLM_MONITOR_SESSION_COOKIE` without writing it to run artifacts.

For monitored OpenCode, the suite records the requested `openai/<model>` selector and runs the same model ID under a dedicated `llm-monitor/<model>` provider selector. This avoids OpenCode's built-in `openai` provider selecting the Responses adapter for a Chat Completions-only gateway. Earlier monitored OpenCode runs lack this immutable selector and cannot be resumed; preserve their evidence and create a new run.

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

When recording is required, the runner also checks that observed request IDs reach durable monitor history in the required mode; content mode requires observed user and assistant content. It stops further dispatch after a recording, capture, or source-revision failure. Temporal request matching cannot establish completeness when other clients use the gateway concurrently.

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

## Evidence archiving and verification

`agent-bench suite archive` preserves consistent SQLite snapshots, monitor telemetry, API observations, and optional native Harbor run logs and artifacts for completed or in-progress benchmark suite runs.

### Create an archive

By default, `archive` runs in dry-run mode, printing the resolved run configuration, database path, and planned archive location without writing files:

```powershell
agent-bench suite archive -r <RUN_ID> -F
```

To execute the archive creation, supply `-x/--execute`:

```powershell
# Archive using live monitor database discovery and recorder drain checks
agent-bench suite archive -r <RUN_ID> -x

# Include native Harbor logs, trial trajectories, and verifier outputs
agent-bench suite archive -r <RUN_ID> -N -x

# Archive an offline database or in-progress run without failing on gaps
agent-bench suite archive -r <RUN_ID> -d path/to/monitor.sqlite3 -P -x
```

Options for `create`:
- `-r, --run, --run-id`: Suite run ID or path to the run directory.
- `-d, --database`: Optional explicit path to the source SQLite database. If omitted, the database path is queried from the live LLM Monitor API.
- `-H, --monitor-host-url`: Host URL for the LLM Monitor instance (e.g. `http://127.0.0.1:8789`).
- `-o, --output`: Target archive output directory. If omitted, evidence is saved to `reports/agent-bench-suite/<RUN_ID>/evidence/<TIMESTAMP>-<UUID>`.
- `-P, --allow-partial`: Permit archiving incomplete, live, or gap-containing runs without raising an error. The resulting archive will be labeled `partial` rather than `verified`.
- `-N, --include-native`: Copy native Harbor trial directories (`harbor-jobs/`, `logs/`, `results/`), including OpenCode's native state database and trajectories.
- `-x, --execute`: Authorize writing the archive; default is dry-run.
- `-F, --llm-friendly`: Emit compact, machine-readable JSON output.

### Verify an archive

The `verify` action validates an existing archive offline:

```powershell
agent-bench suite archive verify -p reports/agent-bench-suite/<RUN_ID>/evidence/<ARCHIVE_DIR> -F
# or shorthand
agent-bench suite archive -p reports/agent-bench-suite/<RUN_ID>/evidence/<ARCHIVE_DIR> -F
```

Verification performs:
1. Directory traversal bounds checks ensuring all files reside within the archive root.
2. File existence and size matching against `archive_manifest.json`.
3. Streaming SHA-256 cryptographic hash verification for every archived file.
4. Offline SQLite database checks: `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and table row-count validation against the recorded manifest.

### Completeness and transcript truncation detection

An archive is only marked **`verified`** if all of the following conditions hold:
- Every planned task in the suite reached a terminal state.
- Every task's observed monitor request IDs exist in `inference_requests`.
- In `content` mode, every request contains non-empty recorded content segments in `inference_contents`.
- Zero content segments have `truncated != 0`.
- The live monitor recorder reported zero dropped observations, healthy worker status, and a fully drained queue.
- SQLite passes foreign key and database integrity checks.

If any of these conditions are unmet (e.g., if LLM Monitor's in-memory live buffer truncated segments or if requests lack content), the archiver explicitly records each defect under `gaps` and designates the archive **`partial`**. Database integrity checks alone never establish transcript completeness.

### Security and privacy

Evidence archives contain full prompts, assistant reasoning, generated source code, and tool calls.
- Archives must be stored exclusively in private, Git-ignored storage (such as under `reports/`).
- Do not commit evidence databases, raw transcripts, or API snapshots to Git.
- Session credentials (`LLM_MONITOR_SESSION_COOKIE`, `LLM_MONITOR_AUTHORIZATION`) are read strictly from the process environment and are never written to `archive_manifest.json` or `EVIDENCE_INDEX.md`.

