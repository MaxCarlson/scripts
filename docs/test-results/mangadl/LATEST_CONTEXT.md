# Validation Context: mangadl

Generated: 2026-09-21T10:44:19.4705662-07:00
Branch: agent/mangadl-gallery-auth
Commit: d8f22fa3f26525b4e274891241f5efe5ceb72d33
Validation report: docs\test-results\mangadl\LATEST.txt

## Validation Highlights

- RESULT: PASS - Compile mangadl package and tests
- RESULT: PASS - Lint mangadl package and tests
- RESULT: PASS - Mangadl CLI help contract
- RESULT: PASS - Mangadl pytest suite
- TARGET RESULT: PASS

## Working Tree

```text
MM modules/mangadl/README.md
MM modules/mangadl/__init__.py
MM modules/mangadl/docs/HANDOFF.md
 M modules/mangadl/docs/README.md
M  modules/mangadl/docs/plans/20260825-0540_gallery-dl-managed-auth/00_implementation-plan.md
A  modules/mangadl/docs/plans/20260825-0540_gallery-dl-managed-auth/06_destination-root-series-layout__planned.md
A  modules/mangadl/docs/plans/20260825-0540_gallery-dl-managed-auth/07_input-wide-auth-preflight__planned.md
MM modules/mangadl/docs/plans/20260825-0540_gallery-dl-managed-auth/HANDOFF.md
MM modules/mangadl/docs/plans/20260825-0540_gallery-dl-managed-auth/STATUS.md
M  modules/mangadl/docs/plans/20260825-0540_gallery-dl-managed-auth/checklist.md
MM modules/mangadl/docs/plans/HANDOFF.md
MM modules/mangadl/mangadl/__init__.py
 M modules/mangadl/mangadl/backends.py
MM modules/mangadl/mangadl/cli_core.py
MM modules/mangadl/mangadl/cli_structure.py
M  modules/mangadl/mangadl/manager.py
M  modules/mangadl/mangadl/state.py
MM modules/mangadl/mangadl/ui.py
MM modules/mangadl/mangadl/worker_core.py
MM modules/mangadl/pyproject.toml
 M modules/mangadl/tests/backends_test.py
MM modules/mangadl/tests/cli_test.py
M  modules/mangadl/tests/managed_auth_test.py
M  modules/mangadl/tests/manager_integration_test.py
M  modules/mangadl/tests/state_test.py
 M modules/mangadl/tests/ui_test.py
MM modules/mangadl/tests/worker_test.py
 M modules/scripts_help/scripts_help/registry/registry.py
 M validation-targets.json
?? docs/test-results/mangadl/
?? modules/mangadl/docs/plans/20260921-0943_partial-safety-and-merge-readiness/
?? modules/mangadl/mangadl/partial_safety.py
?? modules/mangadl/tests/partial_safety_test.py
```

## Project Status Sources

### `docs/plans/20260921-0943_partial-safety-and-merge-readiness/STATUS.md`

# Partial Safety and Merge Readiness Status

## State

Implementation and offline validation complete; stopped for the required user
manual-acceptance boundary. Baseline module suite passed
(`158 passed`). Source/log evidence shows
the accidental download was a valid broad collection expansion, not a worker
loop. The dashboard has a separate unbounded whole-log read on each render.

## Documentation Freshness

Score: **0/100 (healthy)** for 1.16.0 scope: README, project/plan handoffs,
status, checklist, CLI behavior, and version sources are synchronized. The root
validation manifest includes a mangadl target and its dispatcher run passes.

## Verification

- `python -m ruff check mangadl tests`: pass.
- `python -m compileall -q mangadl tests`: pass.
- `python -m pytest tests -q`: **170 passed**.
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
- Live-data read-only preview:
  `mangadl partials clean -d B:\Hent\tmphent3 -t fc7c3b753cc0 -F -j`
  reported 34,220 files and 13,694,065,861 bytes; status remained `dry-run`,
  with zero archive mutation because this legacy partial has no manifest.

## Next Action

User-run live acceptance remains: one ordinary gallery-dl series should confirm
direct destination-root layout plus responsive TUI/raw-log switching. The
legacy accidental partial can be previewed with `--files-only`, but applying
that deletion and any archive repair remains an explicit user decision. S7
input-wide auth preflight is still blocked on the pre-existing S6 acceptance.
No live `B:` download, archive, state, or partial data has been mutated.

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

- [ ] Live-validate one normal gallery-dl series into a disposable destination.
- [ ] Confirm direct destination-root layout and responsive TUI/log switching.
- [x] Preview legacy cleanup for `fc7c3b753cc0` without mutation.
- [ ] Apply legacy cleanup only on explicit user decision.
- [ ] Obtain approval to stage/commit the partial-safety work.
- [ ] Complete the existing integration-branch and final-merge approvals.

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

## Merge Boundary

Do not merge automatically. Completion prepares the branch for the documented
integration path and reports any remaining user-controlled live acceptance,
commit/push, integration-branch, and final merge approvals.
