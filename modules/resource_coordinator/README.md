# Resource Coordinator MVP

## Command line

The CLI groups operations by intent. Human-readable, color-aware output is the
default; add `-j`/`--json` to structured commands for one JSON document on
stdout. `--color auto|always|never` controls human output. In `auto` mode,
`NO_COLOR` or redirected output disables color; explicit `always` and `never`
take precedence. Verbose transport diagnostics use stderr (`-v`/`--verbose`).
Captured miner logs remain an unformatted raw stream.

```text
resource-coordinator
├── status
├── control
│   ├── miner status|start|stop|pause|resume
│   └── gaming status|on|off
├── service restart|shutdown|abort|recover|run
├── system setup|upgrade|repair|teardown
│   ├── startup status|install|enable|disable|repair|uninstall
│   └── auth doctor|repair|reinitialize
├── config show|validate
├── check health|telemetry|preflight|accept
└── logs
```

Examples:

```powershell
resource-coordinator status
resource-coordinator control miner pause -d 2h
resource-coordinator control gaming on
resource-coordinator service restart --reason "activate reviewed settings"
resource-coordinator system upgrade --apply --json
resource-coordinator check health --json
resource-coordinator logs miner --follow
```

Existing command paths remain supported as compatibility aliases, with the
same flags and operational behavior:

| Existing path | Canonical path |
| --- | --- |
| `miner status/start/stop/pause/resume` | `control miner status/start/stop/pause/resume` |
| `gaming status/start/stop` | `control gaming status/on/off` |
| `restart/shutdown/abort/recover/serve` | `service restart/shutdown/abort/recover/run` |
| `setup/upgrade/repair/teardown` | `system setup/upgrade/repair/teardown` |
| `startup <action>` | `system startup <action>` |
| `auth <action>` | `system auth <action>` |
| `doctor/diagnose/preflight/accept` | `check health/telemetry/preflight/accept` |
| `config show/validate`, `status`, `logs` | Unchanged |

`serve` remains supported for existing managed launchers. `service restart`
restarts the running coordinator; `system upgrade` activates updated code.
`service recover` clears a safety inhibition only through its existing
authorization checks. These operations are deliberately distinct.

The Resource Coordinator is a loopback reverse proxy for LM Studio that pauses
one coordinator-owned Windows process while protected model work is active. It
restarts that process after the configured idle cooldown. Use it with a process
that supports the configured Windows console stop mechanism; keep force
termination and external process control disabled.

## Configure one process

Create `config.local.yaml` in this directory. Git ignores that machine-local
file. Replace the executable, arguments, and working directory with the exact
values for the process you intend the coordinator to launch and own.
For `config validate`, `preflight`, and `serve`, always pass
`-c .\config.local.yaml`: the built-in legacy default includes a Krig process
definition.

```yaml
version: "1.0"

service:
  listen_host: "127.0.0.1"
  listen_port: 1235
  upstream_url: "http://127.0.0.1:1234"

processes:
  background_worker:
    backend: windows
    executable: 'C:\Tools\worker.exe'
    arguments: []
    working_directory: 'C:\Tools'
    stop_timeout_seconds: 10
    new_console: false
    adopt_external: false
    allow_external_stop: false
    allow_external_restart: false
    allow_force_termination: false

policies:
  - name: pause-for-inference
    trigger_event: lmstudio.inference_requested
    target_process: background_worker
    resource: gpu.inference
    lease_type: shared
    stop_process: true
    restart_process: true
    only_if_stopped_by_coordinator: true
    stop_timeout_seconds: 10
    cooldown_seconds: 300

  - name: pause-for-model-load
    trigger_event: lmstudio.model_load_requested
    target_process: background_worker
    resource: gpu.inference
    lease_type: exclusive
    stop_process: true
    restart_process: true
    only_if_stopped_by_coordinator: true
    stop_timeout_seconds: 10
    cooldown_seconds: 300
```

The two policies must target the same process and use the same positive
`cooldown_seconds`; that value is the authoritative idle timeout. The process
`stop_timeout_seconds` sets the stop attempt during normal service shutdown;
each policy's `stop_timeout_seconds` sets its stop-before-request attempt. Both
are attempt/verification timeouts, not guaranteed total shutdown bounds. The
legacy process field `restart_cooldown_seconds` is parsed but unused; omit it.

