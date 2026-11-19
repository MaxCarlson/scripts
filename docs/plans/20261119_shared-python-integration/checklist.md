# Integration Checklist

## Prerequisite and ownership

- [x] Inspect supplied shared-package contract and package metadata.
- [x] Match all five wheel hashes against `dist/SHA256SUMS.txt`.
- [x] Install the wheels into a separate scripts integration worktree environment.
- [ ] Independently inspect dirty state/open PRs in shared and toolkit checkouts (sandbox denied external worktree access).

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
- [x] Run latest bootstrap dry-run; no installation or wrapper mutation.
- [ ] Complete Runmux browser TestClient HTTP suite (first request hangs in this environment).
- [ ] Complete full clean scripts installation including `pscripts` and all applications.
- [ ] Run Linux/Ubuntu qualification.

## Retirement/integration

- [x] Preserve existing retirement branch/checkpoint/quarantines and raw evidence files.
- [x] Keep all existing source ownership and data holds; do not delete or move source.
- [ ] Reconcile integration branch with retirement checkpoint after all validation gates.
- [ ] Review five raw JSON files for sensitivity before any future publication.
- [ ] Obtain later cleanup/integration authorization; do not merge, push, publish or retire primary-checkout source in this task.
