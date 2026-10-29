# Runmux Web Server Lifecycle Status

**Branch:** `codex/runmux-web-server-lifecycle-integrated-20261029`  
**Worktree:** `.worktrees/runmux-lifecycle-integration-20261029`  
**Baseline:** `ee4fcb1994da4ea95d03320a22a63997f0ed8342` (`origin/main`)  
**State:** Workstream A completed, verified, and integrated with completed LLM Monitor and History Explorer baselines.  
**Next:** Validate, merge into `main`, and push to `origin/main`.

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
  - CLI discovery, status (`-S/--status`), stop (`-x/--stop`), and scriptable JSON (`-j/--json`):
    - `runmux web` re-discovers running instances, confirms liveness, and outputs `Status: Already running` with verified URL, existing access code (without regeneration), and verified PID.
    - `runmux web -S/--status` inspects instance liveness, returning exit code 0 if running or 1 if stopped, without mutating state or creating credentials.
    - `runmux web -S -j` emits machine-readable JSON status object with liveness, verified URL, access code, PID, and state directory.
    - `runmux web -x/--stop` performs authenticated shutdown of the Web UI server and removes descriptors. Idempotent on repeated calls.
    - Alien/unrelated listener rejection: informs caller without terminating unrelated PIDs or leaking credentials.
    - **Supervisor Independence Invariant:** Verified that stopping the Web UI server leaves supervised Runmux child processes running and healthy.

- **Integrated Feature Baseline:**
  - LLM Monitor host integration (Stages 0–3) merged at `39603daa`.
  - Phase 6C History Explorer (`382c0608`) and LLM Monitor Browser Workspace (Stages 4–5) merged at `ee4fcb19`.
  - Full suite compatibility confirmed across backend, frontend, and lifecycle controls.

## Verification Commands & Evidence

```text
python -m pytest modules/runmux/tests/web_server_lifecycle_test.py modules/runmux/tests/web_cli_test.py -q
-> 27 passed, 1 skipped (POSIX mode test skipped on Windows)

python -m pytest modules/runmux/tests/web_test.py modules/runmux/tests/llm_monitor_integration_test.py modules/runmux/tests/web_llm_monitor_api_test.py modules/runmux/tests/historical_runs_api_test.py -q
-> 39 passed in 10.8s

node modules/runmux/tests/llm_monitor_view_test.js
-> ALL 6 llm_monitor_view_test.js TEST SUITES PASSED!

node modules/runmux/tests/dashboard_test.js
-> Passed (exit 0)

node modules/runmux/tests/history_view_test.js
-> history_view_test.js passed

ruff check modules/runmux/src/runmux/server_lifecycle.py modules/runmux/src/runmux/cli.py modules/runmux/tests/web_server_lifecycle_test.py modules/runmux/tests/web_cli_test.py
-> All checks passed!
```
