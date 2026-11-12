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


## 8. Phase 04 Acceptance Gate
- [x] Backend-neutral execution framework implemented in `execution/` (`contract.py`, `direct_chat.py`, `harbor_backend.py`, `mock_backend.py`, `registry.py`, `__init__.py`).
- [x] Core contracts implemented: `ExecutionPlan`, `TaskContext`, `BackendAttempt`, `ScoredAttempt`, `ExecutionBackend`, `ScoringAdapter`, `ResultNormalizer`.
- [x] Direct-model OpenAI-compatible chat completion client (`DirectChatBackend`) implemented with allowlisted endpoint validation, token accounting, per-request IDs, and failure classification (`INFERENCE_HTTP_ERROR`, `INFERENCE_TIMEOUT`, `INFERENCE_CONNECTION_ERROR`).
- [x] Persistent `suite.py` refactored to support generic execution backends while preserving 100% of existing Harbor execution semantics, run store checkpointing, and LLM Monitor integration.
- [x] Direct execution manifests do not require Docker or Harbor, enabling lightweight local LLM execution.
- [x] Summarize and report metrics updated to aggregate wall times and token usage across both Harbor and direct execution runs.
- [x] 45 unit and regression tests passing (`execution_test.py`, `suite_test.py`, `suite_cli_test.py`).
- [x] Ruff lint checks 100% clean on all Phase 04 files.
- [x] Zero live model inference calls dispatched; deterministic mocks and fixtures used exclusively.

**Status:** Phase 04 is COMPLETE and gate satisfied. Ready to proceed to Phase 05.


## 9. Phase 05 Acceptance Gate
- [x] IFEval adapter implemented (`benchmarks/adapters/ifeval.py`, `__init__.py`).
- [x] JSONL dataset loader for `input_data.jsonl` with exact prompt preservation, instruction ID lists, and kwargs.
- [x] Deterministic 100-task stratified cohort selector across instruction categories (`select_stratified_100_cohort`).
- [x] Official strict and loose scoring rules implemented (`IFEvalScoringAdapter`), correctly evaluating word count relations, casing, JSON format, punctuation, conversational prefixes, and markdown blocks.
- [x] Registered `ifeval_official` scorer in execution registry; outputs `ifeval.strict_prompt`, `ifeval.loose_prompt`, `ifeval.strict_instructions_passed`, `ifeval.loose_instructions_passed`, `ifeval.instructions_total`, and instruction-level accuracy metrics.
- [x] Offline end-to-end execution tested with mock HTTP client; reports 100% pass rate on compliant uppercase responses across 5 smoke tasks.
- [x] 14 unit and regression tests passing (`ifeval_test.py`, `catalog_test.py`).
- [x] Ruff lint checks 100% clean on all Phase 05 files.
- [x] Zero live inference calls dispatched.

**Status:** Phase 05 is COMPLETE and gate satisfied. Ready to proceed to Phase 06.


## 10. Phase 06 Acceptance Gate
- [x] LiveCodeBench adapter implemented (`benchmarks/adapters/livecodebench.py`, `__init__.py`).
- [x] Secure container verifier implemented (`execution/container_verify.py`) with strict security policies (`--network none`, `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, CPU/memory caps).
- [x] Fail-closed verification: when Docker sandbox is unavailable, verifier refuses to run code on host and raises `SandboxUnavailableError`, resulting in `status="infrastructure_invalid"` and `error_code="CONTAINER_SANDBOX_UNAVAILABLE"`.
- [x] Python code extraction implemented (`extract_python_code`) supporting markdown blocks, fallback extraction, and early syntax error rejection via `ast.parse` (`error_code="SYNTAX_ERROR"`).
- [x] Official LCB scoring adapter (`LCBScoringAdapter`) registered as `lcb_official` in execution registry; outputs `pass@1`, execution duration, and exit codes.
- [x] Deterministic 100-problem stratified cohort selector (`select_stratified_lcb_100`) covering easy, medium, and hard difficulty groups.
- [x] Populated smoke and 100-problem cohorts (`lcb-v6-smoke`, `lcb-v6-direct-100`) in catalog.
- [x] 8 unit tests passing in `livecodebench_test.py` covering code extraction, sandbox security, fail-closed enforcement, and end-to-end suite execution.
- [x] Ruff lint checks 100% clean on all Phase 06 files.
- [x] Untrusted model-generated code NEVER executed on host.

**Status:** Phase 06 is COMPLETE and gate satisfied. Ready to proceed to Phase 07.


## 11. Phase 07 Acceptance Gate
- [x] Multi-model comparison module implemented (`comparison.py`).
- [x] Paired task discordance matrix (`both_passed`, `both_failed`, `a_only`, `b_only`, `unpaired`) computed on matching tasks.
- [x] Wilson 95% confidence intervals and coverage percentage calculations implemented.
- [x] Strict comparability verification: flags differing cohorts, source revisions, or unshared tasks in `blockers` without silent comparison corruption.
- [x] Output formatters implemented: formatted terminal table (`format_comparison_table`), Markdown report (`format_comparison_markdown`), and structured JSON.
- [x] CLI command `agent-benchmark suite compare -r RUN_A RUN_B` implemented and tested with `-f table|json|markdown` and `-F/--llm-friendly`.
- [x] `declared_model_intervention_error` contract implemented in `benchmark_core.conditions` supporting `declared-model-intervention-v1`.
- [x] 6 unit tests passing in `comparison_test.py` with 100% clean Ruff checks.

**Status:** Phase 07 is COMPLETE and gate satisfied.

## 12. Phase 08 Acceptance Gate & Final Qualification
- [x] Full CLI golden compatibility verified across all commands (`setup -A`, `suite list`, `suite compare`, `external list`, `task` commands).
- [x] Third synthetic benchmark adapter implemented (`tests/synthetic_adapter_test.py`) proving generic N-benchmark extensibility without modifying shared framework, CLI definitions, scheduler, or results storage.
- [x] Descriptor-only registration of an additional Harbor dataset verified.
- [x] Source setup integrity, hash calculation, atomic staging, and corruption detection verified.
- [x] Scorer fidelity verified for IFEval (strict/loose prompt & instruction accuracy) and LiveCodeBench (direct code generation).
- [x] Runtime isolation verified: Docker container verifier fails closed when daemon is offline; no contestant code runs on host.
- [x] Full test suite passing:
  - `benchmark_core`: 120 passed, 1 skipped (100%).
  - `agent_benchmark`: 696 passed, 10 skipped (100%).
  - Ruff check: 0 errors (100% clean).
- [x] Comprehensive delivery report and extensibility guide published in `08_qualification_and_delivery.md`.
- [x] Zero unapproved live LLM calls, zero model downloads, zero host background daemon modifications.

**Final Status:** All Phases 00 through 08 are COMPLETE. The extensible benchmark platform is fully qualified and READY TO MERGE pending explicit user authorization.
