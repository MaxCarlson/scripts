# Checklist - Minimal LM Studio Activity Automation

- [x] Add tests for managed load admission and stop-before-forward order.
- [x] Add tests for exclusive load/inference contention, cooldown reset/expiry, and idle-action boundary.
- [x] Add tests for generic process lifecycle and compatibility CLI flags.
- [x] Implement generic lifecycle selection and backward-compatible CLI flags.
- [x] Enable only known model-load routes on shared exclusive/shared arbitration; keep unload and unknown routes rejected.
- [x] Preserve uncertain-operation inhibition and coordinator-owned restart rules.
- [x] Run offline tests, Ruff, Mypy, and Git whitespace checks; record environment-specific limitations.
- [x] Update docs, handoff, and checklist with Sol Medium safety-review boundary.
- [ ] Commit bounded implementation and stop for Sol Medium review.
