# Phase 00 Architecture Contract — Extensible Benchmark Platform

## 1. Context and Objective

Transform `agent_benchmark` into an extensible, multi-benchmark evaluation platform capable of supporting an arbitrary number of benchmark suites (Harbor-based agent benchmarks, direct-model benchmarks such as IFEval and LiveCodeBench, and custom third-party benchmarks) while maintaining complete backward compatibility with existing commands, JSON outputs, Harbor integration, and `benchmark_core` models.

## 2. Core Architectural Invariants

1. **No Vendoring or Tracked External Clones**:
   External repositories (`google-research/instruction_following_eval`, `LiveCodeBench/LiveCodeBench`), dataset files, Python virtual environments, and generated run artifacts MUST reside outside the git-tracked `scripts` repository.
   Default storage root:
   - Windows: `%LOCALAPPDATA%\agent-benchmark\`
   - Linux/WSL: `${XDG_DATA_HOME:-~/.local/share}/agent-benchmark/`
   Configurable via `--resource-root` without mutating legacy `-s/--state-dir`.

2. **Core Boundary**:
   `modules/benchmark_core` remains a pure result, data model, statistical analysis, and condition verification library.
   It MUST NOT contain:
   - Task scheduling or subprocess execution
   - LLM inference or HTTP clients
   - Docker or container management
   - Benchmark-specific dataset downloading

3. **Separation of Read-Only vs. Mutating Commands**:
   - `list`, `show`, `tasks`, `plan`, `doctor`, `report`, `compare`, `setup plan`, `setup status`, `setup verify`:
     MUST NEVER trigger LLM inference, download external datasets, create venvs, load models, or start Docker/WSL.
   - Any mutating operation (`install`, `run`, `resume`) requires explicit `-x/--execute`.
   - `setup install -A` without `-x` is strictly a dry-run preview.
   - `setup install -A -x` installs default required resource profiles only (not optional large test archives or unselected releases).

4. **Failure Classification**:
   - Infrastructure, scorer, environment, and network failures are NEVER counted as model task failures.
   - Denominator transparency: reports must clearly separate planned tasks, attempted tasks, validly scored tasks, and infrastructure-invalid tasks.
   - Valid attempts classify as `passed`, `failed`, or `timed_out` (when execution budget is legitimately exceeded by the model).
   - Scorer crash, verifier crash, missing sandbox, malformed output, or hash mismatch classify as `infrastructure_invalid` / `infrastructure_error`.

5. **Sandbox and Containment**:
   - Direct model-generated code (e.g., LiveCodeBench) must ONLY run in an isolated, non-networked, resource-constrained container/sandbox.
   - If Docker or container containment is unavailable, execution fails closed as a readiness blocker; code is never run unsandboxed on the host.

## 3. Interfaces and Protocols (Phase 01–04 Targets)

### 3.1 Registry Descriptors (`agent_benchmark.benchmarks.schema`)
- `BenchmarkDescriptor`:
  - `id`: canonical identifier (e.g., `ifeval`, `livecodebench`, `aider`, `terminal-bench`)
  - `name`: human-readable title
  - `version`: benchmark adapter version
  - `description`: overview
  - `supported_backends`: list of backend IDs (`harbor`, `direct_chat`, etc.)
  - `default_dataset`: default dataset canonical ID
  - `resources`: required resource declarations

- `DatasetDescriptor`:
  - `id`: unique dataset ID (e.g., `aider/aider-polyglot`, `terminal-bench/terminal-bench@4.0.0`, `ifeval/google-2023`, `livecodebench/release_v6`)
  - `benchmark_id`: reference to parent benchmark
  - `name`: dataset title
  - `version`: release or snapshot version
  - `scoring_protocol`: e.g. `single-attempt-v1`, `ifeval-strict-loose-v1`, `lcb-codegeneration-v1`
  - `source_repo`: upstream repo URL (if applicable)
  - `source_revision`: pinned commit or snapshot hash
  - `total_tasks`: total count (or None if dynamic/uninstalled)
  - `default_tasks`: default subset IDs

- `CohortDescriptor`:
  - `id`: canonical cohort identifier (e.g., `aider-python-10`, `ifeval-100`, `lcb-v6-direct-100`)
  - `dataset_id`: parent dataset ID
  - `source_revision`: pinned git SHA or dataset digest
  - `task_ids`: frozen, ordered list of task IDs (or deterministic recipe)
  - `description`: purpose and stratification

### 3.2 External Resources (`agent_benchmark.external_sources`)
- `ResourceSpec`:
  - `type`: `harbor_registry` | `git_sparse` | `git` | `huggingface_dataset` | `python_environment` | `container_image`
  - `url`: remote location
  - `revision`: exact 40-char commit SHA or dataset revision digest
  - `paths`: allowlisted paths for sparse checkout
  - `checksums`: mapping of path to expected SHA-256
- `InstallReceipt`:
  - Stored in `<resource-root>/locks/installed-sources.json`
  - Records installed path, commit, timestamp, platform, integrity digest

### 3.3 Execution Contracts (`agent_benchmark.execution`)
- `ExecutionPlan`:
  - Immutable run manifest containing backend, dataset, cohort, model identity, inference parameters (temperature, max_tokens, etc.), and timeout budgets.
- `TaskContext`:
  - Task identity, inputs, and execution parameters.
- `BackendAttempt`:
  - Raw generation artifacts, tokens observed, latency, exit codes.
- `ScoringAdapter`:
  - `score(task_context, attempt)` -> `ScoredAttempt` containing authoritative metrics, details, and failure classifications.

## 4. Error Taxonomy

| Error Code | Classification | Meaning |
|---|---|---|
| `SETUP_NOT_INSTALLED` | Readiness blocker | Upstream source, dataset, or scorer venv not installed |
| `SOURCE_MISMATCH` | Infrastructure invalid | Installed Git commit or dataset hash does not match pinned receipt |
| `SCORER_MISMATCH` | Infrastructure invalid | Scorer binary or environment digest differs from lock |
| `SANDBOX_UNAVAILABLE` | Readiness blocker | Docker daemon / verifier container unavailable for untrusted execution |
| `MODEL_UNAVAILABLE` | Readiness blocker | Local model server unreachable or requested model not loaded |
| `EXECUTION_UNCERTAIN` | Infrastructure invalid | Ambiguous process termination or lost monitor connection |
| `SCORE_INVALID` | Infrastructure invalid | Scorer crashed, threw unhandled exception, or emitted invalid schema |
| `NETWORK_FORBIDDEN` | Security error | Unauthorized network attempt during sandboxed execution |
| `TASK_TIMEOUT` | Scored attempt | Model legitimately ran out of inference/execution budget |
| `TASK_FAILED` | Scored attempt | Model solution evaluated and failed verification |
| `TASK_PASSED` | Scored attempt | Model solution satisfied all verification criteria |
