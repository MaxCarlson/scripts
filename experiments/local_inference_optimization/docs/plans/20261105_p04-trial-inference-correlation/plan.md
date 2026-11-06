# P04 Verified Trial-to-Inference Correlation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace temporal request attribution in new monitored OpenCode suite runs with authenticated, execution-scoped correlation that persists through LLM Monitor history and benchmark reports.

**Architecture:** The benchmark registers a short-lived execution credential over the Monitor's local capability channel before Harbor dispatch. A scoped Harbor OpenCode v1 adapter injects the credential as an inline `OPENCODE_CONFIG_CONTENT` provider header inside the task container. The gateway verifies the credential, associates its own request ID with validated run/task/execution metadata, persists the association, and strips the credential from upstream headers. Existing manifests without the correlation schema retain legacy report handling.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, httpx, pytest, Harbor 0.25.0, OpenCode 1.19.5.

**Spec:** User-provided P04 implementation handoff; original phase source `C:\Users\mcarls\Downloads\local_llm_inference_optimization_master_and_P00-P20\local_llm_optimization_handoffs\phases\P04_effective_parameter_and_runtime_evidence_instrumentation.md`.

## Global Constraints

- No model calls, benchmark dispatch, live service changes, GPU tests, or inference-environment changes.
- Preserve `lio-evidence-v1`, `lio-experiment-v1`, and `lio-variant-v1`; correlation never upgrades requested/forwarded data to effective settings.
- Keep auth capabilities scoped; store only credential hashes in memory and never write the trace credential into manifests, logs, or upstream requests.
- Preserve historical checkpoints and report readers; distinguish score validity from evidence eligibility.
- Restrict edits to LLM Monitor, Agent Benchmark, LIO evidence tests/docs, and their focused tests.
- Base commit: `f6aac8b98c2931ae7cc474dd15f0aaf4df20eb56`; worktree: `.worktrees/agent-local-inference-p04-correlation-20261105`.

## Review Focus

1. Invalid, expired, mismatched, or post-close credentials must be rejected before upstream dispatch.
2. Concurrent executions and unrelated traffic must remain isolated by execution ID, independent of request timing and repeated task names.
3. The host-to-Harbor boundary must explicitly inject only the scoped OpenCode config into the task process; host environment inheritance alone is insufficient.
4. Credential and prompt data must stay out of persistence, logs, reports, and upstream headers while correlation metadata survives SQLite history serialization.
5. Missing/dropped/delayed capture must make correlation evidence incomplete without changing an already scored verifier outcome.

---

### Task 1: Define and test execution-correlation contracts

**Files:**
- Create: `modules/llm_monitor/llm_monitor/inference_correlation.py`
- Modify: `experiments/local_inference_optimization/contracts.py` only if the existing adapters cannot carry bounded correlation metadata without a schema change.
- Test: `modules/llm_monitor/tests/inference_correlation_test.py`
- Test: `experiments/local_inference_optimization/tests/contracts_test.py`

**Interfaces:**
- `ExecutionContext`: schema version, run ID, task ID, execution ID, optional trial/repetition/variant IDs, verification status and provenance source.
- `ExecutionCredentialRegistry`: register, verify, record gateway request ID, close/reconcile trial ID, and retrieve execution request metadata.
- Credential serialization is separate from evidence serialization and omits the token.

**Steps:**
- [ ] Write failing tests for bounded identifier validation, credential hashing, expiry, closure, multiple requests, duplicate registration, and context serialization.
- [ ] Run the focused test and confirm expected failures.
- [ ] Implement the smallest contract and in-memory registry that passes.
- [ ] Run correlation tests and the existing LIO evidence contract tests.

### Task 2: Persist verified links and expose scoped Monitor endpoints

**Files:**
- Modify: `modules/llm_monitor/llm_monitor/inference_models.py`
- Modify: `modules/llm_monitor/llm_monitor/storage.py`
- Modify: `modules/llm_monitor/llm_monitor/gateway.py`
- Modify: `modules/llm_monitor/llm_monitor/inference_web.py`
- Modify: `modules/llm_monitor/llm_monitor/local_control.py`
- Modify: `modules/llm_monitor/llm_monitor/local_client.py`
- Test: `modules/llm_monitor/tests/gateway_test.py`, `inference_storage_test.py`, `inference_web_test.py`, and `local_control_test.py` (use the existing test modules where no named file exists).

