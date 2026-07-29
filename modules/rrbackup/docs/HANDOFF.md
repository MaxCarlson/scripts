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

1. Browser/remote agent updates the active plan before each implementation stage.
2. Browser/remote agent implements source and tests on the feature branch.
3. Browser/remote agent performs static review and commits a coherent stage.
4. User pulls the branch and runs `./Invoke-RRBackupValidation.ps1 -Bootstrap` in PowerShell 7.
5. User returns the complete generated transcript or pastes its content.
6. Browser/remote agent updates `STATUS.md`, `checklist.md`, and stage handoff documents before patching.
7. Repeat until temporary-repository integration, Windows adapter, production read-only, controlled backup, restore, scheduler, viewer, and alert acceptance are verified.

Do not have multiple agents edit this branch concurrently. A local agent should run tests and report evidence unless explicitly assigned a separate patch branch.

## Validation Safety

Default validation must not access or mutate the production repository.

Production read-only checks require the explicit switch:

```powershell
./Invoke-RRBackupValidation.ps1 -IncludeProductionReadOnly
```

No automated validation may run production backup, restore, init, unlock, forget, prune, or retention application.

## Next Stage

Stage 1 establishes the shared safety foundation and validation harness. See:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/01_safety-foundation__in-progress.md
```
