# Local LLM Runtime Operations — Windows/PowerShell Runbook

**Environment:** Windows 11, PowerShell 7, LM Studio, OpenCode, `local-agent`, `llm-monitor`, and Agent Benchmark.

**Purpose:** Manage the local inference environment confidently and independently, diagnose common failures, and collect reproducible evidence during coding-agent experiments.

## 1. Runtime architecture and identifiers

The components have separate responsibilities:

| Component | Responsibility | Typical endpoint |
|---|---|---|
| LM Studio / `llmster` | Loads models and runs inference | `127.0.0.1:1234` |
| `lms` | CLI for LM Studio model/server lifecycle | Local CLI |
| `local-agent` | Model aliases, configuration verification, bridge orchestration and OpenCode attachment | CLI |
| OpenCode | Coding sessions, inference requests, tool execution | `127.0.0.1:4196` (experiment) |
| `llm-monitor` | Read-only observations and optional telemetry recording | Connects to OpenCode |
| `agent-bench` | Disposable tasks, independent verification and scoring | CLI |

The ordinary OpenCode server on port **4096** is separate from the experimental server on **4196**. Do not stop or reconfigure 4096.

### Model identifiers are not interchangeable

For the current Qwen setup:

- Downloaded LM Studio model key: `qwen38-27b-q4km`
- Loaded instance identifier: `qwen38_23GB`
- OpenCode model alias: `qwen38_23GB`
- Model file: `Qwen3.8-27B-Q4_K_M.gguf`

Use the downloaded model key when loading a model. Use the **loaded instance identifier reported by the current inventory** when unloading. Use the configured OpenCode alias when choosing or verifying the OpenCode model.

Do not infer identifiers from a display name or replace underscores with hyphens.

## 2. LM Studio CLI — essential commands

### Inspect runtime state

```powershell
lms --help
lms daemon status --json
lms server status --json --quiet
lms ls
lms ps
lms ps --json
```

Interpretation:

- `lms ls`: models available on disk.
- `lms ps`: models currently loaded into memory.
- `lms daemon status`: whether the headless daemon is running.
- `lms server status`: whether the HTTP inference server is running.

**A closed HTTP port does not prove a model is unloaded.** Model residency, daemon state and HTTP server state must be checked separately.

For easier inspection:

```powershell
lms ps --json | ConvertFrom-Json | Format-List *
```

If `lms ps` fails, capture stderr and its exit code. Investigate daemon state rather than treating the absence of an inventory as an empty inventory.

### Load the current model

First confirm it appears in `lms ls`. Then:

```powershell
lms load qwen38-27b-q4km `
    --identifier qwen38_23GB `
    --context-length 98304 `
    --gpu max
```

Verify with a fresh `lms ps --json` response. The requested context is not sufficient evidence that the model was actually loaded with that context.

A pre-load memory estimate is available:

```powershell
lms load qwen38-27b-q4km `
    --context-length 98304 `
    --gpu max `
    --estimate-only
```

The estimate is advisory, not measured peak memory.

### Unload the current model

**Use the loaded identifier, not the downloaded model key:**

```powershell
lms ps
lms unload qwen38_23GB
lms ps
```

Important observed behavior: an unsuccessful unload has returned exit code 0 while printing `Model Not Found` on stderr.

Therefore:

1. Inspect stdout and stderr.
2. Check the fresh loaded-model inventory.
3. Verify that the intended instance disappeared.
4. Measure memory reclamation when relevant.

Do not declare success from `$LASTEXITCODE` alone.

Avoid `lms unload --all` unless all loaded instances are explicitly owned by the experiment.

### Start or recover LM Studio services

```powershell
lms daemon status
lms daemon up
lms server start --port 1234 --bind 127.0.0.1
lms server status
```

Start the daemon only if necessary. Avoid restarting a healthy shared service.

For a controlled shutdown, after confirming ownership and that no clients require the service:

```powershell
lms server stop
lms daemon down
```

`lms daemon down` stops the headless daemon; it does not necessarily shut down the LM Studio GUI application.

## 3. `local-agent` — model and bridge management

`local-agent` is the repository's orchestration CLI, not a replacement for every `lms` command.

### Inspect model registrations

```powershell
local-agent model list
local-agent model verify qwen38_23GB `
    --opencode-port 4196 `
    --directory 'C:\path\to\exact\trial-workspace' `
    --context-length 98304 `
    --output-tokens 8192 `
    --json
