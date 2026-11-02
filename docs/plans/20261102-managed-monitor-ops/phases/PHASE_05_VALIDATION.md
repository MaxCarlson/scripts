# Phase 05 — Incident Regression Matrix and Reliability Qualification

## Recommended model: GPT-6.1 Terra — Medium

**Priority:** P1 • **Depends on:** Phases 01–04 checked-in staged code • **Owner:** Independent validator or main agent in an isolated validation worktree • **Scope:** Tests, targeted bug fixes (with explicit ownership), evidence and security review; no full benchmark run

### Objective

Prove that the self-managing system recovers or fails accurately in the **specific previously observed failure modes**, and that it leaves service/process/SQLite evidence intact under interruption, crash and concurrency. Preserve the qualified Agent Benchmark/Harbor/OpenCode v2, web_ui_tools browser auth and Runmux lifecycle behavior.

### Layered validation

**Tier A — deterministic unit tests (mandatory, no live services):** freeze protocol/parser/schema with fake clocks and random generators; deterministic process table including Windows interpreter parent/child; PID recycle; descriptor serialization and ACL refusal; forged health HMAC, replay, wrong instance ID and port collision; token expiration and scope; session 401/403/422 and invalid origin; retry limit; recorder health and shutdown grace; dropped SQLite writes. All test failures must classify correct infrastructure vs code vs authentication error.

**Tier B — local integration fixtures (mandatory):** use ephemeral bound loopback sockets and fake Uvicorn/HTTP server, fake Docker pipe failures, fake LM Studio, temporary isolated SQLite WAL; verify start twice/stop twice, intentional delayed bind, concurrent start, restart with active suite, interrupted worker and recovery with consistent checkpoint. Validate old `llm-monitor web` invocation and Runmux untouched processes. Tests must create/delete only test state.

**Tier C — Windows host validation (mandatory for Windows support claim):** run in approved PowerShell 7+ with the actual project environment; demonstrate explicit Windows pipe ACL and remote-deny policy; process creation time/child identity; exclusive port binding; background lifecycle; no credential leakage; named pipe cross-user denial (where feasible using a controlled secondary test account); Windows Docker Desktop permission denial fixture; actual Docker/LM Studio connection checks only when operator authorizes non-destructive probes. Record command, shell, host OS, Python, exact exit and log. If such an executor is unavailable, mark *Windows integration unverified* rather than claiming support.

**Tier D — WSL2/Docker/Harbor contract smoke (gated):** use a separately authorized host context and existing resources. Verify host monitor origin vs container-facing gateway URL; check that inaccessible named pipe in WSL yields `EXECUTION_CONTEXT_RESTRICTED`; validate container connectivity without changing production settings. If a real single-task Harbor smoke is authorized, restrict to **one task**, explicitly `-x`, record its run ID and exact Monitor history/SQLite verification; do not run 10-task cohort, reload models, or auto-modify Docker. No live smoke when consent/resources absent: report gap.

### Incident-to-test requirements

| Incident | Simulated trigger | Minimum expected proof |
|---|---|---|
| Agent cannot use WSL/Docker/localhost | `PermissionError`, refusal in restricted context | `USE_APPROVED_HOST_CONTEXT`, zero repeat attempts |
| False duplicate monitor due to Python wrappers | two process records, one verified listener | one managed instance, zero unsafe kill |
| Banner before listening socket | delayed/failing `bind` or lifespan | never emits ready before actual response |
| Lost startup code/invalid login | missing/expired session, malformed body | managed bootstrap success or stable blocker; no `/auth/login` retry loop |
| HTTP 401 / 403 | missing scope, bad origin | distinct errors, one renewal maximum, existing protections retained |
| Wrong configuration | `-R metadata` vs `content`, wrong upstream | exact diff, no automatic restart or recording mode mutation |
| Port controlled by foreign process | alien listener that mimics HTTP health | cryptographic identity fails, no shutdown |
| Windows PID recycling | same pid/new create time | identity rejection, preserve descriptor |
| Interrupted shutdown | pending WAL writes/slow drain | no false success; evidence intact, descriptor retained if uncertain |
| Concurrent suite runs | two preflights, one startup lock | only one Monitor spawn, run locks independent |
| Worker interruption | worker exits after preflight/before score | checkpoint recoverable; never mark as scored |
| Token leak attack | exception contains secret or header | redacted logs/JSON/archives/process command line |
| Configured OpenCode Responses adapter | invalid monitored API format | fail closed; no direct inference fallback |
| Failing recorder mid-task | health changes during trial | stop subsequent dispatch and preserve run evidence |

### Suggested test commands (adapt to actual packaging in Phase 00)

```powershell
python -m pytest modules/llm_monitor/tests -q
python -m pytest modules/agent_benchmark/tests -q
python -m pytest modules/runmux/tests/web_server_lifecycle_test.py modules/runmux/tests/web_cli_test.py -q
python -m pytest modules/web_ui_tools/tests -q
ruff check modules/llm_monitor modules/agent_benchmark modules/web_ui_tools
llm-monitor web --help
agent-bench suite doctor --help
agent-bench suite plan --help
```

Do not count any of these as executed until actual log/exit evidence is produced. Some test locations/configuration may differ in the checked-out repo; discover test collection first, including Windows pytest basetemp workaround documented in Monitor history. Use bounded process timeouts with cleanup to prevent hanging test runners.

### Evidence format

Emit machine-readable `validation-receipt-v1.json` containing: repo/branch/commit, dirty status, OS/PS/Python, commands (redacted), exit code, start/end timestamps, test totals/pass/skip/fail, log artifact paths/hashes, live probes and explicit `not_run_reason`, code/infra classification, and security findings. Store test fixtures under isolated temp dirs. Use a human `STATUS.md` pointing to exact receipt and known gaps. No generated fake success numbers.

### Exit gate

All required fixture tests pass; no safety/auth regression; host-specific claims backed by host evidence; unresolved failures classified with remediation and owner. Integration-ready commit has clean diff and an independent review of token/ACL/descriptor handling. Phase 06 may proceed with documented known limits but cannot call an untested Windows feature production-qualified.
