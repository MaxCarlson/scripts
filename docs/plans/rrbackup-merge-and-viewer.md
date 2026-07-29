# RRBackup Consolidation, Viewer, and Alerting Plan

## Status

- [x] Historical repository provenance analyzed
- [x] Existing `rrbackup` and `backup_module` implementations audited
- [x] Production repository compatibility contract defined
- [ ] Shared engine implemented
- [ ] Legacy compatibility shims implemented
- [ ] Scheduler management redesigned
- [ ] Viewer implemented
- [ ] Alerting implemented
- [ ] Temporary-repository test matrix passing
- [ ] Read-only production compatibility checks passing
- [ ] Controlled production backup verified
- [ ] Scheduled production execution verified

## Objective

Consolidate `modules/rrbackup` and `modules/backup_module` into one reliable Restic management package that preserves the proven local backup workflow, supports named local and remote backup sets, provides safe setup and scheduling tools, exposes a detailed backup-history viewer, and alerts when expected backups are missing or failing.

The canonical package and long-term CLI are `rrbackup`, `rrb`, and `rrbackup`. The legacy `backup_module` command remains available as a compatibility shim for at least one release cycle.

## Production Compatibility Contract

The merged implementation must preserve read and write compatibility with the existing production repository without requiring repository migration.

| Setting | Required value |
|---|---|
| Repository | `B:\ResticRepos\PC-Local` |
| Password file | `C:\BackupConfig\restic-local-password.txt` |
| Source list | `C:\BackupConfig\local-sources.txt` |
| Exclude list | `C:\BackupConfig\local-excludes.txt` |
| Snapshot tag | `local-main` |
| Snapshot host | `Xeres` |
| Existing snapshots | `a1609113`, `022aad5b` |
| Restore root | `B:\ResticRestore` |
| Filesystem snapshot behavior | `--use-fs-snapshot` on supported Windows systems |
| Cache exclusion behavior | `--exclude-caches` |
| CPU policy | normal cutoff 25%, overdue cutoff 85%, overdue after 3 days, maximum wait 60 minutes |

The existing snapshots were created by the direct Restic predecessor workflow before the committed `backup_module` implementation existed. `backup_module` is the behavioral successor and compatibility baseline, not the historical creator.

## Non-Negotiable Safety Rules

1. Do not run retention or prune automatically during migration.
2. Do not run repository-wide unfiltered `forget --prune` on a mixed repository.
3. Do not silently rewrite production configuration.
4. Do not count a dry run as a successful backup.
5. Do not count a scheduler process launch as a successful backup.
6. Do not count a CPU-gated skip as a successful backup.
7. Do not modify the production repository during unit or integration tests.
8. Do not run `unlock` as a generic connectivity test.
9. Do not treat every `restic init` failure as an already-initialized repository.
10. Do not use PID files as locks unless process identity and staleness are validated.
11. Do not remove or rename the `backup_module`, `rrb`, or `rrbackup` public command surfaces during the compatibility period.
12. Do not allow `--print-command` or equivalent preview modes to execute a backup.

## Canonical Package Layout

```text
modules/rrbackup/
  pyproject.toml
  rrbackup/
    __init__.py
    __main__.py
    cli.py
    config.py
    legacy_config.py
    models.py
    restic.py
    runner.py
    policy.py
    locking.py
    state.py
    restore.py
    retention.py
    viewer.py
    alerts.py
    setup.py
    scheduler/
      __init__.py
      base.py
      windows.py
      systemd.py
      cron.py
  backup_module/
    __init__.py
    __main__.py
    cli.py
  tests/
    cli_test.py
    config_test.py
    legacy_config_test.py
    restic_test.py
    runner_test.py
    policy_test.py
    locking_test.py
    state_test.py
    restore_test.py
    retention_test.py
    viewer_test.py
    alerts_test.py
    scheduler_windows_test.py
    scheduler_systemd_test.py
    scheduler_cron_test.py
    integration_test.py
```

The old independent `modules/backup_module` engine is retained only until the compatibility package has been proven. Its implementation is then removed or reduced to a documented redirect without deleting the public command.

## Behavioral Sources of Truth

### Preserve from `backup_module`

- Production repository defaults
- Source-list and exclude-list files
- `--files-from-verbatim`
- `--iexclude-file`
- `--use-fs-snapshot`
- `--exclude-caches`
- CPU gating and overdue thresholds
- Atomic status-file writes
- Real process locking concept
- Snapshot listing, search, and restore workflows
- Explicit schedule create/list/delete/run command surface
- Legacy JSON configuration support

### Preserve from `rrbackup`

