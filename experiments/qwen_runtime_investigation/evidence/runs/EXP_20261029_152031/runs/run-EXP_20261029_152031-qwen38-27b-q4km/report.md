# Benchmark Report: run-EXP_20261029_152031-qwen38-27b-q4km

## Overview

- **Suite ID:** `agent-benchmark` (version `1.18.0`)
- **Created At:** 2026-10-29T15:20:34Z
- **Scoring Basis:** `worker_first_attempt_full_success`
- **Planned Repetitions:** 1
- **Evaluated Tasks:** 1 tasks

## Reproducibility & Environment

- **Suite Fingerprint:** `802fd5de24b975ac3cbe0a78b84b4d743e6dc1502d778cc59b52d924c3b4c4ad`
- **Random Seed:** `None`
- **Environment:**
  - `machine`: AMD64
  - `platform`: Windows-11-10.0.26300-SP0
  - `python`: 3.12.10
- **Additional Metadata:**
  - `agent_runtime`: {'kind': 'opencode', 'version': '1.19.3', 'bridge_version': '3.0.0', 'agent': 'benchmark-files', 'prompt_sha256': 'd2d760a2839aa4ae64b3b5a17b3520ff2f39006e3615b332109f9d8740934e40', 'allowed_tools': ['StructuredOutput', 'edit', 'glob', 'grep', 'list', 'read'], 'permissions_sha256': '0af3347ab44392a4340d675fff7588d8b50af377e2a0fbe577863dfb1c348abf', 'model_identity': {'requested_id': 'qwen38-27b-q4km', 'provider': 'lmstudio', 'runtime_model_id': 'qwen38-27b-q4km', 'lms_model_key': 'qwen38-27b-q4km', 'display_name': 'Qwen3.8 27B', 'quantization': 'Q4_K_M', 'selected_variant': None, 'available_variants': [], 'max_context_length': 262144, 'size_bytes': 16810714336, 'resolution': 'exact_model_key'}, 'model_settings': None, 'requested_inference_profile': {'schema': 'opencode-inference-profile-v1', 'context_length': 98304, 'output_limit': 8192, 'reasoning': {'mode': 'unconfigured', 'effort': None, 'provenance': 'source_config'}, 'sha256': '53b62d405bae38aacc43a64171e0c33ae7e6512f5f805d6f98e8cbdd55162ac0'}}
  - `benchmark_version`: 1.18.0
  - `budget_profile`: canonical-120s
  - `comparison_contract`: {'schema': 'comparison-conditions-v1', 'tasks': {'qwen-file-creation': {'task_sha256': 'cefd376e81cbc89309535ee5edecada788285ef05fecd6be74072cab0b2b7175', 'verifier_sha256': 'fb7af3cda99ec0fd11ea5b7b51504dec1e0138f1f6162b711d30856014e17861'}}, 'execution_profiles': {'qwen-file-creation': 'file-tools-v1'}, 'scope_policy': 'trial-local-scratch-v1', 'isolation_policy': 'isolated-git-project-v1', 'context_length': 98304, 'budget': {'profile': 'canonical-120s', 'task_seconds': 120.0, 'grace_seconds': 15.0, 'verifier_seconds': 10.0}, 'environment': {'python': '3.12.10', 'platform': 'Windows-11-10.0.26300-SP0', 'machine': 'AMD64', 'harness_version': '1.18.0', 'host_fingerprint': '6d970eb8e25340c75cd29feaa29d84c52c26ea452980a291e7a5949429477acf', 'model_identity': {'requested_id': 'qwen38-27b-q4km', 'provider': 'lmstudio', 'runtime_model_id': 'qwen38-27b-q4km', 'lms_model_key': 'qwen38-27b-q4km', 'display_name': 'Qwen3.8 27B', 'quantization': 'Q4_K_M', 'selected_variant': None, 'available_variants': [], 'max_context_length': 262144, 'size_bytes': 16810714336, 'resolution': 'exact_model_key'}, 'runtime': {'kind': 'opencode', 'version': '1.19.3', 'bridge_version': '3.0.0', 'agent': 'benchmark-files', 'prompt_sha256': 'd2d760a2839aa4ae64b3b5a17b3520ff2f39006e3615b332109f9d8740934e40', 'allowed_tools': ['StructuredOutput', 'edit', 'glob', 'grep', 'list', 'read'], 'permissions_sha256': '0af3347ab44392a4340d675fff7588d8b50af377e2a0fbe577863dfb1c348abf', 'model_settings': None, 'requested_inference_profile': {'schema': 'opencode-inference-profile-v1', 'context_length': 98304, 'output_limit': 8192, 'reasoning': {'mode': 'unconfigured', 'effort': None, 'provenance': 'source_config'}, 'sha256': '53b62d405bae38aacc43a64171e0c33ae7e6512f5f805d6f98e8cbdd55162ac0'}}}}
  - `comparison_eligible`: True
  - `effective_context_length`: 98304
  - `evidence_limits`: {}
  - `isolation_policy`: isolated-git-project-v1
  - `model_identity`: {'requested_id': 'qwen38-27b-q4km', 'provider': 'lmstudio', 'runtime_model_id': 'qwen38-27b-q4km', 'lms_model_key': 'qwen38-27b-q4km', 'display_name': 'Qwen3.8 27B', 'quantization': 'Q4_K_M', 'selected_variant': None, 'available_variants': [], 'max_context_length': 262144, 'size_bytes': 16810714336, 'resolution': 'exact_model_key'}
  - `requested_context_length`: 98304
  - `requested_inference_profile`: {'schema': 'opencode-inference-profile-v1', 'context_length': 98304, 'output_limit': 8192, 'reasoning': {'mode': 'unconfigured', 'effort': None, 'provenance': 'source_config'}, 'sha256': '53b62d405bae38aacc43a64171e0c33ae7e6512f5f805d6f98e8cbdd55162ac0'}
  - `scope_policy`: trial-local-scratch-v1
  - `task_tool_profiles`: {'qwen-file-creation': 'file-tools-v1'}

