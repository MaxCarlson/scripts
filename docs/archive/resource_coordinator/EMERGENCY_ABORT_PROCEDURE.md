# Emergency abort and crash protocol

Preparation only. No live execution is authorized by this document. The first test requires separate user authorization after every [acceptance gate](SUPERVISED_LIVE_ACCEPTANCE_PLAN.md) is reviewed.

## Before a test

Set a private unpredictable `RESOURCE_COORDINATOR_OPERATOR_TOKEN` in the service environment and the operator terminal, without putting it in logs, command history or source. The existing configured recovery token is a fallback; prefer the separate operator token. Verify the exact gateway URL and keep it loopback/private. Loopback alone is not caller authorization. Prepare an independent exact-process/upstream reconciliation method before launching anything.

## Responsive coordinator

In the prepared operator terminal, invoke the installed module/CLI:

```powershell
python -m resource_coordinator.cli abort --url http://127.0.0.1:1235 --reason "Operator observed unsafe or uncertain execution"
```

The CLI sends a bearer token and the current username. Equivalent HTTP is **POST** `/_coordinator/abort` with Authorization Bearer and JSON containing nonempty `operator` and `reason`. Missing service/token is 503; incorrect credentials 403; malformed attribution 400. Confirm HTTP 200, `service_state=reconciliation_required`, and `is_ready=false` on the read-only status endpoint. Further proxy requests are denied.

The abort cancels cooldowns, blocks new process starts/admission and latches restart denial for this service instance. It does **not** terminate a running miner, recall forwarded inference or prove either has stopped. It cannot interrupt a blocking OS call. Do not send further inference to test rejection.

Inspect recorded exact process identities and upstream execution independently. If manual intervention is required, it needs the operator's separately established authority and exact target; no image-wide kill or ambiguous PID command is part of this procedure. Stop the experiment on any uncertain response, failed stop, unexpected relaunch, concurrent execution, process mismatch or gateway failure. Capture logs and observations without credentials.

## Hung or crashed coordinator

Treat nonresponse, forced termination, host crash or event-loop stall as a failed experiment. Do not rely on an unacknowledged abort. Disable all clients and independent launchers; use the prepared out-of-band reconciliation method. No automatic coordinator/miner restart is permitted. Do not use a second Ctrl+C as a safety mechanism: forced exit loses in-memory protections and cannot prove upstream termination.

Independently establish that every possibly forwarded request has terminated and the exact miner/children/watchdogs are stopped or deliberately contained. Low GPU utilization and a loaded-model listing are insufficient proof. Keep mining disabled while any inference may remain active. If the state cannot be established, retain NO-GO and seek operator intervention.

## After any abort

No recover/force/restart command is an authorized continuation. Terminal service recovery is intentionally rejected. Save evidence and end the test. Any later experiment requires independent reconciliation, reviewed configuration and fresh user authorization. The in-memory latch is not durable: restarting the coordinator would erase it, not resolve uncertainty. This protocol permits a supervised crash-abort boundary; unattended recovery remains blocked.