- Canonical package and command names
- TOML configuration
- Named backup sets
- Local and remote repository definitions
- Rclone-assisted repository support
- Config editing commands
- Restic `check` and `stats` command concepts
- Cross-platform scheduling abstractions
- Schedule and retention models where they reflect implemented behavior

### Rewrite Rather Than Merge Blindly

- Restic subprocess execution
- Lock ownership and stale-lock recovery
- State and run-record model
- Scheduler implementation
- Repository setup and initialization
- Connectivity and credential checks
- Retention and pruning
- Setup wizard
- Viewer and alerting
- Tests and production-readiness documentation

## Configuration Model

TOML becomes the canonical long-term configuration format. Existing JSON and built-in `backup_module` defaults remain readable.

Configuration precedence:

1. Explicit CLI option
2. Explicit environment variable
3. Explicit config path
4. Canonical user config
5. Imported legacy JSON config
6. Legacy built-in defaults

The merged CLI must expose the effective source of every resolved field.

### Required Commands

```text
rrb config show
rrb config path
rrb config validate
rrb config init
rrb config import-legacy
rrb config set
rrb config unset
rrb config add-set
rrb config remove-set
rrb config enable-set
rrb config disable-set
rrb config list-sets
```

All mutating commands support `--dry-run` or a preview by default where practical, plus explicit application.

## Backup Runner

### Run States

- `queued`
- `waiting`
- `skipped`
- `running`
- `success`
- `failure`
- `interrupted`
- `dry-run`

### Required Run Record

Each run record must include:

- Run ID
- Profile and backup-set name
- Invocation source: interactive, scheduler, compatibility CLI, or API
- Start and end timestamps
- Host and user
- Resolved repository
- Resolved source and exclusion inputs
- Restic executable and version
- Command fingerprint with secrets excluded
- CPU policy decision and samples
- Lock identity
- Exit code
- Snapshot ID when created
- Snapshot timestamp
- Files new, changed, and unmodified
- Bytes processed
- Packed bytes added
- Error summary
- Scheduler correlation ID when applicable

The last successful snapshot must be derived from Restic when possible. Local state is supplemental and must not replace repository truth.

## Locking

The lock record must contain:

- PID
- Process creation time
- Executable path
- Command identity
- Host
- Acquisition timestamp
- Profile and set name

A lock is stale only when the process identity no longer matches. PID existence alone is insufficient because PIDs are reused.

The implementation must avoid holding an exclusive backup lock during a long CPU-wait period unless doing so is an explicit policy. A separate lightweight scheduling or reservation lock may be used to prevent duplicate queued runs.

## Preview and Dry-Run Semantics

### `--print-command-only`

- Validate configuration
- Resolve the full Restic command
- Redact secrets
- Print the command
- Acquire no backup lock
- Perform no CPU sampling
- Write no status or log file
- Run no Restic process
- Return zero when validation succeeds

### `--dry-run`

- Execute Restic with `--dry-run`
- Record state as `dry-run`
- Never update last-success timestamps
- Never satisfy freshness or scheduler-health checks
- Never send a success notification that implies a snapshot exists

## Scheduler Management

### Required Commands

```text
rrb schedule create
rrb schedule show
rrb schedule list
rrb schedule update
rrb schedule enable
rrb schedule disable
rrb schedule delete
rrb schedule run
rrb schedule health
rrb schedule export
rrb schedule import
```

### Windows Task Scheduler Requirements

- Preserve the existing task name `BackupModuleLocalBackup` during initial migration unless explicitly changed
- Store an explicit action with absolute executable and config paths
- Start when available after a missed trigger
- Optional wake-to-run
- No overlapping executions
- Retry policy
- Appropriate execution time limit for multi-terabyte initial backups
- Visible last result and next run
- Export existing task XML before replacement
- Use the current principal unless explicitly changed
- Distinguish task launch success from backup success

### Cross-Platform Requirements

- Windows Task Scheduler
- systemd user timers where available
- cron only as a compatibility fallback
- Robust quoting of executables, paths, profiles, and config files
- Schedule parser that rejects unsupported free-form values instead of silently converting them

## Retention

Retention is opt-in and disabled by default during migration.

Every snapshot created by the merged package receives stable ownership tags:

```text
rrbackup:profile:<profile>
rrbackup:set:<set-name>
```

Existing legacy snapshots tagged only `local-main` remain unmanaged until explicitly adopted.

Required commands:

```text
rrb retention show
rrb retention preview
rrb retention apply
rrb retention adopt-legacy
```

