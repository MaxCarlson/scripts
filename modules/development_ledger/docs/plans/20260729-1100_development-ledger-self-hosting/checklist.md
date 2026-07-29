# Development Ledger Self-Hosting Checklist

## Remote implementation

- [x] Add a recording-success adapter without changing the public CLI.
- [x] Add unit coverage for adapter result mapping.
- [x] Add the root `development-ledger` validation target.
- [x] Emit JUnit XML from the module pytest run.
- [x] Record the raw root-dispatcher transcript as the target's final command.
- [x] Add a scripts-repository manifest integration test.
- [x] Create the structured active plan and handoff files.
- [x] Review source, manifest, documentation, and path consistency.

## Local validation

- [ ] Pull the updated feature branch.
- [ ] Run `./Invoke-Tests.ps1 -Target development-ledger`.
- [ ] Confirm every target section passes.
- [ ] Confirm JUnit XML is consumed by the ledger command.
- [ ] Confirm `RUNS.jsonl` receives exactly one new event.
- [ ] Confirm generated projections are present and readable.
- [ ] Record `MC-S1-001` after inspection.
- [ ] Commit and push raw validation plus ledger evidence.

## Follow-up

- [ ] Read generated `PROGRESS.md` remotely.
- [ ] Diagnose any failures before broader integration.
- [ ] Decide whether to promote CLI/dispatcher integration or migrate another plan.
