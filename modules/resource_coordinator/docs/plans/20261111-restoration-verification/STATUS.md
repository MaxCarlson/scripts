# H2A + H2C — Status

## H2A integrated-source checkpoint

- Repository: `C:\Users\mcarls\src\scripts`.
- Branch: `agent/resource-coordinator-v013-integration-restoration-20261111`.
- Worktree: `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-v013-integration-restoration-20261111`.
- Main base: `6a57877b6304515172e75eaf4d28d2cce88514aa` (`origin/main` at integration).
- Maintenance source: `e6a28b929c0a6f8dc8ddf6f31f3553e15a44335e`.
- Merge base: `3d1cefa0596cfba5a68e436589f3bba7edc04a53`.
- Integrated merge checkpoint: `d84865883baaa7e88af280eb3563d3a59694ae6e`.
- Incoming change paths: 16, all in `modules/resource_coordinator/`; merge had no conflicts. Concurrent main changes affecting other modules were retained.
- Primary checkout's dirty paths were inspected and left untouched. The published maintenance feature worktree remains clean and intact.

### H2A validation

Runtime: Windows, Python 3.12.10, pytest 9.0.3, pytest-asyncio 1.3.0; `PYTHONPATH` explicitly pointed at the integration worktree's `modules/resource_coordinator`, and `resource_coordinator.__file__` resolved inside that worktree.

Focused command, from `modules/resource_coordinator`:

```powershell
$env:PYTHONPATH=(Get-Location).Path
python -m pytest --override-ini 'addopts=' tests\test_maintenance.py -vv -ra --basetemp <unique-candidate-temp>
```

Result: exit 0, **30 passed**.

Expanded command:

```powershell
$env:PYTHONPATH=(Get-Location).Path
python -m pytest --override-ini 'addopts=' tests\test_maintenance.py tests\test_leases.py tests\test_durable_state.py tests\test_gateway.py tests\test_admission.py tests\test_factory_gateway_integration.py tests\test_service_lifecycle.py tests\test_integration_phase_d.py tests\test_policies.py tests\test_actions.py tests\test_processes.py tests\test_miner_adapter.py tests\test_phase2_miner_lifecycle.py tests\test_config.py tests\test_operator_credentials.py tests\test_cli.py -k 'not test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window' -q -ra --basetemp <unique-candidate-temp>
```

Result: exit 0, **214 passed, 1 deselected** in 14.09 seconds. The deselected GPU-idle restart test was previously shown to fail identically on the unchanged maintenance baseline due persisted manual-hold behavior; it is unrelated to incoming main changes.

Static checks (exit 0):

```powershell
python -m ruff check <nine changed Python paths>
python -m compileall -q resource_coordinator tests
git diff --check origin/main...HEAD
```

Sandbox diagnostics: the expanded pytest command showed no progress for over a minute and was stopped; a standalone `asyncio.run(asyncio.sleep(0))` also exceeded an 8-second process watchdog in the sandbox. The identical isolated maintenance suite passed with normal Windows socket permissions. This is recorded as an execution-environment restriction, not a product failure. No production listener, miner, GPU, Scheduled Task, service, or WSL action was performed.

Prior broad exploratory run disposition (from the published feature status): stale architecture expectations (2), unavailable loopback port (1), corrected short cooldown fixture (1), acceptance harness temp-lock/timing instability (1; isolated test passed), and live-mode guard correctly refusing its already-running-miner target (1). They were not counted as H2A passes. No live test was retried.

## H2C implementation checkpoint

Pending. See `plan.md`. The current H2A merge commit is preserved as the base for verifier work. Do not claim automatic optimizer release until Mining adds tuning-scope declaration and exact trial-process registration, and target Windows/NVML capabilities are accepted.
