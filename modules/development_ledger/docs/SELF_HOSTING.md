# Development Ledger Self-Hosting

## Current integration

The first live integration uses the existing ordered command pipeline in the repository-root dispatcher.

Run from the repository root:

```powershell
./Invoke-Tests.ps1 -Target development-ledger
```

The target:

1. installs `development-ledger` with development dependencies,
2. compiles and lints the package and tests,
3. validates the active structured plan,
4. checks the CLI help contract,
5. runs pytest with JUnit XML and branch coverage,
6. records JUnit plus the current `LATEST.txt` transcript as its final command.

## Dispatcher adapter

The final command uses:

```text
python -m development_ledger.dispatcher_record ... -w
```

The normal `development-ledger record` command returns `1` after successfully recording a run that contains failed/error tests. The root dispatcher has already preserved those command failures, so the adapter maps only result `1` to `0` after evidence is written. Result `2` and other nonzero recording failures remain failures.

This keeps two facts separate:

- the validated software may have failed checks,
- the evidence-recording operation may still have succeeded.

## Generated evidence

```text
docs/test-results/development-ledger/LATEST.txt
modules/development_ledger/docs/plans/20260729-1100_development-ledger-self-hosting/ledger/
```

The ledger directory should contain `RUNS.jsonl`, `LATEST.json`, `PROGRESS.md`, `TRACEABILITY.md`, and `MANUAL_CHECKS.md`. Do not edit those generated files manually.

## Deferred until evidence review

After the first local cycle is inspected, decide whether to:

- promote recording-success semantics into the public `record` command,
- add first-class ledger fields and a generic final ledger phase to `Invoke-Tests.ps1`,
- migrate the RRBackup plan to structured ledger state,
- add repository-wide generated-progress routing instructions,
- register the accepted module in scripts-help.