`new_console: false` gives the Windows backend a process group for graceful
Ctrl+Break delivery. The target must handle that signal and exit with its child
processes. If verification fails, the request is not forwarded. Force
termination remains disabled in this example. `adopt_external` and the
external stop/restart permissions remain false so the coordinator does not
claim an already-running process by executable name.

## Validate and run

From PowerShell, using the repository's Python environment:

```powershell
Set-Location "C:\Users\mcarls\src\scripts\modules\resource_coordinator"
python -m resource_coordinator.cli config validate -c .\config.local.yaml
python -m resource_coordinator.cli preflight -c .\config.local.yaml
python -m resource_coordinator.cli serve -c .\config.local.yaml --start-process background_worker --stop-process-on-shutdown background_worker
```

`--start-process` makes the coordinator the process owner. The explicit
`--stop-process-on-shutdown` option stops that owned target on normal service
shutdown. It is not automatic process adoption. Leave the serve terminal open;
after requests finish, press **Ctrl+C once** and wait for Uvicorn/service
shutdown. Verify the recorded target PID has exited. The configured drain
timeout does not impose a strict bound on Windows/API shutdown. A crash or
forced exit does not trigger automatic reconciliation or restart.

## Route an LM Studio client through the gateway

The request path must be:

```text
OpenCode or API client -> http://127.0.0.1:1235/v1 -> LM Studio at :1234
```

For the installed OpenCode 1.19.3 config at
`%USERPROFILE%\.config\opencode\opencode.json`, change only
`provider.lmstudio.options.baseURL` from
`http://127.0.0.1:1234/v1` to `http://127.0.0.1:1235/v1`. Keep the existing
provider, model IDs, aliases, context settings, and credentials. The current
shared config was inspected read-only and was not modified. OpenCode documents
`options.baseURL` as the endpoint for an OpenAI-compatible provider.

```json
"options": {
  "baseURL": "http://127.0.0.1:1235/v1"
}
```

