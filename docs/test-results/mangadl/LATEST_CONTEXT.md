# Validation Context: mangadl

Generated: 2026-09-21T16:48:18.0454589-07:00
Branch: agent/mangadl-gallery-auth
Commit: 8f0d2d83abfc22c36d91d25ce2f7f96ab6c22adb
Validation report: docs\test-results\mangadl\LATEST.txt

## Validation Highlights

- RESULT: PASS - Compile mangadl package and tests
- RESULT: PASS - Lint mangadl package and tests
- RESULT: PASS - Mangadl CLI help contract
- RESULT: PASS - Mangadl pytest suite
- TARGET RESULT: PASS

## Working Tree

```text
 M docs/test-results/mangadl/LATEST.txt
 D docs/test-results/mangadl/LATEST_CONTEXT.md
 D docs/test-results/mangadl/LATEST_PROGRESS.diff
 D docs/test-results/mangadl/history/20260921-100720_mangadl.txt
 D docs/test-results/mangadl/history/20260921-100720_mangadl_context.md
 D docs/test-results/mangadl/history/20260921-100720_mangadl_progress.diff
 M modules/mangadl/docs/HANDOFF.md
 M modules/mangadl/docs/plans/20260825-0540_gallery-dl-managed-auth/HANDOFF.md
 M modules/mangadl/docs/plans/20260825-0540_gallery-dl-managed-auth/STATUS.md
 M modules/mangadl/docs/plans/20260825-0540_gallery-dl-managed-auth/checklist.md
 M modules/mangadl/docs/plans/20260921-0943_partial-safety-and-merge-readiness/HANDOFF.md
 M modules/mangadl/docs/plans/20260921-0943_partial-safety-and-merge-readiness/STATUS.md
 M modules/mangadl/docs/plans/20260921-0943_partial-safety-and-merge-readiness/checklist.md
 M modules/mangadl/docs/plans/HANDOFF.md
?? docs/test-results/mangadl/history/20260921-160434_mangadl.txt
?? docs/test-results/mangadl/history/20260921-160434_mangadl_context.md
?? docs/test-results/mangadl/history/20260921-160434_mangadl_progress.diff
```

## Project Status Sources

### `docs/plans/20260921-0943_partial-safety-and-merge-readiness/STATUS.md`

# Partial Safety and Merge Readiness Status

## State

S4 interactive cleanup and legacy archive reconciliation is implemented. The
accidental download was a valid broad collection expansion, not a worker loop.
The broad-collection guard, bounded dashboard log reader, interactive partial
browser, and archive-aware legacy reconciliation are all present in 1.17.0.

## Documentation Freshness

Score before this sync: **60/100 (needs review)**. README and code described
1.17.0 correctly, but project/plan handoffs and validation counts still
described the 1.16.0 baseline. This documentation-sync task closes that drift.

## Verification

- `python -m ruff check mangadl tests`: pass.
- `python -m compileall -q mangadl tests`: pass.
- `python -m pytest tests -q`: **182 passed** after the original stashed S4
  implementation was restored.
- `pwsh -NoProfile -File .\Invoke-Tests.ps1 -Target mangadl`: pass with
  editable dependency/package installs, compile, Ruff, CLI help, and 169 tests
  at that checkpoint.
- `pwsh -NoProfile -File .\Invoke-Tests.ps1 -Target mangadl -SkipBootstrap`:
  pass after the final CLI regression test, **170 passed**.
- Scripts-help registry tests: **42 passed** with basetemp
  `modules/mangadl/.pytest_tmp_root/scripts-help-registry`. Two earlier
  invocations without a known-writable basetemp failed before tests with
  `WinError 5`; no assertion failed.
- `git diff --check` and `git diff --cached --check`: pass, with only Git's
  existing LF-to-CRLF checkout warnings.
- Latest live-data read-only preview:
  `mangadl partials clean -d B:\Hent\tmphent3 -t fc7c3b753cc0 -F -j`
  reported 41,957 files and 17,073,852,121 bytes; status remained `dry-run`
  and no archive was supplied or mutated.
- Live network acceptance downloaded chapter 0 into an isolated destination:
  42 distinct images, 1,300,372 bytes, all under `Like No Other\c000`, with no
  gallery-dl category wrapper.
- A live TTY chapter run accepted `l`, `r`, and `l` while downloading, moving
  through activity log, raw backend log, and the worker view without freezing;
  the run completed successfully.

## Next Action

The ordinary gallery-dl layout and responsive TUI/raw-log checks now pass. The
legacy accidental partial can be reconciled against an explicit archive or
cleaned with `--files-only`, but applying either deletion remains an explicit
user decision. S7 input-wide auth preflight remains blocked on its stricter S6
dependency gate: a complete series and a current multi-worker URL-file run.
No live `B:` archive, state, or partial data has been mutated.

