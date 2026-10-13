# Library identity and batch operations checklist

## Stage 1 — storage-aware worker budget

- [x] Detect destination and scratch media independently.
- [x] Remove fixed eight-worker ceiling when either path is SSD; preserve CPU
  budget; cap to four otherwise.
- [x] Update CLI/UI status and docs for policy.
- [x] Add media-combination and runtime-worker tests.
- [x] Run focused/full MangaDL tests and Ruff. Full suite: 235 passed.
- [x] Record exact results and stop for user review.

## Stage 2 — shared URL-to-folder index and source manifest

- [x] Extract audit URL/folder matching into reusable library API.
- [x] Add atomic per-folder source manifest for new successful downloads.
- [x] Reuse resolved folder record in Kavita assignment queueing.
- [x] Preserve conservative legacy fallback and ambiguity handling.
- [x] Backfill missing source manifests during URL-file audit and historical `kavita assign-file` for unique, populated matches; report counts and provide a read-only opt-out.

## Stage 3 — URL-file and folder-only audit

- [x] Audit every manga folder under a selected root without requiring URL file.
- [x] Continue URL-file audit against explicit destination root.
- [x] Backfill only proven URL/folder identities by default; expose `--no-index-backfill` for strictly read-only URL-file audit.
- [x] Add conservative gallery-dl expected page identity enumeration and audit comparisons.
- [x] Report missing/untracked/duplicate folders and page integrity findings; unknown totals remain explicitly unknown.

## Stage 4 — historical URL-file to Kavita collections

- [x] Resolve each URL through shared index and exact Kavita path matching.
- [x] Preview one/multiple collection assignments; apply explicitly.
- [x] Preserve unresolved/ambiguous records as pending, not guessed.

## Stage 5 — Kavita exact-name and pattern selection

- [x] Select already scanned series by exact name.
- [x] Add bounded pattern matching with stable preview of every captured item.
- [x] Require a match-set token after displaying the exact match set.
- [x] Test duplicate/unsafe pattern handling and API write boundaries.

## Stage 6 — safe missing/corrupt image repair

- [x] Plan exact nhentai page repair only when identity, source, and archive keys are
  provable.
- [x] Add dry-run, exact-preview confirmation token, reversible quarantine, archive backup/reconciliation, and
  normal worker/partial/scratch execution.
- [x] Re-audit after repair and test archive reconciliation, incomplete-map refusal, and preview-token binding. Live failure/recovery acceptance remains outstanding.

## Stage 7 — validation and merge readiness

- [x] Run full MangaDL/Kavita validation and update tracked reports.
- [ ] Complete bounded user-approved live checks for TUI, audit, repair preview, and Kavita.
- [ ] Review separate feature branch commits and reconcile main validation
  evidence.
- [x] Obtain explicit merge approval before merging to main (user authorized on 2026-10-12).

## Current implementation verification (2026-10-09)

- Focused repair/CLI/worker tests: 54 passed before the final preview-token test.
- Focused URL-index/audit/Kavita backfill suite: `python -m pytest tests/library_index_test.py tests/destination_audit_test.py tests/cli_test.py tests/kavita_assignment_test.py -q --tb=short -o addopts='' -p no:cacheprovider --basetemp <fresh system-temp>` — 54 passed.
- MangaDL full suite: 254 collected and passed after URL-index backfill changes.
- Kavita full suite: 16 passed.
- Repository dispatcher `& .\\Invoke-Tests.ps1 -Target @('mangadl','kavita') -SkipBootstrap -MaxHistoryAgeDays 3650 -MaxHistoryPerTarget 10`: both targets passed compile, Ruff, CLI help (MangaDL), and pytest (Kavita: 16 tests).
- Repository dispatcher refreshed the tracked `docs/test-results/{mangadl,kavita}/LATEST*` reports. The generated progress-diff artifacts contain intentional blank-line whitespace, so `git diff --check` reports whitespace only in those reports.
- Live acceptance remains outstanding; branch reconciliation and merge are proceeding with user approval.
