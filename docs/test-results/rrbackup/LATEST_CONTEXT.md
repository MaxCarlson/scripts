# Validation Context: rrbackup

Generated: 2026-07-29T09:38:32.0584260-07:00
Branch: agent/merge-restic-backup-modules
Commit: 50bfafb0dc20fba881d5ddff2aa78f865c63d9c7
Validation report: docs\test-results\rrbackup\LATEST.txt

## Validation Highlights

- RESULT: PASS - Clean stale RRBackup editable metadata
- RESULT: PASS - Install RRBackup editable development dependencies
- RESULT: PASS - Compile RRBackup package and tests
- RESULT: PASS - Lint RRBackup safety, CLI, and viewer foundation
- RESULT: PASS - Canonical backup CLI help contract
- ================== 2 failed, 256 passed, 8 skipped in 11.18s ==================
- RESULT: FAIL - RRBackup pytest and coverage suite
- RESULT: PASS - PowerShell test: tests\powershell\environment_smoke_test.ps1
- RESULT: PASS - PowerShell test: tests\powershell\production_read_only_test.ps1
- TARGET RESULT: FAIL
- Failure count: 1

## Working Tree

```text
 M docs/test-results/rrbackup/LATEST.txt
 D docs/test-results/rrbackup/LATEST_CONTEXT.md
 D docs/test-results/rrbackup/LATEST_PROGRESS.diff
?? docs/test-results/rrbackup/history/20260729-090444_rrbackup.txt
?? docs/test-results/rrbackup/history/20260729-090444_rrbackup_context.md
?? docs/test-results/rrbackup/history/20260729-090444_rrbackup_progress.diff
```

## Project Status Sources

### `docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/STATUS.md`

# Status

## Overall

Stage 1 is verified. The latest Windows checkpoint passed package compilation, focused correctness lint, 199 tests, and both PowerShell checks; 8 environment-dependent tests skipped intentionally. The `LATEST.txt`, `LATEST_CONTEXT.md`, `LATEST_PROGRESS.diff`, and bounded-history migration also worked.

Stage 2 is now in progress. The branch adds the canonical `backup` entry point, redirects `rrb` and `rrbackup` to one hierarchical application after installation, introduces the first working viewer/audit/repository/schedule-discovery slice, and preserves selected legacy flat commands through translation or temporary delegation.

A post-validation manual check exposed a real installed-entry-point namespace failure that the old smoke test masked by injecting `PYTHONPATH`. The repository namespace compatibility shim has been restored, version lookup moved to a dedicated module, and validation now executes the actual installed `backup`, `rrb`, and `rrbackup` entry points with the injected path removed.

## Stage 1 — Verified

- [x] Canonical profile and source-attribution model
- [x] Legacy `backup_module` JSON/default adapter
- [x] Production-compatible Restic command builder
- [x] Hard preview/print-only execution barrier
- [x] Distinct dry-run state that never updates last success
- [x] CPU normal/overdue policy with waiting before lock acquisition
- [x] Process-identity lock with ownership token and stale-lock race protection
- [x] Atomic run history, latest-run, and last-success state
- [x] Snapshot and backup-summary JSON parsers
- [x] Shared backup execution engine
- [x] Terminal state for wait, lock, execution, interruption, and finalization failures
- [x] Compile and focused lint gates
- [x] Local Windows verification

### Verified Stage 1 evidence

- 207 tests collected
- 199 passed
- 8 intentionally skipped
- 0 failed
- 0 errors
- package branch coverage: 55%
- compile: passed
- focused correctness lint: passed
- PowerShell environment smoke test: passed
- production read-only test: safely skipped

## Stage 2 — Implemented and Awaiting Validation

- [x] Package version advanced to `1.0.0` for the new entry point
- [x] `backup`, `rrb`, and `rrbackup` entry points target one canonical application
- [x] Root help exposes exactly six major areas
- [x] `backup edit` translates to `backup config`
- [x] Canonical and underscore-style aliases for migrated options
- [x] Legacy `backup`, `list`, `stats`, `check`, and `progress` command translation
- [x] Temporary delegation for legacy setup/prune/config mutation commands
- [x] `backup run` preview, dry-run, CPU-policy bypass, and distinct skipped exit code
- [x] `backup view` dashboard, timeline, snapshots, snapshot details, runs, run details, logs, storage, health, schedules, setup, system, provenance, search, audit, and export
- [x] `backup config` effective, path, validate, discover, import preview, profiles, and sets
- [x] Read-only Windows Task Scheduler discovery adapter
- [x] `backup restore` search, preview, explicit `--apply` run gate, and availability reporting
- [x] `backup repository` status, keys, locks, stats, check, cache status, explicit init gate, and retention preview placeholder
- [x] Comprehensive audit collector with configuration provenance, path metadata, source/exclusion entries, repository metadata, keys, snapshots, runs, logs, locks, schedules, health, provenance, and recommendations
- [x] Secret environment values and password contents excluded from audit output
- [x] Installed-entry-point namespace regression fixed and tested
- [x] Stale editable metadata cleanup added before validation install
- [x] Parser, packaging, health, audit, repository, and scheduler tests added

## Stage 2 Remaining

- [ ] Pass the expanded Windows validation checkpoint
- [ ] Add TOML/named-set conversion to the canonical engine
- [ ] Preserve all historical `backup_module` commands through the shared engine
- [ ] Reduce `modules/backup_module` to a compatibility shim
- [ ] Add snapshot tag/host/path filtering to the canonical viewer
- [ ] Implement path redaction for `backup view audit --redact-paths`
- [ ] Add detailed scheduler event history, service, startup, systemd, and cron discovery
- [ ] Add structured restore history and hash verification
- [ ] Verify known production snapshots through canonical read-only commands
- [ ] Run production read-only validation explicitly

## Canonical CLI

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`. `rrb` and `rrbackup` expose the same hierarchy after editable installation. `backup_module` and `python -m backup_module` remain compatibility surfaces while their independent engine is removed.

The comprehensive read-only diagnostic command is:

```text
backup view audit
```

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known snapshots: `a1609113`, `022aad5b`
- Latest snapshot: 2026-04-14
- Current backup schedule: absent
- Automated production mutation: prohibited

## Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

Authoritative evidence:

```text
docs/test-results/rrbackup/LATEST.txt
docs/test-results/rrbackup/LATEST_CONTEXT.md
docs/test-results/rrbackup/LATEST_PROGRESS.diff
```

### `docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/checklist.md`

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

