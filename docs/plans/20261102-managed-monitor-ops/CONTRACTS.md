# Proposed Implementation Contracts — Freeze During Phase 00

**Status:** design proposal; not a statement of existing runtime behavior. All contracts must be reconciled with the completed `web stop` agent, current branch and tests before code is modified. Version: `managed-monitor-ops-v1`.

## 1. Command compatibility

| Command | Purpose | Mutates state? | Authorization |
|---|---|---|---|
| `llm-monitor web` | Existing foreground behavior maintained as deprecated/compatible alias | Starts service as today | Explicit CLI invocation |
| `llm-monitor web start [-p PORT] [--gateway] [-R MODE] [-n] [-f text\|json]` | Managed start/reuse verified instance | Yes if absent | Explicit direct invocation |
| `llm-monitor web status [-p PORT] [-f text\|json]` | Identity/readiness/config probe | No | None; no token/code issuance |
| `llm-monitor web stop [-p PORT] [-f text\|json]` | Safe signed graceful shutdown | Yes | Direct user invocation + verified instance identity |
| `llm-monitor web restart [-p PORT] [--gateway] [-R MODE]` | Serialized graceful stop+start | Yes | Direct invocation; refuse active trial/unknown owner |
| `agent-bench suite doctor [-F/--full] [-f/--format json]` | Context-aware diagnostics | No service/model changes | None |
| `agent-bench suite plan ... [-r/--recover-local]` | Pure plan; optional single managed start | Only with `-r` | Explicit local recovery flag |
| `agent-bench suite run/resume ... [-r] -x/--execute` | Benchmark run/resume | Yes | `-x` always for inference; `-r` separately authorizes managed start |

**Existing flags must not be repurposed:** `suite -F/--llm-friendly` for existing subcommands, `-x/--execute` for inference, `-R/--recording` and `llm-monitor -R/--record-inferences` for their respective existing meanings; `-U/--monitor-url` container-facing inference and `-H/--monitor-host-url` host management; `-n/--no-browser`; `-p/--port`; `--gateway` and `--gateway-upstream`. `doctor -F/--full` is independently scoped to **doctor** only. Every new option also has a short flag where feasible, but do not manufacture ambiguous aliases. Add `--help` at each parser level. Treat returned port 8788 (snapshot default) and example 8789 as distinct; don't silently change default.

## 2. Managed instance descriptor, version 1

Fields (illustrative serialized metadata, not production secrets):

```json
{
  "schema_version": 1,
  "instance_id": "opaque-random-id",
  "owner_identity": "windows-user-sid-or-posix-uid",
  "host": "127.0.0.1",
  "port": 8789,
  "pid": 12345,
  "process_create_time": 1730000000.0,
  "executable_identity": "normalized-image-or-hash",
  "config_fingerprint": "sha256:...",
  "control_endpoint": "opaque-instance-scoped-local-address",
  "started_at": "2026-11-02T00:00:00Z"
}
```

Security-critical HMAC/control secret may be stored as owner-protected separate secret or descriptor only if file ACL checks pass; `status -f json` **must not expose it**. Windows ACL verification, symlink/junction checks, atomic write/fsync (as appropriate), stale descriptor quarantine, exact PID/create-time checks and HMAC instance challenge are mandatory. Fingerprint canonicalizes selected provider endpoint, gateway enable/upstream, recorder mode/database, service port and relevant config values; ignore volatile session IDs/paths unrelated to effective behavior. Never trust a filesystem descriptor alone.

## 3. Local-control protocol (`monitor-local-control-v1`)

**Transport:** local Windows named pipe (explicit SID ACL and reject remote) or POSIX AF_UNIX (owner-only parent directory + socket, peer credential validation where supported). If safe permissions cannot be applied, the channel does not start. All requests/response use bounded length-prefixed UTF-8 JSON, no pickle.

