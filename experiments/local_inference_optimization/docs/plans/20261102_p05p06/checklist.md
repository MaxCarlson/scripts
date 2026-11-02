# P05/P06 Checklist

- [x] Preserve legacy profile (`opencode-inference-profile-v1`) and read-only modules (`agent_benchmark`, `llm_monitor`, `benchmark_core`).
- [x] Separate load-time from request-time feature scopes.
- [x] Enforce typed parameter bounds, dependencies, and conflict prevention.
- [x] Gate on backend capabilities, failing closed on unknown or unsupported capabilities.
- [x] Produce deterministic plans with canonical `plan_sha256` fingerprints.
- [x] Ensure compiler never emits `stage: "effective"` evidence.
- [x] Implement safe apply and rollback engine guarded by explicit authorization and drift detection.
- [x] Maintain test isolation using synthetic temporary fixtures, zero runtime service interaction.
- [x] Achieve 100% test pass rate across all 75 tests.
- [x] Commit changes cleanly on `agent/local-inference-p05p06-20261102`.
