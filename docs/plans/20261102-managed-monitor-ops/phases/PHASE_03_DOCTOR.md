# Phase 03 — Environment Doctor and Stable Failure Taxonomy

## Recommended model: GPT-6.1 Terra — Medium

**Priority:** P0/P1 • **Depends on:** Phase 00 contracts; consumes 01/02 lifecycle/auth adapters when available • **Owner:** Agent Benchmark diagnostics implementer • **Primary files:** `modules/agent_benchmark/agent_benchmark/suite_doctor.py` (new), `suite_cli.py`, `suite_monitor.py`, tests and docs

### Objective

Provide a single, **non-mutating** `agent-bench suite doctor` that diagnoses readiness from the *current execution context*, records probe provenance, distinguishes different classes of failure and recommends exactly one next operator/agent action. It must not misclassify a sandbox denial as a dead host, replay identical failing operations, dispatch inference, restart services, create credentials on disk or change Docker settings.

### CLI and contract

```powershell
agent-bench suite doctor
agent-bench suite doctor -F --full -f json
agent-bench suite doctor -F -f json -U http://host.docker.internal:8789/v1 -H http://127.0.0.1:8789
```

`-F/--full` **within the doctor subcommand only** enables additional bounded probes; this does not redefine `-F/--llm-friendly` used by other suite subcommands. `-f/--format` has text/json choices. Default probes should require neither a cohort manifest nor a loaded model. Optional `-L/--llm-monitor`, `-U/--monitor-url`, `-H/--monitor-host-url`, `-e/--endpoint`, `-R/--recording`, and model/agent options should use existing semantics only after parser collision check. JSON output must be exactly one valid document on stdout; diagnostics/probe debug logs go to stderr and contain no credentials.

### Probe engine

Represent each as a typed probe result: `name`, `status`, `error_code`, `duration_ms`, `observed_context`, `evidence_kind`, `retryable`, `suggested_action`, `details` (sanitized), `checked_at`. Use deadline budgets (e.g., 1–3 s per local probe, 10–20 s overall with testable constants), no hidden unbounded loops. Validate URL and no proxy forwarding (`httpx.Client(trust_env=False, follow_redirects=False)`) for loopback. Do not `docker ps` after `DOCKER_PIPE_ACCESS_DENIED` unless context changed.

Probes and failure distinctions:

1. **Runtime context:** OS, Python environment, Windows user SID/UID, sandbox hints based only on observed access failures, WSL2/Ubuntu vs Windows process isolation; classify with `confidence: observed/inferred/unknown`. Do not confidently claim a sandbox is active based on environment variable alone.
2. **Managed Monitor:** descriptor check, process PID+create time, challenge-response, bound socket health, configuration fingerprint, gateway status, loaded inventory and recording status. Differentiate `ABSENT`, `UNMANAGED_LISTENER`, `UNREACHABLE_FROM_CONTEXT`, `UNHEALTHY`, `CONFIG_MISMATCH`, `READY`.
3. **Authentication:** no credential probe spam; one channel bootstrap if requested as read-only authorization acquisition, distinguish missing channel, denied ACL, expired token, wrong Origin, wrong Host, HTTP 401, HTTP 403 and HTTP 422 (invalid schema). Do not auto-post browser login.
4. **LM Studio:** check configured host endpoint and current model inventory only if reachable; distinguish refused, timeout, 401, malformed response, missing model, and blocked socket. No loading/unloading models.
5. **Docker/Harbor:** use low-impact local availability/permission/version probes; classify daemon not running vs Unix/Windows pipe permission vs unavailable CLI vs inaccessible context. Avoid Docker restarts, container creation, image pulls and Harbor execution. Registry/source-revision validation may require network, so avoid doing it unless a configured cohort requires it; report network validation as skipped if not probed.
6. **Gateway endpoint mapping:** validate host's management origin separately from Harbor container target; warn if container-internal `localhost` would be incorrectly interpreted as host loopback. Do not claim container reachability solely from host health.
7. **SQLite recorder:** read-only health; dropped observations, last write error, drain latency, explicit requested recording mode; no DB initialization/migration. No sensitive request history in doctor output.

### Error taxonomy and exit status

Define explicit codes in `CONTRACTS.md`. Diagnostic top-level `status` is `ready|degraded|blocked|unknown`; a `blocked` probe is not automatically host-down. Use proposed exit codes `0 = checked and required dependencies ready`, `1 = known blocker`, `2 = invocation/configuration error`, `3 = unexpected diagnostic/runtime error`; distinguish skipped/unknown per probe, not silently pass. If showing an environment probe fails, mark `unknown` not `healthy`. Report best remedy based on observed error precedence (security/context first, configuration mismatch next, service absent only after trustworthy evidence).

### Implementation stages

1. Write fixture-driven tests of `monitor-preflight-v1` serialization, redaction, stable ordering, optional diagnostic scopes, subprocess timeout/cancellation and exit behavior. Freeze codes before adding recovery logic.
2. Implement context + Monitor diagnostics using Phase 01/02 verified adapters without launching the service. Use dependency injection for subprocess, network and clock; isolate platform probes rather than embedding OS logic in CLI dispatch.
3. Add Docker/WSL/LM Studio and gateway-mapping checks with bounded behavior. Permission errors are diagnostic outcomes, not reasons to retry the same command.
4. Implement prioritization of one recommended action (`USE_APPROVED_HOST_CONTEXT`, `CHECK_MANAGED_MONITOR`, `FIX_CONFIGURATION`, `REAUTHENTICATE_MANAGED`, `REPAIR_RECORDER`, etc.). Attach evidence for each recommendation.
5. Wire parser/help/text/JSON; add unit+CLI tests and manual host validation when approved. Ensure `doctor` cannot dispatch model inference in monkeypatched integration test.
6. Record exact validated status/code matrix, benchmark suite compatibility, commit checkpoint and phase report.

### Incident regression fixtures

- Windows Docker Desktop named pipe exists but access denied; no second identical attempt.
- Socket refuses connections in sandbox while authorized host reports healthy; diagnostic `context_restricted` not `host_down`.
- Stale Monitor descriptor, alien listener, delayed bind, parent/child Python interpreter ambiguity.
- Missing/expired scoped capability; malformed login schema (422) treated as incompatible/invalid request, never retry against `/auth/login`.
- Correct code but mismatched Origin 403; missing code 401.
- Valid monitor but wrong `--gateway`/`-R content`, recorder dropped count nonzero, model missing.
- Wrong host vs container URL and model API format `openai_responses` when monitored OpenCode requires Chat Completions.
- Probe timeout/cancellation and secret-bearing exception redaction.

### Acceptance criteria

`doctor` returns one concise accurate report; no service mutation, no inference, no cookie file or code exposure; stable JSON + documented exit codes; no false host-down conclusion on access denied; fixtures reproduce all named incident failure modes. Deliver diff, tests with real exit codes and any unverified host-specific checks for Phase 04.
