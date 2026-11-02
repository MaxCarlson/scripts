# Phase 02 — Protected Local Control Channel and Authentication Bootstrap

## Recommended model: GPT-6.1 Terra — High

**Priority:** P0 • **Depends on:** Phase 01 verified instance identity • **Owner:** Monitor security/auth implementer; coordinate minimal modifications to `web_ui_tools` • **Threat model:** same-user trusted host clients, arbitrary web-origin HTTP clients, other local users, WSL/containers, stolen descriptors, untrusted local processes

### Objective

Let an authorized same-user benchmark process discover and authenticate to its exact managed Monitor without reading startup logs, prompting for a browser login code, or copying cookies to env files. Preserve strict browser access-code/session and Origin/Host defenses. The local channel grants **only read-oriented Monitor access**, not permission to launch inference, mutate recording mode or shut down unknown services.

### Architecture (selected)

1. **Transport:** Windows native named pipe named by current user and opaque instance ID, created with an explicit security descriptor granting the required current user's SID and trusted OS principals only. Reject remote clients (`PIPE_REJECT_REMOTE_CLIENTS` or equivalent), explicitly deny `NETWORK`, enforce bounded connection count, message size, timeout and rate limit. Treat default named-pipe DACL as unsafe. Use tested Windows API binding when standard library helpers cannot set ACLs; `multiprocessing.connection.Listener(AF_PIPE)` + default security does **not** suffice. On POSIX use a per-user mode-0700 directory and mode-0600 AF_UNIX socket with peer credential checks where available. The client authenticates instance identity before trusting reply.
2. **Wire format:** versioned length-prefixed UTF-8 JSON bytes, no Python pickle or `Connection.recv()` object unpickling; 64 KiB maximum request/response, strict fixed-field validation; commands `hello`, `health`, `issue_read_capability`, optionally `revoke_capability` / `shutdown` *only if Phase 01 ownership policy is satisfied*. Authenticate challenge and bind to HMAC/instance ID, timestamp, nonce; enforce one-use challenges/replay windows.
3. **Capability:** cryptographically random, server-side memory-only **short TTL** (recommend 60–300 seconds, choose by tests) bearer token, audience fixed to Monitor instance/config fingerprint, scopes explicit (e.g. `inference:status:read`, `inference:models:read`, `recording:health:read`, `requests:summary:read`, `history:verification:read`). No generic admin privileges or browser session spoofing. Avoid stdout, CLI args, disk, and environment storage. Token refresh once per failing operation after validating the same instance. Revoke on shutdown/restart; compare in constant time.
4. **HTTP adapter:** Extend application auth gate narrowly for a distinct `Authorization` scheme on an allowlist of read-only `/api/inference/v1/...` routes. Preserve exact required `Origin`, `Host`, no-store, path/method guard. The gateway inference `/v1/chat/completions` is not reclassified as read permission. For history data, grant the minimum endpoints needed for evidence verification without serving stored prompt/assistant content via default access; if current history endpoint always returns content, add a narrow metadata-only endpoint behind the same policy or separate scope explicitly.
5. **Client:** A library such as `llm_monitor.local_client.ManagedMonitorClient` resolves descriptor, verifies instance identity, talks to pipe/socket, caches scoped token in memory, injects headers for `httpx`, and redacts errors. `agent_benchmark/suite_monitor.py` uses it through a small adapter; no change to benchmark manifest semantics. On external/non-managed Monitors, retain explicit user-provided auth path without pretending managed authentication exists.

### Security nuance

- An ACL granting a user account access is **not** a fine-grained trust boundary between two malicious processes *of the same user*. Document this assumption; a malicious same-user process with user privileges may be able to obtain a capability. Controls protect against arbitrary browser/web requests and other users, **not** full compromise of the user's own account.
- Windows and WSL2 are separate access domains. No automatic WSL named-pipe bridge, no chmod of global Docker sockets, no privilege elevation. A restricted Codex/AGY process must receive `EXECUTION_CONTEXT_RESTRICTED` with host action, not a bypass.
- Do not rely on `Origin` alone for non-browser clients; authenticated control + origin/host checks are complementary.
- No persistent `monitor_session.env` generation. Keep legacy `LLM_MONITOR_SESSION_COOKIE` support narrowly for preexisting user workflows with documentation/migration warning; don't accidentally prefer stale file tokens over newly managed capability.

### Implementation stages

1. Inspect `app.py` and `inference_web.py` method/path map and exact current browser sessions. Freeze allowlist + schema in `CONTRACTS.md`; document capabilities that are deliberately forbidden.
2. Build transport with explicit Windows ACLs/remote deny and Unix owner permissions. Negative tests: other SID, anonymous, remote pipe, symlink, malformed message, oversized frame, replay, wrong instance. Test no deserialization gadgets.
3. Implement ephemeral scope-bound token manager on Monitor side. Test cross-instance/cross-port token denial, expiration, revocation, constant-time verification, excessive issuance, and restart invalidation.
4. Extend API auth middleware as narrowly as possible; test preexisting 401/403/422 semantics, origin mismatch, Host spoofing, browser login code+cookie, WebSocket session protection, no localhost shortcut, and POST denial for read tokens.
5. Introduce reusable host client and integrate into `suite_monitor.py` for validated monitored routes. Test 401-refresh-once, no repeated invalid login JSON attempts, stable data contracts, token redaction, external Monitor explicit-auth fallback.
6. Provide exact protocol/schema docs, security review, commit checkpoint and independent reviewer notes before Phase 04 relies on it.

### Expected target APIs (illustrative; implementation may move paths)

```text
local control: hello -> {schema_version, instance_id, challenge_signature, capabilities}
local control: issue_read_capability -> {token, expires_in_seconds, scopes, instance_id}
HTTP: GET /api/inference/v1/models
HTTP: GET /api/inference/v1/status
HTTP: GET /api/inference/v1/recording/status
HTTP: GET /api/inference/v1/requests
HTTP: GET /api/inference/v1/history/{id}   # metadata-only projection for benchmark proof
```

### Acceptance criteria

- From approved native Windows host context, `agent-bench suite plan ... -L` obtains valid scoped access without code/cookie handling by an agent; an expired token refreshes at most once.
- A forged pipe, default-insecure ACL, attacker-controlled descriptor or wrong Monitor identity cannot mint or redirect credentials.
- Uncredentialed localhost HTTP remains unauthorized; wrong Origin/Host remains 403/400; browser login/cookie works unchanged; WebSocket protections remain.
- No token, browser cookie, startup code or request content leaks into stdout, files, exception repr, worker environment, CLI arguments or archive.
- Different-user/remote/WSL-unbridged contexts fail predictably and do not cause unsafe changes.

### Review and report

Deliver a concise threat model, named-pipe ACL proof on Windows, tests/exit logs, exact API/method allowlist, migration strategy, new dependencies/versions (if any), and phase commit SHA. A Linux-only test run is not adequate evidence that Windows ACL enforcement works. Never weaken default browser auth to make a sandbox test pass.
