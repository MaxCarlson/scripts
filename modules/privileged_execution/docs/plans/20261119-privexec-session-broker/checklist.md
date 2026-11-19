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
- [x] `h4.preflight`, `h4.qualify`, and `h4.recover` capability descriptors and PowerShell adapters
- [x] Operator-supplied `PSCredential` handling in trusted broker/worker memory (zero disk/CLI/log exposure)
- [x] Preservation of H4 `-Apply`, `-AuthorizeGuestMutation`, pinned hashes, and checkpoint guards
- [x] H4 adapter unit/mock tests pass
- [x] Repeatable Windows installation/uninstall scripts (dry-run by default) & validation docs
- [x] Shared repo integration (`modules/scripts_help/scripts_help/registry/registry.py`)

## Final Acceptance Criteria
- [x] Agent-facing `privexec` CLI works
- [x] Trusted broker can be started by the operator
- [x] Client authentication uses actual Windows identity (`RunAsClient` + `WindowsIdentity.GetCurrent`)
- [x] Per-capability, target, mode, and expiration authorization works
- [x] Unapproved operations are denied
- [x] Arbitrary elevated shell execution is impossible through the public interface
- [x] Trusted code and policy are protected by SHA-256 + reparse-point guards (ACL enforcement pending elevated install)
- [x] Mutations default to dry-run
- [x] Explicit apply and a valid mutation grant are both required
- [x] Approved PowerShell/Python operations execute successfully
- [x] Agent retrieves structured results and evidence
- [x] Duplicate request IDs do not duplicate execution
- [x] Broker crashes cannot trigger automatic mutation replay
- [x] Conflicting target mutations are rejected
- [x] Guest credentials do not appear in client requests or logs
- [ ] Windows security controls tested with real separate operator & non-admin agent accounts (pending authorized Windows elevation/account validation; see `docs/WINDOWS_VALIDATION.md`)
- [x] Existing H4 validation logic is preserved
- [ ] Multi-step H4 workflow executed against live `RC-H4-Windows-Acceptance` VM (adapters & mock tests complete; live VM execution pending explicit operator authorization)
