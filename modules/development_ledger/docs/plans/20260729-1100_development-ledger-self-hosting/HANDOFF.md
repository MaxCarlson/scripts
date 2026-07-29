# Stage Handoff

## Current state

The first self-host run produced complete evidence and one attributable pytest failure. The schema assertion, JUnit-ID normalization, and false environment-routing metadata are corrected on the feature branch.

The correction stage is frozen pending one local rerun.

## Local command

```powershell
git pull --ff-only && ./Invoke-Tests.ps1 -Target development-ledger
```

## Expected corrected evidence

- All target sections pass.
- Pytest reports 58 tests after the added classname-normalization regression case.
- `TRACEABILITY.md` matches the dispatcher adapter and repository-integration tests to `AC-S1-001` and `AC-S1-002`.
- `RUNS.jsonl` receives exactly one additional immutable event.
- `PROGRESS.md` no longer routes this source-level correction to a local agent.
- Both acceptance items are verified from JUnit and dispatcher transcript evidence without a separate manual command.
- The prior raw report is archived under bounded history.

## Generated paths

```text
docs/test-results/development-ledger/LATEST.txt
modules/development_ledger/docs/plans/20260729-1100_development-ledger-self-hosting/ledger/
```

## Constraints

- Do not edit generated ledger files manually.
- Do not begin broader dispatcher or CLI integration before reviewing the corrected run.
- Do not migrate RRBackup plan state in the same local pass.
- Preserve the exact root-dispatcher exit code and complete transcript.
