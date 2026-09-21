# Partial Safety and Merge Readiness Checklist

## S1 - Guard and Track

- [x] Reject broad collection extractors by default.
- [x] Add explicit short/long collection opt-in.
- [x] Write versioned partial metadata before backend launch.
- [x] Record successful archive-key/path ownership for gallery-dl files.
- [x] Preserve tracking controls until successful merge, then remove them.
- [x] Add focused normal, failure-preservation, archive-switch, and merge tests.

## S2 - Cleanup and Responsiveness

- [x] Add dry-run-first `partials clean` CLI.
- [x] Validate target containment, activity, metadata, archive, and manifest.
- [x] Remove exact archive keys transactionally before filesystem deletion.
- [x] Add explicit legacy files-only escape hatch without archive mutation.
- [x] Replace full-log reads with a bounded tail reader.
- [x] Add cleanup and large-log regression tests.

## S3 - Merge Readiness and Docs Update

- [x] Document collection opt-in and safe partial cleanup in README.
- [x] Update project and plan handoffs/status/checklists.
- [x] Add a mangadl repository validation target.
- [x] Synchronize all version sources and help registry metadata.
- [x] Run focused tests, full tests, compile, Ruff, and dispatcher validation.
- [x] Review staged plus unstaged diff for merge blockers.
- [x] Record remaining live acceptance and approval requirements.

## Manual Acceptance and Integration (Not Yet Approved)

- [ ] Live-validate one normal gallery-dl series into a disposable destination.
- [ ] Confirm direct destination-root layout and responsive TUI/log switching.
- [x] Preview legacy cleanup for `fc7c3b753cc0` without mutation.
- [ ] Apply legacy cleanup only on explicit user decision.
- [x] Obtain approval to stage/commit/push the partial-safety work.
- [ ] Complete the existing integration-branch and final-merge approvals.
