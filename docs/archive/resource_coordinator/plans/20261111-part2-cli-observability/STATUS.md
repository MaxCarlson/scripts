# Resource Coordinator Part 2 Status

## Baseline

- Repository: `C:\Users\mcarls\src\scripts`
- Branch: `agent/rc-part2-cli-observability-20261111`
- Worktree: `.worktrees/resource-coordinator-part2-cli-observability-20261111`
- Base and starting HEAD: `c9135582611280e95d387988dfdb2f6cf3eebf3a` (`origin/main` after Part 1 documentation synchronization)
- Starting status: clean
- Package version at base: `0.14.0`; candidate metadata and module version are `1.0.0`.
- Canonical plan: V3; SHA-256 `BA842936C9DE945EE8463FD41C3E60491A5714DCA1CF481064DC915DBF516F46`; blob `3a1c2f7662a54469bb6dc15ad6462a4295ec93e6` (verified in this worktree)
- Part 1 baseline lifecycle failure remains assigned to Part 3; Windows/UAC acceptance remains H4.
- During final review, `origin/main` advanced three commits to `4f4373d2533e4e0c6bd115eda6623ed65fbadc49`. The commits touch Notifications and its operator documentation only; no Resource Coordinator or `scripts_help` paths overlap. They were merged into this feature branch after the Part 2 source commit, producing merge checkpoint `74d32468e30f76f7e5897148a975a9aabd228b09`. `main` remains at the upstream commit; the Part 2 diff from current `origin/main` contains only the 22 scoped paths listed in the commit.

## Progress

- [x] Verified V3 hash/blob and read Part 2, its dependencies, global requirements, acceptance criteria, and Part 3 boundary.
- [x] Fast-forwarded `main` to the published Part 1 documentation closeout `c9135582611280e95d387988dfdb2f6cf3eebf3a`; fetched remote matches.
- [x] Created isolated Part 2 worktree from the synchronized mainline.
- [x] Recorded pre-change baseline validation and classified environment/baseline failures.
- [x] Implemented the canonical CLI, hidden compatibility aliases, shared recovery/serve/accept/preflight argument helpers, global JSON/color options, and explicit dispatch normalization.
- [x] Added the `rc` console script, preserved both legacy script names, synchronized package version `1.0.0`, and registered the command in `scripts_help`.
- [x] Added recursive gateway sanitization, inference/maintenance/gaming status views, read-only maintenance reconciliation, and ownership-qualified telemetry.
- [x] Added inference aggregation, a safely unavailable-by-default LM Studio observer, and online/offline read-only recovery assessment including bounded, sanitized upgrade-receipt inspection.
- [x] Added intentional status, telemetry, maintenance, setup, preflight, acceptance, inference, and recovery renderers; explicit doctor/installation result codes; CLI documentation.
- [x] Added Part 2 plan, checklist, status evidence, and CLI documentation.
- [x] Reviewed source, security sanitization, recovery boundaries, tests, and changed-file scope.
- [x] Merged the three reviewed Notifications-only mainline commits into this feature branch without changing `main`.
- [x] Committed the Part 2 source and test checkpoint as `43c4bd9884cce7d00324dd0d1316da376bf4a0d7`.
- [x] Committed post-merge evidence and pushed the feature branch; remote ref `origin/agent/rc-part2-cli-observability-20261111` matched `44f6b40f07f0d4defdba5eb63c152e79f2724b32` after fetch. This status-only closeout will be pushed as a follow-up commit.

## Current state

Implementation, focused validation, mainline ancestry merge, evidence commit, and feature-branch push verification are complete. The feature branch was clean at the verified `44f6b40f07f0d4defdba5eb63c152e79f2724b32` checkpoint. No production operations have been performed.

### Pre-change validation

- `tests/test_cli_architecture.py`: **161 passed**, exit 0, using the project `.venv` and a module-local absolute pytest temp root. The same async-heavy suite stalls in the restricted sandbox during Windows Proactor self-pipe setup; the successful normal-permission run is the applicable result.
- Combined CLI/gateway/installation/config/factory baseline: **178 passed, 1 failed**, exit 1. The failure was `test_managed_model_load_stops_process_before_upstream_forwarding`.
- The same gateway failure reproduced individually on unchanged `main` at `c9135582611280e95d387988dfdb2f6cf3eebf3a`; the compared source and test files were identical. It is pre-existing and will remain visible, not suppressed.
- An earlier run before creating the module-local pytest temp-root parent had 81 passed and 98 setup errors; it was discarded and rerun correctly. No product tests ran in the stalled sandbox attempt.

## Limitations and next phase

Part 2 does not implement automatic recovery mutation or Part 3 durable-state changes. LM Studio no-wake behavior and target Windows/RTX 5090 capabilities remain unqualified. The feature branch is not merged or deployed.

