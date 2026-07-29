# Consolidation Checklist

## Stage 1 — Safety Foundation

- [x] Create canonical plan structure
- [x] Document hybrid remote/local workflow
- [x] Add module-root test orchestrator
- [x] Add tracked test-result handoff file
- [x] Capture complete pytest stdout/stderr
- [x] Run all `*_test.ps1` scripts from one command
- [x] Add PowerShell environment smoke test
- [x] Add opt-in production read-only test
- [x] Run initial local Windows baseline
- [x] Triage inherited baseline failures
- [ ] Correct or replace environment-dependent inherited tests
- [ ] Add shared models
- [ ] Add configuration resolver
- [ ] Add Restic command boundary
- [ ] Add print-command-only barrier
- [ ] Correct dry-run semantics
- [ ] Add CPU policy
- [ ] Add atomic state store
- [ ] Add process-identity lock
- [ ] Add snapshot parser
- [ ] Add Stage 1 tests
- [ ] Reach agreed Stage 1 coverage threshold
- [ ] Complete static review
- [ ] Pass local Windows validation

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