## Variant Configurations

| Variant ID | Configuration Details |
|---|---|
| `qwen38-27b-q4km` | `effective_context_length=98304`, `model=qwen38-27b-q4km`, `provider=lmstudio` |

## Primary Results

| Variant | Total Trials | Eligible | Passed | Failed | Timed Out | Infra Error | Unscored | Micro Success | Macro Success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen38-27b-q4km` | 1 | 0 | 0 | 0 | 0 | 1 | 0 | N/A | N/A |

## Duration & Latency

| Variant | All-Scored (Mean ± Stdev) | All-Scored (Median [Min, Max]) | Successful-Only (Mean ± Stdev) | Successful (Median) |
|---|---|---|---|---|
| `qwen38-27b-q4km` | N/A | N/A | N/A | N/A |

## Resource & Token Metrics

| Variant | Metric | Mean | Median | Available / Total |
|---|---|---:|---:|---:|
| `qwen38-27b-q4km` | `agent.coordinator_repairs` | 0.0 count | 0.0 count | 1/1 |
| `qwen38-27b-q4km` | `agent.local_retries` | 0.0 count | 0.0 count | 1/1 |
| `qwen38-27b-q4km` | `agent.worker_after_retry_pass` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `agent.worker_first_pass` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `agent.workflow_final_pass` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `duration.verification_ms` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `duration.worker_ms` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `tokens.coordinator.input` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `tokens.coordinator.output` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `tokens.worker.input` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `tokens.worker.output` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `tools.calls` | N/A | N/A | 0/1 |
| `qwen38-27b-q4km` | `tools.failures` | N/A | N/A | 0/1 |

## Notable Observations & Warnings

- Variant `qwen38-27b-q4km` has insufficiently sampled tasks with 0 eligible scored trials: `qwen-file-creation` (excluded from macro-average calculation).
- Variant `qwen38-27b-q4km` has 0 eligible scored trials (all trials failed infrastructure checks or were unscored).
