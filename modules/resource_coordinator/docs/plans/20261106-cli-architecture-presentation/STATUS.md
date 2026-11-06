# Resource Coordinator CLI Architecture and Presentation

## Goal

Expose seven canonical command groups while preserving every existing command path and flag, and use centralized Rich presentation for human output with uncontaminated optional JSON.

## Implementation choices

- Keep `argparse`; represent legacy root commands as hidden parsers, and give both legacy and canonical parsers stable `operation_id` values so application handlers are shared.
- Keep existing handlers and endpoint/mutation behavior; move parser construction and shared output rendering into focused modules where this reduces coupling.
- Rich handles human presentation only. JSON and raw log streams bypass Rich; application logs go to stderr and default to warnings/errors.
- `serve` remains an indefinite compatibility path for managed launchers. `restart` remains service lifecycle and `upgrade` remains system code activation.
- No live service/task/GPU/model operations and no TUI in this phase.

## Checkpoints

1. Record legacy parser/flag/operation contracts with table-driven tests.
2. Add canonical parser tree, hidden compatibility parsers and operation normalization; validate help and aliases.
3. Add Rich output policy and centralized human/JSON renderers; verify JSON stdout and raw log behavior.
4. Convert command families incrementally, preserve errors/exit codes, update help and README.
5. Run focused and relevant module regressions, Ruff, compileall and diff checks; review, commit and integrate only validated files.

## Current status

- [x] Verified Phase 1 at `c12779ab7dc69bac133b495757dc97989a51dcf9`, pushed to `origin/main`.
- [x] Reused the clean Phase 1 worktree and created branch `codex/resource-coordinator-cli-refactor-20261106`; primary `main` and its unrelated dirty files are untouched.
- [x] Added table-driven legacy flag/path and canonical operation-ID contracts; canonical and legacy paths normalize to shared handler arguments.
- [x] Added seven-group canonical help hierarchy while preserving hidden root aliases, legacy `serve`, `recover -r/-n`, and `accept -u` meanings.
- [x] Added centralized Rich human rendering, semantic status colors, `NO_COLOR`/TTY policy, JSON redaction, warning-level default console logging, and raw log passthrough.
- [x] Converted structured CLI output including auth, miner/gaming status, config validation, diagnostics, lifecycle, recovery, and installation/upgrade results; maintained finite JSON stdout and error exit codes.
- [x] Documented the canonical hierarchy, compatibility mapping, flag/output policy, and distinction between service restart, code upgrade, and safety recovery.
- [x] Final focused offline regressions: 277 passed; bridge route regressions: 2 passed, 29 deselected.
- [x] Ruff, Python compilation, and `git diff --check` passed.

### Validation evidence

- `$env:PYTHONPATH = (Join-Path (Get-Location) 'modules/resource_coordinator'); python -m pytest -o addopts='' --basetemp=modules/resource_coordinator/.pytest_tmp_root modules/resource_coordinator/tests/test_cli.py modules/resource_coordinator/tests/test_cli_architecture.py modules/resource_coordinator/tests/test_installation.py modules/resource_coordinator/tests/test_operator_credentials.py modules/resource_coordinator/tests/test_service_lifecycle.py modules/resource_coordinator/tests/test_phase2_miner_lifecycle.py modules/resource_coordinator/tests/test_gateway.py modules/resource_coordinator/tests/test_factory_gateway_integration.py -q` — **277 passed**.
- `$env:PYTHONPATH = (Join-Path (Get-Location) 'modules/local_agent_bridge'); python -m pytest -o addopts='' modules/local_agent_bridge/tests/model_limits_test.py -k 'inference_route_defaults_to_coordinator_and_cannot_fall_back_to_lm_studio or active_delete_switch_uses_coordinator_route' -q` — **2 passed, 29 deselected**.
- Ruff on changed Resource Coordinator Python files — **passed**.
- `python -m compileall -q modules/resource_coordinator/resource_coordinator` — **passed**.
- `git diff --check` — **passed**.
- One earlier combined test attempt used pytest's default `%TEMP%` and failed with `PermissionError: [WinError 5]` under the elevated runner. Re-running with the module-local `--basetemp` succeeded; this is not a product failure.

No live coordinator, miner, GPU, LM Studio, or Scheduled Task was queried or changed. The default restricted runner hung at the async CLI preflight test; running the same focused suite in the approved normal-permission context completed successfully.

### Implementation files

- `resource_coordinator/cli_parser.py`: parser hierarchy and compatibility parsing.
- `resource_coordinator/cli_dispatch.py`: stable operation-ID normalization into existing handler argument shapes.
- `resource_coordinator/presentation.py`: Rich text/tables, JSON redaction, and color selection.
- `resource_coordinator/cli.py`: shared dispatch and human/JSON output integration.
- `resource_coordinator/installation.py`: shared renderer for setup/upgrade results.
- `tests/test_cli_architecture.py` and `tests/test_cli.py`: compatibility, dispatch, help, JSON, color, and raw-log coverage.
- `pyproject.toml`, `resource_coordinator/__init__.py`: Rich dependency and package version `0.11.0`.
- `README.md`: command hierarchy and compatibility documentation.

Pending: scoped final diff review, package-install verification if required by integration, checkpoint commit, and safe merge into the latest `main`. No live deployment is authorized by this phase.

## Initial repository facts

- `cli.py` currently constructs 19 top-level parsers and contains handlers, transport, formatting and logging setup.
- `config` and `logs` are already top-level groups and remain there.
- Existing handlers cover setup/upgrade/repair/teardown/startup/auth, service lifecycle, config, miner/gaming, logs, preflight, diagnostics, accept and abort.
- Current package version is 0.10.0; add Rich as a compatible dependency and advance the minor version when implementation is complete.
- No module-specific `AGENTS.md` exists. The primary `main` checkout contains preserved unrelated changes and will not be used for edits.
