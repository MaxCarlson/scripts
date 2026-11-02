# Local Inference Optimization Contracts

Status: offline implementation for review, not an agreed cross-team contract or permission to activate a feature. P02 baseline and P07 no-op/runtime gates are not established here.

## 1. P03/P04: Experimental Identity and Evidence Contracts
`contracts.py` exposes `lio-experiment-v1`, `lio-variant-v1`, `lio-trial-v1`, and `lio-evidence-v1` validators. Experiment identity includes the task digest, baseline reference, fixed settings, permitted dimensions, repetition/randomization and decisions. Variant identity covers model/quantization evidence, context, output, reasoning, settings, prompt policy and configuration digest. Trial identity separately carries run/trial IDs, task, repetition, evidence reference, source revision and workspace digest. All versioned objects reject unsupported fields and schema versions.

Fingerprints use SHA-256 over ASCII JSON with lexicographically sorted object keys, compact separators, finite numbers and explicit nulls. Experiment dimensions are sorted as a set; other arrays preserve order. File paths are accepted as observed metadata but excluded from variant fingerprints; all other variant fields, including the weak/verified identity state, remain included. Timestamps and generated run/trial IDs are not variant fields and never enter variant hashes. Files are never read to obtain model digests. A verified digest is an external attestation; syntax validation does not prove it was actually calculated. Weak alias/size evidence cannot establish content equivalence. Use existing `benchmark_core.conditions.contract_error`/`contract_key` and strict task/verifier comparison rules for actual benchmark comparability; a fingerprint match is not sufficient.

Evidence uses an allowlist of scalar settings, bounded observation lists, timestamps, producer, optional model/backend/workspace, capability records, artifact hashes and numerical metrics. Requested, planned, observed and effective stages are distinct. Effective fields require a matching verified backend-runtime observation, backend identity/version and an artifact reference. This is validation of supplied attestations, not independent runtime verification or a trust decision. No requested or captured request is promoted to effective. Unknown/unavailable/unsupported records have null values. Callers must establish source authenticity, trial/session correlation, freshness, artifact integrity and exclusivity externally before relying on an observation; this module does not inspect or verify runtime state.

The `legacy_profile_requests` adapter accepts the existing `opencode-inference-profile-v1` `to_dict()` shape and maps only requested values. It neither changes the legacy profile nor recalculates its file hash. `monitor_request_observations` accepts the *already-correlated* llm-monitor v1 request-evidence result, supports a narrow parameter subset, and emits observed request evidence, never effective backend settings. Correlation and capture are performed upstream; unknown or unsupported fields cannot be silently turned into effective observations. `benchmark_metric` maps benchmark_core metric fields while excluding free-text reason.

Model file paths and opaque IDs can still be sensitive: callers must provide sanitized, non-secret values and access-control stored evidence. No credentials, headers, full environments, raw prompts or responses are accepted as schema fields. Strict schema validation cannot detect every secret disguised as an allowed value.

## 2. P05: Versioned Feature Registry (`registry.py`)
`registry.py` implements the `lio-feature-def-v1` schema and the `FeatureRegistry` catalog:
- **Feature Definitions:** Enforces stable feature IDs (`^[a-z0-9][a-z0-9._-]{0,63}$`), semver versions, load-time versus request-time execution scopes, parameter typing/bounds/enums/defaults, prerequisite dependencies, mutual exclusion conflicts, and backend capability requirements.
- **Scope Invariants:** Request-time features are strictly prohibited from requiring model reloads (`reload_required=False`).
- **Initial Catalog:** Built-in definitions for `context`, `output_limit`, `temperature`, `top_p`, `top_k`, `batch_size`, `flash_attention`, `gpu_kv_cache`, `reasoning`, `speculation_mode`, and `max_draft_tokens`.
- **Validation:** `validate_settings()` enforces bounds and enumerated choices, fails closed on unknown parameters, and evaluates the dependency/conflict DAG.

## 3. P06: Configuration Compiler and Backend Mapping (`compiler.py`)
`compiler.py` implements the `lio-plan-v1` schema and `compile_plan()` pipeline:
- **Separation of Stages:** Generates non-mutating execution plans with `stage: "planned"`. The compiler never produces or emits `stage: "effective"` evidence records.
- **Deterministic Plans:** Outputs sorted lists of `load_operations` and `request_operations` bound to the variant's fingerprint, target model, and backend identity, producing a deterministic canonical `plan_sha256`.
- **Backend Mappings:**
  - `lmstudio_rest_v1`: Maps load operations to LM Studio REST load payload (`context_length`, `eval_batch_size`, `flash_attention`, `offload_kv_cache_to_gpu`, `echo_load_config: True`) and request operations to native chat parameters (`max_output_tokens`, `temperature`, `top_p`, `top_k`, `reasoning_effort`).
  - `lmstudio_openai_v1`: Maps request parameters to OpenAI-compatible chat completions fields (`max_tokens`, `temperature`, `top_p`, `reasoning_effort`).
  - `opencode_v1`: Maps configuration into OpenCode provider and model layers.
- **Capability Gating:** Fails closed if any required capability is missing or marked `unknown` (yields `status: "rejected"` with blocker) or `unsupported` (yields `status: "unsupported"` with blocker).
- **No-op Baseline Check:** `is_baseline_equivalent()` proves whether a plan introduces deltas against the baseline variant. Missing baseline evidence is explicitly reported as unknown rather than assumed equivalent.

## 4. P06: Safe Offline Apply and Rollback Engine (`apply.py`)
`apply.py` implements the `lio-receipt-v1` transaction journal for offline testing:
- **Safety Gating:** Disabled by default. All mutations require explicit operator authorization (`authorized=True`). Real production configurations are never targeted.
- **Drift Protection:** Validates target file SHA-256 against `expected_before_sha256` before modifying. If drift is detected, execution immediately aborts.
- **Atomic Operations:** Uses temporary files in the target directory and atomic rename (`os.replace`) to prevent partial application.
- **Rollback Engine:** Restores snapshot backups from transaction receipts while verifying that external modifications have not occurred since the transaction.

## 5. Downstream Interface Requirements & Next Gates
See [`DOWNSTREAM_CONTRACTS.md`](DOWNSTREAM_CONTRACTS.md) for interface specifications.

- **P07 Gate:** Live experimentation remains blocked until P02 baseline sealing and P07 no-op parity verification pass.
- **P08+ Features:** Subsequent feature adapters consume `FeatureRegistry` and `compile_plan()` without altering legacy `opencode-inference-profile-v1` profiles.
