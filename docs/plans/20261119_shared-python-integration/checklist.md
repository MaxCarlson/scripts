# Integration Checklist

## Prerequisite and ownership

- [x] Inspect supplied shared-package contract and package metadata.
- [x] Match all five wheel hashes against `dist/SHA256SUMS.txt`.
- [x] Install the wheels into a separate scripts integration worktree environment.
- [x] Independently inspect local dirty state in shared and toolkit checkouts: shared clean at `a5602e56` (`feat/dev-bootstrap-20261119`), package/dist tree same as `main` `ff134131`; toolkit clean at `0462cf49`. Read-only GitHub query found no open scripts PR and one unrelated toolkit Dependabot PR; shared repository query was inaccessible (API 422), so check its open PRs before integration.

## Scripts installer and launcher

- [x] Add scripts-owned shared distribution ranges and source install detection.
- [x] Exclude shared source copies from root/module setup, dependency resolution, bootstrap and module discovery.
- [x] Preserve toolkit transferred application and CLI exclusions.
- [x] Keep TermDash installed CLI discoverable.
- [x] Remove toolkit `.venv` fallback from generated scripts launchers.
- [x] Add scripts-owned manifest refresh adapter and invocation-preserving wrapper tests.
- [x] Update scripts-owned package dependencies and corresponding embedded package versions.

## Validation

- [x] Targeted setup/shared-package/launcher tests (28 passed; one submodule-dependent test excluded).
- [x] Consumer regression selection: backup_module, compresser, rrbackup, system_manager, scheduler (61 passed).
- [x] sysmon sampler tests (4 passed).
- [x] vdedup capability tests (19 passed; one actual-GPU test deselected).
- [x] Runmux web CLI and adapter tests (22 passed).
- [x] Construct Runmux ASGI app using installed `web-ui-tools` with temporary state and without starting a service.
- [x] Verify installed shared import paths and distribution versions under `python -I`.
- [x] Verify `pip check` and TermDash CLI help.
- [x] Exercise TermDash dashboard model update/read without starting its renderer.
- [x] Run latest bootstrap dry-run; no installation or wrapper mutation.
- [x] Complete full `bootstrap_latest.py` in a representative clean scripts export with the pinned `pscripts` and nested submodule commits; 62 package installs, 157 launchers, 0 failures; clean-env `agent-continuity` resolved.
- [x] Run clean-env `pip check`, all five shared import provenance checks, TermDash and Runmux CLI help, generated TermDash/Runmux `.cmd` wrapper help, and transferred-command collision check (none).
- [ ] Complete Runmux browser TestClient HTTP suite. **Blocked before request dispatch** by Windows Proactor `_fallback_socketpair`/`socket.accept`; same stall reproduced with minimal FastAPI in baseline primary environment. Runmux app construction passes; no application regression identified. Retry under a Windows environment where asyncio socket pairs work.
- [x] Compare the Runmux HTTP hang against a baseline minimal FastAPI app and capture bounded faulthandler evidence; no scripts-owned fix justified.
- [ ] Run Linux/Ubuntu qualification. WSL Ubuntu and docker-desktop are stopped; startup service state is unknown, so neither distro was started. Use isolated Linux CI/WSL with confirmed safe startup configuration.

## Retirement/integration

- [x] Preserve existing retirement branch/checkpoint/quarantines and raw evidence files.
- [x] Keep all existing source ownership and data holds; do not delete or move source.
- [x] Prepare non-mutating retirement reconciliation and rollback order; integration changes must be accepted first, then selectively apply qualified module removals on a separate branch after comparing current main and quarantine manifests.
- [ ] Apply retirement deletions or merge retirement work (explicitly out of scope for this phase).
- [ ] Review five raw JSON files for sensitivity before any future publication.
- [ ] Obtain later cleanup/integration authorization; do not merge, push, publish or retire primary-checkout source in this task.
