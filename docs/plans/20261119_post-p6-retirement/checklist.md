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
- [ ] Complete a fresh dependency-resolved bootstrap and clean `pip check` after an approved wheel/index source is available.
- [ ] Complete post-removal Ubuntu HTTP and consumer qualification through the owning workflow agent.
- [ ] Complete clean Windows root bootstrap through its owning agent; preserve the known Windows descriptor/socket limitation.
- [x] Push replacement branches and open replacement review PRs #34 and #35; do not merge.
- [x] Close stale PRs #27 and #28 with comments linking their current-main replacements.
- [ ] Merge the toolkit-only PR only with separate approval; keep shared-source PR pending clean-index package availability.
- [ ] Do not synchronize/clean primary checkout, quarantine local residuals, or alter any hold without a separate inventory and approval.

## Candidate split

- Toolkit-only PR: 13 directories (`agent_sync`, `agt`, `knowledge_manager`, `llm-interface`, `llm-models`, `llm-patcher`, `lmstui`, `local_agent_bridge`, `web_ai_automator`, `agent_benchmark`, `benchmark_core`, `interactive_reports`, `ai_orchestrator`).
- Shared-source PR: four directories (`script_logging`, `termdash`, `cross_platform`, `web_ui_tools`).
- Retained: eight directories, detailed in `STATUS.md`.
