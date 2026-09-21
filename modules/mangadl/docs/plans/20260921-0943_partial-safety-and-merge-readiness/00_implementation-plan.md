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
4. **S4 - Interactive cleanup and legacy reconciliation:** optional targets
   open a multi-select tree UI; legacy owners recover their URLs and exact
   gallery-dl archive keys before archive-consistent deletion.

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
