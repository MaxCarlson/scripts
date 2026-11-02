# Checklist

- [x] Preserve legacy profile (`opencode-inference-profile-v1`) and read-only module ownership (`agent_benchmark`, `llm_monitor`, `benchmark_core`).
- [x] Keep request evidence separate from effective runtime evidence (lifecycle stages: requested, planned, observed, effective).
- [x] Validate canonical serialization, malformed inputs, compatibility, and privacy (allowlisted fields, credentials rejected).
- [x] Complete comprehensive test coverage across all 15 validation areas (46 tests passing).
- [x] Document P05/P06 downstream contracts and interface specifications (`DOWNSTREAM_CONTRACTS.md`).
- [x] Feature branch reviewed and committed.
