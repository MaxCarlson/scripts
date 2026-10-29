# Benchmark Report: run-EXP_20261029_161327-qwen38-27b-q4km

## Overview

- **Suite ID:** `agent-benchmark` (version `1.18.0`)
- **Created At:** 2026-10-29T16:13:29Z
- **Scoring Basis:** `worker_first_attempt_full_success`
- **Planned Repetitions:** 1
- **Evaluated Tasks:** 1 tasks

## Reproducibility & Environment

- **Suite Fingerprint:** `73f6a4d39d07ec2058227d83f099d9e408d284f892ed7d1267370d4c9d91ebba`
- **Random Seed:** `None`
- **Environment:**
  - `machine`: AMD64
  - `platform`: Windows-11-10.0.26300-SP0
  - `python`: 3.12.10
- **Additional Metadata:**
  - `agent_runtime`: {'kind': 'opencode', 'version': '1.19.3', 'bridge_version': '3.0.0', 'agent': 'benchmark-files', 'prompt_sha256': 'd2d760a2839aa4ae64b3b5a17b3520ff2f39006e3615b332109f9d8740934e40', 'allowed_tools': ['StructuredOutput', 'edit', 'glob', 'grep', 'list', 'read'], 'permissions_sha256': '0af3347ab44392a4340d675fff7588d8b50af377e2a0fbe577863dfb1c348abf', 'model_identity': {'requested_id': 'qwen38-27b-q4km', 'provider': 'lmstudio', 'runtime_model_id': 'qwen38-27b-q4km', 'lms_model_key': 'qwen38-27b-q4km', 'display_name': 'Qwen3.8 27B', 'quantization': 'Q4_K_M', 'selected_variant': None, 'available_variants': [], 'max_context_length': 262144, 'size_bytes': 16810714336, 'resolution': 'exact_model_key'}, 'model_settings': None, 'requested_inference_profile': {'schema': 'opencode-inference-profile-v1', 'context_length': 98304, 'output_limit': 8192, 'reasoning': {'mode': 'effort', 'effort': 'none', 'provenance': 'experiment_profile'}, 'sha256': '8442a059ee9809772b8e6cc149750e877549ef8f933a97bb5bcddb151c826dc6'}}
  - `benchmark_version`: 1.18.0
  - `budget_profile`: canonical-120s
  - `comparison_contract`: {'schema': 'comparison-conditions-v1', 'tasks': {'qwen-session-state': {'task_sha256': '61dff43acae297754d08a1bd1ed11e08eb68f5210f84f1bc2c950d0154b15aae', 'verifier_sha256': '3f0af46198d8f5ed2113f2efba80b80cfde93dcb96f7e5f687363605e59cb672'}}, 'execution_profiles': {'qwen-session-state': 'file-tools-v1'}, 'scope_policy': 'trial-local-scratch-v1', 'isolation_policy': 'isolated-git-project-v1', 'context_length': 98304, 'budget': {'profile': 'canonical-120s', 'task_seconds': 120.0, 'grace_seconds': 15.0, 'verifier_seconds': 10.0}, 'environment': {'python': '3.12.10', 'platform': 'Windows-11-10.0.26300-SP0', 'machine': 'AMD64', 'harness_version': '1.18.0', 'host_fingerprint': '6d970eb8e25340c75cd29feaa29d84c52c26ea452980a291e7a5949429477acf', 'model_identity': {'requested_id': 'qwen38-27b-q4km', 'provider': 'lmstudio', 'runtime_model_id': 'qwen38-27b-q4km', 'lms_model_key': 'qwen38-27b-q4km', 'display_name': 'Qwen3.8 27B', 'quantization': 'Q4_K_M', 'selected_variant': None, 'available_variants': [], 'max_context_length': 262144, 'size_bytes': 16810714336, 'resolution': 'exact_model_key'}, 'runtime': {'kind': 'opencode', 'version': '1.19.3', 'bridge_version': '3.0.0', 'agent': 'benchmark-files', 'prompt_sha256': 'd2d760a2839aa4ae64b3b5a17b3520ff2f39006e3615b332109f9d8740934e40', 'allowed_tools': ['StructuredOutput', 'edit', 'glob', 'grep', 'list', 'read'], 'permissions_sha256': '0af3347ab44392a4340d675fff7588d8b50af377e2a0fbe577863dfb1c348abf', 'model_settings': None, 'requested_inference_profile': {'schema': 'opencode-inference-profile-v1', 'context_length': 98304, 'output_limit': 8192, 'reasoning': {'mode': 'effort', 'effort': 'none', 'provenance': 'experiment_profile'}, 'sha256': '8442a059ee9809772b8e6cc149750e877549ef8f933a97bb5bcddb151c826dc6'}}}}
  - `comparison_eligible`: True
  - `effective_context_length`: 98304
  - `evidence_limits`: {}
  - `isolation_policy`: isolated-git-project-v1
  - `model_identity`: {'requested_id': 'qwen38-27b-q4km', 'provider': 'lmstudio', 'runtime_model_id': 'qwen38-27b-q4km', 'lms_model_key': 'qwen38-27b-q4km', 'display_name': 'Qwen3.8 27B', 'quantization': 'Q4_K_M', 'selected_variant': None, 'available_variants': [], 'max_context_length': 262144, 'size_bytes': 16810714336, 'resolution': 'exact_model_key'}
  - `requested_context_length`: 98304
  - `requested_inference_profile`: {'schema': 'opencode-inference-profile-v1', 'context_length': 98304, 'output_limit': 8192, 'reasoning': {'mode': 'effort', 'effort': 'none', 'provenance': 'experiment_profile'}, 'sha256': '8442a059ee9809772b8e6cc149750e877549ef8f933a97bb5bcddb151c826dc6'}
  - `scope_policy`: trial-local-scratch-v1
  - `task_tool_profiles`: {'qwen-session-state': 'file-tools-v1'}

