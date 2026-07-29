# RRBackup Consolidation, Viewer, and Alerting Implementation Plan

## Objective

Consolidate `modules/rrbackup` and `modules/backup_module` into one safe Restic management package with:

- one shared engine,
- compatible `rrb`, `rrbackup`, and `backup_module` commands,
- explicit setup and configuration management,
- scheduler CRUD and health reporting,
- a Git-history-like backup viewer,
- missed-backup detection and alerts,
- scoped retention,
- comprehensive automated tests and Windows validation scripts.

## Production Compatibility Contract

| Setting | Required value |
|---|---|
| Repository | `B:\ResticRepos\PC-Local` |
| Password file | `C:\BackupConfig\restic-local-password.txt` |
| Source list | `C:\BackupConfig\local-sources.txt` |
| Exclude list | `C:\BackupConfig\local-excludes.txt` |
| Legacy tag | `local-main` |
| Known snapshots | `a1609113`, `022aad5b` |
| Restore root | `B:\ResticRestore` |
| Normal CPU cutoff | 25% |
| Overdue CPU cutoff | 85% |
| Overdue threshold | 3 days |
| Maximum CPU wait | 60 minutes |

The existing snapshots were created by the direct Restic predecessor workflow. `backup_module` is the behavioral successor and compatibility baseline. The old RRBackup development configuration targets a separate Google Drive repository.

## Safety Invariants

- No production mutation from automated tests.
- No automatic prune or retention during migration.
- No repository-wide unscoped forget/prune.
- Dry-run never updates backup-success state.
- Preview never launches Restic.
- Scheduler launch success never implies snapshot success.
- CPU-gated skip never counts as backup success.
- Repository snapshots are authoritative; local state is supplemental.
- Existing public commands and legacy option aliases remain available during the compatibility period.
- Production read-only validation is opt-in.

## Stages

### Stage 1 — Safety Foundation

- Canonical models and configuration resolution
- Restic command builder and subprocess boundary
- Preview and dry-run semantics
- Run-state persistence
- Process-identity locking
- CPU policy
- Snapshot summary parsing
- Root validation runner and PowerShell checks
- High-coverage unit tests

### Stage 2 — Compatibility Merge

- Move production-default behavior into the shared engine
- Preserve legacy JSON/default loading
- Add `backup_module` compatibility package and command
- Preserve legacy underscore options as aliases
- Add canonical TOML profile/set model

### Stage 3 — Scheduler Redesign

- Schedule create/show/list/update/enable/disable/delete/run/health/export/import
- Windows Task Scheduler adapter first
- systemd timer and cron adapters
- No-overlap, retry, missed-run, executable-path, and config-path handling
- Scheduler execution correlation with run records and snapshots

### Stage 4 — Viewer

- Snapshot, run, scheduler, configuration, check, and alert correlation
- Dashboard and Git-like timeline
- Health, gaps, storage, details, sets, schedules, and runs views
- Human, JSON, JSON Lines, CSV, and Markdown outputs
- Explicit provenance and freshness for every data source

### Stage 5 — Alerting

- Health evaluator
- Missed/failed/overdue/scheduler/repository/lock/config alert conditions
- Persistent deduplication and lifecycle state
- Terminal, append-only log, webhook, Windows notification, and configurable email/external-command transports

### Stage 6 — Scoped Retention

- Stable ownership tags for new snapshots
- Preview by default
- Explicit apply
- Explicit legacy adoption
- Tests proving unrelated and legacy snapshots remain outside scope

### Stage 7 — Cleanup and Acceptance

- Remove duplicate engines while retaining compatibility shims
- Correct documentation and remove stale test artifacts
- Quarantine secret-like tracked files and rotate credentials if verified real
- Temporary-repository suite
- Production read-only suite
- Controlled real backup
- Small restore with hash verification
- Scheduled execution verification
- Viewer and alert acceptance

## Test Strategy

- Unit tests for every public function, normal path, edge case, and failure path.
- Mock filesystem, process, environment, scheduler, network, and clock boundaries.
- Temporary Restic repository integration tests for init, initial/incremental backup, dry-run, preview, list, search, restore, hashes, check, stats, viewer, and scoped retention.
- PowerShell scripts for Windows entry points, Task Scheduler definition generation/inspection, path quoting, and optional production read-only compatibility.
- Generated temp data remains under `modules/rrbackup/.pytest_tmp_root/`.
- Validation transcripts remain under `modules/rrbackup/test-results/` and are ignored.

## Local Validation Loop

From the repository root:

```powershell
./Invoke-RRBackupValidation.ps1 -Bootstrap
```

Optional production read-only checks:

```powershell
./Invoke-RRBackupValidation.ps1 -IncludeProductionReadOnly
```

The validation runner must emit one paste-ready transcript and return nonzero when any required check fails.
