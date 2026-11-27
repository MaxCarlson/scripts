# Checklist — Inference Crash-Recovery

## Safety journal storage

- [ ] Versioned SQLite schema initialized only by explicit local command.
- [ ] Missing, corrupt, unreadable, or unsupported state fails closed.
- [ ] Strict request phase transitions and unresolved listing are covered by tests.
- [ ] Explicit resolution stores actor, reason, and unverified-upstream status.
- [ ] Persisted fields exclude request content, prompts, completions, headers, and credentials.

## Runtime integration

- [ ] Startup restores unresolved rows as `gpu.inference` inhibition before readiness.
- [ ] `reserved` commits before blocking policy actions.
- [ ] `possibly_forwarded` commits before upstream send.
- [ ] Terminal outcome commits before reservation release.
- [ ] Journal failures veto side effects or latch abort/inhibition.
- [ ] Existing admission, completion-classification, service-lifecycle, and shielded cleanup protections remain intact.

## Verification and handoff

- [ ] Focused tests pass.
- [ ] Full resource-coordinator module tests pass; skips and environment limits are recorded.
- [ ] Ruff, format, Mypy, and `git diff --check` pass.
- [ ] Handoff and safety documents describe new behavior and remaining NO-GO limits.
- [ ] Stage only intended module files and commit after review; do not push or merge.
