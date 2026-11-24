# Post-P6 source retirement checklist

- [x] Verify current scripts main and preserve the primary checkout's untracked/ignored data.
- [x] Inspect the old PR #27/#28 branches and worktrees; retain them unchanged and build replacements from current main.
- [x] Compare all 25 unique directories to canonical toolkit/shared ownership and inspect remaining imports, package metadata, launchers, and data.
- [x] Preserve eight specific ownership/data/optional-integration holds: `agent_abilities`, `agent_skills`, `agent_memory`, `llm_local`, `llm_monitor`, `resource_coordinator`, `resource_metrics`, and `orchestrator_web_viewer`.
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
- [x] Record dependency contracts and evidence for all eight remaining holds in `STATUS.md`, including nested Gitlink SHAs, Agent Memory DB paths/sidecars, optional `llm_local`, Monitor APIs/state, H4 bundle/source pins, and viewer metadata/API parity.
- [x] Record the active Resource Coordinator H4 worktree's exact dirty/untracked state without modifying it.
- [ ] Complete a fresh dependency-resolved bootstrap and clean `pip check` after an approved wheel/index source is available.
- [ ] Dispatch and complete hosted Linux qualification on both retirement refs. Attempt blocked: `gh auth status` reports an invalid saved token and API DNS lookup failure; GitHub connector has no workflow-dispatch operation; native Chrome app control timed out. Read-only Actions queries confirm zero `workflow_dispatch` runs on both refs.
- [ ] Complete full authenticated submodule checkout/bootstrap, complete-environment `pip check`, installed import provenance, launcher ownership, post-removal Runmux HTTP tests, and consumer regressions in hosted Linux CI.
- [ ] Complete clean Windows root bootstrap through its owning agent; preserve the known Windows descriptor/socket limitation.
- [x] Push replacement branches and open replacement review PRs #34 and #35; do not merge.
- [x] Close stale PRs #27 and #28 with comments linking their current-main replacements.
- [ ] Merge the toolkit-only PR only with separate approval; keep shared-source PR pending clean-index package availability.
- [ ] Do not synchronize/clean primary checkout, quarantine local residuals, or alter any hold without a separate inventory and approval.

## Candidate split

- Toolkit-only PR: 13 directories (`agent_sync`, `agt`, `knowledge_manager`, `llm-interface`, `llm-models`, `llm-patcher`, `lmstui`, `local_agent_bridge`, `web_ai_automator`, `agent_benchmark`, `benchmark_core`, `interactive_reports`, `ai_orchestrator`).
- Shared-source PR: four directories (`script_logging`, `termdash`, `cross_platform`, `web_ui_tools`).
- Retained: eight directories, detailed in `STATUS.md`.

## Qualification refs

- Toolkit-only: `qualify/retirement-toolkit-pr33-pr35-20261124` at `526af4aafda829013f246c6b13e0947fe62806b0` — 62 local tests passed.
- Combined: `qualify/retirement-combined-pr33-pr34-pr35-20261124` at `f4a06aab3a24fe2bb672f5b63ba0b06d8e2e752a` — 65 ownership/Help/Gitlink tests and 13 Runmux CLI/package-metadata tests passed locally.
- Hosted PR #33 run `45302927058` is the workflow-correction baseline only; it predates source removal. It does not satisfy either post-retirement hosted gate.
- PR #34 remains draft and PR #35 remains open. No merge occurred.
