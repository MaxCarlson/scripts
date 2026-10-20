# Resource Coordinator MVP

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
and `Restart inhibited: False`, then press Ctrl+C once in the serve terminal.
Because status becomes unavailable after shutdown, note the managed PID first
and independently confirm that exact PID has exited. Do not terminate a
process by image name.

## Routes and limits

- Protected inference routes include `/v1/chat/completions`, `/v1/completions`,
  `/v1/embeddings`, `/v1/responses`, `/v1/messages`, the corresponding supported
  `/api/v0` chat/completion/embedding routes, and `/api/v1/chat`.
- Supported explicit model-load routes are `POST /api/v0/model/load` and
  `POST /api/v1/models/load`; they use an exclusive `gpu.inference` reservation
  and require the matching policy above.
- Model unload and unknown state-mutating routes are rejected. Inference is
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