`preview` is the default behavior. `apply` requires explicit confirmation or `--yes`. Retention must scope by stable tags or a deliberate Restic grouping policy. Repository-wide unfiltered pruning is prohibited.

## Viewer

The viewer is a first-class reporting and diagnostic subsystem, not only a formatted alias for `restic snapshots`.

### Required Commands

```text
rrb viewer
rrb viewer timeline
rrb viewer snapshots
rrb viewer sets
rrb viewer schedules
rrb viewer health
rrb viewer runs
rrb viewer gaps
rrb viewer storage
rrb viewer details <snapshot-or-run-id>
rrb viewer export
```

`rrb view` may be provided as an alias.

### Default Viewer Output

The default view should provide a compact dashboard containing:

- Overall health
- Profiles and backup sets
- Repository availability
- Latest successful snapshot per set
- Snapshot age
- Expected interval
- Missed-backup count
- Current overdue duration
- Last runner result
- Last scheduler result
- Next scheduled run
- Active or stale locks
- Recent data added
- Repository check age
- Alert status

### Timeline View

The timeline should resemble a detailed Git history while remaining readable in a terminal.

Example shape:

```text
● 2026-07-29 03:00  local-main  MISSED       expected scheduled run
│
○ 2026-07-28 03:00  local-main  MISSED       machine unavailable or task absent
│
● 2026-04-14 21:41  local-main  SUCCESS      022aad5b
│  duration 11m36s · +20,378 files · 12,111 changed · +7.34 GB packed
│  paths C:\, D:\Pictures, D:\Torrents\Movies, D:\Torrents\TV, D:\Torrents\anime
│
● 2026-04-11 22:09  local-main  SUCCESS      a1609113
   duration 37h49m55s · initial snapshot · 11.171 TiB logical
```

The exact glyphs must degrade cleanly when Unicode or color is unavailable.

### Viewer Data Sources

The viewer correlates:

1. Restic snapshot metadata and summaries
2. Local run records
3. Scheduler definitions and execution history
4. Current configuration
5. Repository check and stats results
6. Alert records

It must indicate the provenance and freshness of each data source. Unknown information is displayed as unknown, not inferred as success.

### Missed-Backup Detection

Missed-backup detection must use explicit schedule expectations, not merely a fixed global age threshold.

For each enabled backup set:

- Calculate expected trigger times in the profile timezone
- Apply configured grace period
- Account for disabled schedules and maintenance windows
- Correlate scheduler executions with run records and snapshots
- Count expected runs with no successful snapshot
- Distinguish missed, skipped, failed, running, and unknown
- Detect a scheduler that ran successfully but produced no snapshot
- Detect a snapshot created manually outside the schedule

### Viewer Formats

- Human-readable terminal dashboard
- Detailed terminal timeline
- `--json`
- `--json-lines`
- `--csv` for snapshot and run tables
- `--markdown` for reports
- `--no-color`
- `--ascii`
- `--since`, `--until`, `--limit`
- Filters for profile, set, host, tag, state, and repository

Interactive TUI behavior may be added later, but the initial viewer must remain fully usable in non-interactive shells and scheduled reports.

## Alerting

Alerting runs independently from backup execution and is based on verified state.

### Alert Conditions

- Backup overdue beyond grace period
- One or more expected runs missed
- Consecutive failures
- Scheduler disabled or absent
- Scheduler result indicates launch failure
- Scheduler launched but no matching run record exists
- Runner succeeded but no snapshot was created
- Repository unavailable
- Repository check failed or too old
- Stale lock
- Credential or password file unavailable
- Source or exclusion file unavailable
- Restore verification overdue

### Alert Destinations

Initial implementation:

- Terminal and structured exit codes
- Windows notification/toast where practical
- Email through a configurable SMTP transport or external command
- Generic webhook
- Append-only alert log

Later extensions may include ntfy, Pushover, Discord, Slack, or other transports, but the core must not depend on a vendor-specific service.

### Alert Deduplication

Alerts need stable fingerprints and state transitions:

- Open
- Acknowledged
- Resolved
- Reopened

Repeated checks must not generate uncontrolled duplicate notifications. Escalation intervals are configurable.

### Required Commands

```text
rrb alert check
rrb alert test
rrb alert list
rrb alert acknowledge
rrb alert resolve
rrb alert configure
```

`rrb alert check` returns a nonzero exit code when actionable health conditions exist, allowing Task Scheduler or external monitoring to detect failure.

## Setup Workflow

Setup must be decomposed into explicit, independently testable actions rather than one destructive wizard.

```text
rrb setup inspect
rrb setup validate
rrb setup repository
rrb setup credentials
rrb setup profile
rrb setup schedule
rrb setup alerts
rrb setup verify
```