## Implementation and validation

- **Final focused regression:** From `modules/resource_coordinator`, ran `python -m pytest tests/test_cli.py tests/test_cli_architecture.py tests/test_part2_cli.py tests/test_part2_observability.py tests/test_recovery_presentation.py tests/test_gateway.py tests/test_factory_gateway_integration.py tests/test_admission.py tests/test_maintenance.py tests/test_restoration.py tests/test_durable_state.py tests/test_leases.py tests/test_service_lifecycle.py tests/test_installation.py tests/test_operator_credentials.py tests/test_config.py -q --basetemp <absolute module-local root> --junitxml <same-root>/junit.xml` under normal Windows socket permissions. **503 tests: 502 passed, 1 failed, 0 errors, 0 skipped; exit 1.** JUnit: `.pytest_tmp_root/part2-final-regression-plus-presentation-20261111220228/junit.xml`.
- The one failure was `test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window`; it remains the Part 1 baseline failure reproduced on unchanged main. Its fake miner stays stopped because `manual override is active`. It was not changed or suppressed.
- During the new async gateway tests, the restricted sandbox stalled during Windows Proactor socket setup. Those cases were rerun with normal socket permissions and passed. The broad final run used the same verified normal-permission context.
- New receipt and maintenance-release safety regressions were demonstrated red then green: interrupted receipts remain blocked and sanitized; oversized receipts are rejected before reading; maintenance release does not proceed after a failed status read and does not accept a mismatched disposition; LM Studio observations require a fresh matching runtime identity.
- Isolated console-script validation: installed the candidate into `modules/resource_coordinator/.pytest_tmp_root/part2-script-venv/venv` with `pip --no-deps --no-build-isolation --ignore-installed`; generated and executed `rc.exe`, `resource-coordinator.exe`, and `gpu-coordinator.exe`. Each printed `resource-coordinator 1.0.0`. Current PowerShell `Get-Command rc` found no conflicting command.
- The final targeted Part 2 CLI/observability/presentation regression run completed after the receipt-size and unavailable-apply refinements: **19 passed**, exit 0. Changed-file Ruff and the correctly scoped compilation command passed after those code changes. `git diff --check` will be rerun after this final status edit.
- After merging current `origin/main`, the same focused test set was rerun with normal Windows socket permissions: `python -m pytest tests/test_part2_cli.py tests/test_part2_observability.py tests/test_recovery_presentation.py -q --basetemp C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-part2-cli-observability-20261111\modules\resource_coordinator\.pytest_tmp_root\part2-final-normal-20261111221126`; **19 passed**, exit 0. The sandbox-only rerun stalled during Windows Proactor setup after eight tests and was interrupted; it produced no assertion failure. The Part 2 source paths are unchanged by the merge, and `git diff origin/main...HEAD --name-only` confirms the incoming Part 2 scope is confined to Resource Coordinator and its help registry.
- Packaging validation caveat: an earlier `pip --prefix` probe unexpectedly uninstalled the pre-existing Resource Coordinator 0.6.0 distribution from the shared development `.venv`. No production installation was touched. The shared `.venv` was restored to 0.6.0 from repository commit `bf6d3be3fc630f7f482086fd55c15b1b047ace21`; `pip show` confirmed version 0.6.0 and its original shared `.venv` location. Later packaging checks used `--ignore-installed` and the isolated venv.
- Final static commands after the receipt-size/exit-code refinement: `python -m ruff check` over all changed Python implementation/test files (exit 0); `python -m compileall -q modules/resource_coordinator/resource_coordinator modules/resource_coordinator/tests modules/scripts_help/scripts_help/registry/registry.py` (exit 0); `git diff --check` after this evidence edit (exit 0).

### Safety and compatibility boundaries

- `rc recover` without flags is read-only. `-a/--apply` explicitly reports unavailable with exit code 2 and performs no network mutation. `-f/--force` remains the authenticated inference override; root and service short flags remain distinct.
- Maintenance reconciliation defaults to read-only. The force route is restricted to a server-reported `recovery_required` record, validates requested operation/session identities, and reports success only for the matching audited operator-override disposition. It never calls inference recovery to clear maintenance.
- The LM Studio observer default performs no probe. An injected observation is downgraded to unavailable unless coverage, timestamp, freshness, and runtime identity are valid. No auto-recovery claim is emitted.
- Part 3 journal revisions, `RECONCILED` transitions, startup-holder canonicalization, and automatic recovery remain deferred. H4 still owns actual Windows/UAC/Scheduled Task acceptance; WDDM/NVML and RTX 5090 capability qualification and controlled live acceptance also remain outstanding.
