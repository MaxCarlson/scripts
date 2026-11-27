# Phase B architecture review — 2026-10-19

Reviewed baseline `0c946e96` on `resource-coordinator-20261019-0915`, in the existing worktree. Corrections remain on that branch. Version is now 0.2.0 because recovery configuration, explicit force permission, and the direct AnyIO dependency change the package contract. No service configuration, miner process, or live inference was touched. Nothing is merged or published.

## Decision

**Offline review complete; unattended deployment is blocked.** A single supervised Krig/Qwen acceptance experiment is reasonable only after the operator establishes the prerequisites below and explicitly authorizes that experiment. This review does not establish actual Krig shutdown behavior or actual LM Studio execution termination.

The generic triggers, conditions, actions, events, named resources, and two-stage reservations remain intact. Safety takes priority over automatic recovery: uncertainty leaves mining stopped. Model residency does not itself prevent restart.

## Confirmed defects and corrections

| Defect at baseline | Correction / offline evidence |
| --- | --- |
| Successful B cleared A's unresolved inhibition | Removed automatic clearing from both response paths. Preserve the earliest hold and record subsequent uncertain holders. Successful B cannot establish A's termination. |
| Cancellation in lease-requested/acquired observers leaked claims | Reservation cleanup covers notification awaits; publish activation ownership under the lock before callbacks. Regression tests cancel at both notifications. |
| Closing a waiting reservation could activate it later | Check closed state under arbitration lock; serialize activation; close wakes waiters. Closed requests raise instead of becoming orphaned leases. |
| Awaiting release callbacks under the lease lock deadlocked reentrant callbacks | Commit release state and wake waiters under lock; emit outside it. Reentrant acquisition regression passes. Duplicate release is idempotent. |
| Cancellation in hooks/send/read leaked gateway claims; read errors could release without inhibition | One cleanup owner spans forwarding and response delivery. Shield cleanup under ASGI cancellation; inhibit any forwarded request without verified completion before releasing it. |
| Generator-only cleanup could be skipped if downstream failed before streaming began | StreamingResponse ASGI lifetime owns cleanup, including failure sending response headers and client disconnects. Tested with direct ASGI send failures and a mocked upstream byte stream. |
| First choice finish_reason, tool_calls, and arbitrary event names counted as whole-request completion | Require a complete SSE terminal frame plus normal upstream EOF and HTTP 200. Recognize compatible DONE, native chat.end, and response.completed. Tool boundaries, partial choices, truncated frames, errors after a marker, and interrupted streams remain uncertain. |
| Any successful JSON object, including empty/in-progress data, was accepted | Validate terminal choices, native chat results, completed Responses, embedding results, and path-specific model-load results. Chunked JSON is read as JSON, rather than presumed to be SSE. |
| Recovery HTTP endpoint allowed anonymous clearing without attribution or evidence | Disabled without RESOURCE_COORDINATOR_RECOVERY_TOKEN. Bearer authentication, explicit override=true, operator, and reason are required. Clear is atomic with rejection of any active/pending claims. Reports upstream_verified_idle=false. CLI uses the same route, encoded query params, environment token, --force/-f and --reason/-n. |
| Standalone miner CLI built separate state, losing manual overrides and bypassing daemon leases | pause/resume refuse mutation until authenticated daemon-side controls exist. status remains read-only. This is a deliberate compatibility restriction. |
| v0 completions/embeddings and Messages bypassed coordination | Classify them as inference. Unknown mutating endpoints return 501 instead of being forwarded without arbitration. Messages completion formats remain conservative/unsupported and may retain inhibition. |
| Zero cooldown dispatched an uncancellable stale idle event; expired timers lost cancellation ownership during restart | Track zero-duration timers too; retain task ownership through idle dispatch/actions; recheck activity and inhibition. New same-resource reservation cancels an in-progress delayed restart. Idle policies also check other registered policy resources. |
| Windows console flags and PID targeting assumed a console group | NEW_PROCESS_GROUP is used only without NEW_CONSOLE. Break is attempted only for a coordinator-launched group in the inherited-console mode. External/new-console processes have no assumed group. |
| Windows terminate/kill was implicit and mislabeled graceful | Explicit allow_force_termination (default false) is required. Console signal dispatch alone never proves stop. Scan for absence for 0.3 seconds and check captured descendants. No guarantee is claimed about CUDA cleanup from forceful termination. |
| AccessDenied could mean successful stop; target changed between discovery/action; external permission was forgotten after stopping | UNKNOWN/access denied fail closed; verify PID and creation time at action; preserve stopped-external ownership in supervisor; already-running external processes never launch duplicates. Tests replace every OS boundary. |
| CommandAction timeout/cancellation left subprocess running | Kill and reap the direct child on timeout/cancellation. This is not a process-tree containment mechanism. |
| Unsafe configuration coercions and ignored persistence/drain settings | Reject string booleans, unsupported versions/backends, nonexistent policy targets, invalid lease types, negative/nonfinite durations, bad ports, nonabsolute Windows executable paths, and enabled unimplemented persistence/drain. Preserve explicit zero cooldown. serve no longer overwrites file configuration when flags are omitted. |
| Decoded HTTP bodies retained upstream compression/length headers | Strip stale content-encoding/content-length. Disable upstream redirects so forwarded requests cannot silently escape the selected endpoint. |

