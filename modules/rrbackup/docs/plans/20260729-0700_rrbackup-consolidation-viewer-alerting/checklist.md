# Consolidation Checklist

## Stage 1 — Safety Foundation

- [x] Create canonical plan structure
- [x] Document hybrid remote/local workflow
- [x] Add repository-root validation dispatcher and target manifest
- [x] Add authoritative `LATEST.txt`, context snapshot, progress diff, and bounded history
- [x] Add PowerShell environment smoke and opt-in production read-only tests
- [x] Add canonical profile and source attribution
- [x] Add legacy `backup_module` JSON/default adapter
- [x] Add Restic command boundary and secret redaction
- [x] Add print-command-only hard barrier
- [x] Correct dry-run state semantics
- [x] Add CPU normal/overdue policy
- [x] Ensure CPU waiting precedes lock acquisition
- [x] Add atomic run-state store
- [x] Add process-identity lock and ownership token
- [x] Add stale-lock replacement race protection
- [x] Add snapshot and backup-summary parsers
- [x] Add shared backup execution engine
- [x] Add terminal-state handling for all failure paths
- [x] Add unit and lifecycle regression tests
- [x] Add compile and correctness-lint gates
- [x] Pass local Windows validation: 199 passed, 8 skipped
- [x] Validate `LATEST.*` migration and bounded history
- [x] Mark Stage 1 verified

## Stage 2 — Compatibility Merge and Hierarchical CLI

- [x] Define six-area CLI architecture
- [x] Map useful shell audits to first-class commands
- [x] Define `backup view audit` contract
- [x] Add canonical `backup` entry point
- [x] Bump package to `1.0.0`
- [x] Route `backup`, `rrb`, and `rrbackup` to one canonical application
- [x] Restore repository namespace compatibility shim
- [x] Add actual installed-entry-point smoke checks without injected `PYTHONPATH`
- [x] Clean stale editable metadata before validation install
- [x] Add `backup run`
- [x] Add `backup view` hierarchy and default dashboard
- [x] Add `backup config` hierarchy
- [x] Add `backup edit` alias translation
- [x] Add `backup schedule` read-only discovery hierarchy
- [x] Add `backup restore` search/preview/explicit-run hierarchy
- [x] Add `backup repository` read-only hierarchy and explicit mutation gates
- [x] Preserve common legacy `rrb` commands through translation
- [x] Temporarily delegate legacy setup/prune/config mutation commands
- [x] Preserve underscore-style option aliases for migrated commands
- [x] Add canonical hyphenated options
- [x] Import legacy JSON/default configuration into canonical profile
- [x] Add root and major-area help-contract tests
- [x] Add JSON stdout-purity coverage for print-only behavior
- [x] Add secret-redaction tests
- [x] Add `backup config discover`
- [x] Add executable/runtime/environment diagnostics
- [x] Add known path and input-file discovery
- [x] Add Windows Task Scheduler discovery
- [x] Add repository status/key/stats/check/cache/lock inspection
- [x] Add dashboard, timeline, snapshots, runs, logs, storage, health, setup, system, provenance, schedules, audit, and export views
- [x] Add parser, packaging, health, audit, repository, and scheduler tests
- [ ] Pass expanded Windows validation checkpoint
- [ ] Add TOML and named-set conversion to shared engine
- [ ] Add snapshot tag/host/path filters
- [ ] Implement `--redact-paths`
- [ ] Add optional legacy shell-history evidence adapter
- [ ] Add detailed scheduler event, service, startup, systemd, and cron discovery
- [ ] Add restore history and hash verification
- [ ] Verify known production snapshots through canonical CLI
- [ ] Preserve every historical `backup_module` command through shared engine
- [ ] Reduce `modules/backup_module` to a compatibility shim
- [ ] Remove duplicate engine only after compatibility tests pass

## Stage 3 — Scheduler Management

- [ ] Windows Task Scheduler create/update/delete/run/export/import
- [ ] systemd user timer CRUD
- [ ] cron compatibility CRUD
- [ ] Schedule health and history
- [ ] No-overlap, retry, wake, and start-when-available behavior
- [ ] Scheduler/run/snapshot correlation

## Stage 4 — Viewer Expansion

- [x] Dashboard foundation
- [x] Timeline foundation
- [x] Snapshot listing and details
- [x] Search foundation
- [x] Runs and logs
- [x] Schedules and setup/system diagnostics
- [x] Provenance and comprehensive audit foundation
- [x] Storage and health foundation
- [ ] File browsing inside snapshots
- [ ] Rich set/profile views
- [ ] Expected-run gap engine
- [ ] Detailed missed-backup timeline
- [ ] JSON Lines and CSV output
- [ ] Alert-state view
- [ ] Optional full-screen TUI

## Stage 5 — Alerts

- [ ] Alert persistence and fingerprints
- [ ] Deduplication and acknowledge/resolve/reopen states
- [ ] Stable health exit codes
- [ ] Alert log
- [ ] Generic webhook
- [ ] Windows notification
- [ ] Email/external command
- [ ] Schedule-compatible health check

## Stage 6 — Retention

- [ ] Ownership tags
- [ ] Preview by default
- [ ] Explicit apply confirmation
- [ ] Legacy snapshot adoption
- [ ] Mixed-repository isolation tests

## Stage 7 — Acceptance

- [ ] Temporary repository suite
- [ ] Production read-only suite
- [ ] Controlled production backup
- [ ] Small restore and hash verification
- [ ] Scheduled execution
- [ ] Viewer acceptance
- [ ] Audit-command acceptance
- [ ] Alert acceptance
- [ ] Documentation cleanup
- [ ] Compatibility-period documentation
