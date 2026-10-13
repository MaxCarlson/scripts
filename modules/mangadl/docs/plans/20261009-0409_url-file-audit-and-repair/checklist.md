# URL-File Audit and Repair Checklist

## Planning

- [x] Inspect the requested branch and current MangaDL audit, input, backend,
  state/archive, partial/scratch, repair, Kavita, test, and documentation
  surfaces.
- [x] Define staged behavior, safety constraints, architecture, and proposed
  verification.
- [x] Record that implementation requires explicit user approval.
- [x] User approves implementation (2026-10-09).

## Stage 1 — audit contract and CLI

- [x] Define result states/schema and preserve existing CLI compatibility.
- [x] Decide the audit URL-file short option while preserving run's direct URL.
- [x] Add structured findings and deterministic JSON with default read-only
  behavior.
- [x] Add focused input, CLI, provenance, stdout/stderr, and no-mutation tests.
- [x] Run focused audit tests, CLI help, and Ruff; record results.
- [x] Fix and regression-test the `modules/kavita` import collision found in
  user's manual run.
- [x] Run complete MangaDL and Kavita suites and scoped Ruff checks.
- [x] User reports false-complete Paradise result; continue implementation to
  close the identified acceptance gap.

## Stage 2 — identity and completeness adapters

- [x] Define nhentai metadata resolver use and exact destination evidence.
- [x] Enumerate nhentai expected-page totals without downloading image payloads.
- [x] Fail closed for collections, ambiguous matches, and unknown metadata.
- [x] Add adapter and no-download/no-archive-mutation tests.

## Stage 3 — local image integrity

- [x] Map deterministic numbered image identities to expected page identities.
- [x] Report missing, duplicate, extra, zero-byte, truncated, and undecodable
  image files.
- [x] Add bounded scanning, progress, stable report output, and failure-path
  tests.

## Stage 4 — repair planning and execution

- [ ] Build exact URL/page/folder repair plans; dry-run remains the default.
- [ ] Specify reversible quarantine and narrowly scoped gallery-dl archive
  reconciliation with recovery evidence.
- [ ] Execute only through safe backend worker/partial/scratch lifecycle.
- [ ] Verify post-repair file integrity and full expected-page coverage.
- [ ] Add tests for repair success, failure, interruption, rollback, and resume.

## Stage 5 — Kavita/docs continuity

- [ ] Preserve canonical URL-to-folder assignments without implicit API writes.
- [ ] Document backend support, unknown states, repair preview/apply, and
  rollback behavior.
- [ ] Update handoff and validation target records with verified results.

## Stage 6 — validation and acceptance

- [ ] Run focused and full MangaDL tests, CLI checks, compile/Ruff, and root
  dispatcher; record exact results.
- [ ] Review bounded read-only preview before any live repair.
- [ ] Perform only user-approved small acceptance; stop for manual validation
  before commit/push/merge unless explicitly authorized.
