# Development Ledger Self-Hosting Status

## Overall

The first self-hosting run completed end to end and produced authoritative evidence. The target correctly failed because pytest reported one failing test, while the final ledger-recording command still passed and wrote all projections.

A focused correction pass is implemented and awaits one rerun of the same root target.

## First-run evidence

- Bootstrap/install: passed.
- Compile: passed.
- Ruff correctness lint: passed.
- Structured plan validation: passed.
- CLI help contract: passed.
- Pytest: 56 passed, 1 failed.
- Branch coverage: 81%.
- Ledger recording: passed after the pytest failure.
- Root target result: failed, preserving the original validation failure.

## Root causes corrected

1. `run-event.schema.json` is valid through top-level `oneOf`; the schema test accessed `payload["type"]` before checking `oneOf`.
2. Pytest 9 emitted dotted `classname` values without `file`, producing IDs such as `pytest:tests.dispatcher_record_test::...` instead of the documented `pytest:tests/dispatcher_record_test.py::...`.
3. Routine Windows validation prerequisites were listed as unresolved environment dependencies, causing a false generated `handoff_local` recommendation.

## Correction implementation

- `development-ledger` version advanced to `1.1.1`.
- Schema validation uses a safe object-or-`oneOf` assertion.
- Pytest classname-only JUnit cases normalize to stable forward-slash file paths.
- Regression coverage includes function and test-class classname forms.
- Active plan revision advanced to `2` with no unresolved environment dependency.
- Existing dispatcher adapter and manifest target remain unchanged.
- Dispatcher transcript evidence now replaces the redundant manual acceptance check.

## Awaiting corrected evidence

```powershell
./Invoke-Tests.ps1 -Target development-ledger
```

Commit and push the regenerated changes under:

```text
docs/test-results/development-ledger/
modules/development_ledger/docs/plans/20260729-1100_development-ledger-self-hosting/ledger/
```

## Next decision

After the corrected run, inspect `PROGRESS.md` and `TRACEABILITY.md`. If automated evidence is clean and both items are verified, decide whether to promote generic dispatcher integration or migrate RRBackup.
