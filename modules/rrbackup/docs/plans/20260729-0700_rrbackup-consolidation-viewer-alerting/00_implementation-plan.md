# RRBackup Consolidation, Viewer, and Alerting Implementation Plan

## Objective

Consolidate `modules/rrbackup` and `modules/backup_module` into one safe Restic management package with:

- one shared engine,
- canonical `backup` CLI plus compatible `rrb`, `rrbackup`, and `backup_module` commands,
- six discoverable hierarchical command areas,
- explicit setup and configuration management,
- scheduler CRUD and health reporting,
- a Git-history-like backup viewer,
- one-command replacement for ad hoc shell-based backup audits,
- missed-backup detection and alerts,
- scoped retention,
- comprehensive automated tests and Windows validation scripts.

The CLI contract is defined in:

```text
../../CLI_ARCHITECTURE_AND_AUDIT_COVERAGE.md
```

## Canonical CLI Areas

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`.

`backup`, `rrb`, and `rrbackup` expose the same hierarchy. `backup_module` remains a compatibility adapter for its historical flat commands and underscore-style options.

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
- Audit and diagnostic output never reveals password contents, secret environment values, tokens, or private keys.
- Routine backup diagnosis must not require ad hoc platform shell commands.

## Stages

### Stage 1 — Safety Foundation

- Canonical models and configuration resolution
- Restic command builder and subprocess boundary
- Preview and dry-run semantics
- Run-state persistence
- Process-identity locking
- CPU policy
- Snapshot summary parsing
- Repository-root validation dispatcher and target manifest
- RRBackup PowerShell checks registered as a validation target
- Timestamped tracked reports under `docs/test-results/rrbackup/`
- High-coverage unit tests

### Stage 2 — Compatibility Merge and Hierarchical CLI

- Move production-default behavior into the shared engine
- Preserve legacy JSON/default loading
- Add canonical `backup` entry point
- Preserve `rrb`, `rrbackup`, `backup_module`, and `python -m backup_module`
- Add six major command areas and nested help
- Preserve legacy underscore options as aliases
- Add canonical hyphenated options
- Add canonical TOML profile/set model
- Add `backup view audit`, `backup config discover`, and launcher/scheduler/repository diagnostics
- Replace all useful consolidation shell-audit capabilities with first-class commands

### Stage 3 — Scheduler Redesign

- Schedule create/show/list/update/enable/disable/delete/run/health/history/discover/export/import
- Windows Task Scheduler adapter first
- systemd timer and cron adapters
- Startup-command and service launcher discovery
- No-overlap, retry, missed-run, executable-path, and config-path handling
- Scheduler execution correlation with run records and snapshots

### Stage 4 — Viewer

- Snapshot, run, scheduler, configuration, repository, check, audit, and alert correlation
- Dashboard and Git-like timeline
- Health, gaps, storage, details, sets, schedules, runs, logs, setup, system, provenance, and audit views
- Human, JSON, JSON Lines, CSV, and Markdown outputs
- Explicit provenance and freshness for every data source

### Stage 5 — Alerting

- Health evaluator
- Missed/failed/overdue/scheduler/repository/lock/config alert conditions
- Persistent deduplication and lifecycle state
- Terminal, append-only log, webhook, Windows notification, and configurable email/external-command transports
- Alert configuration under `backup config alerts`
- Alert state under `backup view alerts` and `backup view health`

### Stage 6 — Scoped Retention

- Stable ownership tags for new snapshots
- Preview by default
- Explicit apply
- Explicit legacy adoption
- Tests proving unrelated and legacy snapshots remain outside scope
- Repository retention operations under `backup repository retention`

### Stage 7 — Cleanup and Acceptance

- Remove duplicate engines while retaining compatibility shims
- Correct documentation and remove stale test artifacts
- Quarantine secret-like tracked files and rotate credentials if verified real
- Temporary-repository suite
- Production read-only suite
- Controlled real backup
- Small restore with hash verification
- Scheduled execution verification
- Viewer, audit, and alert acceptance

## Shell-Audit Replacement Requirement

The module must internalize the useful information gathered during consolidation through PowerShell and direct Restic commands, including:

- command and wrapper resolution,
- environment-variable provenance,
- known and relocated configuration discovery,
- source/exclusion/status/log/lock inspection,
- repository keys, snapshots, stats, check, cache, and lock information,
- scheduler definitions, actions, settings, results, and event history,
- services, startup commands, systemd timers, and cron launchers,
- local run records and logs,
- missed-backup and provenance conclusions.

The comprehensive read-only replacement is:

```text
backup view audit
```

Machine-readable forms:

```text
backup view audit --json
backup view audit --markdown
```

Legacy shell-history inspection is explicit and opt-in:

```text
backup view audit --include-legacy-evidence
```

## Test Strategy

- Unit tests for every public function, normal path, edge case, and failure path.
- Mock filesystem, process, environment, scheduler, network, clock, and platform-adapter boundaries.
- Temporary Restic repository integration tests for init, initial/incremental backup, dry-run, preview, list, search, restore, hashes, check, stats, viewer, audit, and scoped retention.
- CLI contract tests for root help, nested help, aliases, output purity, and compatibility surfaces.
- PowerShell scripts for Windows entry points, Task Scheduler definition generation/inspection, path quoting, and optional production read-only compatibility.
- Generated temp data remains under `modules/rrbackup/.pytest_tmp_root/`.
- The repository-root dispatcher bootstraps declared dependencies and invokes pytest with import isolation.
- Complete local results are written to tracked, timestamped files under `docs/test-results/rrbackup/`.

## Local Validation Loop

From the repository root:

```powershell
./Invoke-Tests.ps1
```

Optional production read-only checks:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```

The dispatcher reads `validation-targets.json`, selects `rrbackup` by default, captures complete pytest and PowerShell output, returns nonzero when required checks fail, and writes a report named:

```text
docs/test-results/rrbackup/YYYYMMDD-HHMMSS_rrbackup.txt
```

The user commits and pushes the generated report for remote diagnosis.
