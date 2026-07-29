# Stage 2 — Compatibility Merge and Hierarchical CLI

## Status

Planned. Stage 1 safety primitives and baseline corrections remain the current implementation focus.

## Goal

Consolidate `rrbackup` and `backup_module` behind one engine, introduce the canonical `backup` entry point, preserve existing public interfaces, and establish the six-area hierarchical command model defined in `docs/CLI_ARCHITECTURE_AND_AUDIT_COVERAGE.md`.

## Major Command Areas

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`.

`rrb` and `rrbackup` expose the same hierarchy. `backup_module` remains a compatibility adapter for its historical flat commands and underscore-style options.

## Deliverables

- [ ] Bump the package major version for the new `backup` entry point
- [ ] Add the `backup` console entry point
- [ ] Preserve `rrb` and `rrbackup`
- [ ] Preserve `backup_module` and `python -m backup_module`
- [ ] Build one shared parser/dispatch layer
- [ ] Add root and nested help for all command areas
- [ ] Add `edit` alias for `config`
- [ ] Preserve legacy underscore-style options as aliases
- [ ] Add canonical hyphenated options
- [ ] Import `backup_module` JSON/default behavior into the shared configuration model
- [ ] Reduce the old `modules/backup_module` implementation to a compatibility package after tests pass
- [ ] Add `backup view audit` data model and platform adapters
- [ ] Add `backup config discover`
- [ ] Add `backup schedule discover`, `show`, and `history`
- [ ] Add `backup view system`, `setup`, and `provenance`
- [ ] Add `backup repository status`, `keys`, `locks`, `stats`, `check`, and `cache status`
- [ ] Add machine-readable JSON for every audit section
- [ ] Add redaction and secret-exclusion tests
- [ ] Add CLI hierarchy/help contract tests
- [ ] Add compatibility-command tests

## Shell-Audit Replacement Contract

The merged CLI must make the following one-off shell investigations unnecessary for normal operation:

- executable and wrapper resolution,
- process/user/machine environment inspection,
- known path and metadata inspection,
- source/exclusion file inspection,
- relocated config discovery,
- direct Restic snapshot JSON queries,
- scheduled-task action and settings inspection,
- scheduler event-history inspection,
- startup/service/systemd/cron launcher discovery,
- status/log/lock inspection,
- Restic key, stats, check, and cache inspection,
- missed-backup and provenance determination.

The single comprehensive replacement is:

```text
backup view audit
```

with structured equivalents:

```text
backup view audit --json
backup view audit --markdown
```

Legacy shell-history scanning is opt-in only:

```text
backup view audit --include-legacy-evidence
```

## Test Requirements

- Root help lists exactly the six major command areas plus compatibility information.
- Each major command and nested operation supports `-h` and `--help`.
- `backup`, `rrb`, and `rrbackup` dispatch to the same engine.
- `backup_module` historical commands generate equivalent shared-engine requests.
- JSON stdout contains only JSON.
- Audit output never includes password contents, secret environment values, tokens, or private keys.
- Platform adapters can be unit tested without changing the host process's `os.name`.
- Windows Task Scheduler, systemd, cron, services, and startup discovery are adapter-based and mockable.
- Missing platform APIs are reported as unavailable rather than causing command failure.
- A temporary fixture can reproduce the historical direct-Restic/`backup_module` layout and be fully discovered through `backup config discover` and `backup view audit`.

## Exit Criteria

Stage 2 is complete when:

1. One engine powers all four public command surfaces.
2. The six-area CLI hierarchy and all help-contract tests pass.
3. `backup view audit` replaces every useful diagnostic from the consolidation scripts.
4. Existing production snapshots are visible through the new read-only commands.
5. The old `modules/backup_module` engine no longer contains independent backup logic.
6. Local Windows validation passes through `Invoke-Tests.ps1`.
