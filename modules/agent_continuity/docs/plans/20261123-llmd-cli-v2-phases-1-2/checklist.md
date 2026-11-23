# Checklist

- [x] Phase 1 listing and read models.
- [x] Phase 2 unified registration.
- [x] Phase 3 flat picker, runtime observation, and duplicate-resume protection.
- [x] Phase 4 positional start authorization and historical session selection.
- [x] Preserve legacy start, switch, and continue defaults.
- [x] Run full module tests, Ruff, and diff checks.
- [x] Review Phase 4 changes; commit locally.


## Operational diagnostics

- [x] Trace registry/session locks and launch persistence boundaries.
- [x] Add read-only scoped doctor output and lock/runtime limitations.
- [x] Add dry-run, exact-ID, lock-guarded, idempotent pending recovery.
- [x] Clarify metadata failures after provider submission.
- [x] Run full suite, Ruff, and whitespace checks.
- [x] Review and commit operational diagnostics locally.

## Independent review corrections

- [x] Prevent picker preview and contended named continuation from mutating lifecycle/history.
- [x] Establish runtime ownership from environment ID, runtime kind, hostname, and WSL distribution; otherwise report UNKNOWN and refuse recovery.
- [x] Render human-readable doctor output without changing the JSON schema.
- [x] Assert interactive initialization leaves durable dispatcher state unchanged.
- [x] Run focused and full tests, Ruff, and diff checks; commit locally without pushing.