```json
{
  "protocol_version": 1,
  "request_id": "opaque-client-nonce",
  "instance_id": "opaque-random-id",
  "command": "issue_read_capability",
  "requested_scopes": ["inference:models:read", "inference:status:read", "recording:health:read"]
}
```

Response contains `protocol_version`, `request_id`, `instance_id`, `expires_in_seconds`, `issued_scopes`, `capability_token` (**secret, never logged**), error metadata on failure and no embedded browser cookie. Require server challenge-response bound to known instance, limits (messages, connections, TTL, replay, issuance quotas) and explicit command/method allowlists. No arbitrary command execution. Process status and signed shutdown may use Phase 01's existing HMAC endpoint rather than pipe, but both must verify the same instance; do not maintain two contradictory sources of identity.

**HTTP authorization:** for allowlisted `GET /api/inference/v1/...`, accept the new scoped capability independently of browser session cookie. Check correct method/path, instance, scope, expiry, revocation, current Host and Origin; no access to `/auth/*`, WebSocket, recording-mode POST or `/v1/chat/completions` from the read capability. Do not mint browser cookies, reuse startup code or store bearer tokens on disk. Return minimally necessary metadata for history proof rather than raw full prompt/output by default. Keep existing login schema `{ "code": "..." }`, cookie TTL and strict browser checks unchanged.

## 4. Diagnostics schema `monitor-preflight-v1`

**Top-level required:** `schema_version`, `status`, `execution_context`, `components`, `recommended_action`, `recovery`, `inference_dispatched`, `checked_at` (ISO timestamp), `elapsed_ms` (numeric). **Probe required:** `state`, `error_code` (nullable when healthy), `retryable`, `elapsed_ms`, `evidence_kind`, `remedy`. **Never required:** exact sensitive exception strings, machine-user full home path, environment variable values, cookies, tokens, login codes, request content.

**States:** `ready`, `absent`, `starting`, `unreachable`, `permission_denied`, `authentication_required`, `configuration_mismatch`, `unhealthy`, `unsupported`, `unknown`, `skipped`. Top-level `ready|degraded|blocked|unknown`. A context-denied probe is **not** evidence of host failure. A skipped/unknown probe does not count as passed.

**Proposed stable error codes** (reserve future extension namespace):

| Code | Description | Recovery |
|---|---|---|
| `MONITOR_NOT_RUNNING` | Verified absence | Optional `-r` start |
| `MONITOR_UNMANAGED_LISTENER` | Port occupied by unverified service | Operator inspection; no kill |
| `MONITOR_IDENTITY_MISMATCH` | PID/create-time/challenge mismatch | Fail closed; operator investigation |
| `MONITOR_STARTUP_TIMEOUT` | Bind/ASGI readiness not observed | Inspect logs; no false ready |
| `MONITOR_CONTROL_UNREACHABLE` | Cannot access protected control channel | Context check, not default restart |
| `MONITOR_CONTROL_PERMISSION_DENIED` | OS transport ACL denied | Approved host context |
| `MONITOR_AUTH_BOOTSTRAP_FAILED` | No verified scoped credential possible | Check identity/ACL; one attempt |
| `MONITOR_TOKEN_EXPIRED` | Short-lived capability expired | Refresh once through verified channel |
| `MONITOR_HTTP_UNAUTHORIZED` | HTTP 401 under current capability | Refresh once, then block |
| `MONITOR_HTTP_ORIGIN_REJECTED` | HTTP 403 origin mismatch | Fix Origin, not credentials |
| `MONITOR_HTTP_INVALID_PAYLOAD` | HTTP 422 shape failure | Fix request contract, don't retry unchanged |
| `MONITOR_CONFIG_MISMATCH` | Effective config differs from requested | Exact diff, no silent restart |
| `MONITOR_ROUTE_INCOMPATIBLE` | Wrong model/ChatCompletions routing | Correct route; no fallback |
| `MONITOR_RECORDER_UNHEALTHY` | Recording degraded/dropped | Stop dispatch and preserve evidence |
| `MONITOR_SHUTDOWN_UNCONFIRMED` | Safe shutdown not confirmed | Preserve descriptor, inspect/drain |
| `DOCKER_PIPE_ACCESS_DENIED` | Docker pipe/socket denied | Change approved execution context |
| `DOCKER_UNAVAILABLE` | Docker daemon verified absent/unavailable | Operator action; no implicit restart |
| `LOCAL_SOCKET_RESTRICTED` | Sandbox cannot access local service | Use approved host context |
| `EXECUTION_CONTEXT_RESTRICTED` | Broad host access blocked by context | No identical repeat |
| `LM_STUDIO_UNREACHABLE` | Configured provider cannot be reached | Diagnose context/provider separately |
| `EXECUTION_AUTHORIZATION_REQUIRED` | Run/resume lacks `-x` | Request explicit execution |
| `RECOVERY_NOT_AUTHORIZED` | Missing `-r` for managed service start | Show safe command |
| `SUITE_CONFIGURATION_INVALID` | Unsupported options/conflict | Correct supplied flags |
| `DIAGNOSTIC_INTERNAL_ERROR` | Unexpected diagnostic defect | Preserve trace/log sans secrets |

