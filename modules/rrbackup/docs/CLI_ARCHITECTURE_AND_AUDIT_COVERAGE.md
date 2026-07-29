# Merged Backup CLI Architecture and Audit Coverage

## Objective

The merged module must expose every useful backup-management and diagnostic capability through one discoverable hierarchical CLI. Routine administration, provenance analysis, schedule diagnosis, repository inspection, and missed-backup investigation must not require ad hoc PowerShell, Bash, registry, service, scheduler, or Restic command sequences.

The canonical command is:

```text
backup
```

The existing commands remain supported during the compatibility period:

```text
rrb
rrbackup
backup_module
python -m backup_module
```

`backup`, `rrb`, and `rrbackup` use the new hierarchical interface. `backup_module` preserves its historical flat commands and options as a compatibility adapter over the same engine.

Adding the `backup` entry point is an intentional public-interface addition. The package version must follow the repository's major-version rule for entry-point changes.

## Major Command Areas

The public CLI has six major command areas.

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` is an alias for `backup config`.

The root help page must explain the six areas, global options, configuration precedence, safety model, examples, and compatibility commands:

```text
backup --help
backup -h
```

Every major command and every nested operation has independent `-h` and `--help` output.

## 1. `backup run`

Execute or preview a configured backup set.

Representative interface:

```text
backup run <set>
backup run <set> --print-command-only
backup run <set> --dry-run
backup run <set> --force
backup run <set> --ignore-cpu-policy
backup run <set> --tag <tag>
backup run <set> --exclude <pattern>
backup run <set> --restic-arg=<argument>
```

Responsibilities:

- resolve effective configuration and record each field's source,
- validate repository, credential, source, and exclusion inputs,
- apply CPU and overdue policy,
- prevent overlapping runs,
- invoke Restic through the shared command boundary,
- capture the resulting snapshot ID and summary,
- write atomic structured run records,
- distinguish success, failure, skip, interruption, preview, and dry run,
- correlate scheduled invocations with resulting snapshots.

`--print-command-only` must not acquire a backup lock, sample CPU, write state, create logs, or launch Restic.

## 2. `backup view`

Provide all human-readable and machine-readable backup information.

Default:

```text
backup view
```

The default command displays the health dashboard.

Nested operations:

```text
backup view dashboard
backup view timeline
backup view snapshots
backup view snapshot <snapshot-id>
backup view files <snapshot-id>
backup view search <pattern>
backup view runs
backup view run <run-id>
backup view logs
backup view storage
backup view gaps
backup view health
backup view schedules
backup view setup
backup view system
backup view provenance
backup view alerts
backup view audit
backup view export
```

### `backup view audit`

`backup view audit` is the first-class replacement for the one-off PowerShell audits used during consolidation. It must collect all available evidence in one read-only operation and state when a data source is unavailable.

Default audit sections:

1. CLI and executable resolution
2. Runtime and package versions
3. Effective configuration and value provenance
4. Relevant environment variables and their scope
5. Entry-point and wrapper targets
6. Canonical and discovered configuration files
7. Repository, credential, source, exclusion, status, log, and lock paths
8. Safe metadata for those paths: existence, type, size, creation time, and modification time
9. Resolved source and exclusion entries
10. Repository availability and format/version information
11. Repository keys, with secret material excluded
12. Snapshot count and recent snapshot metadata
13. Snapshot tags, hosts, users, paths, parents, and Restic versions
14. Local run records and status files
15. Recent module logs
16. Active and stale locks
17. Configured schedules and scheduler implementation
18. Scheduler actions, arguments, working directory, principal, triggers, settings, last result, next run, and missed-run count
19. Scheduler event history when available
20. Other launch mechanisms: services, startup commands, cron, systemd timers, and platform equivalents
21. Missed-backup and provenance conclusions
22. Warnings and recommended next actions

Output modes:

```text
backup view audit --json
backup view audit --markdown
backup view audit --section <name>
backup view audit --include-legacy-evidence
backup view audit --redact-paths
```

The default audit must never reveal password contents, environment-secret values, repository keys, tokens, or other credential material.

`--include-legacy-evidence` may explicitly search platform shell history for historical backup commands when supported. Shell-history inspection is opt-in because it can expose unrelated private command text. Future provenance must come from module run records, not shell-history scraping.

## 3. `backup config` / `backup edit`

Create, discover, import, inspect, validate, and modify configuration.

Nested operations:

```text
backup config show
backup config effective
backup config path
backup config validate
backup config init
backup config discover
backup config import-legacy
backup config set
backup config unset
backup config profiles
backup config sets
backup config credentials
backup config retention
backup config alerts
backup config export
```

`backup edit` is an alias for this command group.

Required diagnostic behavior:

- show the source of every effective field,
- inspect process, user, and machine environment-variable sources where supported,
- discover configs in canonical and legacy locations,
- find the existing direct-Restic/`backup_module` artifacts,
- report missing or unreadable files without exposing password contents,
- show source and exclusion file entries,
- validate unsupported or ignored fields instead of silently accepting them,
- import legacy JSON or built-in defaults into TOML only after preview and confirmation.

## 4. `backup schedule`

Manage and diagnose backup schedules.

Nested operations:

```text
backup schedule list
backup schedule show <name>
backup schedule create
backup schedule update <name>
backup schedule enable <name>
backup schedule disable <name>
backup schedule delete <name>
backup schedule run <name>
backup schedule health
backup schedule history
backup schedule discover
backup schedule export <name>
backup schedule import
```

The schedule interface must expose the information previously obtained through `Get-ScheduledTask`, `Get-ScheduledTaskInfo`, Task Scheduler event logs, systemd, cron, startup-command, and service inspection.

Schedule detail must include:

- backend and identifier,
- enabled/state status,
- executable, arguments, and working directory,
- user/principal and privilege level,
- triggers and timezone,
- last run, next run, last scheduler result, and missed triggers,
- retry policy,
- wake/start-when-available behavior,
- multiple-instance/no-overlap behavior,
- execution time limit,
- correlation with module run records and snapshots.

A scheduler launch result must never be presented as backup success unless a matching successful run and snapshot exist.

## 5. `backup restore`

Find, preview, restore, and verify backup data.

Nested operations:

```text
backup restore search <pattern>
backup restore preview <snapshot-id>
backup restore run <snapshot-id>
backup restore verify <restore-id>
backup restore history
```

Responsibilities:

- search snapshots by name, path, host, tag, set, and date,
- convert Windows and Unix paths correctly,
- default to a new safe restore target,
- print a complete restore plan before execution,
- avoid overwriting original files by default,
- record restore operations,
- support content/hash verification.

Read-only search and file inspection may also be reached through `backup view search` and `backup view files`.

## 6. `backup repository`

Inspect and maintain Restic repositories with explicit safety boundaries.

Nested operations:

```text
backup repository status
backup repository init
backup repository check
backup repository stats
backup repository keys
backup repository locks
backup repository cache
backup repository retention
backup repository adopt-legacy
```

Representative detailed operations:

```text
backup repository check --read-data
backup repository stats --mode restore-size
backup repository cache status
backup repository cache cleanup --apply
backup repository retention show
backup repository retention preview
backup repository retention apply --yes
backup repository locks list
backup repository locks remove-stale --apply
```

Safety requirements:

- read-only is the default where practical,
- setup and connectivity checks must classify errors accurately,
- `unlock` is not a generic connectivity check,
- retention preview is mandatory before application,
- legacy snapshots remain unmanaged until explicitly adopted,
- retention is scoped by stable ownership tags,
- repository-wide unfiltered prune is prohibited,
- cache cleanup, stale-lock removal, init, retention application, and other mutation require explicit action.

## Alert Placement

Alert state is part of the viewer and health model rather than a seventh major area.

```text
backup view alerts
backup view health
backup config alerts
backup schedule create --health-check
```

`backup view health --notify` may evaluate and deliver configured alerts. The implementation must also expose a non-interactive health command and stable exit codes suitable for schedulers and external monitoring.

Alert conditions include:

- backup overdue,
- expected run missed,
- consecutive failures,
- scheduler absent or disabled,
- scheduler launch failure,
- scheduler launch with no matching run,
- successful wrapper exit with no snapshot,
- repository unavailable,
- repository check failed or stale,
- stale lock,
- missing credential/source/exclusion files,
- restore verification overdue.

## Mapping of Consolidation Audit Commands

| Previously required shell operation | Merged CLI capability |
|---|---|
| Resolve `restic`, Python, `rrb`, `rrbackup`, and `backup_module` executables | `backup view system` and `backup view audit` |
| Inspect process/user/machine backup environment variables | `backup config effective` and `backup view audit` |
| Read generated `.cmd` wrappers and resolve their targets | `backup view system --entry-points` |
| Check known repository/config/source/exclude/status/log/lock paths | `backup view setup` |
| List source and exclusion entries | `backup config show --include-input-files` |
| Search for relocated configuration artifacts | `backup config discover` |
| Query snapshots directly with Restic JSON | `backup view snapshots --json` |
| Inspect snapshot paths, tags, host, user, parent, and Restic version | `backup view snapshot <id>` and `backup view timeline` |
| Inspect shell history to infer legacy provenance | `backup view audit --include-legacy-evidence` |
| Search all scheduled-task names and actions | `backup schedule discover` |
| Display task action, principal, triggers, settings, last/next run, and result | `backup schedule show <name>` |
| Search Task Scheduler event history | `backup schedule history` |
| Search startup commands and Windows services | `backup schedule discover --all-launchers` |
| Inspect systemd timers and cron entries | `backup schedule discover --all-launchers` |
| Read local status and recent logs | `backup view runs`, `backup view logs`, and `backup view audit` |
| Inspect active or stale locks | `backup repository locks` and `backup view health` |
| Run `restic key list` safely | `backup repository keys` |
| Run repository stats | `backup repository stats` and `backup view storage` |
| Run repository check | `backup repository check` |
| Inspect and clean Restic cache | `backup repository cache status/cleanup` |
| Determine whether backups are overdue or missing | `backup view health`, `backup view gaps`, and `backup view timeline` |
| Produce one complete diagnostic artifact | `backup view audit --markdown` or `--json` |

## Global Output and Filtering Options

All information-producing operations should support consistent output conventions where applicable:

```text
--json
--json-lines
--csv
--markdown
--quiet
--verbose
--no-color
--ascii
--since
--until
--limit
--profile
--set
--repository
--host
--tag
--state
```

Every global option must have a short form unless a documented compatibility or ambiguity exception is approved.

## Help and Discoverability Acceptance Tests

The automated suite must verify:

1. `backup -h` and `backup --help` return success and list all six major areas.
2. Every major command supports `-h` and `--help`.
3. Every nested operation supports independent help.
4. All public options have short and long forms.
5. `backup edit` resolves to `backup config`.
6. `rrb` and `rrbackup` expose the same hierarchical command tree.
7. Historical `backup_module` commands and underscore-style options remain functional through the compatibility adapter.
8. Help output distinguishes read-only, preview, dry-run, and mutating operations.
9. JSON-producing commands emit no deprecation or progress text on stdout.
10. Unsupported free-form schedules and ignored configuration fields fail validation rather than silently changing behavior.
