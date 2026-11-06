# P03/P04 Offline Regression Closure

Date: 2026-11-06

## Source and environment

- Worktree: `.worktrees/integrate-local-inference-p03-p04-20261106`
- Branch: `integrate/local-inference-p03-p04-20261106`
- Starting commit: `0041d008e55c7fa2d6682273ec2242aebfbabe67`
- Python: 3.12.10; pytest: 9.0.3
- Installed OpenCode package metadata: 1.19.5. The OpenCode executable was not
  run. Package version is metadata only, not a runtime acceptance test.
- Pytest imports were checked against the integration worktree. The corrected
  LIO invocation printed `benchmark_core`, `llm_monitor`, and `agent_benchmark`
  module paths under this worktree.

All inference requests used fake gateway transports or in-process ASGI. The
Harbor subprocess was replaced before invocation. No Harbor task, model,
Coordinator, GPU, or service was launched or changed.

## Prior stall diagnosis

The isolated attempt test initially stalled before entering its test coroutine.
The faulthandler stack was in `asyncio.run()` while Windows initialized the
event-loop self-pipe (`socket.socket.accept` via
`ProactorEventLoop._make_self_pipe`). Trying the selector event loop produced
the same restricted-environment socketpair block. Under normal Windows
permissions, the exact test passed. The complete `attempt_test.py` then passed
all 23 tests in 8.35 seconds. This is an execution-environment restriction,
not an attempt/verifier deadlock.

The gateway token-forwarding test also passed under the sandbox’s normal Windows
permissions. The complete gateway test file passed as part of the 48-test
attempt-plus-gateway run.

## Mocked Harbor/OpenCode propagation

Added `modules/agent_benchmark/tests/opencode_harbor_propagation_test.py`. The
test calls the production `execute_harbor_run()` environment builder with
synthetic study metadata and a fake final Harbor subprocess. It observes the
issued execution credential in the environment passed to that process, then
passes the captured environment through production
`scoped_opencode_environment()`. A harmless Python child parses the resulting
inline OpenCode config and confirms the model, Monitor endpoint, existing
headers, tool/prompt policy marker, and unrelated provider are preserved while
the correlation header appears only on the intended OpenAI provider.

The test registers two unique attempts, checks a later token-free attempt has
no stale header, sends a synthetic completion through the gateway's ASGI app
and `httpx.MockTransport`, verifies the registry associates the gateway request
with the execution, confirms the credential is stripped before upstream
forwarding, and reconciles a distinct native Harbor trial ID afterward.

This proves code-level host-process/environment construction under mocks. It
does not prove Docker container environment inheritance, actual OpenCode config
interpretation, live network reachability, or deployed Monitor compatibility.

## Diagnosed broader-suite results

### Agent Benchmark

Command:

```powershell
python -m pytest -vv -o faulthandler_timeout=30 --basetemp modules/agent_benchmark/.pytest_tmp_p03p04_diag/agent-full-direct-basetemp modules/agent_benchmark/tests
```

Result: 643 passed, 10 skipped, 5 failed; exit 1; 100.62 seconds.

- Two diagnostic tests initially failed because the deeply nested temporary
  path made Windows fail to launch the verifier (`NotADirectoryError`). Both
  passed when rerun with the module-local short root
  `modules/agent_benchmark/.pytest_tmp_root`.
- Two OpenCode v2 tests require Docker readiness. Docker Desktop's named pipe
  was unavailable; the execution test refused before reaching the subprocess.
  No container or Harbor task ran.
- `test_adversarial_secret_scrubbing_in_exceptions_and_receipts` called the
  default local Monitor recovery probe at `127.0.0.1:8788`; it returned
  `MONITOR_IDENTITY_MISMATCH` for its synthetic descriptor. The test stopped
  before process spawn or inference dispatch. This is a test isolation defect;
  do not use this test in a future offline suite until its probe dependency is
  mocked. The test was not rerun.

The focused attempt and gateway command passed 48 tests. The dedicated
propagation, OpenCode correlation/config, Monitor-preflight, and attempt/gateway
regression command passed 74 tests. The extra standalone propagation test
passed 1 test.

### LLM Monitor

The first full run exposed a stale test expecting SQLite schema v3. P04's
authoritative storage schema is v4, so `storage_test.py` now asserts v4. The
full command then passed: 277 passed, 2 skipped, exit 0 (279 collected). Two
existing skips are platform-dependent filesystem cases. Only deprecation
warnings from the installed websockets/uvicorn stack were emitted.

### P03/P04 LIO integration

An initial collection attempt imported `benchmark_core` from the main checkout's
editable finder and failed at collection. It was not a product failure. The
corrected invocation removed editable finders, prepended the integration
worktree module paths, printed all three package origins, and passed all 4
`test_p03_p04_integration.py` tests.

## Validation summary

| Area | Result |
| --- | --- |
| Agent `attempt_test.py` + Monitor `gateway_test.py` | 48 passed |
| P04 correlation/config/attempt/gateway focused set | 74 passed |
| New mocked propagation test | 1 passed |
| LIO P03/P04 integration fixture | 4 passed |
| Full LLM Monitor directory | 277 passed, 2 skipped |
| Full Agent Benchmark directory | 643 passed, 10 skipped, 5 failed as diagnosed above |
| Existing combined P03/P04 integration checkpoint evidence | 273 passed, 1 skipped |

The focused commands used `python -m pytest`; full test imports resolved from
the integration worktree. The LIO command additionally removed editable
finders and printed source paths. The preexisting 273/1 checkpoint evidence
remains valid and is not replaced by the broader-suite result.

## Remaining acceptance

- Run the Monitor identity test only after changing its fixture to mock the
  local probe instead of querying the default Monitor port.
- Resolve or explicitly gate the two Docker-readiness-dependent OpenCode v2
  tests for environments without Docker.
- Confirm Harbor-to-container environment propagation and OpenCode's actual
  inline-config interpretation in a separately authorized live acceptance.
- Verify deployed Monitor compatibility and effective backend settings through
  independent runtime evidence. Correlation alone is not settings evidence.
- No real P02 baseline is sealed by this synthetic validation.