Source paths: `core/leases.py`, `core/policies.py`, `core/processes.py`, `core/actions.py`, `adapters/lmstudio/gateway.py`, `config.py`, `cli.py`. Targeted regressions: `tests/test_architecture_review.py`. Existing mock chat fixtures now include terminal finish_reason; the prior recovery test now supplies an authenticated, attributed override.

## Remaining risks and uncertainties

1. **Cross-resource coordination needs further work.** `gpu.inference` and `gpu.model_loading` are distinct arbitration domains: EXCLUSIVE on the latter does not exclude SHARED on the former. The default configuration only wires an inference stop policy. The new idle check is a conservative snapshot, not a serialized transaction across resources; a different resource can arrive while a restart action is already awaiting. Multiple simultaneous cooldowns can also leave a restart skipped. Before general use, define resource conflict groups and serialize process actions with all conflicting claims; wire and test model-load policy explicitly. The supervised experiment must use only the inference domain with Qwen already loaded.
2. **External supervision remains outside coordinator control.** A 0.3-second absence window cannot prove a supervisor will not relaunch Krig later. Detached or newly spawned descendants with different executable names can escape the captured child snapshot. Disable independent auto-relaunch for the experiment; unattended use requires supervisor integration or an OS-enforced containment/lifecycle contract and continuous violation handling.
3. **No upstream idle verifier exists.** HTTP connection close, timeout, model loaded/unloaded status, and successful later inference do not establish that an earlier execution stopped. Recovery is a deliberately attributable operator override, never a verified-idle claim. The shared bearer identifies possession of an operator credential; the operator label is self-reported, not a distinct authenticated principal.
4. **No crash persistence or startup reconciliation.** Restarting the coordinator loses holds, reservations, stop ownership, manual overrides, and cooldown state. A new process must not be treated as proof that old upstream work finished. A successful new request after restart can otherwise resume mining while old work remains active.
5. **Scope and plugin limits.** Direct LM Studio traffic, UI/SDK/WebSocket requests, other clients, and external process launchers bypass this HTTP gateway. Arbitrary callbacks can block indefinitely, suppress cancellation, reenter supervisor locks, or start work outside policy arbitration. Built-in command cleanup reaps a direct child only. Exclusive-lease fairness/starvation, duplicate policy registration, full schema strictness for programmatically constructed config objects, bounded callback execution, manager/task shutdown, request/body limits, comprehensive proxy header fidelity, and stable audit retention and help-registry registration need follow-up before general deployment.
6. **Validation boundary.** Existing ASGITransport fixtures buffer streaming and alone cannot demonstrate a live client-disconnect path. Added direct ASGI tests cover header/body send failure and upstream read errors without networking; actual TCP transport, Windows console delivery, Krig/CUDA behavior, and installed LM Studio versions remain unverified. No clean-environment package install, wheel validation, dependency-minimum matrix, or coverage measurement was performed. GPU telemetry is still mocked, not a safety verifier.

## One supervised live acceptance test: prerequisites and acceptance

This is preparation, not authorization to run it.

- Establish a single coordinator instance on loopback and a single isolated test client; prevent all other inference and model-load traffic during the experiment. Independently establish upstream idle at startup. Preload Qwen and keep it resident throughout.
- Inspect the actual Krig executable, PID/create time, launch ownership, child tree, and supervisor behavior. Disable independent relaunch. Review a test-only config with correct paths, bounded timeouts/cooldown, external-stop/restart permissions, and exactly one inference stop/resume policy. Default placeholder paths are not operational configuration.
- Choose the stop method explicitly. The default new-console configuration cannot promise graceful break delivery. Either use a verified coordinator-owned inherited-console process group or explicitly authorize forceful termination after assessing Krig/CUDA behavior. This review does not authorize that choice or stopping the live miner.
- Keep recovery disabled for the normal-path experiment. Any disconnect, malformed response, timeout, stop-verification failure, or uncertainty means abort and leave mining stopped; independently verify upstream termination before considering an operator override. Do not restart the coordinator as a recovery technique.
- Observe: reservation/pending recorded before stop; actual Krig absence before upstream forwarding; inference finishes with terminal protocol result; active/pending reach zero; one cooldown; exactly one authorized miner resume; Qwen remains loaded. The operator remains present and can independently stop workloads. Stop at the first unexpected state.

