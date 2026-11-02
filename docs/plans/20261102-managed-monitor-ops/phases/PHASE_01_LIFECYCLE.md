# Phase 01 — Verified Managed Monitor Lifecycle and Readiness

## Recommended model: GPT-6.1 Terra — High

**Priority:** P0 • **Depends on:** Phase 00; existing stop-command work completed/integrated or clearly assigned without overlap • **Owner:** single Monitor lifecycle implementer • **Primary modules:** `llm_monitor`, limited `web_ui_tools` integration • **Non-goals:** benchmark inference, Docker restart, browser authentication redesign

### Objective and behavior

Deliver `llm-monitor web start/status/stop/restart` with deterministic instance ownership, true readiness, safe idempotent commands and graceful persistence. Preserve `llm-monitor web [existing options]` for compatibility if currently used by scripts; deprecate only with tests and release notes. Adopt completed stop implementation rather than replace it, including any already chosen flags/contract.

### Design decisions

**Instance descriptor:** atomic, owner-restricted and versioned; fields include `schema_version`, `instance_id`, `pid`, `process_create_time`, `parent_pid` (informational), executable or process-image identity, `host` (`127.0.0.1`), `port`, creation timestamp, `config_fingerprint`, management channel identifier, optional opaque control HMAC secret (never shown in JSON), and state. Require current-user ownership and reject symlinks/reparse points. Distinguish listener PID from launching PowerShell/Python venv wrapper parent; verify the process actually serving the challenge and its recorded process creation time. If ownership is unknown, return `UNMANAGED_LISTENER`, not termination.

**Health handshake:** adapt Runmux's HMAC challenge-response with a new application/domain string (`llm-monitor-health-v1`). Status must verify socket + signed instance ID + PID/create-time, not use raw PID existence, port alone or stdout banner. On Windows use `SO_EXCLUSIVEADDRUSE` and explicitly pre-bound loopback socket; pass bound socket to Uvicorn. On other OSes, use tested safe socket flags and one-owner descriptor atomicity. Cross-check server `started` readiness with lifespan initialization and recorder/gateway health (service-level health distinct from process-level ready). A ready process may still have an unhealthy upstream; expose separate fields.

**Startup:** lock by host/port/owner during create/discover; detect existing valid instance and return its redacted URL/state without spawn; if same verified instance but configuration differs, report exact settings mismatch and refuse unexpected mutation. If port occupied by alien/unmanaged process, fail with structured error. Never print "listening" before actual bind+ASGI startup. Redacted human startup code may continue printing to local interactive TTY for browser login, but not machine-readable JSON or agent logs; decide whether `--show-login-code` is the proper explicit interactive opt-in after reviewing backward compatibility. Start in foreground by default or expose `-B/--background` as a separately documented opt-in. Ensure background launcher owns a durable log, stable process identity and exit reconciliation.

**Shutdown:** signed, time-bounded, replay-resistant channel authenticated by descriptor secret (or newly hardened local-control channel after Phase 02); request graceful ASGI shutdown, stop ingress, drain existing gateway requests, flush/close inference recorder, verify SQLite durability and process exit; remove descriptor only when authoritative identity and shutdown completion are proven. On timeout, preserve descriptor/evidence and report `SHUTDOWN_UNCONFIRMED`. Do not `taskkill /F` or `Stop-Process -Force` as fallback. `restart` must be explicit, serialize stop/start, preserve effective config, refuse if a trial is active unless a deliberately introduced explicit, safe policy allows it (default refusal).

**Failure domains:** stale descriptor with no process; reused PID; mismatched create time; duplicate Windows interpreter process tree; port collision; ready banner before listener bind; SIGINT during startup; descriptor fs failure; SQLite recorder busy/writes pending. All must be deterministic, safe and actionable.

### Files to inspect/likely modify (adjust to current tree)

- `modules/llm_monitor/llm_monitor/cli.py`: parser/dispatch with old CLI compatibility.
- `modules/llm_monitor/llm_monitor/web.py`: ready-after-bind and graceful lifecycle.
- `modules/llm_monitor/llm_monitor/web_lifecycle.py` (new if needed): identity, descriptor, signed discovery/control, concurrency.
- `modules/llm_monitor/llm_monitor/inference_web.py`: internal health/shutdown integration, preserve API auth boundary.
- `modules/web_ui_tools/src/web_ui_tools/app.py`: minimal supported server-start hook if existing create_server cannot report ready safely; do not fork middleware or broadly change shared behavior.
- `modules/llm_monitor/tests/test_web_lifecycle.py` or repo test naming convention; README, help and examples.

### Implementation stages

1. Examine/merge approved stop-command diff. Document its schema/tests. Add failing tests for no-dup and identity rules.
2. Define immutable config fingerprint with stable serialized canonical fields; secrets are excluded. Add process identity detection and descriptor filesystem protections. Test symlink/junction, concurrent start, PID reuse.
3. Implement signed health endpoint and true bound-socket/lifespan readiness. Test delayed startup, prebind race, failure before bind, malicious foreign HTTP responder.
4. Implement `start/status` with compatibility semantics and `-f/--format {text,json}`. Status is side-effect free; do not generate login codes or session tokens.
5. Integrate existing `stop`; add `restart` with explicit consent semantics, recorder drain checks, default refusal for active benchmark or unconfirmed shutdown. Validate idempotency.
6. Update docs, append exact validation evidence, commit phase checkpoint; no merge without authorization.

### Test plan

Run focused CLI/parser, server auth/readiness, recorder and Runmux compatibility tests; then the full `llm_monitor` suite and affected `web_ui_tools` tests. Include Windows native PowerShell and process-tree tests when a host executor exists, POSIX fixtures for Unix mode, and mocked corrupted status. A real bound-socket test is required in an approved local execution context; sandbox denial cannot be interpreted as host failure. No model inference.

### Acceptance criteria

- Same endpoint + same config started twice yields exactly one verified service.
- Status verifies challenge identity; `pid+create_time` reuse and impostor listener fail closed.
- Windows venv parent/child treated as a process family, not two independently authorized services.
- Ready reports only when listening and serving; failed bind never reports ready.
- Graceful shutdown preserves SQLite evidence and refuses unsafe termination.
- All existing foreground options and browser auth behavior still function.

### Gate / handoff

Provide commit SHA, branch/worktree, changed files, full command/log evidence, compatibility concerns and a short payload documenting lifecycle protocol for Phase 02. Do not claim Windows-native success if only mocked Linux tests ran. Phase 02 must not implement another lifecycle manager.
