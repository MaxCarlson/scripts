# Canonical LLM Monitor Bundle Checklist

- [x] Build a wheel from the pinned canonical Toolkit commit in a disposable source copy.
- [x] Add failing regressions for bundle wheel identity, canonical import origin, and synthetic Runmux API behavior.
- [x] Remove the launcher dependency on the scripts `modules/llm_monitor` source path.
- [x] Stage the wheel and pin source commit/hash in the H4 bundle manifest.
- [x] Run focused synthetic integration, bundle, lint, compile, and whitespace checks.
- [ ] Commit and push the isolated branch for H4 owner review.

## Scripts successor

- [x] Rebuild the canonical wheel from Toolkit `e10544f6` and verify its hash.
- [x] Remove the duplicate Monitor implementation, tests, and web assets while preserving historical docs and Phase-D evidence.
- [x] Verify H4 source snapshots, wheel import provenance, launcher discovery, and synthetic Monitor/Runmux contracts.
- [ ] Run final source-ownership enforcement, commit, and push the successor branch.
