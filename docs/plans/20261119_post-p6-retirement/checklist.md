# Post-P6 source retirement checklist

- [x] Audit the 25-directory ownership inventory and preserve primary-checkout untracked/ignored data.
- [x] Prepare 13 toolkit-source and four shared-source retirements on separate PRs.
- [x] Qualify exact integration refs locally, then hosted: runs 45321529713 (toolkit-only) and 45321531381 (combined) passed wheel, import, HTTP, consumer, Gitlink, clean-bootstrap, launcher and pip-health checks.
- [x] Restore PR #35's qualified module tree with corrective revert `e54550da`; source tree matches qualification checkpoint `f4f8e158`.
- [x] Complete ownership protection PR #36; parser, exact exception, Gitlink and mode changes exercised through the production CLI.
- [x] Prepare separate `llm_local` retirement PR #38 at `1422d0df`; Agent Memory absent-package suite passed 20, canonical package suite passed 10, and installed canonical package consumer tests passed 2 with mocked completions.
- [x] Prepare separate viewer retirement PR #39 at `1d7689f5`; canonical viewer API tests passed 7, direct TermDash attachment smoke passed, and scripts ownership/Help tests passed 50.
- [x] Prepare canonical Monitor metadata PR #5 at `edd54bd`; Runmux adapter/API compatibility tests passed 19 against an installed canonical wheel plus canonical web UI package.
- [ ] Obtain ordinary install-source availability and fresh hosted qualification for PRs #38 and #39 before merge approval.
- [ ] Repair or explain canonical Monitor PR #5 hosted matrix failures; logs were unavailable. Resolve H4 bundle staging before removing scripts Monitor source.
- [ ] Resolve `agent_abilities`/`agent_skills` Gitlink ownership and initialization; establish Agent Memory data-path migration without touching live data; resolve Resource Coordinator H4 and `resource_metrics` bundle contracts.
- [ ] Keep PR #34 gated on ordinary package-index availability and clean-index install qualification.
- [ ] Do not merge, publish, synchronize the primary checkout, or migrate runtime data without the existing separate authorization.