```

Replace the trial path with the exact workspace for the experiment.

`model verify` is read-only. It compares available configuration sources and reports mismatches; unavailable runtime information remains unknown.

For an isolated experiment that deliberately routes its project configuration through the request-capture proxy (for example, OpenCode 4196 -> proxy 1235 -> LM Studio 1234), `model verify` may report the shared registration's `baseURL` (1234) against the effective project URL (1235). This is an expected project override. `--lms-port 1235` changes the verifier's expected endpoint but can still report that the shared registration uses 1234. Confirm the effective URL from the exact OpenCode project's provider configuration and validate actual proxy traffic; do not edit the shared registration just to silence this diagnostic.

Use its report to distinguish:

- Configured OpenCode model limits.
- Actual project-level OpenCode overrides.
- Loaded LM Studio context, when available.
- Missing or contradictory configuration evidence.

Exit code 0 means no mismatch detected, not that every runtime property has been independently measured.

### Full runtime startup

```powershell
local-agent run --help
```

`local-agent run` is the integrated model-configuration/load/foreground-server workflow. It supports `-M/--model-nickname`, `-m/--model`, `-c/--context-length`, `-o/--output-tokens`, `-p/--opencode-port`, and configuration-update options.

For an isolated experiment, direct its OpenCode configuration to a disposable XDG directory before starting it:

```powershell
$env:XDG_CONFIG_HOME = 'C:\path\to\trial-runtime\xdg-config'
local-agent run `
    --model-nickname qwen38_23GB `
    --model qwen38-27b-q4km `
    --context-length 98304 `
    --output-tokens 8192 `
    --opencode-port 4196 `
    --update-model-limits `
    --update-opencode-provider `
    --no-codex `
    --no-agy `
    --no-unload
```

Context and output limits are independent. Keep the limit required by the experiment: for example, 98,304 context with 8,192 output, or 16,384 output when that specific trial calls for it. Do not automatically derive one from the other.

The isolated XDG directory prevents the run from rewriting the ordinary OpenCode configuration. For a per-trial endpoint override, set `OPENCODE_CONFIG` to a separate disposable config file before startup. Inspect the effective project configuration for the exact trial directory after startup; project configuration may override user-level settings. Do not invoke the runtime workflow against shared configuration or port 4096.

## 4. OpenCode — experimental server

### Start an isolated server

After confirming port 4196 is not already in use:

```powershell
opencode serve --hostname 127.0.0.1 --port 4196
```

This is a foreground server. Use an owned terminal or supervisor to manage its lifecycle.

Do not launch a second instance onto the same port or automatically kill whichever process currently owns it.

### Inspect server health

```powershell
local-agent opencode status --port 4196 --json
local-agent opencode ping --port 4196
```

These commands do not start a server or load a model.

They verify OpenCode's health, not LM Studio model readiness.

### Attach to an existing coding session

```powershell
local-agent opencode attach `
    --port 4196 `
    --session 'ses_ACTUAL_SESSION_ID' `
    --dir 'C:\path\to\exact\trial-workspace'
```

Attachment opens OpenCode's interactive TUI. It does not automatically submit a prompt, but the TUI is not strictly read-only.

For passive observation, use `llm-monitor`.

### Troubleshooting

If OpenCode is unreachable:

1. Check `local-agent opencode status --port 4196`.
2. Confirm the listener and owning process.
3. Check the server process's working directory and environment.
4. Check authentication settings if health requests are rejected.
5. Restart only the experimental server after confirming its ownership.

Do not assume a healthy OpenCode server implies a model is loaded.

## 5. LLM Monitor — live observation and recording

Always supply the **correct OpenCode endpoint and exact project directory**.

A session ID alone is not sufficient to disambiguate every recorded session.

For the examples below, first set:

```powershell
$oc = 'http://127.0.0.1:4196'
$project = 'C:\path\to\exact\trial-workspace'
$session = 'ses_ACTUAL_SESSION_ID'
$db = 'C:\path\to\trial\telemetry.sqlite3'
```

### Discover sessions

```powershell
llm-monitor sessions `
    --url $oc `
    --directory $project
```

### Best interactive dashboard

```powershell
llm-monitor tui `
    --url $oc `
    --project-directory $project `
    --session $session `
    --database $db `
    --interval 1
```

The TUI shows session status, activity, available telemetry and historical data. It does not itself start persistent recording.

### Observe live SSE activity

```powershell
llm-monitor live `
    --url $oc `
    --project-directory $project `
    --session $session `
    --format text
```

This continuously updates a compact terminal status display until interrupted.

To allow bounded raw reasoning text to be displayed:

```powershell
llm-monitor live `
    --url $oc `
    --project-directory $project `
    --session $session `
    --format text `
    --show-reasoning
```

Raw reasoning can contain sensitive material. Do not enable or persist it casually.

For automated, bounded metadata snapshots:

```powershell
llm-monitor live `
    --url $oc `
    --project-directory $project `
    --session $session `
    --observe-seconds 120 `
    --format json
