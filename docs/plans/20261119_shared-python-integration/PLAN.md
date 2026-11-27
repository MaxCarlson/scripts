# Scripts Shared-Package Integration Plan

> **Execution:** Native in this session, authorized by the handoff's autonomous implementation instruction.

**Goal:** Make scripts install and use the five qualified shared distributions from its own environment, independent of the toolkit and shared source checkouts, then qualify consumers and prepare—but do not merge or physically retire—source cleanup.

**Architecture:** Keep the five library sources and wheel artifacts owned by `shared-python-modules`. A scripts-owned registry supplies normalized package constraints and marks shared module directories as non-installable source copies. Both scripts bootstraps ensure the shared distributions through pip, while application dependency metadata expresses compatible release ranges. Generated wrappers use the scripts `.venv`; a thin scripts-owned wrapper refreshes the scripts manifest before delegating execution/history to `script-logging`.

**Tech Stack:** Python 3.12 on Windows, pip wheelhouse, PowerShell, pytest, Git worktrees.

**Spec:** User handoff “Agent Handoff — Scripts Shared-Package Integration and Retirement Preparation” (2026-11-19).

## Global Constraints

- All writes stay within the `scripts` repository and the isolated integration worktree.
- Shared and toolkit repositories are read-only; do not modify their sources, branches, or worktrees.
- Use qualified wheels from the shared wheelhouse for staging; never embed a local checkout path in package metadata.
- Keep `web_ui_tools`, `termdash`, and `cross_platform` source present in the primary scripts checkout; do not merge quarantined removals.
- Preserve the retirement worktree at `cc3273f0`, its 16 quarantines, manifests, rollback evidence, and five raw untracked JSON files.
- Do not push, merge, publish, permanently delete, or run local inference or production workloads.
- Preserve CLI names, optional dependencies, invocation history/schema, and the existing `agent-continuity` bootstrap baseline.

## Review Focus

- A prior toolkit-source install may satisfy a version range while retaining a cross-repository `direct_url`; tests must prove it is replaced by a standard distribution.
- `-I` wrapper execution may affect imports and editable setup utilities; verify from the scripts environment without `PYTHONPATH`.
- Optional Runmux web dependencies must remain optional while installing correctly when selected.
- Removing shared source directories from discovery must not remove the TermDash installed CLI or scripts-owned commands.
- Bootstrap dry-run must report shared distributions without installing packages or creating wrappers.

## Tasks

### Task 1: Record artifact and ownership evidence

Verify all five wheel hashes, metadata and import roots against the shared handoff. Record any Git-state limitations for other repositories and the current integration worktree baseline.

### Task 2: Separate shared distributions from source modules

Create a scripts-owned shared-package registry/helper; test package constraints and source-directory exclusion. Update `setup.py`, `modules/setup.py`, `modules/setup_utils/dependency_resolver.py`, and `bootstrap_latest.py` so fresh setup installs the five distributions and does not install their source directories. Preserve the 23 transferred application exclusions and discover shared console entry points from installed metadata.

### Task 3: Remove toolkit launcher-environment dependency

Add regression tests for Windows/POSIX generated wrappers and a scripts-owned manifest-refreshing launcher adapter. Use the scripts `.venv` for `script-logging`; preserve delegated argument handling, target interpreter, invocation history, and manifest refresh behavior.

### Task 4: Align scripts-owned consumer requirements

Update only scripts-owned package metadata that directly depends on the shared libraries, using the handoff's compatible version ranges and preserving extras/markers. Do not edit transferred application directories or the shared library source copies.

### Task 5: Qualify clean installation and consumers

Install from the wheelhouse into an isolated scripts worktree environment, run `pip check`, verify imports and CLI provenance with `python -I`, run bootstrap dry-run and launcher tests, and execute applicable safe consumer regressions. Attempt Linux qualification only if a supported environment is available without external repository changes.

### Task 6: Document, review, and checkpoint

Update scripts integration/retirement status with exact versions, hashes, test evidence, unresolved gates, and rollback steps. Review the task-only diff and commit on the local integration branch. Do not merge, push, publish, or remove primary-checkout sources.

## Verification Commands

- `python -m pytest scripts_setup/tests/transferred_modules_test.py modules/setup_utils/tests`
- Focused consumer test suites for `backup_module`, `compresser`, `rrbackup`, `runmux`, `sysmon`, `system_manager`, `vdedup`, and `scheduler` (offline/mocked fixtures only).
- `python -I -m pip check` in the isolated scripts `.venv`.
- `python -I -c` import provenance checks for all five shared imports.
- `python bootstrap_latest.py --dry-run` and all relevant wrapper/CLI help smoke checks.
- `git diff --check` and task-only staged-diff review.
