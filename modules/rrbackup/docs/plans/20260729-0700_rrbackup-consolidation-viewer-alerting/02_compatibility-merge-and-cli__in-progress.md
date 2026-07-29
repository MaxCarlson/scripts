# Stage 2 — Unified Backup CLI, Inventory, and Terminal UI

## Status

In progress. Automated validation proved the safety engine and most of the first CLI slice, but manual acceptance identified an over-fragmented command tree, raw JSON as the default human interface, unrelated scheduler matches, and an unexpectedly expensive storage command. This stage is being corrected around task-oriented dashboards and wizards before the old backup module is removed.

## Checkpoint Cadence

Stage 2 is intentionally divided into bounded validation checkpoints rather than implemented as one large batch.

Each checkpoint should:

- contain one closely related feature or correction group,
- be large enough to justify roughly 10–20 minutes between local pull/test/push cycles,
- include its own source changes, tests, documentation update, static review, and manual-test list,
- stop for local validation before the next checkpoint begins,
- avoid stacking multiple unverified subsystems,
- make failures attributable to a small set of recent changes.

Remote implementation must not continue into the next checkpoint after publishing a validation-ready checkpoint. The next checkpoint begins only after the latest automated and manual results are reviewed.

## Stage 2 Checkpoint Sequence

### Checkpoint 2A — Single-CLI UX Foundation — Current

Scope:

- install only the `backup` console command,
- expose the seven task-oriented root areas,
- unify canonical TOML sets and legacy `local-main` in one backup inventory,
- provide concise colored human renderers and plain/JSON/Markdown alternatives,
- condense `backup view` into six sections,
- make `backup run` select configured backups by name or chooser,
- make `backup schedule` display configured backups rather than arbitrary OS tasks,
- restrict scheduler discovery to module-owned tasks,
- combine repository status into one human summary,
- ensure slow restore-size statistics run only through explicit refresh,
- add tests for parser, inventory, presentation, scheduler filtering, repository caching, and preview safety.

Out of scope for Checkpoint 2A:

- applying scheduler mutations,
- writing production configuration through the create wizard,
- retention execution,
- removing the old `backup_module` engine,
- cross-platform scheduler CRUD completion.

Wizard and scheduler-apply code may exist as unaccepted scaffolding, but local acceptance for this checkpoint is preview/read-only only.

### Checkpoint 2B — Create and Schedule Wizard Preview

Scope:

- interactive create wizard,
- interactive schedule editor,
- multi-backup selection,
- minute/hour/day/week/month/year inputs,
- retention inputs,
- complete proposed configuration and scheduler preview,
- no production writes unless a later apply checkpoint is explicitly entered.

### Checkpoint 2C — Configuration and Scheduler Apply

Scope:

- atomic canonical configuration writes,
- Windows Task Scheduler create/update/delete/run/export/import,
- explicit confirmation and `--apply` gates,
- rollback/export-before-replacement behavior,
- isolated temporary and controlled local acceptance.

### Checkpoint 2D — Compatibility Shim and Duplicate-Engine Removal

Scope:

- preserve required historical `backup_module` commands through the shared engine,
- replace `modules/backup_module` internals with a thin adapter,
- remove duplicate engine code only after compatibility tests pass.

### Checkpoint 2E — Production Read-Only and Controlled Acceptance

Scope:

- canonical production snapshot verification,
- manual TUI acceptance,
- controlled backup and restore verification only after explicit approval,
- final Stage 2 documentation and handoff.

## Progress Assessment

### Accomplished

- The shared safety engine is verified on Windows.
- The installed `backup` command works.
- Snapshot, timeline, health, provenance, repository, scheduler-discovery, and audit data sources work against the existing production repository.
- The two known production snapshots are visible with correct tags, paths, host, user, parent, version, and summary metadata.
- 256 tests passed in the latest Stage 2 run.
- Installed-entry-point smoke tests passed.

### Not Yet Accomplished

- Human output is not consistently formatted or color-coded in a locally verified build.
- The condensed `backup view` UX has not passed local acceptance.
- Strict scheduler filtering has not passed local validation.
- The configured-backup run chooser has not passed local validation.
- Repository summary and explicit storage refresh have not passed local validation.
- Create and schedule-edit wizards have not passed preview-only acceptance.
- Two inherited integration tests still assert obsolete `rrb` help text in the last pushed report.
- The old `backup_module` implementation has not yet been reduced to a shim.

### Stall/Loop Check

Measurable progress occurred. The current work is not repeating Stage 1; it is a bounded UX and command-model correction driven by successful manual use of the new data layer. Checkpoint 2A must now be validated before any further Stage 2 feature implementation.

## Canonical Command

Only one public executable is required:

```text
backup
```

The internal Python package may retain the `rrbackup` name during consolidation, but the `rrb` and `rrbackup` console entry points are removed with explicit user approval.

## Root Command Areas

```text
backup create
backup run
backup view
backup schedule
backup restore
backup repo
backup config
```

`repo` replaces `repository` as the public spelling.

## Task-Oriented UX

### `backup view`

`backup view` is one interactive dashboard rather than a list of mostly independent display commands.

