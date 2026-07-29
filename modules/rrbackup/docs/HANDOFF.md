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

Stage 1 implementation is complete and awaiting local validation. The inherited public CLI has not yet been redirected to the new engine.

Historical and static analysis established:

- `B:\ResticRepos\PC-Local` contains two known snapshots: `a1609113` and `022aad5b`.
- The snapshots predate the committed `backup_module` implementation.
- `backup_module` is the behavioral successor to the direct Restic workflow.
- The existing `rrbackup` development config targets an unrelated Google Drive repository.
- No current local backup schedule is installed.
- Production retention/prune operations are prohibited during consolidation.

## Collaboration Loop

1. The browser/app agent performs planning, implementation, documentation, test authoring, commits, pushes, and diagnosis through connected repository tools.
2. The user pulls the branch and runs the repository-root `Invoke-Tests.ps1` dispatcher.
3. The dispatcher bootstraps dependencies and runs compilation, focused correctness lint, pytest/coverage, and PowerShell validation scripts.
4. The user stages, commits, and pushes the generated files under `docs/test-results/<target>/`.
5. The browser/app agent reads `LATEST.txt`, `LATEST_CONTEXT.md`, and `LATEST_PROGRESS.diff`, then patches failures or begins the next stage.

Do not have multiple agents independently edit this branch. A local agent should primarily execute validation and report environment-specific evidence unless explicitly assigned a separate patch branch.

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

## Authoritative Validation Evidence

```text
../../../docs/test-results/rrbackup/LATEST.txt
../../../docs/test-results/rrbackup/LATEST_CONTEXT.md
../../../docs/test-results/rrbackup/LATEST_PROGRESS.diff
```

Prior artifacts under `history/` are comparison-only. The dispatcher retains at most three prior artifacts of each type and removes artifacts older than 14 days by default.

The repository-wide expansion plan for paired validation/context/diff evidence is:

```text
../../../docs/plans/20260729-0900_validation-evidence-context-history/
```

That subsystem should not be expanded further during RRBackup consolidation unless it blocks validation or loses evidence.

## Latest Proven Baseline

Before the new safety foundation was added, the latest complete local run recorded:

- 134 tests collected
- 126 passed
- 8 intentionally skipped
- 0 failed
- 0 errors
- package branch coverage: 36%
- environment smoke test: passed
- production read-only test: safely skipped

The skipped tests require either a user RRBackup configuration or explicitly enabled Google Drive access.

## Stage 1 Implementation Checkpoint

RRBackup is now version `0.3.0` and declares `psutil` as a runtime dependency.

New shared components:

```text
rrbackup/engine.py
rrbackup/locking.py
rrbackup/models.py
rrbackup/policy.py
rrbackup/profile.py
rrbackup/restic.py
rrbackup/snapshots.py
rrbackup/state.py
```

Implemented semantics:

- canonical legacy profile adapter with source attribution,
- exact production-compatible Restic backup command construction,
- hard preview/print-only execution barrier,
- dry-run state distinct from real success,
- CPU normal/overdue policy evaluated before lock acquisition,
- PID-plus-create-time process locking with ownership tokens,
- invalid-lock protection and active-lock skip behavior,
- atomic current/history/last-success state,
- snapshot and backup-summary JSON parsing,
- snapshot-ID capture after successful backups,
- terminal state after wait, lock, execution, interruption, or result-finalization failures.

New tests cover the individual components and complete engine lifecycles, including preview, CPU skip, lock contention, dry-run, success, nonzero exit, interruption, malformed summaries, and exception paths.

## Next Action

Run the root dispatcher after pulling this checkpoint. The manifest now runs:

1. editable dependency bootstrap,
2. package/test compilation,
3. focused correctness lint,
4. full pytest and branch coverage,
5. PowerShell smoke tests.

After the generated evidence is pushed, correct any Stage 1 failures. If it passes, mark Stage 1 verified and begin Stage 2 compatibility merge and hierarchical CLI implementation.

## Canonical CLI Contract

The merged module will expose:

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`. `rrb` and `rrbackup` will expose the same hierarchy. `backup_module` and `python -m backup_module` will preserve their historical interface through a compatibility adapter.

The full CLI and shell-audit replacement contract is:

```text
docs/CLI_ARCHITECTURE_AND_AUDIT_COVERAGE.md
```

The comprehensive read-only replacement for prior PowerShell audits will be:

```text
backup view audit
```

Stage 2 is planned in:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/02_compatibility-merge-and-cli__planned.md
```
