# P03/P04 Handoff

## Summary
- **Goal:** Offline experimental identity and evidence contract foundation.
- **Branch:** `agent/local-inference-p03p04-20261102`
- **Base Commit:** `d4c6b1fbbbc71291f6bea6b848e8b309e80d18d7`
- **Location:** `experiments/local_inference_optimization`

## Implemented Contracts & Adapters
1. **Experiment Identity (`lio-experiment-v1`):** Versioned, canonical fingerprinting (`experiment_fingerprint`), dimension permutation invariance, study and task-set digest binding, strict control parameter types.
2. **Variant Identity (`lio-variant-v1`):** Configuration fingerprinting (`variant_fingerprint`), strict separation of path vs content digest, weak vs verified model identity enforcement (`has_verified_model_digest`).
3. **Trial Identity (`lio-trial-v1`):** Execution identification separate from variant/configuration hashes, run/trial ID validation, git source revision binding.
4. **Evidence & Provenance (`lio-evidence-v1`):** Distinct lifecycle stages (`requested`, `planned`, `observed`, `effective`), strict verification gating for effective settings (correlated runtime observation, backend identity/version, artifact receipt), explicit unknown/unsupported handling, privacy allowlisting (rejecting credentials, headers, raw prompts/responses).
5. **Adapters (`adapters.py`):**
   - `legacy_profile_requests`: Read-only mapping of `opencode-inference-profile-v1` to `requested` stage only.
   - `monitor_request_observations`: Normalization of correlated `llm_monitor` request telemetry to `observed` stage only.
   - `benchmark_metric`: Extraction of numerical/quality metrics from `benchmark_core.models.MetricValue`.

## Documentation
- `README.md`: Module architecture, contract semantics, security and privacy boundaries.
- `DOWNSTREAM_CONTRACTS.md`: Detailed P05 Feature Registry and P06 Configuration Compiler / Apply specifications.
- `EXPERIMENT_PROTOCOL.md`: Pre-registration rules, comparison types, and statistical methodology.
- `COMPARISON_CONDITIONS.md`: Conditions for valid comparative analysis and comparability criteria.

## Verification
- **Test Suite:** 46 passed in `experiments/local_inference_optimization/tests/contracts_test.py`.
- **Linter & Formatter:** `ruff check` and `ruff format --check` clean.
- **Safety Invariants:** All tests run offline with synthetic fixtures; socket/subprocess operations blocked; no runtime services, models, or read-only modules modified.

## Remaining Dependencies
- P02 untouched baseline capture and manifest sealing remain external prerequisites for live comparisons.
- P07 live parity recovery and runtime sign-off remain external gates before activating optimization interventions.
- P05 and P06 owners will implement the feature registry and compiler based on `DOWNSTREAM_CONTRACTS.md`.
