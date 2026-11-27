# H4.5 Resume Checkpoint

Date: 2026-11-15

## Goal

Complete the H4.5 guest-only Windows installation, upgrade, interruption, and rollback acceptance infrastructure. Do not mutate production RC, Scheduled Tasks, KRig, GPU settings, LM Studio, or WSL. No disposable guest was available or authorized for mutation in this run.

## Workspace

- Repository: `C:\Users\mcarls\src\scripts`
- Worktree: `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-h4-full-windows-lifecycle-20261115`
- Intended branch: `agent/rc-h4-full-windows-lifecycle-20261114`
- Source base: published H4 candidate `a618d6b0edcdb9e15f019a9e5109914643c20e99`; reported `main` at task start was `04835a8c93c90881614d55651688800d5f646cad`.
- V3 plan verified in this worktree: SHA-256 `BA842936C9DE945EE8463FD41C3E60491A5714DCA1CF481064DC915DBF516F46`, blob `3a1c2f7662a54469bb6dc15ad6462a4295ec93e6`.
- Original H4 and Part 2/3 worktrees were not intentionally modified.

## Implemented but uncommitted

- `resource_coordinator/installation.py`: added guarded `InstallationRuntime` injection for task identities, loopback listener, scoped credential provider, process/listener/GPU observers, clock/sleep, and test fault injection; added isolated paths and validation; passed runtime task names into legacy attribution so guest upgrades do not require production task names; task helper uses protected payload identities.
- `tools/h4_qualification/windows_acceptance.py`: added guest-only install/upgrade/rollback/full/cleanup profiles, source version/tree hash checks, reparse-point rejection, exact phase cleanup manifests, per-phase cleanup verification, bounded upgrade fault points, and a listener-port/PID/create-time/executable ownership guard.
- `tests/test_h4_installation_runtime.py`: runtime, path-isolation, and legacy-call compatibility coverage; passes in the focused combined suite.
- `tests/test_h4_windows_acceptance.py`: phase manifest, listener ownership, runner authorization, and profile coverage.
- H4 documentation: `STATUS.md`, `checklist.md`, `ACCEPTANCE_MATRIX.md`, `WINDOWS_ACCEPTANCE.md`, plus this checkpoint.

Current Git status and the scoped diff are readable and verified. `git fetch origin` cannot write the shared `.git/FETCH_HEAD` in this sandbox (`Permission denied`), so remote refs could not be refreshed. The branch's upstream still points to the preceding H4 documentation branch. No commit or push has been attempted; do not push to that stale upstream.

## Fresh verification from this stop point

Python 3.12.10 was invoked explicitly as `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe` from the RC module directory.

- Combined focused H4 runner/runtime/installation/task transport selection: **136 tests, 0 failed, 3 skipped**, exit 0. Skips are opt-in Windows task-mutation tests.
- Runner `offline` profile: **110 tests, 0 failed, 1 skipped**, exit 0; artifacts were written under a unique module-local temporary root. The mock-backed profile made no task or service changes.
- Ruff on changed implementation and tests: exit 0.
- `compileall` on changed implementation and tests: exit 0.
- `git diff --check`: exit 0.
- Initial combined runs exposed test seam compatibility and temp-root mistakes; these were corrected without changing existing assertions. An intermediate malformed `--basetemp` invocation failed during pytest setup and is excluded from the pass counts.
- No actual guest acceptance was run. No production state was changed.

## Continue here

1. On the new machine, start with `git -C <worktree> status --short --branch`, branch/worktree inventory, and remote refs. Preserve any concurrent changes; do not reset or overwrite this worktree.
2. Review the exact diff. In particular, inspect all `ManagedInstallation` mutations, helper task identity validation, source-root hashing, manifest-driven cleanup, and the custom-name `_legacy_attribution()` change.
3. Validation is complete for the focused H4 runner/runtime/installer/helper selection and the offline profile. Review the final diff and exact status before publication.
4. Commit and push the isolated task branch only when repository metadata access and the intended remote ref can be verified. Do not merge to `main`.
5. Execute task/UAC/install/upgrade/rollback profiles only on a separately identified and mutation-authorized disposable Windows guest. A user-supplied authorization phrase or `is_vm` flag is not guest proof.

## Still blocked

- Actual Task Scheduler/UAC/service/install/upgrade/rollback acceptance: `NOT_TESTED` pending an authorized disposable guest and scoped mutation approval.
- Historical WinError 206 root cause: unresolved until the actual isolated upgrade orchestration identifies the failing boundary.
- WDDM complete process attribution: still unproven; preserve the previous 3/3 known-KRig correlation only as partial evidence.
- H5 supervised maintenance: not ready while guest acceptance and approved deployment/running-version identity are missing.
- Unattended recovery: disabled pending complete authoritative execution-boundary evidence and separate approval.
