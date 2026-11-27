# Resource Metrics Canonical Retirement Checklist

- [x] Add failing regression tests for source absence, setup list, consumer dependency metadata, and canonical import provenance.
- [x] Replace legacy package dependency names with the pinned canonical distribution across affected consumers (reconciled with origin/main where 7 consumers were already updated and 4 toolkit modules were retired; updated `llm_monitor` and `resource_coordinator`).
- [x] Update module installer ordering and remove the legacy package registration (already removed on `origin/main` and verified by regression test).
- [x] Remove only the 9 tracked `modules/resource_metrics` files; preserve ignored/untracked residuals.
- [x] Run consumer API imports and focused module/H4 tests against the canonical wheel.
- [x] Run Ruff, compile, Git whitespace checks, and source-ownership CLI validation.
- [ ] Update retirement ledger and push the isolated batch for ordered H4 integration.