Primary sections inside the dashboard:

1. Overview
2. Backups
3. History
4. Repository
5. Schedules
6. Diagnostics

The default TTY experience uses the shared `termdash.interactive_list.InteractiveList` component and supports:

- Up/Down and `j`/`k`
- Page Up/Page Down
- horizontal scrolling
- filtering
- Enter for details
- expandable/collapsible detail blocks
- compact one- or two-line rows
- consistent status colors

Non-interactive and automation access remains available through flags:

```text
backup view --section overview
backup view --section history
backup view --section diagnostics
backup view --section audit --json
backup view --plain
```

Legacy display-specific operations may remain as hidden translation aliases during development, but they are removed from normal help.

### `backup run`

```text
backup run
backup run auto
backup run <backup-name>
```

With no name or with `auto`, display the configured backup inventory with:

- backup name
- source summary
- repository
- health
- last successful snapshot
- schedule
- next expected run
- missed-run count

Interactive selection allows an early run without requiring the user to know source files, tags, excludes, or repository arguments. Direct named execution remains available for scripts.

### `backup schedule`

The default view is backup-centric, not a raw Task Scheduler query. One compact record is shown per configured backup, with schedule details directly below it.

```text
backup schedule
backup schedule wizard
backup schedule edit <backup-name>
backup schedule list --plain
```

The wizard supports selecting one or more backups and editing:

- minute/hour/day/week/month/year frequency
- interval
- time of day
- weekday/day of month/month of year where applicable
- retention counts for latest/hourly/daily/weekly/monthly/yearly snapshots

Scheduler discovery must include only tasks owned by this backup module or whose executable/arguments invoke the canonical `backup` command. Generic Windows tasks containing the word `Backup` are excluded.

### `backup repo`

`backup repo` displays one combined, labeled repository summary:

- repository availability and format
- current key metadata
- active/stale locks
- snapshot count
- latest snapshot logical size
- last known integrity-check state
- cached full storage statistics, when available

The slow `restic stats --mode restore-size` operation is never run implicitly. It requires an explicit refresh operation and a loading indicator:

```text
backup repo --refresh-storage
backup repo check
```

JSON remains available only when explicitly requested.

### `backup create`

A themed setup wizard creates a complete backup definition by walking through:

1. name
2. source paths
3. exclusions
4. repository target
5. credential method
6. schedule
7. retention
8. preview
9. explicit save/apply

The wizard uses the same palette, table layout, confirmation style, and keyboard conventions as `view`, `run`, and `schedule`.

## Shared UI Rules

- Green: healthy/success/enabled
- Yellow: warning/due/manual/preview
- Red: failure/critical/missed/disabled
- Cyan: headings, identifiers, and selected values
- Dim: secondary metadata
- Magenta: active interactive mode or automatic selection

Plain text, JSON, and Markdown outputs never contain ANSI escape sequences.

## Automated Test Requirements

- Only the `backup` console entry point is installed.
- Root help lists the seven task-oriented areas.
- `view` help is concise and does not expose the old long display-command list.
- Human renderers are snapshot-tested without ANSI.
- Color policy is tested independently from terminal capability.
- TUI formatters, detail blocks, sorting, filtering, and selection callbacks are unit tested without launching curses.
- Inventory combines canonical TOML sets and the legacy `local-main` profile.
- Schedule discovery rejects unrelated operating-system backup tasks.
- Schedule calculations cover minute/hour/day/week/month/year and missed-run counts.
- Slow repository statistics are never invoked by default views.
- JSON stdout remains machine-clean.
- Existing safety, engine, snapshot, repository, and audit tests continue passing.

## Remaining Compatibility Work

- Convert canonical TOML backup sets into shared engine profiles.
- Preserve needed `backup_module` behavior through `backup` commands.
- Replace `modules/backup_module` internals with a thin import/translation shim.
- Remove duplicate engines after local and manual acceptance.

## Safety Boundaries

- Default views and wizards do not mutate production state.
- Wizards show a complete preview before writing configuration or scheduler state.
- Scheduler creation/update requires explicit confirmation or `--apply`.
- `backup run --print-command-only` launches no process and writes no state.
- Slow repository operations are explicit.
- Retention application remains disabled until ownership scoping is verified.
- Production mutation remains prohibited during automated validation.

## Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

Manual acceptance after Checkpoint 2A must cover:

1. root and nested help simplification,
2. visual hierarchy and color consistency,
3. TUI navigation and resize behavior,
4. backup inventory and preview-only selection,
5. backup-centric schedule readability,
6. repository summary readability,
7. proof that default repository view does not run full storage statistics.

Wizard apply operations are not part of Checkpoint 2A acceptance.

## Exit Criteria

Stage 2 completes when:

1. `backup` is the only installed public executable,
2. configured backups are represented through one inventory model,
3. view/run/schedule/repo/create use the shared terminal presentation layer,
4. default human output is concise and readable,
5. JSON/Markdown output remains available explicitly,
6. schedule discovery contains only module-owned backup schedules,
7. the old `backup_module` engine is reduced to compatibility-only code,
8. automated and manual Windows validation pass.
