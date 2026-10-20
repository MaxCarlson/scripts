# Checklist - Minimal LM Studio Activity Automation

- [x] Add tests for managed load admission and stop-before-forward order.
- [x] Add tests for exclusive load/inference contention, cooldown reset/expiry, and idle-action boundary.
- [x] Add tests for generic process lifecycle and compatibility CLI flags.
- [x] Implement generic lifecycle selection and backward-compatible CLI flags.
- [x] Enable only known model-load routes on shared exclusive/shared arbitration; keep unload and unknown routes rejected.
- [x] Preserve uncertain-operation inhibition and coordinator-owned restart rules.
- [x] Run offline tests, Ruff, Mypy, and Git whitespace checks; record environment-specific limitations.
- [x] Update docs, handoff, and checklist with Sol Medium safety-review boundary.
- [x] Commit bounded implementation and stop for Sol Medium review (`eff159c40f0929ce85f9ca9584e35753e60170c3`).
- [x] Review model-load admission, arbitration, cooldown and ownership; reject standalone loads without a managed service (`717316713cb8a86a8a4d3f5465f31b146414766c`).
- [x] Require coordinator-owned stop permission for automatic restart in config parsing and service preflight (`8d21630f1c5d953b1ec424fd7bb74434c5a10485`).
- [x] Rerun all offline tests and static checks; record operational NO-GO pending independent environmental gates.
- [x] Add opt-in disposable Windows HTTP harness against mocked upstream; assert process stop verification precedes request forwarding.
- [x] Add mock upstream failure case retaining restart inhibition and a second request during cooldown.
- [x] Run complete resource-coordinator suite with disposable Windows tests enabled and real-LM-Studio test disabled (245 passed, 1 live test skipped).
- [x] Run Ruff check/format and Mypy; record existing missing-`types-psutil` stub limitation.
- [ ] Commit, push, and merge the tested offline harness and procedure; stop before real inference for separate authorization.
