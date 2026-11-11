# Reliable Inference Recovery — Status

## Checkpoint

- Base: `9102815920eff843c724f4f98a7957d94d46fbb2` (local v0.11.7 main checkpoint).
- Branch: `agent/resource-coordinator-inference-recovery-20261111`.
- Worktree: `.worktrees/resource-coordinator-inference-recovery-20261111`.
- Implementation commit: `927fa3e3051f81ae9c19123974376527c236914f`.
- Follow-up regression commit: `da504cf54341052a0a1ee74fedded90628a7b40b`.
- CLI-to-ASGI integration regression commit: `c310177da304f727603d7b923f5a5f6b50da4f30`.
- Final review implementation commit: `5401e4a4b4ca06a6a39a3a81e86ad7f248e17aea`.
- Final-review source version: `0.12.0` (backward-compatible dedicated explicit model-load deadline and terminal payload validation).
- Primary checkout and prior integration worktree were not modified.
- No live coordinator, miner, LM Studio, production credential, journal, Scheduled Task, GPU, or WSL setting was accessed or changed.

## Implemented

- `service recover -f -r ...` reads the existing protected shared operator token when no environment override is set. It never provisions, rotates, or repairs a token during recovery. The existing recovery-token and operator-token environment overrides remain supported.
- The recovery endpoint accepts the dedicated recovery token or an explicitly configured operator token. When using the on-disk shared token, the server revalidates its ACL before accepting it. Missing/insecure credentials fail closed; unauthorized calls still return 403.
- Recovery CLI output redacts the selected token from server-controlled success/error output and does not log exception text.
- Model-load streaming completion requires documented `model_load.end` success fields (`model_instance_id` and finite nonnegative `load_time_seconds`) and clean EOF. Progress, `[DONE]`, failure-shaped/malformed events, parse errors, and truncated streams retain the hold. `/api/v1/chat` remains inference: its intermediate `model_load.end` cannot release the lease; only a valid `chat.end` after clean stream completion can do so.
- Explicit protected model loads have `service.model_load_timeout_seconds` (600-second default; valid range greater than zero and no more than 3600). This is an overall upstream and response-stream deadline after lease acquisition. Existing inference HTTPX phase timeout and lease acquisition behavior remains 120 seconds by default. Model-load timeout diagnostics distinguish the overall deadline from HTTPX read inactivity, and timeout leaves the miner inhibited.
- Timed-out/interrupted forwarded operations retain restart inhibition and durable request records. Records add operation/model/resource/lease, timestamps and elapsed time, timeout type/configuration, exception class, safe static detail, HTTP status, terminal evidence, inhibition identity/reason, and operator guidance without storing prompt/body text.
- `/_coordinator/status` keeps existing fields and adds an allowlisted `gpu_inference.recovery` view with unresolved request records, journal availability, and recovery recommendation.
- Added a Resource Monitor contract at `RESOURCE_MONITOR_CONTRACT.md`. No new Resource Monitor GUI or backend cancellation endpoint was added.

## Validation

Environment: candidate venv, Python 3.12.10, pytest 9.2.0, pytest-asyncio 1.4.1.post1, Windows. Pytest ran from this worktree's `modules/resource_coordinator`; test imports resolved to the candidate module. Each invocation used its own absolute `--basetemp` below `modules/resource_coordinator/.pytest_tmp_root/`.

For the commands below, `$py` was `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-integration-candidate-20261111\modules\resource_coordinator\.venv\Scripts\python.exe`, and the working directory was this branch's `modules/resource_coordinator`.

