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