**Recommended action enumeration:** `NONE`, `USE_APPROVED_HOST_CONTEXT`, `START_MANAGED_MONITOR`, `CHECK_MANAGED_MONITOR`, `FIX_CONFIGURATION`, `REAUTHENTICATE_MANAGED`, `REPAIR_RECORDER`, `CHECK_PROVIDER`, `CHECK_DOCKER`, `GRANT_LOCAL_RECOVERY`, `REVIEW_DIAGNOSTIC_LOGS`. Choose primary action deterministically with evidence; multiple subordinate remedies may be included, bounded.

**Exit status:** doctor `0` ready, `1` known blocked, `2` invalid invocation, `3` internal error. Lifecycle commands `0` desired verified state, `1` mismatch/unsafe or not achievable, `2` invalid arguments; unexpected bugs may use `3` if consistent with repo conventions. Do not change existing suite semantics without explicit compatibility review.

## 5. Recovery transition contract

`DISCOVER -> IDENTITY_VERIFIED -> CONFIG_MATCH -> CAPABILITY_ACTIVE -> ROUTE_HEALTHY -> RECORDER_HEALTHY -> READY`. Allowed recovery edges: `ABSENT + recover_local -> START_ONCE -> DISCOVER`; `CAPABILITY_EXPIRED -> REFRESH_ONCE -> CAPABILITY_ACTIVE`. All other blockers emit diagnostics. Hard caps: at most one managed start, one token refresh per preflight, one retry per changed state; overall deadline bounded; no repeating denied probes unless user changed context. Proof of absence must be authoritative, not inferred from a sandbox-only refused socket.

`plan` -> always `inference_dispatched=false`. `run`/`resume` -> must check `-x` before any Harbor dispatch. Preflight receipt includes instance identity/config provenance but excludes credential. Existing run manifests remain immutable. Recorder dropping observations or persistence proof failing blocks next task; never score partial evidence as a valid complete run.

## 6. Security review checklist

- [ ] Windows named pipe ACL explicitly bound to user SID; remote access denied; default ACL never trusted.
- [ ] File state directory owner-only, symlink/reparse rejection, no insecure temp files.
- [ ] HMAC health/shutdown domains separated, timestamp/nonce anti-replay, constant-time compare.
- [ ] Read capability short-lived, instance-bound, scope-bound, revoked on restart/shutdown, never serialized.
- [ ] Browser code/cookie/Origin/Host and authenticated WebSocket unchanged.
- [ ] No direct fallback or daemon restart for Docker/WSL/sandbox limitations.
- [ ] Config fingerprint mismatch cannot trigger silent restart or recording changes.
- [ ] No content or secrets in `doctor`, `--llm-friendly`, logs, checkpoint, archive, subprocess argv.
- [ ] Live writes to SQLite WAL drained/verified before confirmed shutdown.
