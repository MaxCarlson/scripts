# H2A + H2C — Status

## Checkpoint A: v0.13 integration

- Repository: `C:\Users\mcarls\src\scripts`.
- Worktree/branch: `.worktrees/resource-coordinator-v013-integration-restoration-20261111`, `agent/resource-coordinator-v013-integration-restoration-20261111`.
- Target base at integration: `6a57877b6304515172e75eaf4d28d2cce88514aa`.
- Maintenance source: `e6a28b929c0a6f8dc8ddf6f31f3553e15a44335e`; merge base `3d1cefa0596cfba5a68e436589f3bba7edc04a53`.
- Integration merge: `d84865883baaa7e88af280eb3563d3a59694ae6e`.
- H2A evidence commit: `b794d0e0c13b5aeab49adaf57aada63e4ac97f0e`.
- All 16 incoming paths were under `modules/resource_coordinator/`; the merge had no conflicts. The primary checkout's unrelated dirty files and the published source feature worktree were preserved.

### H2A validation

Windows environment, Python 3.12.10, pytest 9.0.3, pytest-asyncio 1.3.0; `PYTHONPATH` pointed to this candidate's module directory and import resolution was verified from this worktree.

| Command/result | Exit |
|---|---:|
| Focused `tests\test_maintenance.py` | 30 passed | 0 |
| Expanded H2A suites (maintenance, leases, durable state, gateway, admission, service lifecycle, policies, actions, processes, config, credentials, CLI) | 214 passed, 1 deselected | 0 |
| Ruff on H2A changed Python files | passed | 0 |
| `compileall -q resource_coordinator tests` | passed | 0 |
| `git diff --check` | passed | 0 |

The deselected test is the known baseline GPU-idle/manual-hold behavior documented by the preceding feature status. A sandbox asyncio smoke test stalled before application code; the same isolated suites passed with ordinary Windows socket permissions. The earlier exploratory failures remain classified in the integration history; no live-mode test was retried.

## Checkpoint B: H2C trusted verifier

Implementation checkpoint: `873a49382a5e03da47f793608d3519f7e69da646` (`feat(resource-coordinator): verify maintenance restoration`), committed separately after H2A. Package version is 0.14.0.

- `core/restoration.py` adds an injectable structured observer, optional read-only NVML adapter, process identity observer, exact baseline comparison and fail-closed reason codes.
- `maintenance_verification` is disabled by default and requires an explicit GPU UUID, supported dimensions, miner executable names, bounded observation deadlines and explicit platform process-attribution acceptance.
- Acquire requires a complete scope (`power`, `offsets`, or `power_offsets`); partial dimension claims are rejected before RC stops its miner. The baseline is captured after verified managed-miner stop, bound to the operation and persisted before grant.
- `POST /_coordinator/maintenance/processes/register` authenticates the caller and independently reads PID, creation time and executable path/name. RC never adopts or terminates the process.
- Release verification compares exact power limit (mW), graphics/memory offsets (MHz), GPU UUID, PCI identity and driver, and requires GPU-process attribution plus a complete host inventory with no registered or configured known miner still running.
- Verification executes in a bounded worker outside the event loop. Timed-out workers are not force-killed; the manager rejects overlapping observer attempts until the read-only worker exits. The same session, operation and expiry are revalidated before release. Timeout, cancellation, expiry, unsupported evidence, persistence failure or stale ownership retains the fence.
- Fixed/locked clock modes are not eligible for automatic release because an independent getter for prior locked-clock state has not been established.
- The verifier uses no GPU mutation calls. Status/event summaries exclude process paths and fencing tokens; durable evidence is shape-bounded.

### Final validation

Environment: Windows, Python 3.12.10 from `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe`, pytest 9.0.3, pytest-asyncio 1.3.0. Each test run used a unique absolute `--basetemp` under this candidate. Async commands ran with normal Windows socket permissions because sandbox asyncio setup stalls before tests.

| Command/result | Exit |
|---|---:|
| `pytest tests\test_restoration.py tests\test_config.py` | 24 passed | 0 |
| Nine named H2C lifecycle tests (baseline/order, no-stop preflight rejection, capability gate, complete-scope enforcement, service configuration, surviving miner, timeout/retry gate, expiry race, authenticated registration) | 9 passed | 0 |
| Expanded integrated regression set: maintenance, restoration, leases, durable state, gateway, admission, factory/gateway, service lifecycle, inference integration, policies, actions, process supervision, miner adapter, config, credentials, CLI; excluding the documented baseline test | 232 passed, 1 deselected | 0 |
| Installation, Windows helper transport, and CLI architecture suites | 249 passed, 3 skipped | 0 |
| `ruff check` on all changed Python files | passed | 0 |
| `compileall -q resource_coordinator tests` | passed | 0 |
| `git diff --check` | passed | 0 |

Final H2C-expanded validation was run after the scope and observer-worker serialization fixes and before the documentation-only evidence update. The one added legacy-baseline unit test was subsequently included in the 24-test restoration/configuration run.

Exact final commands were run from `modules/resource_coordinator` with `$env:PYTHONPATH=(Get-Location).Path`; each pytest invocation used its own absolute candidate-local temp directory:

```powershell
python -m pytest --override-ini 'addopts=' tests\test_restoration.py tests\test_config.py -q -ra --basetemp <candidate>\modules\resource_coordinator\.pytest_tmp_h2c_units_final

python -m pytest --override-ini 'addopts=' tests\test_maintenance.py::test_trusted_verifier_captures_bound_baseline_registers_process_and_releases_off_lock tests\test_maintenance.py::test_unavailable_observation_preflight_does_not_stop_managed_miner tests\test_maintenance.py::test_unaccepted_gpu_process_attribution_disables_automatic_acquisition tests\test_maintenance.py::test_partial_scope_for_broad_mode_is_rejected_before_miner_stop tests\test_maintenance.py::test_configured_trusted_verifier_is_wired_by_coordinator_service tests\test_maintenance.py::test_trusted_release_fails_closed_on_running_trial_and_keeps_gpu_fence tests\test_maintenance.py::test_trusted_release_timeout_retains_hold_and_is_bounded tests\test_maintenance.py::test_expiry_during_verification_cannot_commit_release tests\test_maintenance.py::test_authenticated_process_registration_route_checks_os_identity -vv -ra --basetemp <candidate>\modules\resource_coordinator\.pytest_tmp_h2c_maintenance_gate

python -m pytest --override-ini 'addopts=' tests\test_maintenance.py tests\test_restoration.py tests\test_leases.py tests\test_durable_state.py tests\test_gateway.py tests\test_admission.py tests\test_factory_gateway_integration.py tests\test_service_lifecycle.py tests\test_integration_phase_d.py tests\test_policies.py tests\test_actions.py tests\test_processes.py tests\test_miner_adapter.py tests\test_phase2_miner_lifecycle.py tests\test_config.py tests\test_operator_credentials.py tests\test_cli.py -k 'not test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window' -q -ra --basetemp <candidate>\modules\resource_coordinator\.pytest_tmp_h2c_expanded_final_gate

python -m pytest --override-ini 'addopts=' tests\test_installation.py tests\test_windows_task_transport_integration.py tests\test_cli_architecture.py -q -ra --basetemp <candidate>\modules\resource_coordinator\.pytest_tmp_h2c_windows
python -m ruff check resource_coordinator/config.py resource_coordinator/core/durable_state.py resource_coordinator/core/maintenance.py resource_coordinator/core/service.py resource_coordinator/core/restoration.py resource_coordinator/adapters/lmstudio/gateway.py tests/test_config.py tests/test_maintenance.py tests/test_restoration.py
python -m compileall -q resource_coordinator tests
git diff --check
```

The `<candidate>` placeholder above means `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-v013-integration-restoration-20261111`. The command output and accepted exit codes are summarized in this status record; no live-system logs or telemetry were generated.

The three skips are opt-in real Windows Scheduled Task, read-only helper, and UAC tests; they were not enabled. The 249-test Windows/helper result preceded the final verifier-only scope/observer-serialization changes; the final expanded regression run includes those changes. A first async run exposed a test-fixture double binding of one gateway; the fixture was corrected and the focused test then passed. No product defect was indicated by that fixture failure.

## Safety and remaining acceptance

- No real GPU, KRig, LM Studio, production Coordinator, service, credential, Scheduled Task, or WSL state was read or changed for H2C acceptance.
- No RTX 5090/Windows WDDM NVML process-attribution or clock-offset capability was verified. `gpu_process_attribution_confirmed` stays false by default. NVIDIA documents device/driver-dependent support and process-query limitations; deployments must validate their exact profile before enabling automatic release ([NVML device queries](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html), [nvidia-smi process reporting](https://docs.nvidia.com/deploy/nvidia-smi/index.html)).
- When process attribution or any required setting cannot be verified, the correct behavior is no automatic release and an authenticated operator reconciliation. Locked-clock modes always require that path.
- H2B Mining commit `8f53e3d32d2bce560a2b35c802e6ac1c3fbfa7db` was inspected through the connected GitHub read-only source view. It implements acquisition idempotency/polling, server expiration, strict release dispositions, redaction and ownership confirmation before GPU busy checks ([Mining coordinator.py at H2B](https://github.com/MaxCarlson/Mining/blob/8f53e3d32d2bce560a2b35c802e6ac1c3fbfa7db/mining_optimizer/coordinator.py), [Mining cli.py at H2B](https://github.com/MaxCarlson/Mining/blob/8f53e3d32d2bce560a2b35c802e6ac1c3fbfa7db/mining_optimizer/cli.py)). It does not yet send `tuning_scope` or register optimizer trial PIDs. Those additive client changes are required for the trusted automatic release path. No Mining files were edited.
- Source tests validate fakes and mocked NVML only. The prior Windows upgrade `WinError 206`, isolated elevated Scheduled Task acceptance, production deployment, cross-repository H3 acceptance and actual hardware profile remain separate gates.

## Integration disposition

H2A and H2C source work is complete on the isolated feature branch. This is not approval to merge or deploy. After the H2B client adds scope and process registration, run cross-repository protocol tests. Before enabling automatic release, independently qualify NVML setting readback and complete process attribution on the exact deployment hardware/driver. Preserve operator recovery as the fallback. The next source integration review should use the final pushed commit recorded by the completing agent.

### Publication checkpoint

- A normal non-force push published the integration branch to `origin/agent/resource-coordinator-v013-integration-restoration-20261111` at `8c1fbd0509f20843829092827e094632a34aa75c`.
- A subsequent fetch confirmed the remote feature ref matched that commit, `origin/main` remained `6a57877b6304515172e75eaf4d28d2cce88514aa`, and the target remained an ancestor. No `main` ref was updated.
- Any later status-only commit and final remote SHA are reported in the completion message.
