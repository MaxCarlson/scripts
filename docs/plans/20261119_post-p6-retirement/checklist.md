# Post-P6 source retirement checklist

- [x] Verify current scripts main and preserve the primary checkout's untracked/ignored data.
- [x] Inspect the old PR #27/#28 branches and worktrees; retain them unchanged and build replacements from current main.
- [x] Compare all 25 unique directories to canonical toolkit/shared ownership and inspect remaining imports, package metadata, launchers, and data.
- [x] Preserve the seven remaining ownership/data/optional-integration holds: `agent_abilities`, `agent_skills`, `agent_memory`, `llm_local`, `resource_coordinator`, `resource_metrics`, and `orchestrator_web_viewer`.
- [x] Stage 13 toolkit-only source removals on `retire/toolkit-sources-current-main`.
- [x] Stage four shared-source removals and dependency/validation-target corrections on `retire/shared-sources-current-main`.
- [x] Verify qualified wheel hashes/metadata, offline wheel install, import provenance, TermDash help, XInstall fallback, Runmux CLI, setup ownership tests, and bootstrap dry-runs.
- [x] Preserve the TermDash `TERMDASH_WEB_ATTACH` integration by holding `orchestrator_web_viewer`; update its optional dependency to `mxc-termdash` and verify package metadata.
- [x] Inventory tracked, untracked, and ignored primary-checkout module files read-only; record inaccessible ignored-cache paths and the unapplied synchronization/quarantine plan in `STATUS.md`.
- [x] Keep current-main validation targets and the recent media/procparsers work intact.
- [x] Create and push isolated qualification refs for `main + PR #33 + PR #35` and the combined `main + PR #33 + PR #34 + PR #35`; preserve the PR branches.
- [x] Refresh local retirement checks on the exact qualification SHAs: 62 tests on toolkit-only, 65 ownership/Help/Gitlink tests on combined, and 13 Runmux CLI/package-metadata tests on combined.
- [x] Recheck the five staged wheel SHA-256 values and isolated import provenance on the combined ref; all five `mxc-*` versions resolve from the qualification target and all five legacy distributions are absent there.
- [x] Correct the TermDash/viewer disposition: `mxc-termdash` source can retire; `orchestrator_web_viewer` remains held because the optional `TERMDASH_WEB_ATTACH` path calls its API.
- [x] Record dependency contracts and evidence for the seven remaining holds in `STATUS.md`, including nested Gitlink SHAs, Agent Memory DB paths/sidecars, optional `llm_local`, H4 bundle/source pins, and viewer metadata/API parity.
- [x] Recheck the Harbor/Monitor transfer; preserve its source feature branch/worktree and verify all 176 Monitor source paths and historical evidence against the toolkit branch.
- [x] Confirm no active Monitor process, no scripts `.venv` Monitor installation, Runmux's `package_missing` fallback, and the telemetry database outside the module tree.
- [x] Remove the 176 tracked `llm_monitor` files and obsolete Scripts Help module entry in an isolated worktree; retain the transferred distribution and CLI exclusion records.
- [x] Re-run the ownership, Scripts Help, Runmux optional-package, and consumer regressions on the stacked proposal: 58 ownership/Help tests, 19 Runmux integration/API tests (including the package-missing case), and 11 web CLI tests passed.
- [x] Record the active Resource Coordinator H4 worktree's exact dirty/untracked state without modifying it.
- [x] Complete a fresh dependency-resolved bootstrap and clean `pip check` on the preserved toolkit-only and combined refs through hosted qualification.
- [x] Dispatch and complete hosted Linux qualification on both retirement refs: runs `45321529713` and `45321531381` passed the recorded checks.
- [x] Complete authenticated submodule checkout/bootstrap, installed import provenance, launcher ownership, synthetic Runmux HTTP tests, and consumer regressions for those exact refs in hosted Linux CI.
- [ ] Run hosted qualification on this additional stacked Monitor-removal follow-up before treating it as merge-ready.
- [ ] Complete clean Windows root bootstrap through its owning agent; preserve the known Windows descriptor/socket limitation.
- [x] Push replacement branches and open replacement review PRs #34 and #35; do not merge.
- [x] Close stale PRs #27 and #28 with comments linking their current-main replacements.
- [ ] Merge the toolkit-only PR only with separate approval; keep shared-source PR pending clean-index package availability.
- [ ] Do not synchronize/clean primary checkout, quarantine local residuals, or alter any hold without a separate inventory and approval.

## Candidate split

- Toolkit-only PR: 13 directories (`agent_sync`, `agt`, `knowledge_manager`, `llm-interface`, `llm-models`, `llm-patcher`, `lmstui`, `local_agent_bridge`, `web_ai_automator`, `agent_benchmark`, `benchmark_core`, `interactive_reports`, `ai_orchestrator`).
- Shared-source PR: four directories (`script_logging`, `termdash`, `cross_platform`, `web_ui_tools`).
- Retained: seven directories, detailed in `STATUS.md`.

## Qualification refs

- Toolkit-only: `qualify/retirement-toolkit-pr33-pr35-20261124` at `526af4aafda829013f246c6b13e0947fe62806b0` — 62 local tests passed.
- Combined: `qualify/retirement-combined-pr33-pr34-pr35-20261124` at `f4a06aab3a24fe2bb672f5b63ba0b06d8e2e752a` — 65 ownership/Help/Gitlink tests and 13 Runmux CLI/package-metadata tests passed locally.
- Hosted PR #33 run `45302927058` remains the workflow-correction baseline; post-removal hosted runs are `45321529713` and `45321531381` on the preserved qualification refs.
- PR #34 remains draft and PR #35 remains open. No merge occurred.
- The Monitor follow-up branch is based on PR #35 head `217ba2ab8c22ebb3c493bfaae13341a686e04925`; local post-removal checks are recorded above, but no hosted run or merge is claimed.
- The existing ownership-protection draft PR #36 remains separate and unmodified; its review/remaining launcher audit is still open.

## Continuation checkpoint — 2026-11-24 Monitor composition

- [x] Reconcile PR #34 against the existing PR #35 plus Monitor-removal tree without restoring Monitor source or tests.
- [x] Compose current main, PR #33 qualification corrections, PR #34, PR #35, and existing Monitor removal on `qualify/retirement-monitor-pr34-pr35-20261124`.
- [x] Verify the qualification commit includes PR #33 `72dbf83`, PR #35 `f4f8e15`, Monitor removal `99ef8af`, PR #34 `f7b119a`, and has main merge-base `b60155b9`.
- [x] Confirm all 18 proposed source directories are absent and all seven held directories remain present.
- [x] Run the combined focused selection on the final composition: 86 passed in 5.17s, including ownership, shared packages, Gitlink validation, Scripts Help, Runmux optional behavior, web CLI, and viewer metadata tests.
- [x] Preserve PR #34 and PR #35 branches, primary checkout diagnostics and runtime sidecars, both Harbor worktrees, the Resource Coordinator H4 worktree, and historical quarantine evidence.
- [ ] Dispatch and pass hosted Linux qualification on `d21a159327dea15b6032c61bad7e11f36ad6f1f7`; current `gh` token is invalid and API DNS lookup fails. Existing runs `45321529713`/`45321531381` do not cover this revision.
- [ ] Hosted full authenticated bootstrap, launcher and consumer regressions, final `pip check`, and Ubuntu synthetic Runmux HTTP tests on the final composition.
- [ ] Complete owning agent's Windows root-setup qualification; retain the known Windows HTTP socket-pair limitation.
- [ ] Keep seven ownership/data/dependency holds and do not merge or synchronize primary `scripts/main` without separate approval.
