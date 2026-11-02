# Phase 04 — Bounded Recoverable Benchmark Preflight

## Recommended model: GPT-6.1 Terra — High

**Priority:** P1 • **Depends on:** verified Phases 01–03 • **Owner:** integrated Agent Benchmark workflow owner • **Primary files:** `suite_monitor.py`, `suite_cli.py`, `suite.py`, optionally `suite_recovery.py` (new), `suite_worker.py`, tests, docs

### Objective

Replace manual start/auth/diagnose loops in monitored suites with deterministic preflight + bounded recovery. Maintain strict separation of **read-only planning**, **local service recovery authorized by `-r/--recover-local`**, and **inference authorization via `-x/--execute`**. Never change an already running Monitor's configuration to make the benchmark pass; never launch inference just because preflight became healthy.

### State machine

```text
DISCOVER -> CLASSIFY_CONTEXT -> VERIFY_IDENTITY -> CHECK_CONFIG -> AUTHENTICATE
         -> CHECK_MODEL_ROUTE -> CHECK_RECORDER -> READY

MONITOR_ABSENT + explicit recover-local + approved config -> START_ONCE -> VERIFY_IDENTITY
MONITOR_ABSENT + no recover-local                    -> BLOCKED (start command)
MONITOR_READY + matching config                       -> reuse
SESSION_EXPIRED + reachable approved control          -> REFRESH_ONCE -> AUTHENTICATE
WRONG_CONFIG / ALIEN_LISTENER / ACTIVE_TRIAL_CONFLICT -> BLOCKED, no mutation
RECORDER_UNHEALTHY                                    -> BLOCKED and preserve evidence
DOCKER_PIPE_ACCESS_DENIED / SOCKET_RESTRICTED          -> CONTEXT_BLOCKED, no Docker restart
MODEL_ROUTE_MISMATCH                                  -> BLOCKED, no alternate direct route
```

All transitions are explicit, emit structured `monitor-preflight-v1` receipts, use total/step timeouts, and carry an idempotency key based on `instance_id`, phase, selected config and run correlation. For the same unchanged blocker, one attempt is enough; retries require a state change or user action. A dropped recorder observation is a hard stop **before** new scored dispatch, including in background workers.

### Authorization rules

- `suite plan` is **read-only** by default; reports blockers. With `-r/--recover-local` it may start an **absent** managed Monitor, but must still never infer. This mutation is operator opt-in and should be stated clearly in help.
- `suite run/resume` require `-x/--execute` for all inference. `-r` separately opts into local Monitor start. Avoid conflating permissions. `-x` without `-r` does not allow Monitor start/restart; read-only auth bootstrap itself is allowed within scoped security contract.
- Never shut down a Monitor not owned/started by this workflow; never restart on config mismatch; do not stop Monitor on `plan` exit. Do not silently change active `off/metadata/content`, gateway upstream, DB path, loaded model, adapter/provider, or Docker daemon.
- Background worker inherits *authorization decisions as immutable policy fields* in manifest/checkpoint, not a transient human confirmation or bearer token. It reacquires short-lived local token itself in its approved host context; capability must never appear in serialized manifest or subprocess args.
- Only a worker holding the existing exclusive suite run lock may dispatch. Recovery and preflight do not alter task scores or source registry revision. Completed trials never rerun implicitly, and infrastructure-invalid retries remain governed by existing `--retry-invalid` semantics.

### Configuration and provenance

Adopt exact desired Monitor specification from explicit suite inputs or an operator-approved configuration profile; if unspecified, use the repo's current documented defaults and report them. Canonical config fingerprint includes gateway enablement/upstream, LM Studio endpoint, recorder mode/DB and bound port. Map container gateway URL (`host.docker.internal`, when verified) separately from host monitor management URL (`127.0.0.1`). Reject OpenCode native Responses-vs-ChatCompletions confusion; preserve `llm-monitor/<model>` effective OpenCode selector from current suite code. Every `monitor-preflight.json` receipt includes schema version, verified server `instance_id`, fingerprint, host/container URL sources, supported adapter and API format, requested/actual recording mode, time, probe results, recovery actions, and **no secrets**.

### Implementation stages

1. Formalize transition engine (`suite_recovery.py` or contained service), typed errors and deterministic stop conditions. Write tests first for every state row and unchanged blocked retries. The doctor probe library is authoritative for classification; never duplicate diagnostics in the state machine.
2. Add CLI `-r/--recover-local` to plan/run/resume while leaving current `-F/--llm-friendly`, `-x/--execute`, `-R`, `-U`, `-H`, `-L` and backwards compatibility intact. Document how `-r` differs from inference authorization.
3. Implement discovery/reuse and bounded start-once via Phase 01 lifecycle. Require known config and verified owner, fail closed on mismatch/alien port. Thread-safe/file-lock coalescing prevents concurrent suite plans from starting two Monitors.
4. Replace cookie/manual-code bootstrap with Phase 02 `ManagedMonitorClient`; tolerate one instance-verified renewal, no browser login payloads, no persistence. Keep explicitly configured legacy external Monitor auth paths clearly separated.
5. Integrate with planning, run, resume and worker task boundary. Before each task recheck identity, model, recording and dropped count. After task check durable request IDs/content coverage and recorder drift; if degraded, checkpoint task as infrastructure-invalid or blocked per existing semantics, never scored successful falsely.
6. Ensure run interruption leaves Monitor and sqlite evidence discoverable; do not stop shared Monitor automatically. Include preflight receipts in run metadata and archive verification with sanitization; do not add secrets to manifest digest.
7. Regression test on host-approved context; no full Harbor cohort. Commit checkpoint, report performance overhead (diagnostic/preflight timings), retry count and exact evidence paths.

### Scenarios and expected outputs

| Input condition | Automatic behavior | Outcome |
|---|---|---|
| No Monitor; no `-r` | Diagnostic only | `MONITOR_NOT_RUNNING` and exact start instruction |
| No Monitor; `-r` | Start once, verify ownership/ready, acquire capability | Continue plan; no inference |
| Correct Monitor live | Reuse without spawn, verify fingerprint | Continue |
| Browser session expired | Does **not** affect managed capability; local token renews once if expired | Continue or `MONITOR_AUTH_BOOTSTRAP_FAILED` |
| Existing Monitor wrong `-R`/upstream | Report key/value mismatch; do not restart | `MONITOR_CONFIG_MISMATCH` |
| Recorder writing error, backlog/dropped | Halt new inference, preserve checkpoint and request IDs | `MONITOR_RECORDER_UNHEALTHY` |
| Docker pipe denied | No restart; one contextual report | `USE_APPROVED_HOST_CONTEXT` |
| `plan -r` now fully healthy | Emit plan/provenance | `inference_dispatched=false` |
| `run` without `-x` | Reject before any benchmark dispatch | `EXECUTION_AUTHORIZATION_REQUIRED` |
| Wrong OpenCode API format | Reject; no direct inference bypass | `MONITOR_ROUTE_INCOMPATIBLE` |

### Acceptance criteria

Preflight is idempotent under concurrent plans/workers; bounded recovery never escalates service privileges; no inference on `plan`/`doctor`; explicit `-x` remains mandatory; no stale session loop; no Docker/WSL restarts; no previously scored trials altered; recording evidence verified before scoring. Deliver typed transition test matrix, comprehensive CLI tests, exact execution receipts, SHA and remaining platform limits.