There is a model-key mismatch to resolve before using the current OpenCode
selection: its configured model keys are `qwen38_17GB` and `qwen38_23GB`, while
LM Studio currently lists the model as `qwen38-27b-q4km`. In OpenCode, the key
under `provider.lmstudio.models` is the model ID used in the `provider/model`
selection. Therefore changing the URL alone routes traffic through the
coordinator but may still send an ID LM Studio does not list. Do not rename the
existing entries silently. A minimal explicit OpenCode adjustment is to retain
both existing entries, add a `qwen38-27b-q4km` model entry with the same desired
display/context settings, and select `lmstudio/qwen38-27b-q4km` for the
coordinated session. The shared OpenCode file remains unchanged; make that
configuration edit only after reviewing it. See the [OpenCode model
configuration docs](https://opencode.ai/docs/models/) for the model-key rule.

For review, the scoped changes are:

```diff
- "model": "lmstudio/qwen38_23GB",
+ "model": "lmstudio/qwen38-27b-q4km",
- "baseURL": "http://127.0.0.1:1234/v1"
+ "baseURL": "http://127.0.0.1:1235/v1"
  "models": {
    "qwen38_17GB": { ... keep existing ... },
    "qwen38_23GB": { ... keep existing ... },
+   "qwen38-27b-q4km": { "name": "Local worker: qwen38-27b-q4km" }
  }
```

Other OpenAI-compatible clients need the same base-URL change. Requests sent
directly to LM Studio on port 1234 bypass coordination and cannot be observed.
The coordinator does not rewrite client configuration or intercept traffic.

## Send one test request

This PowerShell example sends a real inference request to the selected local
model through the coordinator. Choose a model ID that LM Studio already
reports as loaded; this command does not load or unload models. The latest
read-only check found Qwen `qwen38-27b-q4km` not loaded, so do not run this
example until that precondition is true.

```powershell
$body = @{
  model = "qwen38-27b-q4km"
  messages = @(@{ role = "user"; content = "Reply with exactly READY." })
  temperature = 0
  max_tokens = 16
  stream = $false
} | ConvertTo-Json -Depth 6

Invoke-RestMethod `
  -Uri "http://127.0.0.1:1235/v1/chat/completions" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

The same chat-completions route is used by OpenCode. If LM Studio API
authentication is enabled, configure the client with a bearer token; do not
put tokens in this file or shell history.

## Observe and stop

In another PowerShell window:

```powershell
python -m resource_coordinator.cli status --url http://127.0.0.1:1235
```

Status reports service readiness, active and pending inference requests,
cooldown state and remaining time, restart inhibition, and each managed
process's state, PID, executable, lifecycle owner, and whether the coordinator
stopped it. A stopped target is eligible for restart only when the coordinator
owns the stop and no active, pending, or uncertain operation inhibits restart.

Before normal shutdown, wait for `Active inferences: 0`, `Pending requests: 0`,
and `Restart inhibited: False`. The CLI and coordinator discover the shared
operator credential automatically; no profile edit is needed. A successful
`restart` drains work and relaunches the service through
the `serve` command's in-process supervisor loop; `shutdown` drains and exits.
The user-logon task is not assumed to restart a clean exit. A drain timeout or
uncertain request leaves the service stopped from admission and retains its
instance lock for reconciliation.

```powershell
python -m resource_coordinator.cli restart --reason "activate reviewed config"
python -m resource_coordinator.cli shutdown --reason "operator shutdown"
```

## Managed installation commands

The Resource Coordinator CLI can inspect or reconcile its own installation.
`setup` is a dry run unless `--apply` is supplied. Setup preserves existing
configuration, state, and logs. Scheduled Task changes may prompt for UAC;
noninteractive calls fail with an elevation diagnostic instead of prompting.
If the copied template still has a placeholder wallet/worker or no miner is
configured, setup returns `degraded` and names the missing mining configuration.

```powershell
resource-coordinator system setup
resource-coordinator system setup --apply
resource-coordinator system setup --apply --viewer
resource-coordinator check health --json
resource-coordinator system upgrade
resource-coordinator system upgrade --apply
resource-coordinator system upgrade --apply --json
resource-coordinator system startup status --json
resource-coordinator system startup install -m logon --apply
resource-coordinator system startup install -m boot --apply
resource-coordinator system startup disable --apply
resource-coordinator system startup enable --apply
resource-coordinator system startup repair --apply
resource-coordinator system startup uninstall --apply
resource-coordinator system teardown
resource-coordinator system teardown --apply
```

The optional `--viewer` opens a separate read-only PowerShell window after
user logon. Closing it only closes the viewer; mining remains owned by the
coordinator.

`upgrade` previews by default. `upgrade --apply` runs from the CLI process,
records a durable receipt, closes admission through the authenticated service
lifecycle, waits for the old coordinator and its instance lock to exit, updates
the RC-owned startup task, then verifies the new process's startup-captured
source fingerprint, protected gateway controls, upstream, and effective GPU
power limit before restoring prior mining activity. A legacy runtime without a
fingerprint is treated as needing migration. If any ownership, shutdown, task,
runtime, or GPU check is uncertain, upgrade fails closed and records the exact
phase for `resource-coordinator system upgrade --apply` to safely retry. Use
`--non-interactive` to reject the transition before shutdown when UAC is needed.
The command does not force-terminate the coordinator or miner.

The runtime fingerprint is captured when each coordinator process starts; it
does not change when the source checkout later advances. `doctor` reports
`upgrade_state` as `current`, `available`, `in_progress`, `recovery_required`,
or `unknown`. `setup` remains a non-interrupting installation repair and
recommends `upgrade --apply` when a ready process is running old code.

For a coordinator-owned miner start, use `resource-coordinator control miner start`;
do not launch KRig directly. The service task's configured run level supplies
the NVIDIA privileges needed by its child process. `doctor` compares the
configured and observed GPU power limit, reports task inventory errors, checks
the running package path/version, and verifies process-capture directory access;
these conditions degrade health. It reports core-clock locks as dynamic
observations and the KRig core offset as unverifiable with the available
`nvidia-smi` telemetry; those settings are not presented as driver-verified.
Teardown preserves the configuration, credential, journal,
and log files. If the service is unreachable, teardown requires a readable,
valid idle journal and an unlocked instance lock; it refuses to act when a
coordinator-owned miner is still running because the service's graceful
process-group handle is unavailable.

## Miner, gaming, and log controls

Privileged CLI commands discover a local operator credential automatically.
The first coordinator start or privileged CLI command provisions a random
credential under `%USERPROFILE%\\.resource_coordinator\\secrets` on Windows
(or `~/.resource_coordinator/secrets` elsewhere), with Windows ACLs limited to
the current user and LocalSystem. The value is never printed or passed in
process arguments. `RESOURCE_COORDINATOR_OPERATOR_TOKEN` remains an optional
advanced override. Setup verifies that the credential file ACL grants the
interactive user and LocalSystem access before registering startup.

Credential diagnostics and recovery do not call the coordinator:

```powershell
resource-coordinator system auth doctor
resource-coordinator system auth repair
resource-coordinator system auth reinitialize
```

`repair` reapplies restrictive ACLs without rotating the token. `reinitialize`
rotates it only while the coordinator port is stopped; it refuses to run while
the coordinator is listening. Missing, malformed, inaccessible, or mismatched
credentials are reported and never silently replaced. Credential failures
disable privileged operations but do not prevent read-only status, inference,
or miner supervision from running.

All mutations go through the ready coordinator and require
the automatically discovered operator credential. They require a durable
`state_persistence_path`; the standalone CLI does not manage a miner locally.
Controls refuse while GPU leases, inference/model-loading cooldowns, safety
inhibitions, gaming mode/recovery, or lifecycle gates are active. During gaming,
use `gaming stop` to restore the saved model and return miner control to normal
coordination before issuing a miner mutation.

```powershell
python -m resource_coordinator.cli control miner status
python -m resource_coordinator.cli control miner pause --duration 2h
python -m resource_coordinator.cli control miner pause --until-gpu-below 20 --window 60s
python -m resource_coordinator.cli control miner stop
python -m resource_coordinator.cli control miner resume
python -m resource_coordinator.cli control miner start
python -m resource_coordinator.cli control gaming status
python -m resource_coordinator.cli control gaming on
python -m resource_coordinator.cli control gaming off
python -m resource_coordinator.cli logs miner --follow
python -m resource_coordinator.cli logs krig_miner --follow
```

Timed holds and GPU-idle conditions are journaled. The conditional pause keeps
the miner stopped until valid telemetry covers the complete rolling window and
the average is below the threshold; missing samples never count as idle. Gaming
mode saves the loaded LM Studio model identifiers and supported load settings,
stops the coordinator-owned miner, then unloads models through LM Studio's
native model API. Gaming stop restores models, observes the configured cooldown,
and restarts mining only if the miner was running under coordinator ownership
before gaming mode. If a transition fails, it retains the miner hold and
durable recovery state for an explicit retry.

`logs` reads only the configured process output file through the authenticated
coordinator endpoint. It returns raw appended bytes. Stopping the viewer only
ends log polling; it has no miner lifecycle effect.

Coordinator-captured process output is append-only between restarts. To bound
disk use, a file is rotated before a new miner launch once it reaches 64 MiB;
the three most recent files are kept as `.1`, `.2`, and `.3` beside the active
log. Rotation preserves prior bytes, and the log follower continues from the
active file after a miner restart.

## Routes and limits

- Protected inference routes include `/v1/chat/completions`, `/v1/completions`,
  `/v1/embeddings`, `/v1/responses`, `/v1/messages`, the corresponding supported
  `/api/v0` chat/completion/embedding routes, and `/api/v1/chat`.
- Supported explicit model-load routes are `POST /api/v0/model/load` and
  `POST /api/v1/models/load`; they use an exclusive `gpu.inference` reservation
  and require the matching policy above.
- Client model unload and unknown state-mutating routes are rejected. Gaming
  model unload/restore is available only through the authenticated coordinator
  gaming control. Inference is
  protected before forwarding even if LM Studio internally loads a model just
  in time.
- Direct LM Studio GUI operations, `lms load`, and other direct clients bypass
  this gateway. Loaded-but-idle models do not block the process restart.
- An uncertain upstream result retains restart inhibition. The coordinator
  cannot prove that a timed-out model operation stopped, and its stop/drain
  timeouts are not strict wall-clock shutdown guarantees.
- The initial operating example manages one coordinator-owned process. It does
  not provide unattended crash recovery or manage Krig automatically.

For disposable-process and mock-backed Windows HTTP validation, see
[the integration test procedure](docs/WINDOWS_LMSTUDIO_HTTP_INTEGRATION.md).
The real LM Studio test remains opt-in and requires separate authorization.