## Variant Configurations

| Variant ID | Configuration Details |
|---|---|
| `qwen38-27b-q4km` | `effective_context_length=98304`, `model=qwen38-27b-q4km`, `provider=lmstudio` |

## Primary Results

| Variant | Total Trials | Eligible | Passed | Failed | Timed Out | Infra Error | Unscored | Micro Success | Macro Success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen38-27b-q4km` | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 100.0% | 100.0% |

## Duration & Latency

| Variant | All-Scored (Mean ± Stdev) | All-Scored (Median [Min, Max]) | Successful-Only (Mean ± Stdev) | Successful (Median) |
|---|---|---|---|---|
| `qwen38-27b-q4km` | 8860.0 ms (n=1) | 8860.0 [8860.0, 8860.0] ms | 8860.0 ms (n=1) | 8860.0 ms |

## Resource & Token Metrics

| Variant | Metric | Mean | Median | Available / Total |
|---|---|---:|---:|---:|
| `qwen38-27b-q4km` | `agent.artifact_compliance` | 1.0 boolean | 1.0 boolean | 1/1 |
| `qwen38-27b-q4km` | `agent.budget_pass` | 1.0 boolean | 1.0 boolean | 1/1 |
| `qwen38-27b-q4km` | `agent.clean_termination` | 1.0 boolean | 1.0 boolean | 1/1 |
| `qwen38-27b-q4km` | `agent.completion_ms` | 7250.0 ms | 7250.0 ms | 1/1 |
| `qwen38-27b-q4km` | `agent.coordinator_repairs` | 0.0 count | 0.0 count | 1/1 |
| `qwen38-27b-q4km` | `agent.execution_compliance` | 1.0 boolean | 1.0 boolean | 1/1 |
| `qwen38-27b-q4km` | `agent.first_edit_ms` | 5769.0 ms | 5769.0 ms | 1/1 |
| `qwen38-27b-q4km` | `agent.functional_pass` | 1.0 boolean | 1.0 boolean | 1/1 |
| `qwen38-27b-q4km` | `agent.last_edit_ms` | 5769.0 ms | 5769.0 ms | 1/1 |
| `qwen38-27b-q4km` | `agent.local_retries` | 0.0 count | 0.0 count | 1/1 |
| `qwen38-27b-q4km` | `agent.scope_compliance` | 1.0 boolean | 1.0 boolean | 1/1 |
| `qwen38-27b-q4km` | `agent.scope_violations` | 0.0 count | 0.0 count | 1/1 |
| `qwen38-27b-q4km` | `agent.worker_after_retry_pass` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `agent.worker_first_pass` | 1.0 boolean | 1.0 boolean | 1/1 |
| `qwen38-27b-q4km` | `agent.workflow_final_pass` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `duration.verification_ms` | 125.0 ms | 125.0 ms | 1/1 |
| `qwen38-27b-q4km` | `duration.worker_ms` | 8719.0 ms | 8719.0 ms | 1/1 |
| `qwen38-27b-q4km` | `tokens.coordinator.input` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `tokens.coordinator.output` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `tokens.worker.content` | 549.0 tokens | 549.0 tokens | 1/1 |
| `qwen38-27b-q4km` | `tokens.worker.initial_prompt` | 3016.0 tokens | 3016.0 tokens | 1/1 |
| `qwen38-27b-q4km` | `tokens.worker.input` | 9843.0 tokens | 9843.0 tokens | 1/1 |
| `qwen38-27b-q4km` | `tokens.worker.output` | 549.0 tokens | 549.0 tokens | 1/1 |
| `qwen38-27b-q4km` | `tokens.worker.peak_context` | 3595.0 tokens | 3595.0 tokens | 1/1 |
| `qwen38-27b-q4km` | `tokens.worker.reasoning` | 0.0 tokens | 0.0 tokens | 1/1 |
| `qwen38-27b-q4km` | `tools.calls` | 2.0 count | 2.0 count | 1/1 |
| `qwen38-27b-q4km` | `tools.failures` | 0.0 count | 0.0 count | 1/1 |
