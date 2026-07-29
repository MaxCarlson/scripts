# Consolidation Checklist

## Stage 1 — Safety Foundation

- [x] Create canonical plan structure
- [ ] Add root validation orchestrator
- [ ] Add PowerShell environment smoke test
- [ ] Add opt-in production read-only test
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

## Stage 2 — Compatibility Merge

- [ ] Preserve `rrb`
- [ ] Preserve `rrbackup`
- [ ] Preserve `backup_module`
- [ ] Preserve `python -m backup_module`
- [ ] Preserve legacy underscore options
- [ ] Add canonical hyphenated options
- [ ] Import legacy JSON/default configuration
- [ ] Verify known snapshots through merged CLI

## Stage 3 — Scheduler

- [ ] Windows Task Scheduler CRUD
- [ ] systemd user timer CRUD
- [ ] cron compatibility CRUD
- [ ] Schedule health
- [ ] No-overlap behavior
- [ ] Retry/start-when-available behavior
- [ ] Export before replacement
- [ ] Scheduler/run/snapshot correlation

## Stage 4 — Viewer

- [ ] Dashboard
- [ ] Timeline
- [ ] Snapshots
- [ ] Runs
- [ ] Sets
- [ ] Schedules
- [ ] Gaps
- [ ] Storage
- [ ] Details
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
- [ ] Alert acceptance
- [ ] Documentation cleanup
- [ ] Compatibility-period documentation
