# Post-P6 source retirement checklist

- [x] Audit the 25-directory ownership inventory and preserve primary-checkout untracked/ignored data.
- [x] Prepare 13 toolkit-source and four shared-source retirements on separate PRs.
- [x] Qualify exact integration refs locally, then hosted: runs 45321529713 (toolkit-only) and 45321531381 (combined) passed wheel, import, HTTP, consumer, Gitlink, clean-bootstrap, launcher and pip-health checks.
- [x] Restore PR #35's qualified module tree with corrective revert `e54550da`; source tree matches qualification checkpoint `f4f8e158`.
- [x] Complete ownership protection PR #36; parser, exact exception, Gitlink and mode changes exercised through the production CLI.
- [x] Prepare separate `llm_local` retirement PR #38; canonical-present and absent-package Agent Memory classifier checks use mocked completions. Fix the tracked-source regression and qualify the hosted branch at `ec123539` (run `45347357571`, passed).
- [x] Prepare separate viewer retirement PR #39; canonical viewer API tests passed 7, direct TermDash attachment smoke passed, and scripts ownership/Help tests passed 50. The Gitlink workflow correction is pushed at `1abb7675`; hosted run `45348359248` is in clean bootstrap.
- [x] Prepare canonical Monitor metadata PR #5 at `edd54bd`; Runmux adapter/API compatibility tests passed 19 against an installed canonical wheel plus canonical web UI package.
- [x] Add canonical toolkit Gitlinks for Agent Abilities and Agent Skills at their original upstream pins; fresh worktree initialization and both module suites passed. Scripts source retirement is pushed on `retire/agent-abilities-skills-20261125` (`84231074`); hosted run `45347910359` passed.
- [x] Implement Agent Memory platform-data separation, backward-compatible legacy discovery, and copy-based SQLite/WAL migration on toolkit branch `feat/agent-memory-data-migration-20261125` (`6aaa933`); full suite passed 178, one symlink test skipped. Scripts implementation retirement is pushed at `729e51d8`, preserving the tracked empty index and local sidecars; hosted run `45347914913` passed. Ledger-only commit `5e85cf92` followed.
- [x] Qualify pinned direct GitHub source builds/import origins for Agent Memory, `llm_local`, and viewer in disposable targets without publishing packages.
- [ ] Complete PR #39 hosted qualification (run `45348359248`) before integration; clean bootstrap is still running. PR #38 (`45347357571`), PR #41 (`45347910359`), and PR #42 (`45347914913`) hosted qualifications passed.
- [ ] Diagnose toolkit PR #5 only if actionable hosted evidence appears. Four runs (`45333414610`, `45334638802`, `45345602914`, `45345628821`) show all eight jobs failing with no step payloads; log downloads return 404. Local Runmux compatibility remains 19 passed; do not blindly retry.
- [ ] Coordinate H4 bundle source/metadata and Monitor API contracts with its owner. Preserve active `.worktrees/resource-coordinator-phase-d` and state; only remove `llm_monitor`, `resource_coordinator`, or `resource_metrics` sources after the canonical package contract and immutable bundle qualification pass.
- [ ] Keep PR #34 gated on ordinary package-index availability and clean-index install qualification.
- [ ] Do not merge, publish, synchronize the primary checkout, or migrate runtime data without the existing separate authorization.
