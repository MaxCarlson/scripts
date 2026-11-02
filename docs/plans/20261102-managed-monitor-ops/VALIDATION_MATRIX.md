# Validation Matrix and Evidence Requirements

**This file specifies tests to run in implementation; none are claimed executed by preparation of this plan.** Tests and exact platform outcomes must be updated against source in Phase 00.

## Gates by phase

| Phase | Mandatory verification | Evidence produced | Fail-closed criterion |
|---|---|---|---|
| 00 | Branch/worktree/agent ownership and validated checkpoint audit | `BASELINE.md`, `STATUS.md` | No overlapping agent edits |
| 01 | lifecycle parser, descriptor identity, Windows child process, bind/readiness, shutdown DB drain | lifecycle tests + Windows host log | No unsafe kill or false ready |
| 02 | Windows SID ACL/remote deny, read scope, auth regression, leak checks | threat model, ACL proof, auth integration logs | No localhost/web auth bypass |
| 03 | every error code and doctor JSON schema/timeout/diagnostic redaction | fixture results and CLI snapshots | No false host-down or inference |
| 04 | state machine edges, bounded retries, plan/run auth split, checkpoint and model routing | mock execution/trial receipts | No unauthorized start or inference |
| 05 | cross-module suites, native Windows proof, optional authorized one-task smoke | `validation-receipt-v1.json` | No lost evidence/unsafe platform claim |
| 06 | docs/help drift, independent review, integration order, rollback | PR SHA, release report | No merge without authorization |

## Red-team/regression tests

**Lifecycle:** simultaneous starts same port; independent owned ports; stale state; corrupt ACL; symlink/reparse; PID reuse; wrapper parent and child; alien HTTP listener with correct banner but wrong secret; health HMAC replay/signature substitution; port hijack bind race; delay startup and stdout; restart active run refusal; SIGINT/timeout with SQLite WAL transaction; `stop` twice, `start` twice, `status` never launches.

**Authentication:** named pipe as another SID; remote pipe client; anonymous connections; wrong challenge; invalid/oversized JSON frame; `pickle` rejection; token from another instance/after restart; time-based expiry; 401 refresh exactly once; 403 wrong Origin unchanged; 422 bad login body not retried; SameSite cookie and authenticated WebSocket still protected; missing / invalid `Host`; POST mutation denied with read capability; all redaction surfaces inspected.

**Doctor:** Docker pipe denied, Docker missing/not running, WSL localhost isolated, host/socket `ECONNREFUSED` vs permission denied, DNS/proxy pollution disabled, LM Studio absent, model inventory empty/unsupported, wrong API format, wrong gateway/host URL, wrong recorder mode, dropped observations, stale request history, timeouts/unexpected exceptions, structured JSON stable and single stdout document.

**Recovery:** no permission to start -> no mutation; `-r` start once; two `plan -r` processes coalesce; valid instance reused; mismatched config never restarted; sandbox denial yields host-context action; abort before inference on recorder degrade; explicit `-x` required; no model inference from `plan` or doctor; trial checkpoints survive crash; versioned manifest unchanged; legacy cookie support does not override managed access or leak.

**Harbor fidelity:** preserve exact frozen cohort revision and task order, exact adapter/model effective selector, Chat Completions protocol, single-task checkpoint semantics and score provenance; record real inference only if one-task smoke explicitly authorized.

## Suggested host validation invocation

```powershell
# Read-only or test-only; adapt to actual environment and test paths from Phase 00.
git status --short && git rev-parse HEAD
python -m pytest modules/llm_monitor/tests -q
python -m pytest modules/agent_benchmark/tests -q
python -m pytest modules/runmux/tests/web_server_lifecycle_test.py modules/runmux/tests/web_cli_test.py -q
python -m pytest modules/web_ui_tools/tests -q
ruff check modules/llm_monitor modules/agent_benchmark modules/web_ui_tools
llm-monitor web status -f json
agent-bench suite doctor -F -f json
```

PowerShell `&&` requires PowerShell 7+; capture `$LASTEXITCODE` separately for any actual validator rather than relying on a combined last exit status. No root-level test path or command output is asserted until verified. Never run the full cohort in validation. For actual live smoke, record operator authorization, chosen model, exact task ID and `-x` usage first.

## Validation receipt template

```json
{
  "schema_version": "validation-receipt-v1",
  "repository": "MaxCarlson/scripts",
  "commit_sha": "TO_BE_FILLED_FROM_ACTUAL_GIT",
  "branch": "TO_BE_FILLED",
  "dirty": null,
  "platform": {"os": "TO_BE_FILLED", "python": "TO_BE_FILLED", "shell": "TO_BE_FILLED"},
  "checks": [
    {
      "name": "llm_monitor_tests",
      "command": "python -m pytest modules/llm_monitor/tests -q",
      "exit_code": null,
      "state": "not_run",
      "not_run_reason": "Plan only",
      "log_path": null
    }
  ],
  "security_review": {"state": "not_run"},
  "live_smoke": {"authorized": false, "state": "not_run"}
}
```

Use actual command logs, exit codes and checksums, not these placeholders, at implementation time. Keep logs under run-specific evidence directory, redact sensitive values, and avoid replacing existing forensic artifacts.
