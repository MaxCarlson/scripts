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
- During final review, the locally available `origin/main` advanced three commits to `4f4373d2533e4e0c6bd115eda6623ed65fbadc49`. The three commits touch Notifications and its operator documentation only; no Resource Coordinator or `scripts_help` paths overlap. The Part 2 branch remains based on `c9135582611280e95d387988dfdb2f6cf3eebf3a` pending a safe feature-branch merge of those unrelated mainline commits.

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
- [ ] Incorporate the three reviewed Notifications-only mainline commits into this feature branch, then commit and push the Part 2 work.

## Current state

Implementation and focused validation are complete. Final Git synchronization, commit, push, and post-push verification remain. No production operations have been performed.

### Pre-change validation

- `tests/test_cli_architecture.py`: **161 passed**, exit 0, using the project `.venv` and a module-local absolute pytest temp root. The same async-heavy suite stalls in the restricted sandbox during Windows Proactor self-pipe setup; the successful normal-permission run is the applicable result.
- Combined CLI/gateway/installation/config/factory baseline: **178 passed, 1 failed**, exit 1. The failure was `test_managed_model_load_stops_process_before_upstream_forwarding`.
- The same gateway failure reproduced individually on unchanged `main` at `c9135582611280e95d387988dfdb2f6cf3eebf3a`; the compared source and test files were identical. It is pre-existing and will remain visible, not suppressed.
- An earlier run before creating the module-local pytest temp-root parent had 81 passed and 98 setup errors; it was discarded and rerun correctly. No product tests ran in the stalled sandbox attempt.

## Limitations and next phase

Part 2 does not implement automatic recovery mutation or Part 3 durable-state changes. LM Studio no-wake behavior and target Windows/RTX 5090 capabilities remain unqualified. The feature branch is not merged or deployed.

## Implementation and validation

- **Final focused regression:** From `modules/resource_coordinator`, ran the CLI, architecture, Part 2 CLI/observability, recovery presentation, gateway, factory/gateway integration, admission, maintenance, restoration, durable-state, lease, service lifecycle, installation, operator-credential, and configuration suites with `python -m pytest ... -q --basetemp <absolute module-local temp root> --junitxml <same-root>/junit.xml` under normal Windows socket permissions. **503 tests: 502 passed, 1 failed, 0 errors, 0 skipped; exit 1.** JUnit: `.pytest_tmp_root/part2-final-regression-plus-presentation-20261111220228/junit.xml`.
- The one failure was `test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window`; it remains the Part 1 baseline failure reproduced on unchanged main. Its fake miner stays stopped because `manual override is active`. It was not changed or suppressed.
- During the new async gateway tests, the restricted sandbox stalled during Windows Proactor socket setup. Those cases were rerun with normal socket permissions and passed. The broad final run used the same verified normal-permission context.
- New receipt and maintenance-release safety regressions were demonstrated red then green: interrupted receipts remain blocked and sanitized; oversized receipts are rejected before reading; maintenance release does not proceed after a failed status read and does not accept a mismatched disposition; LM Studio observations require a fresh matching runtime identity.
- Isolated console-script validation: installed the candidate into `modules/resource_coordinator/.pytest_tmp_root/part2-script-venv/venv` with `pip --no-deps --no-build-isolation --ignore-installed`; generated and executed `rc.exe`, `resource-coordinator.exe`, and `gpu-coordinator.exe`. Each printed `resource-coordinator 1.0.0`. Current PowerShell `Get-Command rc` found no conflicting command.
- The final targeted Part 2 CLI/observability/presentation regression run completed after the receipt-size and unavailable-apply refinements: **19 passed**, exit 0. Changed-file Ruff and the correctly scoped compilation command passed after those code changes. `git diff --check` passed before this final status/checklist edit and will be rerun before commit.
- Packaging validation caveat: an earlier `pip --prefix` probe unexpectedly uninstalled the pre-existing Resource Coordinator 0.6.0 distribution from the shared development `.venv`. No production installation was touched. The shared `.venv` was restored to 0.6.0 from repository commit `bf6d3be3fc630f7f482086fd55c15b1b047ace21`; `pip show` confirmed version 0.6.0 and its original shared `.venv` location. Later packaging checks used `--ignore-installed` and the isolated venv.
- Changed-file Ruff and compilation passed before the final small receipt-size/exit-code refinement; rerun them in the final verification below. `git diff --check` passed before the final docs update; it will be rerun after staging.

### Safety and compatibility boundaries

- `rc recover` without flags is read-only. `-a/--apply` explicitly reports unavailable with exit code 2 and performs no network mutation. `-f/--force` remains the authenticated inference override; root and service short flags remain distinct.
- Maintenance reconciliation defaults to read-only. The force route is restricted to a server-reported `recovery_required` record, validates requested operation/session identities, and reports success only for the matching audited operator-override disposition. It never calls inference recovery to clear maintenance.
- The LM Studio observer default performs no probe. An injected observation is downgraded to unavailable unless coverage, timestamp, freshness, and runtime identity are valid. No auto-recovery claim is emitted.
- Part 3 journal revisions, `RECONCILED` transitions, startup-holder canonicalization, and automatic recovery remain deferred. H4 still owns actual Windows/UAC/Scheduled Task acceptance; WDDM/NVML and RTX 5090 capability qualification and controlled live acceptance also remain outstanding.
