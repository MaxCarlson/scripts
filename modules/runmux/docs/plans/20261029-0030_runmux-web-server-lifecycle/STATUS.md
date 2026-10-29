# Runmux Web Server Lifecycle Status

**Branch:** `runmux-web-server-lifecycle-20261029`  
**Worktree:** `.worktrees/runmux-web-server-lifecycle-20261029`  
**Baseline:** `92c5f068fe2d0c8c99ca4a14991388b1819a3764`  
**State:** Workstream A completed and verified. Workstream B deferred per concurrency boundaries.  
**Next:** Stage intended files for review; stop for user manual validation and approval.

## Implementation & Validation Ledger

- **Workstream A (Server Lifecycle Management):** Complete.
  - Server descriptor serialization and host-scoped naming (`server_{clean_host}_{port}.json`) prevents IPv4/IPv6 loopback collisions while maintaining backward compatibility.
  - Owner-only ACL enforcement on Windows (`icacls` removing inheritance, granting user `(F)`, failing closed if `icacls` fails) and POSIX `0600` mode.
  - Symlink and Windows NTFS reparse point/junction detection (`FILE_ATTRIBUTE_REPARSE_POINT`).
  - Cryptographic challenge-response and signed shutdown with HMAC-SHA256 domain separation:
    - Health domain: `runmux-health-v1`
    - Shutdown domain: `runmux-shutdown-v1`
    - Shutdown signature bound to instance ID, HTTP method (`POST`), endpoint path, timestamp, and random nonce.
    - Constant-time verification (`hmac.compare_digest`), 30-second timestamp freshness window, bounded replay cache (60s TTL).
    - Cross-protocol attack prevention tested: health endpoint cannot act as a signing oracle for shutdown.
  - Pre-bound socket using Windows `SO_EXCLUSIVEADDRUSE` (no `SO_REUSEADDR` workaround) and POSIX `SO_REUSEADDR`. Exact bound socket passed to Uvicorn server.
  - Readiness reporting: `RunmuxWebServer.startup` hook triggers `on_ready()` banner only after ASGI application lifespan and TCP socket listening are fully functional.
  - CLI discovery, status (`-S/--status`), and stop (`-x/--stop`):
    - `runmux web` re-discovers running instances, confirms liveness, and outputs `Status: Already running` with verified URL, existing access code (without regeneration), and verified PID.
    - `runmux web -S/--status` inspects instance liveness, returning exit code 0 if running or 1 if stopped, without mutating state or creating credentials.
    - `runmux web -x/--stop` performs authenticated shutdown of the Web UI server and removes descriptors. Idempotent on repeated calls.
    - Alien/unrelated listener rejection: informs caller without terminating unrelated PIDs or leaking credentials.
    - **Supervisor Independence Invariant:** Verified that stopping the Web UI server leaves supervised Runmux child processes running and healthy.

- **Workstream B (LLM Monitor Web Integration):** Deferred.
  - Phase 3C LLM Monitor (`5fd0a288`) and Phase 6C History Explorer (`a03b4fa6`) are unmerged into `main`.
  - Phase 3D is under active development.
  - No edits made to `modules/llm_monitor/`, `modules/local_agent_bridge/`, or `modules/runmux/src/runmux/web_static/*`.

## Verification Commands & Evidence

```text
python -m pytest .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/tests/web_server_lifecycle_test.py -q
-> 15 passed, 1 skipped (POSIX mode test skipped on Windows)

python -m pytest .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/tests/web_cli_test.py -q
-> 8 passed

python -m pytest .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/tests/web_test.py -q
-> 15 passed

python -m pytest .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/tests/lifecycle_test.py .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/tests/lifecycle_api_test.py .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/tests/web_adapter_test.py .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/tests/telemetry_worker_test.py -q
-> 75 passed, 1 skipped

ruff check .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/src/runmux/server_lifecycle.py .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/src/runmux/cli.py .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/tests/web_server_lifecycle_test.py .worktrees/runmux-web-server-lifecycle-20261029/modules/runmux/tests/web_cli_test.py
-> All checks passed!
```
