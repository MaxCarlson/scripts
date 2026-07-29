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

1. The browser/app agent performs as much planning, implementation, documentation, test authoring, and static review as possible.
2. The browser/app agent updates the active plan before each implementation stage.
3. The browser/app agent implements source and tests on the feature branch and pushes a coherent stage.
4. The user pulls the branch and runs `modules/rrbackup/Invoke-Tests.ps1` in PowerShell 7.
5. The script overwrites the tracked `modules/rrbackup/TEST_RESULTS.txt` with complete pytest and PowerShell-test output.
6. The user stages, commits, and pushes `TEST_RESULTS.txt`; manual copy/paste is unnecessary.
7. The browser/app agent reads the committed result file, updates `STATUS.md`, `checklist.md`, and stage handoff documents, and implements the next pass.
8. Repeat until temporary-repository integration, Windows adapter, production read-only, controlled backup, restore, scheduler, viewer, and alert acceptance are verified.

The generalized responsibility split and stage loop are documented in:

```text
docs/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md
```

Do not have multiple agents edit this branch concurrently. A local agent should primarily execute tests and report environment-specific evidence unless explicitly assigned a separate patch branch.

## Validation Safety

Default validation must not access or mutate the production repository.

From `modules/rrbackup`, run the normal suite with:

```powershell
./Invoke-Tests.ps1 -Bootstrap
```

Production read-only checks require the explicit switch:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```

No automated validation may run production backup, restore, init, unlock, forget, prune, or retention application.

## Current Baseline Evidence

The first local run collected 130 tests:

- 112 passed
- 4 skipped
- 10 failed
- 4 errored
- reported coverage: 59%

The failures are baseline defects or outdated tests, not failures introduced by the consolidation branch. The next implementation pass will replace or correct these tests while building the shared safety foundation.

## Next Stage

Stage 1 establishes the shared safety foundation and corrected validation baseline. See:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/01_safety-foundation__in-progress.md
```
