# Library identity and batch operations status

Plan created 2026-10-09 on
`codex/kavita-module-mangadl-collections-20261009-0349`. The user waived
per-stage pauses and asked for continuous implementation through completion.

Implemented in the current working tree:

- SSD destination or scratch removes the fixed worker cap while retaining the
  aggregate logical-CPU budget; neither SSD means a four-worker cap.
- Shared library identity index, atomic `.mangadl-source.json` manifests for
  successful promotions, conservative legacy matching, and resolver reuse in
  URL-file audit and Kavita assignment.
- URL-file audit and historical `kavita assign-file` now backfill missing
  source manifests for unique, non-empty matches. Exact metadata and unique
  deterministic backend identity are accepted; ambiguous, conflicting,
  unresolved, and empty folders are skipped. Both workflows report counts and
  accept `--no-index-backfill` for read-only operation.
- URL-file and folder-only audits; image decode/size checks; gallery-dl
  expected-page enumeration where a complete stable page set can be proven.
- Kavita collection assignment for historical URL files, exact series name,
  and bounded regex selection. Pattern apply is tied to a token for the exact
  previewed match set.
- Exact-page repair for uniquely matched individual nhentai galleries only.
  It previews page/archive identities, requires an exact preview token plus
  `--apply`, backs up the archive, quarantines corrupt files, runs one normal
  MangaDL worker with exact page ranges, then re-audits and reconciles only
  affected archive keys. Custom gallery-dl configuration/archive layouts,
  active runs, incomplete identity maps, and unsupported backends fail closed.

Paradise (`nhentai-633374`) remains unmodified. Its previous audit finding was
192 expected pages, pages 1–158 missing, and page 175 corrupt. Neither a live
repair nor a Kavita API write has been performed.

## Verification

- Focused URL-index/audit/Kavita backfill suite: 54 passed.
- Final MangaDL suite: 254 tests passed.
- Kavita suite: 16 passed.
- Repository dispatcher `& .\\Invoke-Tests.ps1 -Target @('mangadl','kavita') -SkipBootstrap -MaxHistoryAgeDays 3650 -MaxHistoryPerTarget 10`: both targets passed compile, Ruff, CLI help (MangaDL), and pytest (Kavita: 16 tests).
- Direct Ruff checks passed for MangaDL and Kavita. `git diff --check` found no source whitespace errors; it reports intentional blank lines/trailing whitespace only in dispatcher-generated `LATEST_CONTEXT.md` and `LATEST_PROGRESS.diff` reports.
- The initial Kavita test invocation had 13 passes and 3 fixture setup errors because the module temp parent did not exist; after creating that directory, all 16 passed.
- Pytest requires approved filesystem access for temporary-directory cleanup
  in this Windows environment; sandbox-only cleanup has returned Access Denied.

## Merge and acceptance state

- Local implementation validation and generated reports are complete.
- The user explicitly approved committing, pushing, and merging this branch on
  2026-10-12. Branch-only commits and main-only validation evidence are under
  review before the merge.
- Live TUI, audit/repair preview, and Kavita API compatibility remain
  unverified. No live repair, archive mutation, or Kavita collection write has
  been performed.
