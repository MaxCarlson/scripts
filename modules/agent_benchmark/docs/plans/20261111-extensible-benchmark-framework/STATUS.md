# Phase 00 Status — Baseline Inspection & Architecture Specification

## 1. Environment & Repository Status
- **Date:** 2026-11-11
- **Branch:** `feature/agent-benchmark-extensible-framework-20261111`
- **Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\agent-benchmark-extensible-20261111`
- **Base Commit:** `6467edc6` (clean working tree from `main`, ancestor of latest origin updates)
- **Python Environment:** `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe` (Python 3.12.x)

## 2. Baseline Test Execution Evidence

| Test Suite | Command | Result | Notes |
|---|---|---|---|
| `agent_benchmark` tests | `python -m pytest modules/agent_benchmark/tests -q` | 641 passed, 10 skipped, 3 failed | Failures: 2 Docker-unreachable errors in `opencode_v2_test.py` (Docker Desktop daemon not running on Windows host), 1 mock error in `adversarial_incident_test.py` |
| `benchmark_core` tests | `python -m pytest modules/benchmark_core/tests -q` | 119 passed, 1 skipped | Baseline completely passing |
| Ruff linting | `python -m ruff check modules/agent_benchmark modules/benchmark_core` | 26 errors (pre-existing) | Unused imports / variables in doctor, recovery, and test modules |
| Git diff check | `git diff --check` | 0 errors | Clean whitespace |

## 3. Discrepancy Reconciliation
- `agent-benchmark external list --format json`:
  Reads from `agent_benchmark.harbor.datasets.DATASETS` containing `aider/aider-polyglot`, `terminal-bench/terminal-bench@4.0.0`, and `terminal-bench/terminal-bench-2`.
- `agent-benchmark suite list`:
  Reads from `agent_benchmark.suite.COHORTS` containing only `aider-python-10`.
- **Root Cause Confirmed:** Distinct, duplicated registries.
- **Resolution Strategy:** Phase 01 introduces a single canonical catalog and backward-compatible lookup facades.

## 4. Phase 00 Acceptance Gate
- [x] Local repository inspected, clean worktree created on isolated branch.
- [x] Baseline commands and test results recorded.
- [x] Architecture contract and error taxonomy documented (`architecture-contract.md`).
- [x] CLI compatibility matrix and flag scoping documented (`cli-compatibility-matrix.md`).
- [x] Phase 01–08 roadmap and checklist defined (`plan.md`, `checklist.md`).
- [x] No LLM inference, model loading, external cloning, or Docker modification occurred.

**Status:** Phase 00 is COMPLETE and gate satisfied.

## 5. Phase 01 Acceptance Gate
- [x] Unified catalog package implemented (`benchmarks/schema.py`, `benchmarks/catalog.py`, `benchmarks/selection.py`).
- [x] Backward-compatible facades in `harbor/datasets.py` (`DATASETS`, `resolve_dataset`, `select_tasks`) and `suite.py` (`COHORTS`).
- [x] Terminal-Bench datasets (`terminal-bench/terminal-bench@4.0.0`, `terminal-bench/terminal-bench-2`) present in unified discovery and visible in `suite list`.
- [x] Initial registered-but-not-installed descriptors for IFEval (`ifeval/google-2023`, `ifeval-smoke`, `ifeval-100`, `ifeval-full`) and LiveCodeBench (`livecodebench/release_v6`, `lcb-v6-smoke`, `lcb-v6-direct-100`, `lcb-v6-direct-full`).
- [x] `suite list` supports `-f/--format table|json` while maintaining default JSON payload containing backward-compatible `cohorts` key.
- [x] 39 tests passed in 7.4s (`catalog_test.py`, `harbor_datasets_test.py`, `suite_test.py`, `harbor_cli_test.py`).
- [x] Ruff lint checks clean on all Phase 01 files.
- [x] Zero model calls, downloads, or system runtime mutations.

**Status:** Phase 01 is COMPLETE and gate satisfied.

## 6. Phase 02 Acceptance Gate
- [x] Modular `cli_commands/` package implemented (`task.py`, `models.py`, `experiment.py`, `external.py`, `setup.py`, `suite.py`, `common.py`).
- [x] `cli.py` refactored from ~1,200 lines to a readable 125-line root parser/dispatcher.
- [x] `setup -A` and `setup plan -A` parse as equivalent read-only plans for all registered default benchmark resources.
- [x] `setup install -A` produces a non-mutating dry-run preview; `setup install -A -x` stubs Phase 03 without fake success.
- [x] Flag `-A` scoping verified: `-A` means `--all` in `setup`, but remains `--api-format` in `suite plan`.
- [x] Root aliases `plan`, `run`, `status`, `cleanup`, `smoke` preserved alongside canonical `task` namespace.
- [x] All 52 regression and parser tests passed (`cli_refactor_test.py`, `cli_test.py`, `suite_cli_test.py`, `harbor_cli_test.py`, `catalog_test.py`).
- [x] Ruff lint checks clean on all Phase 02 files.
- [x] Zero model calls, downloads, or unapproved mutations.

**Status:** Phase 02 is COMPLETE and gate satisfied. Ready to proceed to Phase 03.


## 7. Phase 03 Acceptance Gate
- [x] External source management subsystem implemented (`external_sources/specs.py`, `stores.py`, `receipts.py`, `manager.py`, `__init__.py`).
- [x] Standard external directory store layout outside Git-tracked repository (`%LOCALAPPDATA%\agent-benchmark` on Windows / `XDG_DATA_HOME` on Linux).
- [x] Content-addressed atomic installation staging and lock file persistence (`locks/installed-sources.json`).
- [x] Path traversal prevention and safety checks (`validate_safety`) enforcing clean identifier paths.
- [x] File and tree SHA-256 hash calculation, verification, and corruption discovery (`verify_resource`).
- [x] CLI commands implemented and tested: `setup -A`, `setup plan -A`, `setup install -A`, `setup install -A -x`, `setup status -A`, `setup verify -A`, `setup upgrade`.
- [x] Read-only commands perform zero downloads or mutations; `-x/--execute` required for any external installation or modification.
- [x] 40 unit and regression tests passing (`setup_sources_test.py`, `cli_refactor_test.py`, `catalog_test.py`, `cli_test.py`).
- [x] Ruff lint checks 100% clean on all Phase 03 files.
- [x] Zero live LLM calls, zero model downloads, system Python env untouched.

**Status:** Phase 03 is COMPLETE and gate satisfied. Ready to proceed to Phase 04.
