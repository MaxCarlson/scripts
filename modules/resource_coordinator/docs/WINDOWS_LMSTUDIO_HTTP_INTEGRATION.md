# Windows LM Studio HTTP integration

This opt-in test exercises the coordinator's actual ASGI gateway over a real
loopback TCP listener while the coordinator owns a uniquely named disposable
`cscript.exe` process. Mock cases never contact LM Studio. The live case is
separately gated, and was not run for this milestone.

## Mock-backed validation

Run from the repository root in PowerShell:

```powershell
$env:RESOURCE_COORDINATOR_RUN_DISPOSABLE_WINDOWS_TEST = "1"
Remove-Item Env:RESOURCE_COORDINATOR_RUN_LIVE_LMSTUDIO_TEST -ErrorAction SilentlyContinue
python -m pytest -s -vv -p no:cacheprovider -o addopts= --basetemp=modules/resource_coordinator/.pytest_tmp_http_integration modules/resource_coordinator/tests/test_windows_disposable_process.py modules/resource_coordinator/tests/test_windows_lmstudio_http_integration.py
```

The test writes a unique temporary JSON configuration and VBS helper. It binds
an ephemeral `127.0.0.1` port and refuses 1234 and 1235. The process is started
by the coordinator with external stop/restart, external adoption, and force
termination disabled. The mock verifies the active lease and verified stopped
state at forwarding; the recorded event order demonstrates admission,
reservation, stop verification, forwarding, confirmed completion, cooldown,
restart, and shutdown cleanup. The success case sends a second request during
the first cooldown and verifies that the process remains stopped and the
cooldown restarts. The failure case returns a mock upstream error and verifies
restart inhibition. Test output records PID, creation time, parent, executable,
working directory, helper script, and event order; it never logs response
bodies or credentials.

## Separately authorized live test

The test function is disabled unless
`RESOURCE_COORDINATOR_RUN_LIVE_LMSTUDIO_TEST=1`. Do not set this variable until
the user separately authorizes the live request. It uses the same disposable
process and isolated temporary configuration, but forwards one request through
the coordinator's real HTTP server to the loopback LM Studio server. It refuses
to start the helper unless the selected model is already reported `loaded` by
the read-only `GET /api/v0/models` endpoint, and repeats that check immediately
before forwarding. It never loads or unloads a model.

Read-only host inspection on 2026-10-19 found LM Studio listening on
`127.0.0.1:1234`; unauthenticated `GET /v1/models` and `GET /api/v0/models`
returned HTTP 200. The installed Qwen identifier `qwen38-27b-q4km` was visible
but reported `not-loaded`; `openai/gpt-oss-20b` was the model reported loaded.
These are observations from that inspection, not a guarantee of current state.
The test rechecks current state and fails before starting the helper if Qwen is
not already resident. LM Studio's documentation says API authentication is off
by default and, when enabled, requires a bearer token. The gateway test accepts
an optional token from `RESOURCE_COORDINATOR_LMSTUDIO_API_KEY`; it does not
store or print it. Current unauthenticated GET success does not establish
whether authentication will remain disabled or whether a future inference POST
will be permitted.

The exact proposed request is:

```http
POST http://127.0.0.1:<ephemeral coordinator port>/v1/chat/completions
Content-Type: application/json

{"model":"qwen38-27b-q4km","messages":[{"role":"user","content":"Reply with exactly READY."}],"temperature":0,"max_tokens":16,"stream":false}
```

If LM Studio authentication is enabled, the harness supplies
`Authorization: Bearer <token>` from the environment. No real client request is
sent directly to LM Studio. The configured upstream timeout is 120 seconds
(connect timeout 5 seconds), the gateway request timeout is 130 seconds, the
disposable process stop timeout is 5 seconds, and the idle cooldown is 5
seconds. The temporary process is a uniquely tagged `cscript.exe` running a
sleep-loop script from the test directory; the test logs its PID and creation
time and refuses ambiguous pre-existing `cscript.exe` processes.

### Emergency cleanup

The test's `finally` path asks the coordinator to stop the process, then
verifies PID, creation time, executable, parent PID, and exact helper script
before using a direct terminate fallback. If the coordinator or test process
hangs or crashes, use the logged PID only after independently verifying those
same identity fields with `Get-CimInstance Win32_Process` and
`Get-Process -Id <PID>`. Confirm the command line contains the unique temporary
script and token. Stop only that verified PID; never stop by image name. Then
confirm that exact PID has exited and remove only the test's unique temporary
directory after confirming no process references its script.

An HTTP timeout does not prove LM Studio stopped executing. On an uncertain
upstream result, the coordinator retains restart inhibition; do not repeat the
request or infer cancellation. Check LM Studio's read-only model/server status
and logs, and resolve the uncertainty before another test. Process cleanup has
bounded identity-checked attempts, but Windows/API teardown does not provide a
hard wall-clock shutdown guarantee.

This milestone does not operate Krig, any unrelated process, model load/unload,
or shared configuration. Direct LM Studio clients can bypass the gateway; the
live procedure therefore requires other clients to remain idle for the single
request window.

LM Studio references: [authentication](https://lmstudio.ai/docs/developer/core/authentication),
[OpenAI-compatible chat completions](https://lmstudio.ai/docs/developer/openai-compat),
and [REST model state](https://lmstudio.ai/docs/developer/rest/endpoints).
