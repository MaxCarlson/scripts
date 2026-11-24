# Canonical LLM Monitor Bundle Checklist

- [x] Build a wheel from the pinned canonical Toolkit commit in a disposable source copy.
- [x] Add failing regressions for bundle wheel identity, canonical import origin, and synthetic Runmux API behavior.
- [x] Remove the launcher dependency on the scripts `modules/llm_monitor` source path.
- [x] Stage the wheel and pin source commit/hash in the H4 bundle manifest.
- [x] Run focused synthetic integration, bundle, lint, compile, and whitespace checks.
- [ ] Commit and push the isolated branch for H4 owner review.