```

JSON mode is intended for structured output after the observation window. It is not the nicest interactive display.

**An established SSE connection is not proof that incremental reasoning events have arrived.** Examine stream-capability and coverage fields.

### Record telemetry to SQLite

Start the recorder **before dispatching inference**:

```powershell
llm-monitor record `
    --url $oc `
    --project-directory $project `
    --session $session `
    --interval 1 `
    --database $db
```

Run it in an independently managed process or terminal. Keep it running through the inference, then stop it cleanly.

Verify collection afterward:

```powershell
llm-monitor db check --database $db

llm-monitor history `
    --session $session `
    --url $oc `
    --database $db `
    --format json
```

For a stored diagnostic report:

```powershell
llm-monitor report `
    --session $session `
    --url $oc `
    --history `
    --database $db `
    --format json
```

If history returns `found=false`, investigate:

- Was the recorder actually running?
- Did it use the same OpenCode endpoint?
- Was the selected project/session correct?
- Is the database path correct?
- Were events collected before the recorder stopped?

Do not interpret `found=false` as zero model activity.

### Important metric distinctions

- Per-inference tokens are not session cumulative tokens.
- `finish=length` can occur in one inference without ending the entire worker session.
- Reasoning-character counts are not exact reasoning-token counts.
- A successful write tool call is not independently verified correct code.
- GPU device utilization cannot automatically be attributed to an OpenCode session.

## 6. GPU and RAM diagnosis

Useful Windows commands:

```powershell
nvidia-smi

nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu `
    --format=csv

Get-CimInstance Win32_OperatingSystem |
    Select-Object FreePhysicalMemory,TotalVisibleMemorySize

Get-Process |
    Sort-Object WorkingSet64 -Descending |
    Select-Object -First 15 Name,Id,WorkingSet64
```

For suspected LM Studio orphan processes:

```powershell
Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match 'llama|LM Studio|llmster|opencode'
    } |
    Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine
```

Windows WDDM may not expose the owning GPU process reliably. Missing PID attribution does not mean the allocation is orphaned.

If model unloading is appropriate, compare memory before and after a graceful unload.

**Resource policy:** An arbitrary 90% host-RAM figure is not a validated hardware failure threshold. Measure available physical memory, commit usage/limit, actual paging pressure and real allocation failures instead. Preserve defensible resource-admission checks and safe process lifecycle management.

Do not terminate an unidentified process merely to reclaim memory.

## 7. Standard experimental startup checklist

For every new controlled trial:

1. Check LM Studio daemon and HTTP server state.
2. Check loaded models using `lms ps --json`.
3. Correct any loaded-instance mismatch; unload/reload only owned models as necessary.
4. Verify actual model context and relevant runtime configuration.
5. Verify experimental OpenCode 4196 health.
6. Verify exact trial project and session identity.
7. Start LLM Monitor recording and any requested SSE observer before inference.
8. Dispatch only through the approved Agent Benchmark workflow.
9. Reconcile worker termination, recorded inference outcomes and independent verification.
10. Stop observers, check telemetry integrity, and preserve sanitized evidence.

Do not confuse successful startup, an HTTP connection, completed inference, completed worker session, and verified coding success. They are separate milestones.

## 8. Frequently encountered failures

| Symptom | First investigation |
|---|---|
| `lms unload` prints `Model Not Found` | Use identifier from current `lms ps`, not inferred model key |
| `lms ps` cannot return inventory | Check daemon/GUI state and capture stderr |
| LM Studio port closed but GPU memory occupied | Check model/backend processes; port state doesn't establish residency |
| OpenCode port 4196 closed | Check owned server process; start isolated server if safe |
| `local-agent model verify` reports unknown limits | Check provider reachability and project configuration |
| `llm-monitor history` returns `found=false` | Check database, recorder lifecycle, endpoint and session scoping |
| `llm-monitor live` connects but shows no reasoning | Inspect stream capability; don't invent token activity |
| Model reaches 8K/16K with `finish=length` | Distinguish inference-level reasoning exhaustion from session failure |
| Model edits but fails verifier | Preserve first-attempt verdict; use targeted, bounded repair |
| Benchmark refuses dispatch | Distinguish resource admission, permissions, stale job receipts and actual model failures |

## 9. Reference documentation

Repository:

- `modules/local_agent_bridge/README.md`
- `modules/llm_monitor/README.md`
- `modules/agent_benchmark/README.md`

Upstream documentation:

- [LM Studio CLI](https://lmstudio.ai/docs/cli)
- [LM Studio load/unload](https://lmstudio.ai/docs/cli/local-models/load)
- [LM Studio loaded-model inventory](https://lmstudio.ai/docs/cli/local-models/ps)
- [LM Studio model management REST API](https://lmstudio.ai/docs/developer/rest)
- [OpenCode server](https://dev.opencode.ai/docs/server/)

**Operating principle:** Inspect actual runtime state, act on exact identifiers, verify the resulting state, and classify failures using observed evidence—not command exit status or assumptions about model behavior.
