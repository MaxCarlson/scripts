# Post-P6 source retirement checklist

- [x] Audit the 25-directory ownership inventory and preserve primary-checkout untracked/ignored data.
- [x] Prepare 13 toolkit-source and four shared-source retirements on separate PRs.
- [x] Qualify exact integration refs locally, then hosted: runs 45321529713 (toolkit-only) and 45321531381 (combined) passed wheel, import, HTTP, consumer, Gitlink, clean-bootstrap, launcher and pip-health checks.
- [x] Restore PR #35's qualified module tree with corrective revert `e54550da`; source tree matches qualification checkpoint `f4f8e158`.
- [x] Complete ownership protection PR #36; parser, exact exception, Gitlink and mode changes exercised through the production CLI.
- [x] Prepare separate `llm_local` retirement PR #38; canonical-present and absent-package Agent Memory classifier checks use mocked completions. Fix the tracked-source regression and qualify the hosted branch at `ec123539` (run `45347357571`, passed).
- [x] Prepare separate viewer retirement PR #39; canonical viewer API tests passed 7, direct TermDash attachment smoke passed, and scripts ownership/Help tests passed 50. The Gitlink workflow correction is pushed at `1abb7675`; hosted run `45348359248` passed.
- [x] Prepare canonical Monitor metadata PR #5 at `edd54bd`; Runmux adapter/API compatibility tests passed 19 against an installed canonical wheel plus canonical web UI package.
- [x] Add canonical toolkit Gitlinks for Agent Abilities and Agent Skills at their original upstream pins; fresh worktree initialization and both module suites passed. Scripts source retirement is pushed on `retire/agent-abilities-skills-20261125` (`84231074`); hosted run `45347910359` passed.
- [x] Implement Agent Memory platform-data separation, backward-compatible legacy discovery, and copy-based SQLite/WAL migration on toolkit branch `feat/agent-memory-data-migration-20261125` (`6aaa933`); full suite passed 178, one symlink test skipped. Scripts implementation retirement is pushed at `729e51d8`, preserving the tracked empty index and local sidecars; hosted run `45347914913` passed. Ledger-only commit `5e85cf92` followed.
- [x] Qualify pinned GitHub VCS installs with dependency resolution for Agent Memory, `llm_local`, and viewer in a fresh disposable venv; `pip check` passed and import origins, including `register_dashboard`, resolved inside that venv. The viewer's `termdash` extra used the qualified wheelhouse; no packages were published.
- [x] Complete hosted qualification for PR #38 (`45347357571`), PR #39 (`45348359248`), PR #41 (`45347910359`), and PR #42 (`45347914913`); all passed their clean bootstrap, launcher, consumer, and dependency-health steps.
- [x] Reconcile PR #39 to current Scripts main and stack it after PR #34; its final retirement removes the Viewer metadata test added by #34. The prior #35-stacked Viewer history is no longer part of the reconciled branch.
- [ ] Diagnose toolkit PR #5 only if actionable hosted evidence appears. Four runs (`45333414610`, `45334638802`, `45345602914`, `45345628821`) show all eight jobs failing before runner assignment (`runner_id=0`, empty steps); log downloads return 404. Local Runmux compatibility remains 19 passed; do not retry until hosted diagnostics are available.
- [ ] Coordinate H4 bundle source/metadata and Monitor API contracts with its owner. Preserve active `.worktrees/resource-coordinator-phase-d` and state; only remove `llm_monitor`, `resource_coordinator`, or `resource_metrics` sources after the canonical package contract and immutable bundle qualification pass.
- [x] Verify all five requested releases on PyPI and qualify clean-index dependency resolution; wheel/sdist metadata and SHA256 match PyPI release records. The PyPI Integrity API returned 404 for all ten artifact provenance requests, so source/build lineage remains an open review limitation.
- [ ] Do not merge, publish, synchronize the primary checkout, or migrate runtime data without the existing separate authorization.

- [x] Update PR #34 validation and installer contracts to use published distributions and fail rather than falling back to local shared source packages.
- [x] Reconcile PR #34, stacked PR #39, and Toolkit PR #5 against refreshed main refs; individual and combined synthetic qualification is recorded in the 2026-11-27 checkpoint.
- [x] Pass the approval gate and complete ordered integration: Toolkit, Scripts Resource Metrics, then Scripts Monitor; see the final closeout below.

- [x] Reconcile and push PR #34, stacked PR #39, and Toolkit PR #5 at final current-main refs; combined tree passed 110 synthetic contracts, ownership CLI, dependency resolution, import provenance, launcher discovery, and pip check.

## 2026-11-27 source-retirement continuation

- [x] Qualify and push the Resource Metrics successor with the published wheel digest, source-ownership CLI, and offline H4 contracts.
- [x] Qualify and push the stacked Monitor successor with Toolkit `e10544f6` wheel provenance, synthetic proxy/Runmux contracts, preserved historical evidence, and source-ownership CLI.
- [x] Reconcile Toolkit Resource Coordinator's Metrics dependency bound in an isolated successor; build metadata verified locally.
- [x] Classify current Coordinator source divergence and preserve the active Phase-D owner worktree.
- [x] Integrate and push the two Scripts successors in order; code integration is at `9d9a813b8b58f5f94bb4fe9ab5ea20d828a88a79` and Toolkit dependency correction at `6b09559c287fb434ede42c4e64f5e5097c6982fd`. Keep full Resource Coordinator source retirement gated on H4/Phase-D owner reconciliation. No PRs were created.


- [x] Relocate all 88 retained Monitor README/docs/examples/evidence files to `docs/archive/llm_monitor/`, preserve their hashes, add archive index, and repair direct references.
- [x] Copy and SHA-256 verify the original local `resource_metrics` (22 files) and `llm_monitor` (280 files) trees under `C:\Users\mcarls\src\_migration_backups\source_retirement_20261127_052030`; retain post-sync residual caches under its `post_sync_residuals` directory.
- [x] Synchronize Scripts primary to the integrated main, preserve unrelated edits, and verify both retired module paths physically absent.
- [x] Verify published Metrics and canonical Toolkit Monitor import origins, `pip check` in both existing venvs, and successful managed Monitor/Coordinator help commands.
- [ ] Keep Resource Coordinator retirement gated on H4 owner reconciliation; Phase-D owner worktree remains protected.

## 2026-11-28 Resource Coordinator candidate

- [x] Prepare canonical Toolkit H4 bundle tooling that selects current source by immutable Toolkit commit and historical source from the pinned Scripts revision; package and verify the canonical Metrics and Monitor wheels.
- [x] Archive tracked Resource Coordinator docs, plans, and historical evidence, then remove the duplicate from the isolated Scripts candidate.
- [x] Keep the transferred-module and CLI ownership registry entries so Scripts setup and launcher discovery continue to delegate to Toolkit.
- [x] Update PrivExec H4 defaults/examples to use the canonical Toolkit tooling path; no live installation or VM action was run.
- [x] Qualify focused Scripts ownership/setup tests and Toolkit H4 offline/synthetic tests (record exact branch heads and results in STATUS.md).
- [x] Preserve the six outstanding Phase-D owner documentation paths (including the crash-recovery plan files) as byte-identical archival copies with status/provenance notes; keep the protected owner worktree unchanged.
- [x] Reconcile substantive Phase-D T1 telemetry implementation into the isolated canonical Toolkit candidate; preserve owner worktree and keep crash-recovery proposal inactive.
- [ ] Obtain explicit integration authorization for the Toolkit candidate before integrating the dependent Scripts retirement.
- [ ] Do not merge or synchronize primary checkouts under this task authorization.