An optional guided wizard may orchestrate these commands, but each action must show a plan and require confirmation before modifying repositories, credentials, schedules, or configuration.

`setup inspect` should discover the current production values and offer to import them without executing a backup.

## Compatibility CLI

The `backup_module` command remains functional and delegates to the shared engine.

Preserve existing command names and underscore-style long options as aliases. Add canonical hyphenated options without immediately removing legacy forms.

Compatibility behavior must include:

- `backup_module backup`
- `backup_module ls`
- `backup_module search`
- `backup_module restore`
- `backup_module status`
- `backup_module defaults`
- `backup_module schedule`

Deprecation messages must not break JSON output or scripts.

## Test Strategy

### Unit Tests

Cover:

- Configuration precedence
- TOML parsing
- Legacy JSON import
- Built-in production defaults
- Command generation
- Preview and dry-run semantics
- CPU policy
- Lock acquisition and stale-lock recovery
- Status transitions
- Interruption recovery
- Snapshot summary parsing
- Viewer correlation
- Missed-run calculations
- Retention scoping
- Alert deduplication
- Scheduler command and definition generation

### Temporary Repository Integration Tests

Create a new temporary Restic repository and verify:

- Initialization
- Initial backup
- Incremental backup
- Snapshot ID capture
- List and timeline output
- Search
- Restore into a safe temporary target
- Content/hash verification
- Check
- Stats
- Scoped retention preview
- Scoped retention application
- Dry-run creates no snapshot
- Print-command-only launches no process
- Failed backup records failure
- Interrupted backup reconciles state

### Production Read-Only Tests

Against `B:\ResticRepos\PC-Local`:

- Open with existing password file
- List exactly the known historical snapshots before any write
- Confirm IDs `a1609113` and `022aad5b`
- Confirm tag `local-main`
- Confirm source paths
- Read snapshot summaries
- Run ordinary `check` only when explicitly requested
- Run stats only when explicitly requested

No production backup, forget, prune, unlock, init, migration, or restore is allowed in automated tests.

### Controlled Production Acceptance

After all temporary-repository tests pass:

1. Export current scheduler state.
2. Print the resolved command without running it.
3. Confirm effective configuration.
4. Run one controlled real backup.
5. Confirm a new snapshot ID is captured.
6. Confirm viewer timeline and health become current.
7. Restore a small known sample to a new timestamped target.
8. Verify restored content hashes.
9. Install the schedule.
10. Trigger one manual scheduled execution.
11. Confirm task result, run result, and snapshot result correlate.
12. Enable alerts only after baseline health is correct.

## Implementation Phases

### Phase 1: Safety Foundation

- Introduce shared models, Restic command runner, configuration resolver, lock manager, and state store
- Add tests before redirecting either public CLI
- Fix dry-run, skipped-success, stale-running, and setup error-classification defects

### Phase 2: Compatibility Merge

- Move `backup_module` behavior into the shared engine
- Add compatibility package and command aliases
- Preserve production defaults
- Add TOML profile representing `local-main`

### Phase 3: Scheduler Redesign

- Add schedule CRUD and health APIs
- Implement Windows Task Scheduler first
- Add systemd and cron adapters
- Export before replacement

### Phase 4: Viewer

- Implement snapshot and run data models
- Implement correlation and missed-run engine
- Add terminal dashboard and timeline
- Add JSON and Markdown export

### Phase 5: Alerting

- Implement health evaluator
- Add alert persistence and deduplication
- Add terminal, webhook, and Windows notification transports
- Add schedule-friendly exit codes

### Phase 6: Retention

- Add ownership tags to new snapshots
- Implement scoped preview
- Add explicit legacy adoption
- Enable application only after production backup and restore verification

### Phase 7: Cleanup

- Remove duplicate implementation code
- Remove committed test-output artifacts
- Correct documentation claims
- Remove or quarantine secret-like files and rotate credentials if they are real
- Keep compatibility shims for the documented period

## Definition of Done

The consolidation is complete only when:

- One engine powers all three public commands
- Existing snapshots remain readable
- A controlled production backup succeeds
- A verified small restore succeeds
- The scheduler produces and records a snapshot
- The viewer accurately reports historical snapshots, the long missed-backup gap, current health, and next run
- Alerts detect a deliberately simulated missed or failed backup without duplicate spam
- Dry runs and previews cannot update success state
- Retention cannot affect snapshots outside its explicit ownership scope
- The full automated test suite passes on Windows
- Cross-platform unit tests pass for non-Windows adapters