### `docs/plans/20260921-0943_partial-safety-and-merge-readiness/checklist.md`

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

- [x] Live-validate one normal gallery-dl chapter into a disposable destination.
- [x] Confirm direct destination-root layout and responsive TUI/log switching.
- [x] Preview legacy cleanup for `fc7c3b753cc0` without mutation.
- [ ] Apply legacy cleanup only on explicit user decision.
- [x] Obtain approval to stage/commit/push the partial-safety work.
- [ ] Complete the existing integration-branch and final-merge approvals.

## S4 - Interactive Cleanup and Legacy Reconciliation

- [x] Open the cleanup UI when no `-t/--target` is supplied.
- [x] Browse nested files with expand/collapse and hierarchical sorting.
- [x] Multi-select one or more top-level partial owner folders.
- [x] Show URL, backend, archive, tracking, and active-worker details.
- [x] Recover legacy URLs from destination-local state databases.
- [x] Accept explicit URL overrides for unresolved legacy owners.
- [x] Reconstruct exact gallery-dl keys without downloading media.
- [x] Remove reconstructed matching keys from explicit `-a/--archive` first.
- [x] Refuse unresolved, ambiguous, partial-subtree, and empty-key reconciliation.
- [x] Keep explicit target and `--files-only` CLI behavior compatible.
- [x] Refuse active/changing targets and recheck the preview fingerprint at apply.
- [x] Add focused UI/model/reconciliation/CLI tests.
- [x] Update README, handoffs, status, version, and validation evidence.

### `docs/plans/20260921-0943_partial-safety-and-merge-readiness/00_implementation-plan.md`

# Partial Safety and Merge Readiness

## Objective

Prevent accidental broad collection downloads, make interrupted gallery-dl
partials safely removable without leaving stale archive entries, eliminate a
dashboard log-view freeze path, and establish the remaining evidence required
to integrate `agent/mangadl-gallery-auth`.

## Invariants

- Cleanup is dry-run-first and requires an explicit apply flag.
- Archive entries are removed before their corresponding files; a failed file
  deletion therefore causes a safe redownload rather than a false archive hit.
- Cleanup never infers archive ownership from timestamps or a concurrently
  changing database. Only worker-recorded archive keys may be removed.
- Targets must resolve beneath the selected `_partial` root; active workers,
  path escapes, and untracked legacy partials are refused by default.
- Broad collection extractors require an explicit run opt-in, while normal
  manga/gallery URLs remain unchanged.
- Dashboard log rendering reads a bounded tail rather than the whole log.
- Tests use only module-local temporary fixtures and never mutate live `B:` data.

## Stages

1. **S1 - Guard and track:** detect broad gallery-dl collection extractors,
   require explicit opt-in, write partial metadata, and record successful
   gallery-dl archive-key/path pairs.
2. **S2 - Cleanup and responsiveness:** add dry-run/apply partial cleanup with
   transactional archive removal, replace full-file log reads with a bounded
   tail reader, and add focused failure-path tests.
3. **S3 - Merge readiness:** update user/handoff documentation, add mangadl to
   the root validation manifest, run focused/full/dispatcher validation, and
   inventory remaining live acceptance and integration approvals.
4. **S4 - Interactive cleanup and legacy reconciliation:** make targets optional
   so `partials clean` opens a multi-select tree UI, display partial ownership
   URLs and state, and reconstruct exact gallery-dl archive keys for selected
   legacy owner folders before archive-consistent deletion.

## Acceptance Criteria

- `mangadl run` rejects `SimplyhentaiSeriesExtractor`-style collection feeds
  unless `--allow-collection` is supplied and reports the reason in dry-run.
- Interrupted gallery-dl jobs retain metadata and a manifest containing only
  archive keys actually associated with completed files in that partial.
- `mangadl partials clean -d DEST -t TARGET` reports planned bytes/files/keys;
  `--apply` removes exact recorded keys transactionally before deleting data.
- Cleanup refuses active, out-of-root, missing-manifest, and mismatched-archive
  cases without changing either filesystem or archive.
- Log view time and memory are bounded by the requested tail size rather than
  total raw-log size.
- The full module suite, compile, Ruff, and repository validation target pass.
- Interactive selection is limited to top-level partial owners while nested
  files remain browsable, and archive-aware legacy apply refuses unresolved or
  ambiguous URL ownership rather than falling back to files-only deletion.

## Merge Boundary

Do not merge automatically. Completion prepares the branch for the documented
integration path and reports any remaining user-controlled live acceptance,
commit/push, integration-branch, and final merge approvals.

