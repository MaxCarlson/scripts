# Reliable Inference Recovery — Status

## Checkpoint

- Base: `9102815920eff843c724f4f98a7957d94d46fbb2` (local v0.11.7 main checkpoint).
- Branch: `agent/resource-coordinator-inference-recovery-20261111`.
- Worktree: `.worktrees/resource-coordinator-inference-recovery-20261111`.
- Implementation commit: `927fa3e3051f81ae9c19123974376527c236914f`.
- Follow-up regression commit: `da504cf54341052a0a1ee74fedded90628a7b40b`.
- Primary checkout and prior integration worktree were not modified.
- No live coordinator, miner, LM Studio, production credential, journal, Scheduled Task, GPU, or WSL setting was accessed or changed.

## Implemented

- `service recover -f -r ...` reads the existing protected shared operator token when no environment override is set. It never provisions, rotates, or repairs a token during recovery. The existing recovery-token and operator-token environment overrides remain supported.
- The recovery endpoint accepts the dedicated recovery token or an explicitly configured operator token. When using the on-disk shared token, the server revalidates its ACL before accepting it. Missing/insecure credentials fail closed; unauthorized calls still return 403.
- Recovery CLI output redacts the selected token from server-controlled success/error output and does not log exception text.
- Model-load streaming completion recognizes `model_load.end`; progress, `[DONE]`, malformed/partial frames, or streams that fail to end cleanly do not release the hold. A terminal failed model-load event is recorded as a verified terminal failure, allowing safe release after the upstream has actually ended.
- Timed-out/interrupted forwarded operations retain restart inhibition and durable request records. Records add operation/model/resource/lease, timestamps and elapsed time, timeout type/configuration, exception class, safe static detail, HTTP status, terminal evidence, inhibition identity/reason, and operator guidance without storing prompt/body text.
- `/_coordinator/status` keeps existing fields and adds an allowlisted `gpu_inference.recovery` view with unresolved request records, journal availability, and recovery recommendation.
- Added a Resource Monitor contract at `RESOURCE_MONITOR_CONTRACT.md`. No new Resource Monitor GUI or backend cancellation endpoint was added.

## Validation

Environment: candidate venv, Python 3.12.10, pytest 9.2.0, pytest-asyncio 1.4.1.post1, Windows. Pytest ran from this worktree's `modules/resource_coordinator`; test imports resolved to the candidate module. Each invocation used its own absolute `--basetemp` below `modules/resource_coordinator/.pytest_tmp_root/`.

For the commands below, `$py` was `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-integration-candidate-20261111\modules\resource_coordinator\.venv\Scripts\python.exe`, and the working directory was this branch's `modules/resource_coordinator`.

| Command / scope | Result |
|---|---|
| `& $py -m pytest -q tests/test_gateway.py --basetemp <unique-absolute-temp> -ra` | Exit 0; 22 passed. Includes read-timeout uncertainty, status projection/redaction, sync and streaming model-load completion, fake miner stop/restart, authenticated shared-token recovery, journal audit, and exactly-one restart. |
| `& $py -m pytest -vv tests/test_cli.py tests/test_cli_architecture.py --basetemp <unique-absolute-temp> -ra` | Exit 0; 187 passed. Includes no-environment protected-file discovery, missing/invalid/insecure credential rejection, explicit override precedence, mismatch handling, and server-echo secret redaction. |
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

## Next action

The isolated feature branch is ready for review as a source candidate with the baseline lifecycle test failure and unavailable post-timeout upstream reconciliation capability explicitly documented. Do not merge or deploy without separate approval. Production deployment remains separately gated and must preserve the manual recovery-token launcher fix, existing credentials/tasks/miner state, and persistent WSL LM Studio mask.