**Readiness:** conditional for that narrowly scoped, separately authorized experiment after these facts/configuration are reviewed. Not ready to run as-is with defaults; not approved for mixed inference/model-loading, native tool workflows, external watchdog relaunch, or unattended use.

## Minimum durable state before unattended operation

Use a single-instance, access-controlled, versioned journal/snapshot with atomic replacement and explicit disk-error behavior. Persist safety transitions before the corresponding external side effects; write failure must veto forwarding/restart.

- Coordinator instance/boot identity, schema/config revision, resource-to-process/conflict mapping, and clean/unclean shutdown marker.
- Each request/reservation's stable ID, resource, pending/forwarded/active/terminal/uncertain phase and upstream correlation ID where available. Persist intent before forwarding: after a crash, every nonterminal forwarded or possibly-forwarded record becomes an inhibition, not an expired lease.
- All unresolved restart inhibitions with original holder, reason, time, affected resources, and evidence. Never clear them merely because new requests succeed.
- Process executable identity, PID/create time when relevant, lifecycle owner, stop intent/result, prior running state, authority to restart, and manual pause override. Persist before stop/start; reconcile reality after crash rather than replaying stale PIDs.
- Cooldown eligibility/deadline and last verified completion. On restart, conservatively restart a full cooldown only after reconciliation proves there are no conflicting outstanding/uncertain operations; clock changes must not shorten it.
- Recovery audit with authenticated actor/credential identity, self-reported operator/reason, affected request IDs, evidence or explicit override, previous state and result. Retain it durably with bounded storage.

On startup, inhibit all potentially affected resources until durable records, actual processes/supervisors, and upstream execution state are reconciled. If reliable upstream cancellation/idle evidence is unavailable, require an operator or retain inhibition indefinitely. Add crash-injection tests at every persistence/side-effect boundary, restart tests, service lifecycle tests, and the Windows/TCP acceptance evidence before unattended deployment. Persistence is unnecessary for a single supervised experiment only if process restarts/crashes explicitly abort the experiment and require manual reconciliation with mining kept stopped.

## Validation evidence

Baseline: 48 passed. Corrected suite: **99 passed**, including 51 new review cases. All checks below were run from the worktree root using `C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe`:

```powershell
$python = "C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe"
& $python -m pytest modules/resource_coordinator/tests -o addopts= -q --basetemp=modules/resource_coordinator/.pytest_tmp_root --tb=short
# 99 passed in 2.47s
& $python -m ruff check modules/resource_coordinator
# All checks passed
& $python -m ruff format --check --line-length 120 modules/resource_coordinator
# 26 files already formatted
& $python -m mypy --ignore-missing-imports modules/resource_coordinator/resource_coordinator
# Success: no issues found in 13 source files
```

The initial sandboxed baseline attempt could not write the worktree pytest temp directory and also failed the subprocess test under sandbox restrictions. With worktree write/process permission, the unchanged baseline passed all 48 tests. Regression tests were exercised failing before their corresponding corrections; fixture setup mistakes were corrected during development. Final checks ran with the same permissions as the successful baseline. No live services were contacted.

A final read-only peer review reproduced two additional gaps in the corrections: trailing truncated SSE after DONE, and parent-exit exceptions bypassing known-child verification. Both now have failing-before-fix regressions and passing corrections in the 99-test result above.

## Primary references consulted

- Microsoft [GenerateConsoleCtrlEvent](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent): group identity, shared-console restriction, return value versus actual termination.
- Microsoft [process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags): NEW_PROCESS_GROUP is ignored with NEW_CONSOLE.
- LM Studio [streaming events](https://lmstudio.ai/docs/developer/rest/streaming-events): native chat.end is the final aggregate, unlike tool-call or message boundaries.
- LM Studio [chat response](https://lmstudio.ai/docs/developer/rest/chat) and [model load](https://lmstudio.ai/docs/developer/rest/load): synchronous response schemas and model-load endpoint.

## Next action

Review this checkpoint and select the live-test stop method/configuration, or authorize the follow-up cross-resource/durable-state work. No live integration, merge, or publication is implied. The correction commit is the commit containing this report; its hash is recorded in the final handoff message.
