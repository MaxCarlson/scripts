# Inference crash-recovery design (proposed)

Status: approved design; implementation has not started.

## Goal

Keep an inference request from silently losing its restart hold when the coordinator process crashes. Persist an operation record before coordinator actions can affect the request, persist that upstream execution may have begun before forwarding, and persist the classified outcome before releasing the in-memory lease. On restart, any request without a durable terminal outcome keeps `gpu.inference` inhibited and the service unready until an operator explicitly resolves it.

This is one incremental safety slice. It does not make the coordinator safe for unattended operation.

## Current path

`LMStudioGateway._proxy_with_coordination` currently reserves an in-memory lease, emits the blocking event that can stop a process, activates the lease, performs fresh admission checks, and then sends the request upstream. `forwarded` is set immediately before `client.send`, because a send that raises or is cancelled may already have reached LM Studio. Cleanup latches an in-memory restart inhibition for uncertain execution, then emits the completion event and releases the reservation. `CoordinatorService.start` performs preflight before opening admission. `StateCodec` can validate and atomically save a limited snapshot, but it is not connected to these transitions and does not contain request phases.

## Approaches considered

1. **Separate synchronous SQLite safety journal (selected proposal).** Use explicit transactions and wait for each durable commit before crossing a side-effect boundary. Keep it separate from telemetry: telemetry writes are queued, lossy and observational. SQLite supplies atomic row updates and crash recovery; it does not provide the coordinator's missing cross-resource or single-instance guarantees.
2. **Extend the JSON snapshot helpers.** This reuses `StateCodec`, but whole-file replacement is not a write-ahead event history, and its documented guarantees do not establish rename durability on power loss. It would also require a new concurrency and transaction protocol.
3. **Reuse telemetry storage.** Rejected because its bounded queue may drop records and callers do not wait for persistence. That behavior is correct for observations and unsafe for admission decisions.

## Proposed behavior

- Add an explicitly configured safety-journal path. Do not silently create a clean journal on service startup. A separate explicit initialization command creates the initial schema; missing, unreadable, corrupt, or unsupported journal state fails closed.
- Store only coordinator metadata: request ID, resource, endpoint path, phase, timestamps, and bounded outcome/reason codes. Never store request bodies, prompts, completions, authorization headers, or credentials.
- Before emitting the blocking request event, commit a `reserved` operation row. This makes a crash during process-stop preparation visible as unresolved rather than silently clean.
- Immediately before `client.send`, commit `possibly_forwarded`. If that commit fails, do not send upstream. A transport exception after this point remains uncertain.
- During shielded cleanup, commit `confirmed_complete` only when the existing completion detector proves normal completion; otherwise commit `uncertain` when forwarding may have occurred. Complete this write before the reservation is released. A failed outcome write latches the existing in-memory abort/inhibition path and leaves the durable row unresolved.
- At managed startup, load and validate the journal before service readiness. Convert every nonterminal row to a restart inhibition and enter reconciliation-required/unready state. Never infer upstream idle from a missing process, connection close, later request, or coordinator restart.
- Provide an explicit local operator command to inspect and resolve a specific unresolved request with `--force` and a required reason. Record the actor, reason, request ID, and explicit `upstream_idle_verified=false` in the journal. This command records an override; it does not verify upstream execution.
- Keep the feature disabled unless a journal path is configured. Existing configurations without the feature retain current behavior and remain subject to the documented crash-recovery NO-GO.

## Failure rules

- Failure to commit `reserved` or `possibly_forwarded` prevents the next side effect.
- Failure to commit an outcome after a request may have reached upstream closes admission, latches restart inhibition, and leaves the request unresolved for startup recovery.
- Any nonterminal row at startup blocks readiness and restart. No automatic clear, retry, or replay is allowed.
- Terminal history is not automatically pruned in this slice. Any later cleanup must preserve unresolved rows and attributable operator resolutions.

## Scope limits

This slice does not journal miner/process start or stop results, implement cross-resource transactions, prevent a second coordinator instance, prove upstream termination, contain external launchers, or establish power-loss durability on Windows. Telemetry remains separate. Unattended operation remains NO-GO until those blockers and the required real Windows/TCP/crash evidence are addressed.

## Acceptance evidence

Offline tests must prove write ordering relative to blocking hooks, upstream send, completion classification, and lease release; fail-closed behavior on journal errors; recovery of unresolved rows as startup inhibition; rejection of missing/corrupt state; explicit audited resolution; and absence of request content or secrets from persisted rows. Process-kill/crash injection and Windows storage acceptance remain later evidence and do not follow from unit tests.
