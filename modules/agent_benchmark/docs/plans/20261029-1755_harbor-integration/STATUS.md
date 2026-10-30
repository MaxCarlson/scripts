# Status: Harbor Integration and Deterministic Coding-Agent Evaluation

**Current Stage:** Complete (Stages A–E Verified)  
**Branch:** `harbor-integration-20261029-1755`  
**Working Directory:** `modules/agent_benchmark/`  
**Package Version Baseline:** 1.20.0 (Agent Benchmark), 0.2.0 (Benchmark Core)  
**Pinned External Version:** `harbor==0.25.0`  

---

## Completed Capabilities
1. **Schema Models & Status Normalization (`agent_benchmark.harbor.models`)**:
   - Pydantic v2 schemas for Harbor 0.25.0 `JobResult`, `TrialResult`, `JobLock`, `VerifierResult`, `AgentContext`, and `ErrorPolicy`.
   - Objective status mapping: 1.0 -> `passed` (1 pt), 0.0 -> `failed` (0 pt), `AgentTimeoutError` -> `timed_out` (0 pt), sandbox/provider/verifier failure -> `infrastructure_error` (unavailable).
2. **Offline Importer (`agent_benchmark.harbor.importer`)**:
   - `HarborImporter` loads Harbor job directories, extracts task digests from `lock.json`, computes timing/token/cost totals, and translates records into canonical `benchmark_core` `RunInfo` and `TrialResult`.
   - Generates standard `run.json`, `trials.jsonl`, `summary.json`, `summary.csv`, `report.md`, and extended `harbor_summary.json`.
   - Idempotent re-import: re-running against the same directory overwrites cleanly without generating duplicate trial IDs.
3. **Dataset Catalog & Task Selection (`agent_benchmark.harbor.datasets`)**:
   - Catalog for `aider/aider-polyglot` (225 tasks across python, cpp, go, java, javascript, rust) and `terminal-bench@4.0.0` (pinned 5 CPU-only tasks).
   - Language filtering, explicit task ID filtering, and reproducible seed-based sampling (`random.Random(seed)`).
4. **Non-Executing Planner (`agent_benchmark.harbor.planner`)**:
   - Preflight environment verification: Docker daemon responsiveness and Harbor CLI availability.
   - Fail-closed safety: planning reports readiness blockers and exits cleanly without running models or starting containers.
5. **Authorized Execution Runner (`agent_benchmark.harbor.runner`)**:
   - Subprocess argument array execution of `harbor run` (never shell string interpolation).
   - Mandatory authorization gate: `-x/--execute` required; refuses otherwise.
   - Fails closed if Docker daemon is not active.
   - Command lock protection under `state.py`.
6. **Comparative Reporting (`agent_benchmark.harbor.reporting`)**:
   - Groups results by benchmark suite and protocol.
   - Calculates points earned, pass rate, coverage, median duration, infrastructure errors, and costs.
   - Renders GitHub-flavored Markdown leaderboard tables.
7. **CLI Integration (`agent_benchmark.cli`)**:
   - Added subcommand group `agent-bench external [list | plan | run | import | report]`.

## Verification Evidence
- 34 focused unit and CLI tests in `tests/harbor_*_test.py`: 100% pass.
- Full `modules/agent_benchmark/tests` regression: 436 passed, 3 skipped.
- Full `modules/benchmark_core/tests` regression: 114 passed, 1 skipped.
- Static analysis with `ruff`: all checks passed cleanly.
- Hardened audit verification:
  - Decoupled dataset identifier and version (`suite_id`, `suite_version`) from Harbor framework package version (`harbor_package_version`).
  - Hardened status evaluation against NaN/Inf values, multi-dimensional reward dicts, and enforced terminal exception precedence over partial verifier output.
  - Enforced deterministic candidate task sorting prior to sampling.
  - Subprocess execution hardened with unique job names (`--job-name`) and fail-closed exit code checks.
  - Leaderboard reporting deduplication for identical jobs imported into multiple directories.
  - Authentic Harbor 0.25.0 native serialization fixture test verified (`harbor_native_0_25_0.json`).