| Command / scope | Result |
|---|---|
| `& $py -m pytest -q tests/test_gateway.py --basetemp <unique-absolute-temp> -ra` | Exit 0; 22 passed. Includes read-timeout uncertainty, status projection/redaction, sync and streaming model-load completion, fake miner stop/restart, authenticated shared-token recovery, journal audit, and exactly-one restart. |
| `& $py -m pytest -q tests/test_cli.py tests/test_cli_architecture.py --basetemp <unique-absolute-temp> -ra` | Exit 0; 188 passed. Includes no-environment protected-file discovery, missing/invalid/insecure credential rejection, explicit override precedence, mismatch handling, server-echo redaction, and an in-process CLI-to-ASGI recovery call using the protected file credential with no environment override. One upstream Starlette `TestClient`/HTTPX deprecation warning is emitted by that new test. |
| `& $py -m pytest -vv tests/test_operator_credentials.py --basetemp <unique-absolute-temp> -ra` | Exit 0; 16 passed. |
| `& $py -m pytest -vv tests/test_durable_state.py tests/test_argon_adversarial_review.py --basetemp <unique-absolute-temp> -ra` | Exit 0; 18 passed, including recovery audit and persistence-failure atomicity. |
| `& $py -m pytest -vv tests/test_phase1_request_arbitration.py --basetemp <unique-absolute-temp> -ra` | Exit 0; 10 passed, including concurrent arbitration, terminal completion, and truncated stream inhibition. |
| `& $py -m pytest -q tests/test_factory_gateway_integration.py tests/test_phase4_unattended_reliability.py --basetemp <unique-absolute-temp> -ra` | Exit 0; 14 passed. |
| `& $py -m pytest -q tests/test_service_lifecycle.py -k 'not test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window' --basetemp <unique-absolute-temp> -ra` | Exit 0; 18 passed, 1 deselected. The excluded test passes alone on the candidate but fails when run in the lifecycle suite. |
| Targeted cancellation and recovery HTTP cases in `test_architecture_review.py` plus the recovery atomicity case in `test_argon_adversarial_review.py` | Exit 0; 7 passed. |
| `python -m compileall -q resource_coordinator` | Exit 0. |
| Ruff check on changed implementation/test files, excluding `test_phase1_request_arbitration.py` | Exit 0; all checked files pass. |
| `git diff --check` | Exit 0. |

The isolated async smoke run initially stalled before application code. A bounded faulthandler trace at `.pytest_tmp_root/candidate-async.stderr.txt` shows the Windows Proactor loop blocked in `socket.py:accept` while constructing asyncio's self-pipe. The same bare asyncio smoke stalled with the ordinary Python 3.12.10 interpreter. One isolated fake-miner gateway async test passed with normal socket permissions, and all async suites listed above passed under that execution. No async test is counted as passed based on the sandbox-only run.

## Known validation issue

`test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window` passes by itself on the candidate, but fails when included in `test_service_lifecycle.py` and the broader lifecycle group. An isolated archive of unchanged base `9102815920eff843c724f4f98a7957d94d46fbb2` reproduced the same failure in the pair `test_gaming_mode_unloads_models_then_restores_model_and_owned_miner` followed by the idle-pause test. Baseline source import was verified under `.pytest_tmp_root/baseline-910281/modules/resource_coordinator`. The failure reports a persisted `manual override is active`; `service.py` and the failing test body are unchanged by this branch. Ruff on the base version of `test_phase1_request_arbitration.py` confirms the same nine pre-existing lint findings reported on the modified file; this branch only changes its mock model-load response.

## Safety and capability limits

- No arbitrary timer, empty lease set, model inventory, or GPU sample clears an inhibition. Only a clean, recognized terminal response releases a live request's lease and begins the existing guarded cooldown.
- After timeout/disconnect, this LM Studio API version exposes no established operation-specific status/cancel capability. The coordinator therefore cannot safely reconcile that request in the background; it keeps the miner stopped and exposes actionable status for an authenticated explicit operator override.
- The operator override remains resource-wide by design: it requires explicit `override: true`, operator, reason, a ready service, and no active/pending claims; the journal is resolved before the in-memory inhibition is cleared. Manual/gaming/global restart guards remain active.
- ACL behavior in tests is mocked at the `_acl_is_restricted` boundary. No real operator credential file was read. Real installed-service acceptance, UAC, and production task behavior were not performed.

## Final review — 2026-11-11

### Findings and corrections