**Interfaces:**
- Authenticated `POST /api/inference/v1/correlation/executions` registers run/task/execution metadata and returns a short-lived raw credential once.
- Authenticated `POST /api/inference/v1/correlation/executions/{execution_id}/complete` closes the execution and binds the Harbor trial ID.
- Authenticated `GET /api/inference/v1/correlation/executions/{execution_id}/requests` returns bounded IDs and evidence status, without request content.
- Gateway `x-benchmark-correlation-token` is verified before forwarding and removed by the existing upstream header allowlist.
- Add a backward-compatible SQLite migration for correlation execution/request fields; v1-v3 databases remain readable and old rows return unavailable correlation.

**Steps:**
- [ ] Write failing tests for authenticated endpoint scopes, invalid/expired/closed tokens, request association, upstream header stripping, and stream/non-stream parity.
- [ ] Run focused Monitor tests and confirm expected failures.
- [ ] Implement registry injection, request correlation persistence, and the bounded API.
- [ ] Add migration tests for legacy schema reads and correlation round-trip through history.
- [ ] Run the Monitor correlation, storage, gateway, auth, and recording suites.

### Task 3: Inject credentials into the actual Harbor OpenCode process

**Files:**
- Modify: `modules/agent_benchmark/agent_benchmark/harbor/opencode_v1.py`
- Modify: `modules/agent_benchmark/agent_benchmark/harbor/runner.py`
- Test: `modules/agent_benchmark/tests/harbor_runner_test.py`, `opencode_v2_test.py` or a focused new OpenCode v1 adapter test.

**Interfaces:**
- `execute_harbor_run(..., correlation_context=...)` scopes the credential to that one Harbor subprocess environment.
- `OpenCodeV1.exec_as_agent` explicitly maps that context to a merged inline OpenCode provider header in the container environment. It must not alter the user's global OpenCode configuration or persist the token in the Harbor task manifest.

**Steps:**
- [ ] Write a failing adapter test proving that the host variable is explicitly copied into the container's OpenCode inline config and route/model settings are preserved.
- [ ] Test absent/malformed context, unrelated OpenCode calls, and that no secret is logged or added to argv.
- [ ] Implement the per-execution adapter injection and use the custom adapter only for strict correlated OpenCode runs.
- [ ] Run adapter and Harbor runner tests. Mark real container propagation unverified; no Harbor task or model will run.

### Task 4: Replace temporal attribution on new strict suite runs

**Files:**
- Modify: `modules/agent_benchmark/agent_benchmark/suite.py`
- Modify: `modules/agent_benchmark/agent_benchmark/suite_monitor.py`
- Modify: `modules/agent_benchmark/agent_benchmark/harbor/runner.py`
- Test: `modules/agent_benchmark/tests/suite_test.py`, `suite_monitor_test.py`, `suite_archive_test.py`.

**Interfaces:**
- New monitored OpenCode manifests declare `benchmark-inference-correlation-v1`; manifests without it continue to load as historical/legacy.
- Each task attempt gets a fresh execution UUID before dispatch. After Harbor returns, that execution is reconciled with the native trial ID.
- Strict mode selects requests only through verified execution correlation. Time-window data remains diagnostic only.
- Missing or incomplete post-run capture marks evidence ineligible while preserving Harbor/verifier task status.

**Steps:**
- [ ] Write failing synthetic tests for multi-request tasks, overlapping executions, unrelated requests, repeated task names, retry attempts, missing capture, delayed history, and strict-vs-legacy reports.
- [ ] Run focused Agent Benchmark tests and confirm expected failures.
- [ ] Implement strict execution registration, correlation lookup, close/reconcile, and score/evidence separation.
- [ ] Verify request IDs and trial/execution references survive checkpoint and report serialization.
- [ ] Run suite, monitor, archive, and recovery regressions.

### Task 5: Document guarantees and validate the combined change

**Files:**
- Modify: `experiments/local_inference_optimization/docs/README.md`
- Modify: `experiments/local_inference_optimization/docs/DOWNSTREAM_CONTRACTS.md`
- Modify: this plan's `STATUS.md` and `checklist.md`.

**Steps:**
- [ ] Document protocol, local auth scope, token lifetime, task-container injection, spoofing boundary, evidence eligibility, historical compatibility, and live acceptance limits.
- [ ] Run focused Monitor, Agent Benchmark, LIO evidence, Ruff, formatting, and diff checks prescribed by module instructions.
- [ ] Review the complete diff for migration safety, race conditions, leaks, API scope, score semantics, and protected paths.
- [ ] Record exact commands/results and the remaining live-only adapter check.
- [ ] Create one self-contained commit on `agent/local-inference-p04-correlation-20261105`; do not merge or push.
