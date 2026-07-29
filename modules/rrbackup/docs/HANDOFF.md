# RRBackup Consolidation Handoff

## Current State

The active branch is:

```text
agent/merge-restic-backup-modules
```

The active plan is:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/
```

Historical and static analysis established:

- `B:\ResticRepos\PC-Local` contains two known snapshots: `a1609113` and `022aad5b`.
- The snapshots predate the committed `backup_module` implementation.
- `backup_module` is the behavioral successor to the direct Restic workflow.
- The existing `rrbackup` development config targets an unrelated Google Drive repository.
- No current local backup schedule is installed.
- Production retention/prune operations are prohibited during consolidation.

## Collaboration Loop

1. The browser/app agent performs as much planning, implementation, documentation, test authoring, and static review as connected tools permit.
2. The browser/app agent updates the active plan before each implementation stage.
3. The browser/app agent implements source and tests on the feature branch and pushes a coherent stage.
4. The user pulls the branch and runs the repository-root `Invoke-Tests.ps1` dispatcher.
5. The dispatcher reads `validation-targets.json`, bootstraps dependencies, runs the selected language-native and PowerShell tests, and writes one authoritative report per target.
6. The user stages, commits, and pushes the generated files under `docs/test-results/<target>/`.
7. The browser/app agent reads `LATEST.txt`, updates `STATUS.md`, `checklist.md`, and stage handoff documents, and implements the next pass.
8. Repeat until temporary-repository integration, Windows adapter, production read-only, controlled backup, restore, scheduler, viewer, audit, and alert acceptance are verified.

The generalized responsibility split and reusable repository-root dispatcher pattern are documented in:

```text
../../../docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md
```

Do not have multiple agents edit this branch concurrently. A local agent should primarily execute tests and report environment-specific evidence unless explicitly assigned a separate patch branch.

## Validation Safety

Default validation must not access or mutate the production repository.

From the repository root, run:

```powershell
./Invoke-Tests.ps1
```

Production read-only checks require:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```

No automated validation may run production backup, restore, init, unlock, forget, prune, cache cleanup, stale-lock removal, or retention application.

## Validation Reports

The authoritative RRBackup result is always:

```text
../../../docs/test-results/rrbackup/LATEST.txt
```

Prior results are comparison-only and are stored under:

```text
../../../docs/test-results/rrbackup/history/
```

The dispatcher retains at most three prior results and removes results older than 14 days by default.

## Validation Evidence

### First committed baseline

- 130 tests collected
- 112 passed
- 4 skipped
- 10 failed
- 4 errored
- package-only branch coverage: 32%

That run proved the original report handoff could capture full output and be consumed remotely.

### Shared-environment failure

The module-local runner then exposed a shared-repository `tests.conftest` import collision. A manual pytest run also used the wrong interpreter and lacked `pytest-mock` and `tomli-w`.

The repository-root dispatcher now resolves the repository virtual environment, bootstraps development dependencies, runs from the target directory, sets target `PYTHONPATH`, and uses pytest importlib mode.

### Latest clean Windows run

The latest complete local report recorded:

- 134 tests collected
- 126 passed
- 8 intentionally skipped
- 0 failed
- 0 errors
- package branch coverage: 36%
- environment smoke test: passed
- production read-only test: safely skipped because it was not enabled

The skipped tests require either a user RRBackup configuration or explicitly enabled Google Drive access. The local LLM's fixes were reviewed and retained because they correctly resolved the dispatcher binding error, dependency/bootstrap isolation, stale console-entry behavior, and Windows integration-test execution.

## Canonical CLI Contract

The merged module will add the canonical `backup` command with six major areas:

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`. `rrb` and `rrbackup` expose the same hierarchy. `backup_module` and `python -m backup_module` preserve their historical interface through a compatibility adapter.

The full CLI and shell-audit replacement contract is:

```text
docs/CLI_ARCHITECTURE_AND_AUDIT_COVERAGE.md
```

The comprehensive read-only replacement for the consolidation PowerShell scripts is:

```text
backup view audit
```

It will aggregate executable resolution, effective configuration, environment provenance, config discovery, input files, repository metadata, keys, snapshots, local runs, logs, locks, schedules, scheduler history, other launchers, health, and provenance without exposing secrets.

## Current Implementation Stage

Stage 1 remains active:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/01_safety-foundation__in-progress.md
```

Stage 2 CLI implementation is planned in:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/02_compatibility-merge-and-cli__planned.md
```