- At review start, feature HEAD was `17ff85792411c42a3e90c416fae1683c892a20f2`; local `main` and `origin/main` were both `9102815920eff843f1a9ec3abe60060a4ffbdd8f`. Merge base equals `main`, and implementation checkpoint `927fa3e3051f81ae9c19123974376527c236914f` is an ancestor. The branch diff contains only Resource Coordinator module paths. The primary checkout's unrelated dirty files were preserved.
- `/api/v1/chat` is classified as inference. Its detector ignores `model_load.end`; the integrated fake-miner regression observes the inference lease active and miner stopped after that event and during generation, then observes one restart after valid `chat.end` and clean EOF.
- Review found that explicit model-load detection accepted a bare or failure-shaped `model_load.end`. It now accepts only the documented successful payload with nonempty `model_instance_id`, finite nonnegative `load_time_seconds`, and clean EOF. Malformed, failed, error-followed, or truncated streams retain inhibition.
- Review confirmed explicit protected loads still inherited the 120-second HTTPX timeout. Added `service.model_load_timeout_seconds`, default `600`, capped at `3600`, as an overall deadline from upstream dispatch through response delivery after lease acquisition. Inference HTTPX phase timeout behavior and the 120-second lease acquisition wait remain unchanged. Timeout is classified as `upstream_operation_deadline`, durably recorded, and does not clear inhibition.
- Fixed streaming `httpx.ReadTimeout` diagnostics to retain `upstream_read_timeout` classification and uncertainty evidence instead of reporting a generic client interruption.
- Package version is now `0.12.0` in `pyproject.toml` and `resource_coordinator.__version__`.

### Final focused validation

Environment: Windows, Python `3.12.10`, candidate venv, pytest `9.2.0`, pytest-asyncio `1.4.1.post1`; imports resolved to this feature worktree. Each pytest command used a unique absolute `--basetemp` below this module's `.pytest_tmp_root`. The final async test command was run with normal socket permissions after the sandbox Proactor self-pipe stall was reproduced before test/application startup.

| Command / scope | Result |
|---|---|
| `& $py -m pytest -vv tests/test_gateway.py tests/test_config.py tests/test_leases.py tests/test_policies.py tests/test_operator_credentials.py tests/test_durable_state.py --basetemp <unique-absolute-temp> -ra` | Exit 0; 84 passed. Covers chat/model-load terminal distinction, validated success schema, malformed/error/truncated streams, lease and miner ownership, slow successful load, bounded overall deadline, stream backpressure, timeout/recovery, credentials, policies, and durable state. |
| `& C:\Users\mcarls\src\scripts\.venv\Scripts\ruff.exe check resource_coordinator/adapters/lmstudio/gateway.py resource_coordinator/config.py resource_coordinator/__init__.py tests/test_gateway.py tests/test_config.py` | Exit 0; all checks passed. |
| `& $py -m compileall -q resource_coordinator` | Exit 0. |
| `git diff --check` | Exit 0. |
| Python/TOML version consistency assertion | Exit 0; both versions are `0.12.0`. |

New red-green checks reproduced and corrected malformed terminal acceptance, overall deadline gaps, downstream streaming backpressure, and streaming read-timeout misclassification. The final combined suite emitted only the existing pytest-asyncio unset-fixture-loop-scope deprecation warning. Previous CLI/architecture/credential integration evidence remains recorded above; it was not rerun because this review did not change CLI authentication code.

The source-level cold-load dependency is addressed with a bounded configurable procedure and mock evidence. No actual LM Studio model was loaded, so runtime readiness for WP04 still requires source integration/deployment, confirmation of the effective configured timeout and healthy Coordinator-owned miner state, and a separately authorized guarded live load. The upstream still has no verified operation-specific cancellation/status API; any timeout remains an operator-recovery case.

## Next action

Review and integrate the committed feature branch when authorized. No merge, push, deployment, live Coordinator/KRig/LM Studio action, Scheduled Task change, or WSL change has been performed. The previously documented baseline-only lifecycle failure and lack of upstream cancellation remain limitations. Production deployment remains separately gated and must preserve the manual recovery-token launcher fix, existing credentials/tasks/miner state, and persistent WSL LM Studio mask.
