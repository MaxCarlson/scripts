# Extensible Benchmark Platform Checklist

## Phase 00 — Baseline, Boundaries, and Contracts
- [x] Inspect local git status, recent commits, worktrees, active branches
- [x] Baseline test runs (`pytest agent_benchmark`, `pytest benchmark_core`, `ruff`, `git diff --check`)
- [x] Dedicated worktree (`C:\Users\mcarls\src\scripts\.worktrees\agent-benchmark-extensible-20261111`) and branch (`feature/agent-benchmark-extensible-framework-20261111`)
- [x] Capture legacy CLI signatures and outputs (`suite --help`, `suite list`, `external list --format json`)
- [x] Architecture contract and error taxonomy (`architecture-contract.md`)
- [x] CLI compatibility matrix and flag collision map (`cli-compatibility-matrix.md`)
- [x] Phase 00 deliverable documentation committed to task branch

## Phase 01 — Unified Benchmark, Dataset, and Cohort Registry
- [x] Implement `benchmarks/schema.py` (`BenchmarkDescriptor`, `DatasetDescriptor`, `CohortDescriptor`, `BackendDescriptor`, `ScorerDescriptor`)
- [x] Implement `benchmarks/catalog.py` (canonical registry, lookup, alias resolution, validation)
- [x] Implement `benchmarks/selection.py` (deterministic subset and cohort selection)
- [x] Migrate Harbor `DATASETS` into canonical catalog; provide backward-compatible facades in `harbor/datasets.py`
- [x] Migrate `aider-python-10` into canonical cohort catalog; provide backward-compatible `COHORTS` in `suite.py`
- [x] Register metadata-only descriptors for IFEval and LiveCodeBench
- [x] Update `suite list` and `external list` to read from the authoritative catalog
- [x] Unit tests for catalog, descriptors, aliases, collision rejection, and deterministic selection (`tests/catalog_test.py`)
- [x] Acceptance verification: `suite list -f json` includes Harbor datasets and Aider cohort; `external list` preserved

## Phase 02 — CLI Refactor and Backward Compatibility
- [x] Create `cli_commands/` module hierarchy (`task.py`, `suite.py`, `setup.py`, `external.py`, `models.py`, `experiment.py`, `common.py`)
- [x] Refactor `cli.py` to be a lightweight dispatcher
- [x] Preserve root task aliases (`plan`, `run`, `status`, `cleanup`, `smoke`) and add `task` namespace
- [x] Implement `setup` namespace parser with `-A/--all`
- [x] Wire `setup -A` and `setup plan -A` to dry-run planner; `setup install -A` to preview
- [x] Preserve `suite plan -A` as `--api-format`
- [x] Preserve `agent-bench`, `agent-benchmark`, and `agent_benchmark` entry points
- [x] Add golden parser tests and output compatibility tests (`tests/cli_refactor_test.py`)
- [x] Verify help text, JSON formatting, and `-F/--llm-friendly` output

## Phase 03 — Generic External Benchmark Setup and Source Locks
- [x] Implement `external_sources/` (`specs.py`, `manager.py`, `stores.py`, `receipts.py`)
- [x] Support resource types: `harbor_registry`, `git_sparse`, `git`, `huggingface_dataset`, `python_environment`, `container_image`
- [x] Implement external storage resolution outside tracked git checkout
- [x] Implement atomic staging, checksum verification, and `installed-sources.json` lock receipts
- [x] Implement `setup install -A -x`, `setup install -d <id> -x`
- [x] Implement `setup status -A`, `setup verify -A`
- [x] Implement `setup upgrade -d <id> -x` side-by-side versioning
- [x] Tests for atomic install, checksum mismatches, path traversal rejection, and lock verification

## Phase 04 — Backend-Neutral Persistent Suite Runner and Direct Model Client
- [x] Define backend protocols in `execution/contract.py` (`ExecutionBackend`, `ScoringAdapter`, `ResultNormalizer`)
- [x] Refactor `suite.py` to use generic backend dispatcher while retaining `RunStore`, checkpointing, and locking
- [x] Implement Harbor execution backend adapter wrapping existing `execute_harbor_run`
- [x] Implement direct-model OpenAI-compatible chat backend in `execution/direct_chat.py` using `httpx`
- [x] Implement mock/stub scoring adapter for offline testing
- [x] Preserve persistent checkpoint schema, resume capability, and LLM Monitor evidence capture
- [x] Unit and characterization tests for backend-neutral execution and resume

## Phase 05 — Official IFEval Integration
- [x] Implement `benchmarks/adapters/ifeval.py`
- [x] Pinned resource declarations for Google Research IFEval reference code and `input_data.jsonl`
- [x] Define frozen cohorts: `ifeval-smoke`, `ifeval-100`, `ifeval-full`
- [x] Implement prompt formatting and direct chat generation
- [x] Implement bridge to official Google IFEval evaluation logic (strict & loose prompt/instruction accuracy)
- [x] Fixture-based tests verifying strict/loose scoring parity against reference outputs
- [x] Offline E2E test with mock direct-chat backend

## Phase 06 — Official LiveCodeBench Direct Code Generation & Sandboxed Scoring
- [x] Implement `benchmarks/adapters/livecodebench.py`
- [x] Pinned resource declarations for LiveCodeBench `release_v6` code-generation-lite
- [x] Define frozen cohorts: `lcb-v6-smoke`, `lcb-v6-direct-100`, `lcb-v6-direct-full`
- [x] Implement code extraction and direct generation formatting
- [x] Implement container verifier (`execution/container_verify.py`) with strict security constraints
- [x] Fail-closed logic when container sandbox is unavailable
- [x] Bridge to official LiveCodeBench evaluation
- [x] Fixture tests for problem execution, timeout, syntax error, and memory bounds

## Phase 07 — Multi-Model Comparison, Score Granularity, and Reports
- [ ] Extend comparison conditions in `benchmark_core` or `agent_benchmark` (`declared-model-intervention-v1`)
- [ ] Implement paired task outcome matrix (both pass, both fail, A only, B only)
- [ ] Implement denominator and coverage calculations (planned, attempted, scored, invalid)
- [ ] Implement Wilson confidence intervals and paired difference statistics
- [ ] Add `suite compare` CLI command supporting JSON, table, and markdown formats
- [ ] Offline comparison tests with synthetic paired run data

## Phase 08 — Qualification, Third-Adapter Proof, and Documentation
- [ ] Run full CLI golden compatibility test suite
- [ ] Implement third synthetic benchmark adapter proving N-benchmark extensibility without framework edits
- [ ] Verify source setup integrity, hash verification, and corruption detection
- [ ] Verify IFEval and LiveCodeBench scorer parity
- [ ] Verify container sandbox enforcement and fail-closed behavior
- [ ] Update `docs/README.md`, `docs/HANDOFF.md`, and module documentation
- [ ] Run complete test suite and linters
- [ ] Prepare final delivery report and git checkpoint
