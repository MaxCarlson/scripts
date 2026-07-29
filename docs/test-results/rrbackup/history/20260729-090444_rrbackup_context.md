# Validation Context: rrbackup

Generated: 2026-07-29T09:05:01.4764509-07:00
Branch: agent/merge-restic-backup-modules
Commit: b24c0564bead4adb4cd50865c696d7646936d4ed
Validation report: docs\test-results\rrbackup\LATEST.txt

## Validation Highlights

- RESULT: PASS - Install RRBackup editable development dependencies
- RESULT: PASS - Compile RRBackup package and tests
- RESULT: PASS - Lint RRBackup safety foundation
- ======================= 199 passed, 8 skipped in 11.16s =======================
- RESULT: PASS - RRBackup pytest and coverage suite
- RESULT: PASS - PowerShell test: tests\powershell\environment_smoke_test.ps1
- RESULT: PASS - PowerShell test: tests\powershell\production_read_only_test.ps1
- TARGET RESULT: PASS

## Working Tree

```text
 D docs/test-results/rrbackup/20260729-082945_rrbackup.txt
?? docs/test-results/rrbackup/LATEST.txt
?? docs/test-results/rrbackup/history/
```

## Project Status Sources

### `docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/STATUS.md`

# Status

## Overall

Stage 1 implementation is complete and awaiting local validation. The reusable repository-root validation dispatcher was previously proven on Windows with 126 passing tests and 8 intentional skips. This checkpoint adds the shared safety engine and a substantial regression suite before any existing public CLI is redirected.

Validation evidence now uses `LATEST.txt`, `LATEST_CONTEXT.md`, and `LATEST_PROGRESS.diff`, with bounded history. The six-area CLI and shell-audit replacement contract remain fixed for Stage 2.

## Completed

- [x] Provenance analysis
- [x] Static audit of both modules
- [x] Production compatibility contract
- [x] Dedicated feature branch
- [x] Canonical project documentation structure
- [x] Hybrid remote/local workflow documented at repository level
- [x] One-time hybrid reminder documented for local agents
- [x] Repository-root `Invoke-Tests.ps1` dispatcher
- [x] Manifest-driven validation targets in `validation-targets.json`
- [x] RRBackup registered as the default validation target
- [x] Dependency bootstrap enabled by default
- [x] Repository virtual-environment Python resolution
- [x] Target working-directory isolation
- [x] Pytest `--import-mode=importlib`
- [x] Authoritative `docs/test-results/<target>/LATEST.txt`
- [x] Paired `LATEST_CONTEXT.md` and `LATEST_PROGRESS.diff`
- [x] Bounded prior-report history
- [x] Full stdout/stderr capture for compilation, lint, pytest, and PowerShell tests
- [x] PowerShell environment/entry-point smoke test
- [x] Opt-in production read-only snapshot compatibility test
- [x] Project-local ignored temporary-test root
- [x] Repository-root dispatcher validated on Windows
- [x] User-config-dependent tests changed from mandatory failure to optional skip
- [x] Live Google Drive tests made explicitly opt-in
- [x] Top-level CLI configuration errors converted to stable nonzero return codes
- [x] Duplicate outer RRBackup package initializer removed
- [x] Canonical six-area CLI architecture defined
- [x] Useful shell-audit capabilities mapped to first-class module commands
- [x] `backup view audit` contract defined
- [x] Canonical legacy `backup_module` profile adapter with source attribution
- [x] Production-compatible Restic backup command builder
- [x] Hard preview/print-only execution barrier
- [x] Distinct dry-run execution mode
- [x] Process-identity-aware lock with ownership token
- [x] Atomic current/history/last-success state store
- [x] CPU normal/overdue decision and wait policy
- [x] Snapshot and backup-summary JSON parsers
- [x] Shared backup execution engine
- [x] CPU gating occurs before lock acquisition
- [x] Dry runs never update last-success state
- [x] Lock, wait, execution, interruption, and finalization failures reach terminal state
- [x] RRBackup version bumped to `0.3.0`
- [x] `psutil` declared as a runtime dependency
- [x] Stage 1 unit and lifecycle regression tests authored

## Awaiting Validation

- [ ] Compile new package and tests on Windows
- [ ] Run focused correctness lint
- [ ] Run full pytest and coverage suite
- [ ] Run PowerShell smoke tests
- [ ] Verify first-run migration to `LATEST.*` validation artifacts
- [ ] Verify generated context snapshot and baseline progress diff
- [ ] Correct failures found by the local run
- [ ] Decide whether Stage 1 coverage is sufficient before Stage 2

## Latest Proven Baseline Before This Checkpoint

- 134 tests collected
- 126 passed
- 8 intentionally skipped
- 0 failed
- 0 errors
- package branch coverage: 36%
- environment smoke test: passed
- production read-only test: safely skipped

The next run adds the new Stage 1 tests and will establish the first safety-foundation baseline.

## New Stage 1 Components

```text
rrbackup/engine.py
rrbackup/locking.py
rrbackup/models.py
rrbackup/policy.py
rrbackup/profile.py
rrbackup/restic.py
rrbackup/snapshots.py
rrbackup/state.py
```

The existing public `rrb` and `rrbackup` commands still use the inherited implementation. Stage 2 will redirect compatible commands only after this safety foundation passes locally.

## CLI Contract

The canonical command will be `backup` with six major areas:

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`. Existing `rrb`, `rrbackup`, `backup_module`, and `python -m backup_module` interfaces remain during the compatibility period.

The complete contract and shell-audit mapping are in:

```text
docs/CLI_ARCHITECTURE_AND_AUDIT_COVERAGE.md
```

The comprehensive read-only diagnostic replacement is:

```text
backup view audit
```

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known snapshots: `a1609113`, `022aad5b`
- Latest snapshot: 2026-04-14
- Current backup schedule: absent
- Production mutation during automated validation: prohibited

## Validation Commands

From the repository root:

```powershell
./Invoke-Tests.ps1
```

Optional production read-only validation:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```

The authoritative evidence is:

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

