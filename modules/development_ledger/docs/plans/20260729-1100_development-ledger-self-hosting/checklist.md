# Development Ledger Self-Hosting Checklist

## Initial remote implementation

- [x] Add a recording-success adapter without changing the public CLI.
- [x] Add unit coverage for adapter result mapping.
- [x] Add the root `development-ledger` validation target.
- [x] Emit JUnit XML from the module pytest run.
- [x] Record the raw root-dispatcher transcript as the target's final command.
- [x] Add a scripts-repository manifest integration test.
- [x] Create the structured active plan and handoff files.

## First local cycle

- [x] Pull the updated feature branch.
- [x] Run `./Invoke-Tests.ps1 -Target development-ledger`.
- [x] Confirm JUnit XML is consumed by the ledger command.
- [x] Confirm `RUNS.jsonl` receives exactly one event.
- [x] Confirm generated projections are present and readable.
- [x] Commit and push raw validation plus ledger evidence.
- [x] Read generated `PROGRESS.md` and `TRACEABILITY.md` remotely.
- [x] Attribute the single pytest failure and traceability mismatch.

## Correction pass

- [x] Fix object-or-`oneOf` schema assertion ordering.
- [x] Canonicalize pytest classname-only JUnit IDs.
- [x] Add regression coverage for function and class-based pytest IDs.
- [x] Advance package version to `1.1.1`.
- [x] Advance active plan state to revision `2`.
- [x] Remove routine validation prerequisites from unresolved environment dependencies.
- [ ] Pull the correction commits.
- [ ] Rerun `./Invoke-Tests.ps1 -Target development-ledger`.
- [ ] Confirm every target section passes.
- [ ] Confirm both plan items receive matched automated evidence.
- [ ] Confirm the generated routing no longer requests a local-agent handoff for source-level failures.
- [ ] Commit and push the regenerated report and ledger evidence.
- [ ] Record `MC-S1-001` after inspecting the corrected run.

## Follow-up

- [ ] Decide whether to promote CLI/dispatcher integration or migrate RRBackup.
