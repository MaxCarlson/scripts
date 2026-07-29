# Stage 2 — Compatibility Merge and Hierarchical CLI

## Status

In progress. The first canonical CLI, viewer, audit, repository-inspection, schedule-discovery, and compatibility-translation slice is implemented and awaiting Windows validation.

## Goal

Consolidate `rrbackup` and `backup_module` behind one engine, expose the canonical `backup` command, preserve existing public interfaces, and make routine backup administration and diagnosis possible without ad hoc shell scripts.

## Canonical Areas

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`. Installed `backup`, `rrb`, and `rrbackup` commands target the same application. `backup_module` remains the historical flat compatibility surface until its independent engine is removed.

## Implemented in This Checkpoint

- Package version `1.0.0`
- New `backup` entry point
- Shared hierarchical parser for `backup`, `rrb`, and `rrbackup`
- Root and nested help contracts
- Legacy underscore-style aliases on migrated options
- Translation of common historical RRBackup commands
- Explicit delegation for historical setup/prune/config mutation commands
- `backup run` preview, dry-run, CPU bypass, tags, exclusions, and raw Restic arguments
- Distinct nonzero exit for skipped runs
- Viewer dashboard, timeline, snapshots, snapshot details, runs, logs, storage, health, setup, system, provenance, schedules, audit, search, and export
- Effective configuration, discovery, validation, and legacy-import preview
- Windows Task Scheduler read-only discovery
- Restore search, preview, and explicit `--apply` execution gate
- Repository status, keys, locks, stats, check, cache status, explicit init gate, and retention preview
- Comprehensive structured audit and Markdown export
- Secret environment and password-content redaction
- Repository namespace compatibility shim
- Installed-entry-point tests without injected `PYTHONPATH`
- Stale editable metadata cleanup before package install
- Parser, packaging, health, audit, repository, and scheduler tests

## Entry-Point Regression

The Stage 1 report passed because the smoke test inherited `PYTHONPATH={target_root}`. A manual `rrb -h` then exposed that repository-local imports could resolve `modules/rrbackup` as a namespace package without executing the inner package initializer.

The correction is structural:

- `modules/rrbackup/__init__.py` is an intentional repository-path compatibility shim.
- The shim extends the package path to `modules/rrbackup/rrbackup`.
- Version data lives in `rrbackup/version.py`.
- Validation removes the injected `PYTHONPATH` before importing and running installed entry points.
- Validation invokes the real `backup`, `rrb`, and `rrbackup` executables.

## Remaining Stage 2 Work

- [ ] Pass expanded Windows validation
- [ ] Convert existing RRBackup TOML/named sets to canonical profiles
- [ ] Preserve all `backup_module` commands through the shared engine
- [ ] Replace `modules/backup_module` internals with a compatibility shim
- [ ] Add snapshot tag/host/path filtering
- [ ] Implement audit path redaction
- [ ] Add detailed scheduler event, service, startup, systemd, and cron discovery
- [ ] Add structured restore history and verification
- [ ] Add optional legacy shell-history evidence
- [ ] Verify production snapshots through canonical read-only commands

## Safety Boundaries

- Default viewer/config/schedule/repository inspection is read-only.
- `backup run --print-command-only` launches no process and writes no state.
- Dry runs never update last-success state.
- Skipped runs return a distinct nonzero exit.
- Restore execution requires `restore run --apply`.
- Repository initialization requires `repository init --apply`.
- Retention application, cache cleanup, stale-lock removal, and legacy adoption are not enabled in this stage.
- Production repository mutation remains prohibited during automated validation.

## Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

The expanded target now performs:

1. stale editable-metadata cleanup,
2. editable dependency installation,
3. package/test compilation,
4. focused lint,
5. canonical CLI help execution,
6. full pytest/coverage,
7. installed entry-point smoke tests,
8. production read-only test only when explicitly enabled.

## Exit Criteria

Stage 2 completes when:

1. all four public command surfaces use the shared engine,
2. root and nested help contracts pass,
3. viewer/audit capabilities replace all useful consolidation shell diagnostics,
4. existing production snapshots are visible through canonical read-only commands,
5. the old `backup_module` engine is reduced to compatibility-only code,
6. local Windows validation passes.
