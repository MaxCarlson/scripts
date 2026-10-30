# Harbor Integration Checklist

**Plan:** `20261029-1755_harbor-integration`  
**Branch:** `harbor-integration-20261029-1755`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755`  
**Authoritative Baseline:** Agent Benchmark 1.20.0, Benchmark Core 0.2.0, Harbor 0.25.0  

---

## Stage A: Harbor Research and Offline Importer
- [x] Create `harbor/` subpackage under `agent_benchmark/`
- [x] Implement `harbor/models.py` (Pydantic models for Harbor 0.25.0 `JobResult`, `TrialResult`, `JobLock`, `ErrorPolicy` mapping)
- [x] Implement `harbor/importer.py` (idempotent normalization into `benchmark_core` `RunInfo` / `TrialResult`)
- [x] Implement `external import` CLI subcommand in `agent_benchmark/cli.py`
- [x] Create sanitized Harbor job fixture and test suite in `tests/harbor_importer_test.py`
- [x] Verify test suite passes without inference or Docker requirements
- [x] Stage A validation and review

## Stage B: Dataset Catalog and Non-Executing Planning
- [x] Implement `harbor/datasets.py` (authoritative catalogs for `aider/aider-polyglot` 225 tasks and `terminal-bench` 89 tasks / 5 pinned CPU tasks)
- [x] Implement language filtering for Aider and deterministic seed subset selection
- [x] Implement `harbor/planner.py` (preflight readiness checks, `base_url` routing, resource and trial projections)
- [x] Implement `external list` and `external plan` CLI subcommands
- [x] Create unit tests in `tests/harbor_planner_test.py` and `tests/harbor_datasets_test.py`
- [x] Stage B validation and review

## Stage C: Controlled Execution
- [x] Implement `harbor/runner.py` (subprocess invocation with argument array, `--include-task-name`, `--base-url`, `-x/--execute` gate)
- [x] Implement Docker daemon connectivity verification (fail closed if unavailable)
- [x] Integrate with `state.py` command lock and pending receipt recovery
- [x] Implement `external run` CLI subcommand
- [x] Create unit tests for runner execution, authorization gates, and failure modes in `tests/harbor_runner_test.py`
- [x] Stage C validation and review

## Stage D: Multi-Agent Evaluation & Comparative Leaderboard
- [x] Implement `harbor/reporting.py` (recursive `rglob("run.json")` discovery, `run_id` deduplication, dataset-separated leaderboard)
- [x] Implement `external report` CLI subcommand
- [x] Create tests for multi-agent leaderboard comparisons in `tests/harbor_importer_test.py` and `tests/harbor_cli_test.py`
- [x] Stage D validation and review

## Stage E: Terminal-Bench Extension, Documentation & Final Hardening
- [x] Curate five CPU-oriented tasks within Terminal-Bench 2.0 and record the reviewed task resource profile
- [ ] Before any Terminal-Bench execution, inspect `log-summary-date-ranges` resource and timeout values at the pinned task source revision (not present in the preserved pilot lock)
- [x] Correctly register Terminal-Bench 2.0 (89 tasks) and Terminal-Bench 4.0.0 (66 tasks) as distinct dataset identities
- [x] Add regression tests for dataset selection, Harbor registry names, and lock-based source revision attribution
- [x] Import a corrected derived report for the historical Oracle trial while preserving the original raw and imported evidence
- [x] Update `modules/agent_benchmark/README.md` with instructions for Harbor setup, Windows 11 / WSL2, Docker, and `agent-bench external` CLI
- [x] Run full repository regression test suite (`agent_benchmark`: 445 passed, 3 skipped; `benchmark_core`: 116 passed, 1 skipped)
- [x] Run lint (`ruff`) and static checks: All checks passed
- [x] Update `STATUS.md` and `HANDOFF.md`

## Live Evaluation Acceptance (Phases A–E)
- [x] Phase A: Verify Docker Linux engine, Harbor 0.25.0 CLI, LM Studio (`qwen38_23GB`), and `host.docker.internal:1234` routing
- [x] Phase B: Execute first live local Qwen trial on Aider Polyglot (`polyglot_python_proverb` -> `reports/harbor/pilot-qwen`)
- [x] Phase C: Execute frozen 10-task deterministic Python baseline (7/10, 100% scored coverage; manifest and evidence preserved)
- [x] Phase D: Audit `codex` and `antigravity-cli` Harbor schemas and credential contracts without paid inference
- [x] Phase E: Execute live Terminal-Bench trial (`build-cython-ext` with `oracle` -> `reports/harbor/tb-pilot`) and multi-suite report

## Remaining Comparative Evaluations
- [x] Prepare the identical-task Codex and Antigravity protocol and commands (no cloud inference executed)
- [ ] Execute Codex and Antigravity against the frozen task set after explicit inference authorization
