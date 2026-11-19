# Checklist — `20261119-privexec-session-broker`

## Phase 0 — Repository baseline and contract
- [x] Inspect local Git branches, worktrees, dirty status, and recent commits
- [x] Create isolated feature worktree (`C:\Users\mcarls\src\scripts-privexec`, branch `feat/privexec-session-broker-20261119`)
- [x] Read repository standards (`AGENTS.md`, `MODULE_STANDARDS.md`, `PYTHON_REPO_STANDARDS.md`, `SCRIPTS_REPO_STANDARDS.md`, `LEGACY_PLANNING_MIGRATION.md`)
- [x] Inspect H4 integration points read-only (`fix/rc-h4-task-discovery-20261115` `ea6ad23f`)
- [x] Persist master plan (`00_implementation-plan.md`) and canonical module docs
- [x] Finalize protocol v1 schema, capability descriptor format, toolchain selection, and Windows ACL model (`01_interface-contract-and-architecture.md`)

## Phase 1 — Secure broker foundation
- [x] Packaged `privexec` Python CLI (`status`, `run`, `result`, `broker start`, `broker stop`)
- [x] C#/.NET 10 broker process (`PrivExecBroker`) + build script
- [x] Local-only named-pipe transport with server-side Windows identity enforcement
- [x] Operator-started session, in-memory authorized scope, expiration, and revocation
- [x] Protected capability descriptor loading
- [x] Synthetic read-only capability and non-mutating installer planning
- [x] Phase 1 negative & positive authorization tests pass

## Phase 2 — Execution and persistence
- [x] Fixed executable/script invocation with SHA-256 verification and reparse-point rejection
- [x] Typed parameter validation (no shell interpolation)
- [x] Bounded stdout/stderr capture, JSON result parsing, and secret redaction
- [x] SQLite operation ledger (`winsqlite3.dll`) with idempotency & canonical payload verification
- [x] Target-level mutation concurrency lock & conflict rejection
- [x] Child timeout/supervision & crash `outcome_unknown` recovery (no auto-replay)
- [x] Phase 2 adversarial security & reliability tests pass

## Phase 3 — H4 integration
- [ ] `h4.preflight`, `h4.qualify`, and `h4.recover` capability descriptors and PowerShell adapters
- [ ] Operator-supplied `PSCredential` handling in trusted broker/worker memory (zero disk/CLI/log exposure)
- [ ] Preservation of H4 `-Apply`, `-AuthorizeGuestMutation`, pinned hashes, and checkpoint guards
- [ ] H4 adapter unit/mock tests pass
- [ ] Repeatable Windows installation/uninstall scripts (dry-run by default) & validation docs
- [ ] Shared repo integration (`modules/scripts_help/scripts_help/registry/registry.py`)

## Final Acceptance Criteria
- [ ] Agent-facing `privexec` CLI works
- [ ] Trusted broker can be started by the operator
- [ ] Client authentication uses actual Windows identity
- [ ] Per-capability, target, mode, and expiration authorization works
- [ ] Unapproved operations are denied
- [ ] Arbitrary elevated shell execution is impossible through the public interface
- [ ] Trusted code and policy are protected from unprivileged agent writes
- [ ] Mutations default to dry-run
- [ ] Explicit apply and a valid mutation grant are both required
- [ ] Approved PowerShell/Python operations execute successfully
- [ ] Agent retrieves structured results and evidence
- [ ] Duplicate request IDs do not duplicate execution
- [ ] Broker crashes cannot trigger automatic mutation replay
- [ ] Conflicting target mutations are rejected
- [ ] Guest credentials do not appear in client requests or logs
- [ ] Windows security controls tested with real identities (pending authorized Windows elevation/account validation)
- [ ] Existing H4 validation logic is preserved
- [ ] Multi-step H4 workflow demonstrated safely (live VM mutation pending explicit operator authorization)
