# Consolidation Checklist

## Stage 1 — Safety Foundation

- [x] Create canonical plan structure
- [x] Document hybrid remote/local workflow
- [x] Add one-time substantial-task hybrid reminder for local agents
- [x] Add repository-root validation dispatcher
- [x] Add manifest-driven validation targets
- [x] Register RRBackup as the default target
- [x] Bootstrap target development dependencies by default
- [x] Use repository virtual-environment Python
- [x] Isolate target working directory and pytest imports
- [x] Capture complete compile/lint/pytest/PowerShell stdout and stderr
- [x] Run all configured `*_test.ps1` scripts from one command
- [x] Add authoritative `LATEST.txt` per target
- [x] Add `LATEST_CONTEXT.md` and `LATEST_PROGRESS.diff`
- [x] Add bounded validation history
- [x] Add PowerShell environment smoke test
- [x] Add opt-in production read-only test
- [x] Run initial local Windows baseline
- [x] Diagnose shared-environment pytest collision
- [x] Validate repository-root dispatcher on Windows
- [x] Reach a clean inherited baseline: 126 passed, 8 skipped
- [x] Triage inherited baseline failures
- [x] Add canonical profile and source-attribution model
- [x] Add legacy `backup_module` JSON/default adapter
- [x] Add Restic command boundary
- [x] Add print-command-only/preview barrier
- [x] Correct dry-run state semantics
- [x] Add CPU normal/overdue policy
- [x] Ensure CPU waiting occurs before lock acquisition
- [x] Add atomic state store
- [x] Add process-identity lock and ownership token
- [x] Add snapshot and backup-summary parsers
- [x] Add shared backup execution engine
- [x] Add terminal-state handling for wait, lock, execution, and finalization failures
- [x] Add Stage 1 unit and lifecycle regression tests
- [x] Add compile and focused correctness-lint gates
- [x] Bump RRBackup to `0.3.0`
- [x] Add `psutil` runtime dependency
- [x] Complete remote static review
- [ ] Validate latest-first report migration and retention
- [ ] Validate generated context snapshot and progress diff
- [ ] Run Stage 1 local Windows validation
- [ ] Correct local failures
- [ ] Evaluate Stage 1 coverage threshold
- [ ] Mark Stage 1 verified

## Stage 2 — Compatibility Merge and CLI

- [x] Define six-area CLI architecture
- [x] Map useful consolidation shell audits to first-class commands
- [x] Define `backup view audit` contract
- [ ] Add canonical `backup` entry point and required major version bump
- [ ] Add `backup run`
- [ ] Add `backup view`
- [ ] Add `backup config`
- [ ] Add `backup edit` alias
- [ ] Add `backup schedule`
- [ ] Add `backup restore`
- [ ] Add `backup repository`
- [ ] Preserve `rrb`
- [ ] Preserve `rrbackup`
- [ ] Preserve `backup_module`
- [ ] Preserve `python -m backup_module`
- [ ] Preserve legacy underscore options
- [ ] Add canonical hyphenated options
- [ ] Import legacy JSON/default configuration
- [ ] Add root and nested help-contract tests
- [ ] Add JSON stdout-purity tests
- [ ] Add secret-redaction tests
- [ ] Add `backup config discover`
- [ ] Add executable/wrapper/environment diagnostics
- [ ] Add known and relocated artifact discovery
- [ ] Add scheduler and launcher discovery
- [ ] Add repository key/stats/check/cache/lock inspection
- [ ] Add optional legacy shell-history evidence adapter
- [ ] Verify known snapshots through merged CLI
- [ ] Reduce `modules/backup_module` to a compatibility shim
- [ ] Remove duplicate engine only after compatibility tests pass

## Stage 3 — Scheduler

- [ ] Windows Task Scheduler CRUD
- [ ] systemd user timer CRUD
- [ ] cron compatibility CRUD
- [ ] Startup-command and service launcher discovery
- [ ] Schedule health
- [ ] Schedule history
- [ ] No-overlap behavior
- [ ] Retry/start-when-available behavior
- [ ] Export before replacement
- [ ] Scheduler/run/snapshot correlation

## Stage 4 — Viewer

- [ ] Dashboard
- [ ] Timeline
- [ ] Snapshots
- [ ] Snapshot details
- [ ] Files and search
- [ ] Runs
- [ ] Logs
- [ ] Sets
- [ ] Schedules
- [ ] Setup and system diagnostics
- [ ] Provenance
- [ ] Comprehensive audit
- [ ] Gaps
- [ ] Storage
- [ ] Health
- [ ] Alerts
- [ ] JSON/JSONL/CSV/Markdown output
- [ ] Missed-backup engine

## Stage 5 — Alerts

- [ ] Health evaluator
- [ ] Alert persistence
- [ ] Deduplication
- [ ] Terminal exit codes
- [ ] Alert log
- [ ] Webhook
- [ ] Windows notification
- [ ] Email/external command
- [ ] Schedule-compatible health check

## Stage 6 — Retention

- [ ] Ownership tags
- [ ] Preview
- [ ] Apply confirmation
- [ ] Legacy adoption
- [ ] Isolation tests

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
